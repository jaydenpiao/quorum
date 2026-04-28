"""Version contract tests for package metadata and runtime surfaces."""

from __future__ import annotations

from importlib.metadata import version as package_version

from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.tracing import _SERVICE_VERSION
from apps.api.app.version import __version__


client = TestClient(app)


def test_root_exposes_runtime_version() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["version"] == __version__


def test_fastapi_and_tracing_versions_match_runtime_version() -> None:
    assert app.version == __version__
    assert _SERVICE_VERSION == __version__


def test_installed_package_metadata_matches_runtime_version() -> None:
    assert package_version("quorum") == __version__
