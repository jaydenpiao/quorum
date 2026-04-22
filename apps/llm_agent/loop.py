"""Tick loop for the LLM adapter.

One tick of this loop is the full proposer-only lifecycle for the
telemetry agent:

1. Load the cursor (last-seen event id).
2. Poll Quorum for events since that cursor.
3. If zero new events → skip the tick. Log ``llm_tick_completed``
   with ``outcome=skipped_idle`` and return.
4. Build a compact JSON user message from the events (stable bytes
   across ticks so the system-prompt prefix caches).
5. Pre-flight the budget with a conservative token estimate. Raise
   ``BudgetExceededError`` before making the call.
6. Call Claude (``claude.call_messages``) with the ordered tool list.
7. Record actual ``usage.input_tokens`` on the budget so the daily
   counter is accurate even if the estimate was off.
8. Handle the response:
   - ``stop_reason == "refusal"`` → emit a refusal log, skip tool
     dispatch, still advance the cursor (the refusal was about this
     specific tick's events).
   - For each ``tool_use`` block → dispatch via ``tools.dispatch_tool_use``.
     Each dispatch POSTs to Quorum as the adapter's agent and returns
     a ``ToolDispatchResult`` we log + attach to the ``TickOutcome``.
9. Persist the cursor and log ``llm_tick_completed``.

Structlog event names emitted (metadata-only, never prompt content):
- ``llm_tick_started`` / ``llm_tick_completed``
- ``llm_call_completed`` — model, input/output tokens, cache hits,
  latency, tool-call names
- ``llm_tool_dispatch_completed`` — one per tool_use block processed

Nothing here writes to ``data/events.jsonl``. The adapter's only
contact surface with the control plane is the authenticated HTTP
POSTs from ``tools.dispatch_tool_use``.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic
import structlog

from apps.llm_agent.budget import LlmBudget
from apps.llm_agent.claude_client import ClaudeClient
from apps.llm_agent.quorum_api import QuorumApiClient
from apps.llm_agent.tools import TOOL_SCHEMAS, ToolDispatchResult, dispatch_tool_use

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TickOutcome:
    """What happened in one tick. Returned so tests can assert on it."""

    events_seen: int
    cursor: str | None
    claude_called: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    stop_reason: str | None = None
    tool_calls: list[ToolDispatchResult] = field(default_factory=list)


def run_tick(
    *,
    budget: LlmBudget,
    claude: ClaudeClient,
    quorum: QuorumApiClient,
    cursor_path: Path,
) -> TickOutcome:
    """Run one tick of the adapter loop.

    See module docstring for the full sequence. Returns a
    ``TickOutcome`` describing what happened.
    """
    agent_id = quorum.agent_id
    _log.info("llm_tick_started", agent_id=agent_id)

    cursor = _load_cursor(cursor_path)
    events = quorum.list_events(
        since_id=cursor,
        limit=claude.config.max_events_per_tick,
    )
    if not events:
        _log.info(
            "llm_tick_completed",
            agent_id=agent_id,
            outcome="skipped_idle",
            events_seen=0,
            cursor=cursor,
        )
        return TickOutcome(events_seen=0, cursor=cursor)

    user_content = _build_user_content(cursor, events)

    # Pre-flight the budget with a conservative estimate. The actual
    # token count from response.usage feeds record_tick() after the
    # call completes so the daily counter is accurate even if the
    # estimate was loose.
    estimated_tokens = _rough_token_estimate(user_content) + _rough_token_estimate(
        claude.system_prompt_text
    )
    budget.check_tick(estimated_tokens)

    # Actual Claude call. TOOL_SCHEMAS is pre-sorted (see tools.py) so
    # the prefix bytes are stable across ticks.
    call_started = time.monotonic()
    response = claude.call_messages(
        user_content=user_content,
        tools=TOOL_SCHEMAS,
    )
    latency_ms = int((time.monotonic() - call_started) * 1000)

    usage = response.usage
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    cache_read_tokens = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cache_write_tokens = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)

    budget.record_tick(input_tokens)

    _log.info(
        "llm_call_completed",
        agent_id=agent_id,
        model=claude.config.model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        latency_ms=latency_ms,
        stop_reason=response.stop_reason,
    )

    tool_results: list[ToolDispatchResult] = []
    if response.stop_reason == "refusal":
        _log.warning(
            "llm_tick_refusal",
            agent_id=agent_id,
            events_seen=len(events),
            cursor=cursor,
        )
    else:
        for block in response.content:
            if isinstance(block, anthropic.types.ToolUseBlock):
                result = dispatch_tool_use(block, quorum)
                _log.info(
                    "llm_tool_dispatch_completed",
                    agent_id=agent_id,
                    tool_name=result.tool_name,
                    tool_use_id=result.tool_use_id,
                    ok=result.ok,
                    api_status_code=result.api_status_code,
                    quorum_entity_id=result.quorum_entity_id,
                )
                tool_results.append(result)

    new_cursor = _last_event_id(events) or cursor
    _persist_cursor(cursor_path, new_cursor)

    _log.info(
        "llm_tick_completed",
        agent_id=agent_id,
        outcome="ok" if response.stop_reason != "refusal" else "refusal",
        events_seen=len(events),
        cursor=new_cursor,
        tool_calls=len(tool_results),
        tools_ok=sum(1 for r in tool_results if r.ok),
    )
    return TickOutcome(
        events_seen=len(events),
        cursor=new_cursor,
        claude_called=True,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        stop_reason=response.stop_reason,
        tool_calls=tool_results,
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


def _build_user_content(cursor: str | None, events: list[dict[str, Any]]) -> str:
    """Deterministic JSON blob for the per-tick user message.

    Stable key order + compact separators so repeated ticks with the
    same events produce identical bytes — this is the prefix caching
    cares about.
    """
    return json.dumps(
        {"cursor_from": cursor, "events": events},
        sort_keys=True,
        separators=(",", ":"),
    )


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
