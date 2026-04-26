"""Tick loop orchestration — full round-trip (events → Claude → Quorum)."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

import anthropic
import httpx
import pytest
import respx

from apps.llm_agent.budget import LlmBudget, TickBudgetExceeded
from apps.llm_agent.claude_client import ClaudeClient
from apps.llm_agent.config import LlmAgentConfig
import apps.llm_agent.loop as loop_module
from apps.llm_agent.loop import run_tick
from apps.llm_agent.quorum_api import QuorumApiClient


def _config(**overrides: object) -> LlmAgentConfig:
    defaults: dict[str, object] = {
        "system_prompt_ref": "prompts/telemetry-agent.md",
        "max_events_per_tick": 50,
    }
    defaults.update(overrides)
    return LlmAgentConfig.model_validate(defaults)


@pytest.fixture
def quorum(monkeypatch: pytest.MonkeyPatch) -> QuorumApiClient:
    monkeypatch.setenv("QUORUM_API_KEYS", "telemetry-llm-agent:test-plaintext-abc")
    return QuorumApiClient(
        base_url="http://localhost:8080",
        agent_id="telemetry-llm-agent",
    )


@pytest.fixture
def claude() -> ClaudeClient:
    sdk = anthropic.Anthropic(api_key="test-key-ignored", max_retries=0)
    return ClaudeClient(_config(), system_prompt="ROLE: telemetry", sdk=sdk)


@pytest.fixture
def budget(tmp_path: Path) -> LlmBudget:
    return LlmBudget(
        agent_id="telemetry-llm-agent",
        daily_cap=1_000_000,
        per_tick_cap=100_000,
        storage_dir=tmp_path,
    )


@pytest.fixture
def cursor_path(tmp_path: Path) -> Path:
    return tmp_path / "cursor.json"


def _events(*ids: str) -> list[dict[str, Any]]:
    return [{"id": i, "event_type": "intent_created"} for i in ids]


class _CapturedLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **kwargs: Any) -> None:
        self.events.append((event, dict(kwargs)))

    def warning(self, event: str, **kwargs: Any) -> None:
        self.events.append((event, dict(kwargs)))


class _CapturedMetrics:
    def __init__(self) -> None:
        self.llm_calls: list[dict[str, Any]] = []
        self.ticks: list[dict[str, str]] = []
        self.proposals: list[dict[str, str]] = []

    def record_llm_call(self, **kwargs: Any) -> None:
        self.llm_calls.append(dict(kwargs))

    def record_tick(self, *, agent_id: str, outcome: str) -> None:
        self.ticks.append({"agent_id": agent_id, "outcome": outcome})

    def record_proposal_created(self, *, agent_id: str, action_type: str) -> None:
        self.proposals.append({"agent_id": agent_id, "action_type": action_type})


def _claude_response(
    *,
    tool_calls: list[dict[str, Any]] | None = None,
    stop_reason: str = "end_turn",
    input_tokens: int = 1234,
    output_tokens: int = 56,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": "ok"}]
    if tool_calls:
        for i, call in enumerate(tool_calls):
            content.append(
                {
                    "type": "tool_use",
                    "id": call.get("id", f"toolu_{i}"),
                    "name": call["name"],
                    "input": call["input"],
                }
            )
    return {
        "id": "msg_01ABC",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-4-7",
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "content": content,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }


# ---------------------------------------------------------------------------
# Idle tick — no Claude call, no cursor advance
# ---------------------------------------------------------------------------


def test_idle_tick_skips_claude_call(
    budget: LlmBudget,
    claude: ClaudeClient,
    quorum: QuorumApiClient,
    cursor_path: Path,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        events_route = mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=[])
        )
        anthropic_route = mock.post("https://api.anthropic.com/v1/messages")

        outcome = run_tick(budget=budget, claude=claude, quorum=quorum, cursor_path=cursor_path)

    assert outcome.events_seen == 0
    assert outcome.claude_called is False
    assert outcome.cursor is None
    assert not cursor_path.exists()
    assert events_route.call_count == 1
    assert anthropic_route.call_count == 0, "no Claude call on idle tick"


# ---------------------------------------------------------------------------
# Happy path — events → Claude → create_finding tool call → Quorum POST
# ---------------------------------------------------------------------------


def test_tick_dispatches_create_finding(
    budget: LlmBudget,
    claude: ClaudeClient,
    quorum: QuorumApiClient,
    cursor_path: Path,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=_events("evt_1", "evt_2"))
        )
        claude_route = mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json=_claude_response(
                    tool_calls=[
                        {
                            "id": "toolu_abc",
                            "name": "create_finding",
                            "input": {
                                "intent_id": "intent_xyz",
                                "summary": "spike in failed health checks",
                                "confidence": 0.8,
                            },
                        }
                    ]
                ),
            )
        )
        findings_route = mock.post("http://localhost:8080/api/v1/findings").mock(
            return_value=httpx.Response(200, json={"id": "finding_abc"})
        )

        outcome = run_tick(budget=budget, claude=claude, quorum=quorum, cursor_path=cursor_path)

    assert outcome.claude_called is True
    assert outcome.events_seen == 2
    assert outcome.cursor == "evt_2"
    assert outcome.input_tokens == 1234
    assert outcome.output_tokens == 56
    assert outcome.stop_reason == "end_turn"
    assert len(outcome.tool_calls) == 1
    assert outcome.tool_calls[0].ok is True
    assert outcome.tool_calls[0].tool_name == "create_finding"
    assert outcome.tool_calls[0].quorum_entity_id == "finding_abc"

    assert claude_route.call_count == 1
    assert findings_route.call_count == 1
    # Cursor advanced + persisted
    assert json.loads(cursor_path.read_text())["cursor"] == "evt_2"


# ---------------------------------------------------------------------------
# Budget — actual usage recorded, not just estimate
# ---------------------------------------------------------------------------


def test_tick_records_actual_input_tokens(
    budget: LlmBudget,
    claude: ClaudeClient,
    quorum: QuorumApiClient,
    cursor_path: Path,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=_events("evt_1"))
        )
        mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200, json=_claude_response(input_tokens=5678, output_tokens=100)
            )
        )

        run_tick(budget=budget, claude=claude, quorum=quorum, cursor_path=cursor_path)

    assert budget.status().daily_used == 5678


def test_user_content_includes_control_plane_context() -> None:
    content = loop_module._build_user_content(
        cursor="evt_0",
        events=_events("evt_1"),
        control_plane_fly_app="quorum-staging",
    )

    payload = json.loads(content)
    assert payload["control_plane"] == {
        "fly_app": "quorum-staging",
        "same_app_fly_deploy_allowed": False,
    }
    assert payload["events"] == _events("evt_1")


def test_llm_call_completed_logs_system_prompt_sha256(
    monkeypatch: pytest.MonkeyPatch,
    budget: LlmBudget,
    claude: ClaudeClient,
    quorum: QuorumApiClient,
    cursor_path: Path,
) -> None:
    captured = _CapturedLogger()
    monkeypatch.setattr(loop_module, "_log", captured)

    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=_events("evt_1"))
        )
        mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json=_claude_response())
        )

        run_tick(budget=budget, claude=claude, quorum=quorum, cursor_path=cursor_path)

    call_logs = [payload for event, payload in captured.events if event == "llm_call_completed"]
    assert len(call_logs) == 1
    expected = hashlib.sha256(claude.system_prompt_text.encode("utf-8")).hexdigest()
    assert call_logs[0]["system_prompt_sha256"] == expected
    assert len(call_logs[0]["system_prompt_sha256"]) == 64
    assert claude.system_prompt_text not in json.dumps(call_logs[0])


def test_tick_records_prometheus_metrics_for_successful_proposal(
    monkeypatch: pytest.MonkeyPatch,
    budget: LlmBudget,
    claude: ClaudeClient,
    quorum: QuorumApiClient,
    cursor_path: Path,
) -> None:
    captured = _CapturedMetrics()
    monkeypatch.setattr(loop_module, "_metrics", captured)

    proposal_input = {
        "intent_id": "intent_123",
        "title": "Comment on fixture issue",
        "action_type": "github.comment_issue",
        "target": "github:jaydenpiao/quorum-actuator-fixtures#1",
        "risk": "low",
        "rationale": "fixture smoke",
        "payload": {
            "owner": "jaydenpiao",
            "repo": "quorum-actuator-fixtures",
            "issue_number": 1,
            "body": "hello",
        },
    }

    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=_events("evt_1"))
        )
        mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json=_claude_response(
                    tool_calls=[
                        {
                            "id": "toolu_proposal",
                            "name": "create_proposal",
                            "input": proposal_input,
                        }
                    ],
                    input_tokens=123,
                    output_tokens=45,
                ),
            )
        )
        mock.post("http://localhost:8080/api/v1/proposals").mock(
            return_value=httpx.Response(
                200,
                json={
                    "proposal": {"id": "proposal_123"},
                    "policy_decision": {"allowed": True},
                },
            )
        )

        outcome = run_tick(budget=budget, claude=claude, quorum=quorum, cursor_path=cursor_path)

    assert outcome.tool_calls[0].ok is True
    assert captured.llm_calls == [
        {
            "agent_id": "telemetry-llm-agent",
            "model": "claude-opus-4-7",
            "input_tokens": 123,
            "output_tokens": 45,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }
    ]
    assert captured.proposals == [
        {"agent_id": "telemetry-llm-agent", "action_type": "github.comment_issue"}
    ]
    assert captured.ticks == [{"agent_id": "telemetry-llm-agent", "outcome": "acted"}]


# ---------------------------------------------------------------------------
# Refusal — Claude refuses, no tool dispatch, cursor still advances
# ---------------------------------------------------------------------------


def test_tick_handles_refusal(
    budget: LlmBudget,
    claude: ClaudeClient,
    quorum: QuorumApiClient,
    cursor_path: Path,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=_events("evt_1"))
        )
        mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json=_claude_response(
                    tool_calls=[
                        {
                            "id": "toolu_refused",
                            "name": "create_finding",
                            "input": {"intent_id": "x", "summary": "y"},
                        }
                    ],
                    stop_reason="refusal",
                ),
            )
        )
        findings_route = mock.post("http://localhost:8080/api/v1/findings")

        outcome = run_tick(budget=budget, claude=claude, quorum=quorum, cursor_path=cursor_path)

    assert outcome.claude_called is True
    assert outcome.stop_reason == "refusal"
    assert outcome.tool_calls == [], "refusal → no tool dispatch"
    assert findings_route.call_count == 0
    # Cursor still advances so we don't re-feed the same events next tick.
    assert outcome.cursor == "evt_1"


# ---------------------------------------------------------------------------
# Tool dispatch failure — Quorum rejects the finding
# ---------------------------------------------------------------------------


def test_tick_records_tool_failure_but_continues(
    budget: LlmBudget,
    claude: ClaudeClient,
    quorum: QuorumApiClient,
    cursor_path: Path,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=_events("evt_1"))
        )
        mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json=_claude_response(
                    tool_calls=[
                        {
                            "id": "toolu_bad",
                            "name": "create_finding",
                            "input": {"intent_id": "x", "summary": "y"},
                        }
                    ]
                ),
            )
        )
        # Quorum rejects with 422 — per-tool failure, not a tick failure.
        mock.post("http://localhost:8080/api/v1/findings").mock(
            return_value=httpx.Response(422, json={"detail": "intent_id not found"})
        )

        outcome = run_tick(budget=budget, claude=claude, quorum=quorum, cursor_path=cursor_path)

    # The tick itself completes; the tool dispatch records ok=False.
    assert outcome.claude_called is True
    assert len(outcome.tool_calls) == 1
    assert outcome.tool_calls[0].ok is False
    assert outcome.tool_calls[0].api_status_code == 422


# ---------------------------------------------------------------------------
# Multiple tool calls in one response
# ---------------------------------------------------------------------------


def test_tick_dispatches_multiple_tool_calls(
    budget: LlmBudget,
    claude: ClaudeClient,
    quorum: QuorumApiClient,
    cursor_path: Path,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=_events("evt_1"))
        )
        mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json=_claude_response(
                    tool_calls=[
                        {
                            "id": "toolu_1",
                            "name": "create_finding",
                            "input": {"intent_id": "i1", "summary": "s1"},
                        },
                        {
                            "id": "toolu_2",
                            "name": "create_finding",
                            "input": {"intent_id": "i2", "summary": "s2"},
                        },
                    ]
                ),
            )
        )
        mock.post("http://localhost:8080/api/v1/findings").mock(
            side_effect=[
                httpx.Response(200, json={"id": "finding_1"}),
                httpx.Response(200, json={"id": "finding_2"}),
            ]
        )

        outcome = run_tick(budget=budget, claude=claude, quorum=quorum, cursor_path=cursor_path)

    assert len(outcome.tool_calls) == 2
    assert [r.quorum_entity_id for r in outcome.tool_calls] == [
        "finding_1",
        "finding_2",
    ]
    assert all(r.ok for r in outcome.tool_calls)


# ---------------------------------------------------------------------------
# Cursor resume across runs
# ---------------------------------------------------------------------------


def test_tick_resumes_from_persisted_cursor(
    budget: LlmBudget,
    claude: ClaudeClient,
    quorum: QuorumApiClient,
    cursor_path: Path,
) -> None:
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    cursor_path.write_text(json.dumps({"cursor": "evt_2"}), encoding="utf-8")

    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=_events("evt_1", "evt_2", "evt_3", "evt_4"))
        )
        mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json=_claude_response())
        )

        outcome = run_tick(budget=budget, claude=claude, quorum=quorum, cursor_path=cursor_path)

    # Only evt_3 + evt_4 are "new"; cursor advances to evt_4.
    assert outcome.events_seen == 2
    assert outcome.cursor == "evt_4"


# ---------------------------------------------------------------------------
# Budget pre-flight — rejected ticks do not call Claude
# ---------------------------------------------------------------------------


def test_budget_rejection_blocks_claude_call(
    claude: ClaudeClient,
    quorum: QuorumApiClient,
    cursor_path: Path,
    tmp_path: Path,
) -> None:
    tight = LlmBudget(
        agent_id="telemetry-llm-agent",
        daily_cap=1_000_000,
        per_tick_cap=10,  # way too small
        storage_dir=tmp_path,
    )
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=_events("evt_1", "evt_2"))
        )
        anthropic_route = mock.post("https://api.anthropic.com/v1/messages")

        with pytest.raises(TickBudgetExceeded):
            run_tick(budget=tight, claude=claude, quorum=quorum, cursor_path=cursor_path)

    assert anthropic_route.call_count == 0, (
        "budget pre-flight must block Claude call before spending"
    )
    assert not cursor_path.exists()
