"""Static checks for the read-only Phase 6 gate preflight."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_phase6_gate.sh"
CHECKLIST = ROOT / "docs" / "design" / "phase-6-gate-checklist.md"
CURRENT_MODE = ROOT / "docs" / "CURRENT_MODE.md"
HANDOFF = ROOT / "docs" / "SESSION_HANDOFF.md"
REPO_MAP = ROOT / "docs" / "REPO_MAP.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_phase6_gate_preflight_script_is_shell_valid() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_phase6_gate_preflight_fails_closed_before_not_before_date() -> None:
    env = {
        **os.environ,
        "QUORUM_PHASE6_TODAY": "2026-05-03",
    }

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "phase6-gate-closed" in output
    assert "not before 2026-05-14 UTC" in output
    assert "today_utc=2026-05-03" in output
    assert "QUORUM_PHASE6_TODAY=YYYY-MM-DD" in output


def test_phase6_gate_preflight_codifies_required_checks() -> None:
    text = _text(SCRIPT)

    assert "QUORUM_RELEASE_TAG" in text
    assert "QUORUM_PHASE6_NOT_BEFORE" in text
    assert "QUORUM_PHASE6_TODAY" in text
    assert "2026-05-14" in text
    assert "date -u +%F" in text
    assert "not_before_utc" in text
    assert "today_utc" in text
    assert "QUORUM_PHASE6_TODAY=YYYY-MM-DD" in text
    assert "scripts/check_event_schema_stability.sh" in text
    assert "schema-stability-ok" in text
    assert "QUORUM_SCHEMA_STABILITY_ANCHOR_TAG" in text
    assert "QUORUM_SCHEMA_STABILITY_BASE_REF" in text
    assert "scripts/check_live_release.sh" in text
    assert "live-release-ok" in text
    assert "CURRENT_MAIN_SHA" in text
    assert 'gh api "repos/${GITHUB_REPO}/branches/${MAIN_BRANCH}"' in text
    assert "gh run list" in text
    assert "current_main_sha" in text
    assert "headSha" in text
    assert "run_sha != current_main_sha" in text
    assert "latest {label} run is stale" in text
    assert "live-release-monitor.yml" in text
    assert "gh workflow run live-release-monitor.yml --repo {github_repo}" in text
    assert "--ref {main_branch} -f release_tag={release_tag}" in text
    assert "ci.yml" in text
    assert "security.yml" in text
    assert "image-push.yml" in text
    assert "gh pr list" in text
    assert "docs/releases/${RELEASE_TAG}-proof.md" in text
    assert "docs/SESSION_HANDOFF.md" in text
    assert "quorum-${RELEASE_TAG}.spdx.json" in text
    assert "phase6-gate-closed" in text
    assert "phase6-gate-ready" in text


def test_phase6_gate_runs_schema_stability_after_calendar_gate() -> None:
    text = _text(SCRIPT)

    calendar_index = text.index("phase6-gate-check: calendar ok")
    main_sha_index = text.index("phase6-gate-check: current-main ok")
    schema_index = text.index("scripts/check_event_schema_stability.sh")
    live_monitor_index = text.index("scripts/check_live_release.sh")

    assert calendar_index < main_sha_index < schema_index < live_monitor_index


def test_phase6_gate_preflight_is_documented_as_phase6_switch_gate() -> None:
    for path in (CHECKLIST, CURRENT_MODE, HANDOFF, REPO_MAP):
        text = _text(path)
        assert "scripts/check_phase6_gate.sh" in text
        assert "scripts/check_event_schema_stability.sh" in text

    assert "docs/PARALLEL_DEVELOPMENT.md" in _text(CHECKLIST)
    assert "docs/design/phase-6-readiness-checkpoint.md" in _text(CHECKLIST)
