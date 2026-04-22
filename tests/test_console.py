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
    assert "loadState" in response.text
