"""Tests for Phase 2 HTTP hardening: security headers, CORS, pydantic strict mode."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app
from tests._helpers import AUTH


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_security_headers_present_on_root(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert "max-age" in response.headers.get("Strict-Transport-Security", "")
    csp = response.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp


def test_csp_script_src_no_unsafe_inline(client: TestClient) -> None:
    """script-src must not allow 'unsafe-inline' — console JS is a static file."""
    response = client.get("/")
    csp = response.headers.get("Content-Security-Policy", "")
    # Locate the script-src directive and confirm 'unsafe-inline' is absent.
    directives = {d.strip() for d in csp.split(";")}
    script_src = next((d for d in directives if d.startswith("script-src")), "")
    assert "'unsafe-inline'" not in script_src, (
        f"script-src must not contain 'unsafe-inline'; got CSP: {csp}"
    )


def test_security_headers_on_api_route(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


def test_cors_allows_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://127.0.0.1:8080",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Preflight should succeed and include ACA-Origin.
    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:8080"


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    # FastAPI/Starlette returns 400 on disallowed preflight or omits the ACA-Origin header.
    origin = response.headers.get("access-control-allow-origin")
    assert origin != "https://attacker.example"


def test_intent_create_rejects_extra_field(client: TestClient) -> None:
    response = client.post(
        "/api/v1/intents",
        json={
            "title": "t",
            "description": "d",
            "environment": "local",
            "requested_by": "operator",
            "injected_admin_flag": True,
        },
        headers=AUTH,
    )
    assert response.status_code == 422


def test_intent_create_rejects_oversize_title(client: TestClient) -> None:
    response = client.post(
        "/api/v1/intents",
        json={"title": "x" * 1000, "description": "d"},
        headers=AUTH,
    )
    assert response.status_code == 422


def test_vote_create_rejects_unknown_decision(client: TestClient) -> None:
    response = client.post(
        "/api/v1/votes",
        json={
            "proposal_id": "p_x",
            "agent_id": "a",
            "decision": "maybe",
            "reason": "",
        },
        headers=AUTH,
    )
    assert response.status_code == 422
