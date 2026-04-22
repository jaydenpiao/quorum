"""Tool schemas + tool-use dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import respx

from apps.llm_agent.quorum_api import QuorumApiClient
from apps.llm_agent.tools import (
    FINDING_TOOL_SCHEMA,
    TOOL_SCHEMAS,
    LlmToolError,
    ToolDispatchResult,
    dispatch_tool_use,
)


# ---------------------------------------------------------------------------
# Stub ToolUseBlock — matches the minimal surface dispatch_tool_use reads
# ---------------------------------------------------------------------------


@dataclass
class _FakeToolUse:
    """Duck-typed stand-in for ``anthropic.types.ToolUseBlock``.

    The dispatcher only reads ``.name``, ``.input``, and ``.id`` so we
    avoid pulling the real SDK class (which is constructed by the
    Messages API response parser in real code).
    """

    id: str
    name: str
    input: Any


@pytest.fixture
def quorum(monkeypatch: pytest.MonkeyPatch) -> QuorumApiClient:
    monkeypatch.setenv("QUORUM_API_KEYS", "telemetry-llm-agent:test-plaintext-abc")
    return QuorumApiClient(
        base_url="http://localhost:8080",
        agent_id="telemetry-llm-agent",
    )


# ---------------------------------------------------------------------------
# Schema contract — catches accidental breaking changes
# ---------------------------------------------------------------------------


def test_finding_tool_schema_is_complete() -> None:
    schema = FINDING_TOOL_SCHEMA
    assert schema["name"] == "create_finding"
    assert "description" in schema
    assert schema["input_schema"]["type"] == "object"
    props = schema["input_schema"]["properties"]
    for field_name in ("intent_id", "summary", "evidence_refs", "confidence"):
        assert field_name in props, f"missing {field_name}"
    assert set(schema["input_schema"]["required"]) == {"intent_id", "summary"}
    # agent_id must NOT be present — server-side actor binding sets it.
    assert "agent_id" not in props


def test_tool_schemas_are_sorted_by_name() -> None:
    """Stable prefix bytes → stable prompt caching."""
    names = [t["name"] for t in TOOL_SCHEMAS]
    assert names == sorted(names)


# ---------------------------------------------------------------------------
# dispatch_tool_use — happy path
# ---------------------------------------------------------------------------


def test_dispatch_create_finding_happy_path(quorum: QuorumApiClient) -> None:
    block = _FakeToolUse(
        id="toolu_abc",
        name="create_finding",
        input={"intent_id": "intent_x", "summary": "spike"},
    )

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://localhost:8080/api/v1/findings").mock(
            return_value=httpx.Response(200, json={"id": "finding_abc"})
        )
        result = dispatch_tool_use(block, quorum)  # type: ignore[arg-type]

    assert result.ok is True
    assert result.tool_name == "create_finding"
    assert result.tool_use_id == "toolu_abc"
    assert result.quorum_entity_id == "finding_abc"
    assert result.api_status_code == 200
    assert route.call_count == 1


def test_dispatch_forwards_input_verbatim(quorum: QuorumApiClient) -> None:
    """The dispatcher does not pre-validate — the Quorum API is the
    source of truth. Tool input forwards byte-for-byte."""
    block = _FakeToolUse(
        id="toolu_x",
        name="create_finding",
        input={
            "intent_id": "i1",
            "summary": "s1",
            "evidence_refs": ["evt_1", "evt_2"],
            "confidence": 0.75,
        },
    )

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://localhost:8080/api/v1/findings").mock(
            return_value=httpx.Response(200, json={"id": "finding_ok"})
        )
        dispatch_tool_use(block, quorum)  # type: ignore[arg-type]

    import json as _json

    sent = _json.loads(route.calls.last.request.content)
    assert sent == {
        "intent_id": "i1",
        "summary": "s1",
        "evidence_refs": ["evt_1", "evt_2"],
        "confidence": 0.75,
    }


# ---------------------------------------------------------------------------
# Failure modes that return a ToolDispatchResult (ok=False)
# ---------------------------------------------------------------------------


def test_dispatch_reports_quorum_4xx_as_not_ok(quorum: QuorumApiClient) -> None:
    block = _FakeToolUse(
        id="toolu_bad",
        name="create_finding",
        input={"intent_id": "x", "summary": "y"},
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://localhost:8080/api/v1/findings").mock(
            return_value=httpx.Response(422, json={"detail": "intent_id not found"})
        )
        result = dispatch_tool_use(block, quorum)  # type: ignore[arg-type]

    assert result.ok is False
    assert result.api_status_code == 422
    assert "intent_id not found" in result.detail


def test_dispatch_reports_quorum_401_as_not_ok(quorum: QuorumApiClient) -> None:
    block = _FakeToolUse(
        id="toolu_auth",
        name="create_finding",
        input={"intent_id": "x", "summary": "y"},
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://localhost:8080/api/v1/findings").mock(
            return_value=httpx.Response(401, json={"detail": "invalid api key"})
        )
        result = dispatch_tool_use(block, quorum)  # type: ignore[arg-type]

    assert result.ok is False
    assert result.api_status_code == 401


def test_dispatch_reports_missing_id_in_response(quorum: QuorumApiClient) -> None:
    """Quorum returns 200 but body has no ``id`` — treat as failed."""
    block = _FakeToolUse(
        id="toolu_x",
        name="create_finding",
        input={"intent_id": "x", "summary": "y"},
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://localhost:8080/api/v1/findings").mock(
            return_value=httpx.Response(200, json={"other_field": "nope"})
        )
        result = dispatch_tool_use(block, quorum)  # type: ignore[arg-type]

    assert result.ok is False
    assert "no id" in result.detail


# ---------------------------------------------------------------------------
# Failure modes that raise LlmToolError (structurally unusable)
# ---------------------------------------------------------------------------


def test_unknown_tool_raises(quorum: QuorumApiClient) -> None:
    block = _FakeToolUse(id="toolu_x", name="get_weather", input={"city": "Paris"})
    with pytest.raises(LlmToolError, match="unknown tool"):
        dispatch_tool_use(block, quorum)  # type: ignore[arg-type]


def test_non_dict_input_raises(quorum: QuorumApiClient) -> None:
    block = _FakeToolUse(id="toolu_x", name="create_finding", input="not-a-dict")
    with pytest.raises(LlmToolError, match="must be an object"):
        dispatch_tool_use(block, quorum)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Result is a frozen dataclass
# ---------------------------------------------------------------------------


def test_result_is_frozen() -> None:
    r = ToolDispatchResult(
        tool_name="create_finding",
        tool_use_id="toolu_x",
        ok=True,
        detail="ok",
    )
    with pytest.raises((AttributeError, TypeError)):
        r.ok = False  # type: ignore[misc]
