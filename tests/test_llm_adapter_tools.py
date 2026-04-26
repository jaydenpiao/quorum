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


# ---------------------------------------------------------------------------
# create_proposal tool (PR 3)
# ---------------------------------------------------------------------------


from apps.llm_agent.tools import (  # noqa: E402
    LLM_ALLOWED_PROPOSAL_ACTION_TYPES,
    PROPOSAL_TOOL_SCHEMA,
)


def test_proposal_tool_schema_is_complete() -> None:
    schema = PROPOSAL_TOOL_SCHEMA
    assert schema["name"] == "create_proposal"
    props = schema["input_schema"]["properties"]
    for field in (
        "intent_id",
        "title",
        "action_type",
        "target",
        "environment",
        "risk",
        "rationale",
        "evidence_refs",
        "rollback_steps",
        "health_checks",
        "payload",
    ):
        assert field in props, f"missing {field}"
    assert set(schema["input_schema"]["required"]) == {
        "intent_id",
        "title",
        "action_type",
        "target",
        "rationale",
        "payload",
    }
    assert "agent_id" not in props, "server-side actor binding sets agent_id"


def test_proposal_action_type_enum_matches_allow_list() -> None:
    """The schema enum and the allow-list constant must stay in sync."""
    enum = PROPOSAL_TOOL_SCHEMA["input_schema"]["properties"]["action_type"]["enum"]
    assert sorted(enum) == sorted(LLM_ALLOWED_PROPOSAL_ACTION_TYPES)
    # High-blast-radius actions are NOT in the list.
    assert "github.open_pr" not in enum
    assert "github.close_pr" not in enum


def test_dispatch_create_proposal_happy_path(quorum: QuorumApiClient) -> None:
    block = _FakeToolUse(
        id="toolu_p1",
        name="create_proposal",
        input={
            "intent_id": "intent_x",
            "title": "label stale PR",
            "action_type": "github.add_labels",
            "target": "owner/repo#5",
            "rationale": "no activity for 30d",
            "payload": {
                "owner": "owner",
                "repo": "repo",
                "issue_number": 5,
                "labels": ["stale"],
            },
        },
    )

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://localhost:8080/api/v1/proposals").mock(
            return_value=httpx.Response(200, json={"id": "proposal_xyz"})
        )
        result = dispatch_tool_use(block, quorum)  # type: ignore[arg-type]

    assert result.ok is True
    assert result.tool_name == "create_proposal"
    assert result.quorum_entity_id == "proposal_xyz"
    assert route.call_count == 1


def test_dispatch_create_proposal_accepts_route_response_envelope(
    quorum: QuorumApiClient,
) -> None:
    """POST /proposals returns proposal + policy_decision, not a top-level id."""
    block = _FakeToolUse(
        id="toolu_p_envelope",
        name="create_proposal",
        input={
            "intent_id": "intent_x",
            "title": "deploy staging",
            "action_type": "fly.deploy",
            "target": "quorum-staging",
            "rationale": "fresh image-push evidence",
            "payload": {
                "app": "quorum-staging",
                "image_digest": "sha256:" + "a" * 64,
            },
        },
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://localhost:8080/api/v1/proposals").mock(
            return_value=httpx.Response(
                200,
                json={
                    "proposal": {"id": "proposal_nested"},
                    "policy_decision": {"proposal_id": "proposal_nested"},
                },
            )
        )
        result = dispatch_tool_use(block, quorum)  # type: ignore[arg-type]

    assert result.ok is True
    assert result.quorum_entity_id == "proposal_nested"
    assert result.detail == "created proposal proposal_nested"


def test_dispatch_create_proposal_rejects_disallowed_action_type(
    quorum: QuorumApiClient,
) -> None:
    """Client-side allow-list must reject before hitting Quorum."""
    block = _FakeToolUse(
        id="toolu_forbidden",
        name="create_proposal",
        input={
            "intent_id": "intent_x",
            "title": "open PR",
            "action_type": "github.open_pr",  # NOT in allow-list
            "target": "owner/repo",
            "rationale": "because",
            "payload": {},
        },
    )

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://localhost:8080/api/v1/proposals")
        result = dispatch_tool_use(block, quorum)  # type: ignore[arg-type]

    assert result.ok is False
    assert "not allowed" in result.detail
    assert route.call_count == 0, "client-side reject — never contacts Quorum"


def test_dispatch_rejects_same_control_plane_fly_deploy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUORUM_API_KEYS", "deploy-llm-agent:test-plaintext-abc")
    quorum = QuorumApiClient(
        base_url="https://quorum-staging.fly.dev",
        agent_id="deploy-llm-agent",
    )
    block = _FakeToolUse(
        id="toolu_same_app",
        name="create_proposal",
        input={
            "intent_id": "intent_x",
            "title": "deploy staging",
            "action_type": "fly.deploy",
            "target": "quorum-staging",
            "rationale": "fresh image-push evidence",
            "payload": {
                "app": "quorum-staging",
                "image_digest": "sha256:" + "a" * 64,
            },
        },
    )

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://quorum-staging.fly.dev/api/v1/proposals")
        result = dispatch_tool_use(block, quorum)  # type: ignore[arg-type]

    assert result.ok is False
    assert "same control-plane app" in result.detail
    assert route.call_count == 0


def test_dispatch_create_proposal_handles_server_403(
    quorum: QuorumApiClient,
) -> None:
    """Even if the client-side enum lets something through, the
    server's allowed_action_types gate is the authoritative one."""
    block = _FakeToolUse(
        id="toolu_srv_403",
        name="create_proposal",
        input={
            "intent_id": "intent_x",
            "title": "add label",
            "action_type": "github.add_labels",
            "target": "owner/repo#1",
            "rationale": "x",
            "payload": {
                "owner": "owner",
                "repo": "repo",
                "issue_number": 1,
                "labels": ["bug"],
            },
        },
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://localhost:8080/api/v1/proposals").mock(
            return_value=httpx.Response(
                403, json={"detail": "action_type 'github.add_labels' not allowed"}
            )
        )
        result = dispatch_tool_use(block, quorum)  # type: ignore[arg-type]

    assert result.ok is False
    assert result.api_status_code == 403
