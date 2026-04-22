"""Tick loop for the LLM adapter.

PR 1 (this PR) ships a **no-LLM-call** tick: the loop reads events,
advances the cursor, and builds (but does not send) a Claude request
body. This proves end-to-end wiring works — cursor persistence, event
filtering, request shape — without paying for real Claude calls until
PR 2 turns on ``create_finding``.

PR 2 will extend ``run_tick()`` to:
- Call ``claude.call_messages(...)`` after budget check
- Process returned ``tool_use`` blocks (starting with ``create_finding``)
- Record actual token usage to the budget

For now the happy path of one tick is: poll events → (no events, skip)
or (N new events → build body → log → persist cursor).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from apps.llm_agent.budget import LlmBudget
from apps.llm_agent.claude_client import ClaudeClient
from apps.llm_agent.quorum_api import QuorumApiClient

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TickOutcome:
    """What happened in one tick. Returned so tests can assert on it."""

    events_seen: int
    cursor: str | None
    request_built: bool


def run_tick(
    *,
    budget: LlmBudget,
    claude: ClaudeClient,
    quorum: QuorumApiClient,
    cursor_path: Path,
) -> TickOutcome:
    """Run one tick of the adapter loop.

    PR 1 scope: read + filter + build-body + advance cursor. No
    Claude call, no tool dispatch. PR 2 flips the body-build step to
    a live call.
    """
    cursor = _load_cursor(cursor_path)
    events = quorum.list_events(
        since_id=cursor,
        limit=claude.config.max_events_per_tick,
    )
    if not events:
        _log.info(
            "llm_tick_completed",
            agent_id=quorum.agent_id,
            outcome="skipped_idle",
            events_seen=0,
            cursor=cursor,
        )
        return TickOutcome(events_seen=0, cursor=cursor, request_built=False)

    # Serialize events into a compact user-message payload. Keep the
    # structure minimal so prompt caching stays stable across ticks —
    # no wall-clock timestamps injected, no per-tick UUIDs.
    user_content = json.dumps(
        {"cursor_from": cursor, "events": events},
        sort_keys=True,
        separators=(",", ":"),
    )

    # Budget preflight. PR 1 doesn't actually call Claude so we don't
    # record spend; but we surface BudgetExceededError early via the
    # check so tests can pin the contract. PR 2 will wrap the call
    # with check/record as documented in the budget module.
    estimated_tokens = _rough_token_estimate(user_content) + _rough_token_estimate(
        claude._system_prompt  # noqa: SLF001 — internal, test-visible
    )
    budget.check_tick(estimated_tokens)

    body = claude.build_request(user_content=user_content)
    assert body["model"] == claude.config.model, "model field must survive build_request"

    new_cursor = _last_event_id(events) or cursor
    _persist_cursor(cursor_path, new_cursor)

    _log.info(
        "llm_tick_completed",
        agent_id=quorum.agent_id,
        outcome="body_built_no_call",
        events_seen=len(events),
        cursor=new_cursor,
        estimated_input_tokens=estimated_tokens,
    )
    return TickOutcome(
        events_seen=len(events),
        cursor=new_cursor,
        request_built=True,
    )


# ---------------------------------------------------------------------------
# Cursor persistence — plain JSON file with atomic replace
# ---------------------------------------------------------------------------


def _load_cursor(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    cursor = data.get("cursor") if isinstance(data, dict) else None
    return cursor if isinstance(cursor, str) and cursor else None


def _persist_cursor(path: Path, cursor: str | None) -> None:
    if cursor is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"cursor": cursor}
    fd, tmp_path = tempfile.mkstemp(
        prefix=f"{path.name}-",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _last_event_id(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        eid = event.get("id")
        if isinstance(eid, str) and eid:
            return eid
    return None


def _rough_token_estimate(text: str) -> int:
    """Approximate token count using the ~4-chars-per-token heuristic.

    Client-side estimation is only used for budget pre-flight before
    the Claude call; actual spend always uses ``usage.input_tokens``
    from the response. The estimate is intentionally loose — we'd
    rather over-estimate and occasionally skip a benign tick than
    under-estimate and silently bust the cap.
    """
    if not text:
        return 0
    # Bias slightly high (divide by 3.5) so the pre-flight is
    # conservative — 30K true tokens ~= 34K estimated.
    return max(1, int(len(text) / 3.5))
