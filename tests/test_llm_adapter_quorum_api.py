"""HTTP client the adapter uses to call the Quorum API."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from apps.llm_agent.quorum_api import QuorumApiClient, QuorumApiError


def _client(monkeypatch: pytest.MonkeyPatch, *, api_key: str | None = None) -> QuorumApiClient:
    if api_key is None:
        monkeypatch.setenv(
            "QUORUM_API_KEYS",
            "telemetry-llm-agent:test-plaintext-abc,operator:other",
        )
    return QuorumApiClient(
        base_url="http://localhost:8080",
        agent_id="telemetry-llm-agent",
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Construction + API key resolution
# ---------------------------------------------------------------------------


def test_construction_requires_non_empty_base_url() -> None:
    with pytest.raises(ValueError):
        QuorumApiClient(base_url="", agent_id="x", api_key="k")


def test_construction_resolves_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUORUM_API_KEYS", "telemetry-llm-agent:my-key")
    client = QuorumApiClient(base_url="http://x", agent_id="telemetry-llm-agent")
    # The Authorization header is constructed per-request; assert indirectly
    # via a mocked call.
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get("http://x/api/v1/events").mock(return_value=httpx.Response(200, json=[]))
        client.list_events()
        assert route.calls.last.request.headers["Authorization"] == "Bearer my-key"


def test_construction_raises_without_env_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUORUM_API_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="QUORUM_API_KEYS"):
        QuorumApiClient(base_url="http://x", agent_id="telemetry-llm-agent")


def test_construction_raises_when_env_lacks_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUORUM_API_KEYS", "operator:other-key")
    with pytest.raises(RuntimeError, match="no entry"):
        QuorumApiClient(base_url="http://x", agent_id="telemetry-llm-agent")


def test_control_plane_app_infers_from_fly_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUORUM_API_KEYS", "deploy-llm-agent:test-plaintext-abc")
    client = QuorumApiClient(
        base_url="https://quorum-staging.fly.dev",
        agent_id="deploy-llm-agent",
    )

    assert client.control_plane_fly_app == "quorum-staging"


def test_control_plane_app_can_be_set_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUORUM_API_KEYS", "deploy-llm-agent:test-plaintext-abc")
    client = QuorumApiClient(
        base_url="http://internal-quorum-api",
        agent_id="deploy-llm-agent",
        control_plane_fly_app="quorum-prod",
    )

    assert client.control_plane_fly_app == "quorum-prod"


def test_control_plane_app_can_be_set_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUORUM_API_KEYS", "deploy-llm-agent:test-plaintext-abc")
    monkeypatch.setenv("QUORUM_LLM_CONTROL_PLANE_FLY_APP", "quorum-staging")
    client = QuorumApiClient(
        base_url="http://internal-quorum-api",
        agent_id="deploy-llm-agent",
    )

    assert client.control_plane_fly_app == "quorum-staging"


# ---------------------------------------------------------------------------
# list_events
# ---------------------------------------------------------------------------


def test_list_events_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    events = [
        {"id": "evt_1", "event_type": "intent_created"},
        {"id": "evt_2", "event_type": "proposal_created"},
    ]
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=events)
        )
        result = client.list_events()
    assert result == events


def test_list_events_filters_after_cursor_client_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)
    events = [
        {"id": "evt_1"},
        {"id": "evt_2"},
        {"id": "evt_3"},
    ]
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=events)
        )
        result = client.list_events(since_id="evt_1")
    assert [e["id"] for e in result] == ["evt_2", "evt_3"]


def test_list_events_returns_all_when_cursor_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)
    events = [{"id": "evt_9"}, {"id": "evt_10"}]
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=events)
        )
        result = client.list_events(since_id="evt_unknown")
    assert result == events  # never-seen cursor → fall back to full list


def test_list_events_respects_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    events = [{"id": f"evt_{i}"} for i in range(10)]
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(200, json=events)
        )
        result = client.list_events(limit=3)
    assert len(result) == 3


# ---------------------------------------------------------------------------
# create_finding / create_proposal
# ---------------------------------------------------------------------------


def test_create_finding_posts_with_bearer_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://localhost:8080/api/v1/findings").mock(
            return_value=httpx.Response(200, json={"id": "finding_abc"})
        )
        result = client.create_finding({"intent_id": "intent_1", "summary": "hi"})

    assert result["id"] == "finding_abc"
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer test-plaintext-abc"
    assert json.loads(req.content) == {"intent_id": "intent_1", "summary": "hi"}


def test_create_proposal_posts_with_bearer_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://localhost:8080/api/v1/proposals").mock(
            return_value=httpx.Response(200, json={"id": "proposal_abc"})
        )
        result = client.create_proposal(
            {
                "intent_id": "intent_1",
                "title": "add label",
                "action_type": "github.add_labels",
                "target": "j/q#5",
                "rationale": "stale",
                "payload": {"labels": ["stale"]},
            }
        )
    assert result["id"] == "proposal_abc"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_non_2xx_raises_quorum_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            return_value=httpx.Response(401, json={"detail": "invalid api key"})
        )
        with pytest.raises(QuorumApiError) as exc:
            client.list_events()
    assert exc.value.status_code == 401
    assert "invalid api key" in exc.value.message


def test_transport_error_becomes_api_error_599(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://localhost:8080/api/v1/events").mock(
            side_effect=httpx.ConnectError("no route to host")
        )
        with pytest.raises(QuorumApiError) as exc:
            client.list_events()
    assert exc.value.status_code == 599
