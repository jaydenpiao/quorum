"""Version contract tests for package metadata and runtime surfaces."""

from __future__ import annotations

from importlib.metadata import version as package_version

from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.tracing import _SERVICE_VERSION
from apps.api.app.version import __version__, _format_display_version, display_version


client = TestClient(app)


def test_root_exposes_runtime_version() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["version"] == __version__
    assert response.json()["display_version"] == display_version


def test_display_version_is_derived_from_runtime_version() -> None:
    assert __version__ == "0.6.2"
    assert _format_display_version(__version__) == display_version
    assert _format_display_version("1.2.3a4") == "v1.2.3-alpha.4"
    assert _format_display_version("1.2.3") == "v1.2.3"
    assert display_version == "v0.6.2"


def test_fastapi_and_tracing_versions_match_runtime_version() -> None:
    assert app.version == __version__
    assert _SERVICE_VERSION == __version__


def test_installed_package_metadata_matches_runtime_version() -> None:
    assert package_version("quorum") == __version__
