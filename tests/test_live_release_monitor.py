"""Static checks for the live release monitor."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_live_release.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "live-release-monitor.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_live_release_monitor_checks_required_surfaces() -> None:
    text = _text(SCRIPT)

    assert "QUORUM_RELEASE_TAG" in text
    assert "https://quorum-staging.fly.dev" in text
    assert "https://quorum-prod.fly.dev" in text
    assert "/readiness" in text
    assert "/api/v1/health" in text
    assert "/api/v1/events/verify" in text
    assert "display_version" in text
    assert "ok=true" in text


def test_live_release_monitor_checks_github_release_and_main_status() -> None:
    text = _text(SCRIPT)

    assert "gh release view" in text
    assert "quorum-${RELEASE_TAG}.spdx.json" in text
    assert "gh run list" in text
    assert "ci.yml" in text
    assert "security.yml" in text
    assert "completed" in text
    assert "success" in text


def test_live_release_monitor_workflow_runs_without_secrets() -> None:
    text = _text(WORKFLOW)

    assert "workflow_dispatch:" in text
    assert "schedule:" in text
    assert "GH_TOKEN: ${{ github.token }}" in text
    assert "QUORUM_RELEASE_TAG: v0.6.3" in text
    assert "scripts/check_live_release.sh" in text
    assert "secrets." not in text
    assert "actions: read" in text
    assert "contents: read" in text
