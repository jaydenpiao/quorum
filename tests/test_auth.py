"""Tests for Phase 2 bearer-token authentication and demo endpoint gating."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.services import auth as auth_module
from tests._helpers import AUTH


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_write_without_token_returns_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/intents",
        json={"title": "x", "description": "y"},
    )
    assert response.status_code == 401
    assert "bearer" in response.json()["detail"].lower()


def test_write_with_wrong_token_returns_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/intents",
        json={"title": "x", "description": "y"},
        headers={"Authorization": "Bearer not-a-real-key"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid api key"


def test_write_with_non_bearer_scheme_returns_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/intents",
        json={"title": "x", "description": "y"},
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert response.status_code == 401


def test_read_routes_remain_unauthenticated(client: TestClient) -> None:
    """Read-only routes do not require auth (console, liveness use them)."""
    for path in ["/api/v1/health", "/api/v1/state", "/api/v1/events"]:
        response = client.get(path)
        assert response.status_code == 200, f"{path} should be public-read"


def test_demo_endpoint_requires_auth(client: TestClient) -> None:
    response = client.post("/api/v1/demo/incident")
    assert response.status_code == 401


def test_demo_endpoint_respects_env_flag(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUORUM_ALLOW_DEMO", "0")
    response = client.post("/api/v1/demo/incident", headers=AUTH)
    assert response.status_code == 404


def test_valid_key_returns_agent_id() -> None:
    auth_module.reload_registry()
    registry = auth_module._load_registry()
    assert "operator-key-dev" in registry
    assert registry["operator-key-dev"] == "test-operator"


def test_empty_registry_rejects_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no keys are configured, the server rejects every request with 401."""
    monkeypatch.setenv("QUORUM_API_KEYS", "")
    auth_module.reload_registry()
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/intents",
            json={"title": "x", "description": "y"},
            headers=AUTH,
        )
        assert response.status_code == 401
        assert "no api keys" in response.json()["detail"].lower()
    finally:
        # Restore the registry for subsequent tests.
        os.environ["QUORUM_API_KEYS"] = (
            "test-operator:operator-key-dev,telemetry-agent:telemetry-key-dev,code-agent:code-key-dev"
        )
        auth_module.reload_registry()
