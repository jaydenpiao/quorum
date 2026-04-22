"""CLI entrypoint for the LLM adapter.

Usage (from the repo root)::

    python -m apps.llm_agent.run --agent-id telemetry-llm-agent

PR 1 ships the scaffolding only: the tick loop runs, polls events,
builds (but does not send) a Claude request body, and advances its
cursor. PR 2+ flips this on.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import structlog

from apps.llm_agent.budget import BudgetExceededError, LlmBudget
from apps.llm_agent.claude_client import ClaudeClient
from apps.llm_agent.config import load_agent_profile, read_prompt
from apps.llm_agent.loop import run_tick
from apps.llm_agent.quorum_api import QuorumApiClient

_log = structlog.get_logger(__name__)


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
            try:
                run_tick(budget=budget, claude=claude, quorum=quorum, cursor_path=cursor_path)
            except BudgetExceededError as exc:
                _log.warning(
                    "llm_tick_skipped_budget",
                    agent_id=profile.id,
                    reason=str(exc),
                )
            if args.once:
                return 0
            time.sleep(llm_config.poll_interval_seconds)
    except KeyboardInterrupt:
        _log.info("llm_adapter_stopped", agent_id=profile.id, reason="keyboard_interrupt")
        return 0
    finally:
        quorum.close()


if __name__ == "__main__":  # pragma: no cover — entrypoint
    sys.exit(main())
