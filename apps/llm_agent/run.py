"""CLI entrypoint for the LLM adapter.

Usage (from the repo root)::

    python -m apps.llm_agent.run --agent-id telemetry-llm-agent

As of PR 3 the tick loop runs end-to-end: polls events, calls Claude,
dispatches returned ``create_finding`` / ``create_proposal`` tool
calls back to Quorum. TickBudgetExceeded skips one tick; DailyBudgetExceeded
backs off for an hour (counter rolls at UTC midnight). --once runs
a single tick and exits.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import structlog

from apps.llm_agent.budget import (
    DailyBudgetExceeded,
    LlmBudget,
    TickBudgetExceeded,
)
from apps.llm_agent.claude_client import ClaudeClient
from apps.llm_agent.config import load_agent_profile, read_prompt
from apps.llm_agent.loop import run_tick
from apps.llm_agent.quorum_api import QuorumApiClient

_log = structlog.get_logger(__name__)

# Back-off interval after a daily-cap hit. The counter rolls
# automatically at the next UTC day boundary; we don't compute the
# exact remainder because this is the low-hanging 80% solution and the
# operator can always SIGTERM the process if they need it sooner.
DAILY_CAP_BACKOFF_SECONDS = 3600.0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent-id",
        required=True,
        help="Agent identity under which to run (must have an 'llm:' block in agents.yaml)",
    )
    parser.add_argument(
        "--config",
        default="config/agents.yaml",
        help="Path to the agents config YAML (default: config/agents.yaml)",
    )
    parser.add_argument(
        "--quorum-url",
        default="http://localhost:8080",
        help="Base URL of the Quorum API (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--cursor-dir",
        default="data/llm_cursors",
        help="Directory for persisting per-agent cursors",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one tick and exit (useful for cron-style runs or smoke tests)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    profile = load_agent_profile(args.config, args.agent_id)
    if profile.llm is None:
        _log.error(
            "llm_adapter_agent_not_llm_enabled",
            agent_id=args.agent_id,
            hint="add an 'llm:' sub-block to this agent in config/agents.yaml",
        )
        return 2

    llm_config = profile.llm

    prompt_text = read_prompt(Path("apps/llm_agent") / llm_config.system_prompt_ref)

    budget = LlmBudget(
        agent_id=profile.id,
        daily_cap=llm_config.daily_token_cap,
        per_tick_cap=llm_config.per_tick_token_cap,
    )
    claude = ClaudeClient(llm_config, prompt_text)
    quorum = QuorumApiClient(base_url=args.quorum_url, agent_id=profile.id)

    cursor_path = Path(args.cursor_dir) / f"{profile.id}.json"

    _log.info(
        "llm_adapter_started",
        agent_id=profile.id,
        model=llm_config.model,
        poll_interval_seconds=llm_config.poll_interval_seconds,
        once=args.once,
    )

    try:
        while True:
            sleep_seconds = llm_config.poll_interval_seconds
            try:
                run_tick(budget=budget, claude=claude, quorum=quorum, cursor_path=cursor_path)
            except TickBudgetExceeded as exc:
                # Single-tick estimate blew the per-tick cap. Likely a
                # fat event batch; back off for the normal poll interval
                # and try again — the event window will be smaller or the
                # operator will intervene.
                _log.warning(
                    "llm_tick_skipped_budget",
                    agent_id=profile.id,
                    cap="per_tick_token_cap",
                    reason=str(exc),
                )
            except DailyBudgetExceeded as exc:
                # Cumulative daily spend hit the cap. The counter rolls
                # at UTC midnight; back off for an hour so we don't burn
                # CPU in a tight loop logging the same thing forever.
                _log.warning(
                    "llm_tick_skipped_budget",
                    agent_id=profile.id,
                    cap="daily_token_cap",
                    reason=str(exc),
                    backoff_seconds=DAILY_CAP_BACKOFF_SECONDS,
                )
                sleep_seconds = DAILY_CAP_BACKOFF_SECONDS
            if args.once:
                return 0
            time.sleep(sleep_seconds)
    except KeyboardInterrupt:
        _log.info("llm_adapter_stopped", agent_id=profile.id, reason="keyboard_interrupt")
        return 0
    finally:
        quorum.close()


if __name__ == "__main__":  # pragma: no cover — entrypoint
    sys.exit(main())
