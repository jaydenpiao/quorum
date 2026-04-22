"""Tick loop orchestration (PR 1 — no-LLM-call version)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

import anthropic

from apps.llm_agent.budget import LlmBudget, TickBudgetExceeded
from apps.llm_agent.claude_client import ClaudeClient
from apps.llm_agent.config import LlmAgentConfig
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
    sdk = anthropic.Anthropic(api_key="test-key-ignored")
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


# ---------------------------------------------------------------------------
# Idle tick (no events)
# ---------------------------------------------------------------------------


def test_tick_with_no_events_is_noop(
    budget: LlmBudget,
    claude: ClaudeClient,
    quorum: QuorumApiClient,
    cursor_path: Path,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=[])
        )
        outcome = run_tick(budget=budget, claude=claude, quorum=quorum, cursor_path=cursor_path)

    assert outcome.events_seen == 0
    assert outcome.request_built is False
    assert outcome.cursor is None
    assert not cursor_path.exists(), "cursor only persists when new events are seen"


# ---------------------------------------------------------------------------
# Happy path — events → body built → cursor advanced
# ---------------------------------------------------------------------------


def test_tick_builds_body_and_advances_cursor(
    budget: LlmBudget,
    claude: ClaudeClient,
    quorum: QuorumApiClient,
    cursor_path: Path,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=_events("evt_1", "evt_2", "evt_3"))
        )
        outcome = run_tick(budget=budget, claude=claude, quorum=quorum, cursor_path=cursor_path)

    assert outcome.events_seen == 3
    assert outcome.request_built is True
    assert outcome.cursor == "evt_3"
    assert cursor_path.exists()
    assert json.loads(cursor_path.read_text())["cursor"] == "evt_3"


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
        outcome = run_tick(budget=budget, claude=claude, quorum=quorum, cursor_path=cursor_path)

    # Only evt_3 + evt_4 are "new"; cursor advances to evt_4.
    assert outcome.events_seen == 2
    assert outcome.cursor == "evt_4"


# ---------------------------------------------------------------------------
# Budget pre-flight
# ---------------------------------------------------------------------------


def test_tick_raises_when_estimate_exceeds_per_tick_cap(
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
        with pytest.raises(TickBudgetExceeded):
            run_tick(budget=tight, claude=claude, quorum=quorum, cursor_path=cursor_path)
    # Cursor must NOT advance when the tick was rejected by the budget —
    # the events still need to be processed on the next tick.
    assert not cursor_path.exists()
