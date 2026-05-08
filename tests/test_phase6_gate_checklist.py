"""Static checks for the Phase 6 gate checklist."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = ROOT / "docs" / "design" / "phase-6-gate-checklist.md"
HANDOFF = ROOT / "docs" / "SESSION_HANDOFF.md"
REPO_MAP = ROOT / "docs" / "REPO_MAP.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_phase6_gate_checklist_records_required_gates() -> None:
    text = _text(CHECKLIST)

    assert "2026-05-14" in text
    assert "14 days" in text
    assert "event schema" in text
    assert "event payload" in text
    assert "proposal, vote, execution, rollback" in text
    assert "lint + format +" in text
    assert "gitleaks" in text
    assert "pip-audit" in text
    assert "docker build" in text
    assert "mypy" in text
    assert "scripts/check_live_release.sh" in text
    assert "scripts/check_event_schema_stability.sh" in text
    assert "QUORUM_SCHEMA_STABILITY_ANCHOR_TAG=v0.6.3" in text
    assert "docs/releases/" in text
    assert "docs/PARALLEL_DEVELOPMENT.md" in text
    assert "docs/design/phase-6-readiness-checkpoint.md" in text
    assert "docs/design/phase-6-entry-plan.md" in text


def test_phase6_gate_checklist_records_no_go_and_fallback_rules() -> None:
    text = _text(CHECKLIST)

    assert "resets the 14-day clock" in text
    assert "schema-sensitive change" in text
    assert "live event-chain verification failure" in text
    assert "Stay single-threaded on `main`" in text
    assert "v0.6.x hardening PRs" in text
    assert "without changing event types" in text
    assert "`fly.deploy` LLM voting" in text


def test_handoff_and_repo_map_point_to_phase6_gate_checklist() -> None:
    path = "docs/design/phase-6-gate-checklist.md"
    checkpoint_path = "docs/design/phase-6-readiness-checkpoint.md"
    entry_plan_path = "docs/design/phase-6-entry-plan.md"

    assert path in _text(HANDOFF)
    assert path in _text(REPO_MAP)
    assert checkpoint_path in _text(HANDOFF)
    assert checkpoint_path in _text(REPO_MAP)
    assert entry_plan_path in _text(HANDOFF)
    assert entry_plan_path in _text(REPO_MAP)
