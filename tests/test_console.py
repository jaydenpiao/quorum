"""Tests for the operator console static assets."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_app_js_served(client: TestClient) -> None:
    """GET /console-static/app.js returns 200 with JS content-type and a known symbol."""
    response = client.get("/console-static/app.js")
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    # Starlette may return application/javascript or text/javascript.
    assert "javascript" in content_type, f"Unexpected Content-Type: {content_type}"
    assert "no-store" in response.headers.get("cache-control", "")
    assert "loadState" in response.text
    assert "DEMO_TOKEN_FALLBACK" in response.text
    assert "ensureDemoToken" in response.text


def test_console_shell_references_external_stylesheet(client: TestClient) -> None:
    response = client.get("/console")

    assert response.status_code == 200
    assert "no-store" in response.headers.get("cache-control", "")
    assert "/console-static/styles.css" in response.text
    assert "Seed dog-food deploy demo" in response.text
    assert "Seed demo incident" not in response.text
    assert "POC console" not in response.text
    assert "<style>" not in response.text
    assert '<script defer src="/console-static/app.js"></script>' in response.text


def test_console_stylesheet_served(client: TestClient) -> None:
    response = client.get("/console-static/styles.css")

    assert response.status_code == 200
    assert "css" in response.headers.get("content-type", "")
    assert "no-store" in response.headers.get("cache-control", "")
    assert ".proposal-table" in response.text
    assert ".timeline" in response.text
