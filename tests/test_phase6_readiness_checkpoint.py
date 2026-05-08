"""Static checks for the Phase 6 readiness checkpoint."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "docs" / "design" / "phase-6-readiness-checkpoint.md"
CHECKLIST = ROOT / "docs" / "design" / "phase-6-gate-checklist.md"
CURRENT_MODE = ROOT / "docs" / "CURRENT_MODE.md"
HANDOFF = ROOT / "docs" / "SESSION_HANDOFF.md"
REPO_MAP = ROOT / "docs" / "REPO_MAP.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_checkpoint_records_current_release_and_gate_state() -> None:
    text = _text(CHECKPOINT)

    assert "v0.6.7" in text
    assert "2026-05-08" in text
    assert "2026-05-14" in text
    assert "1e1758b77856d67a9bfe4f3753be4506eb09954f" in text
    assert "phase6-gate-closed: not before 2026-05-14" in text
    assert "phase6-gate-ready" in text


def test_checkpoint_records_live_proof_commands_and_results() -> None:
    text = _text(CHECKPOINT)

    assert "QUORUM_RELEASE_TAG=v0.6.7 scripts/check_live_release.sh" in text
    assert "QUORUM_RELEASE_TAG=v0.6.7 scripts/check_console_proof.sh" in text
    assert "QUORUM_RELEASE_TAG=v0.6.7 scripts/check_release_proof_archive.sh" in text
    assert "QUORUM_RELEASE_TAG=v0.6.7 scripts/check_phase6_gate.sh" in text
    assert "live-release-ok: v0.6.7" in text
    assert (
        "console-proof-ok: https://quorum-staging.fly.dev/console?proposal_id=proposal_bab1a4a4913d#proposals"
        in text
    )
    assert "release-proof-archive-ok: v0.6.7 proof=docs/releases/v0.6.7-proof.md" in text


def test_checkpoint_records_workflow_and_monitor_evidence() -> None:
    text = _text(CHECKPOINT)

    assert "25562191387" in text
    assert "25562191332" in text
    assert "25562191390" in text
    assert "25560652276" in text
    assert "25425183614" in text
    assert "non-current" in text
    assert "$GITHUB_STEP_SUMMARY" in text


def test_checkpoint_records_schema_stability_preflight_and_no_go_triggers() -> None:
    text = _text(CHECKPOINT)

    assert "scripts/check_event_schema_stability.sh" in text
    assert "QUORUM_SCHEMA_STABILITY_ANCHOR_TAG=v0.6.3" in text
    assert "QUORUM_SCHEMA_STABILITY_BASE_REF=HEAD" in text
    assert "schema-stability-ok: anchor=v0.6.3 base=HEAD" in text
    assert "apps/api/app/domain/models.py" in text
    assert "apps/api/app/services/state_store.py" in text
    assert "apps/api/app/services/postgres_projector.py" in text
    assert "alembic/versions" in text
    assert "examples" in text
    assert "resets the 14-day" in text
    assert "blocks Phase 6" in text


def test_checkpoint_is_discoverable_from_operator_docs() -> None:
    checkpoint_path = "docs/design/phase-6-readiness-checkpoint.md"

    assert checkpoint_path in _text(CHECKLIST)
    assert checkpoint_path in _text(HANDOFF)
    assert checkpoint_path in _text(REPO_MAP)
    assert "scripts/check_event_schema_stability.sh" in _text(CURRENT_MODE)
