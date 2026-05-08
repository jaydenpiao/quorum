"""Static checks for the Phase 6 entry plan."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRY_PLAN = ROOT / "docs" / "design" / "phase-6-entry-plan.md"
CHECKLIST = ROOT / "docs" / "design" / "phase-6-gate-checklist.md"
HANDOFF = ROOT / "docs" / "SESSION_HANDOFF.md"
REPO_MAP = ROOT / "docs" / "REPO_MAP.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_phase6_entry_plan_requires_gate_and_worktree_model() -> None:
    text = _text(ENTRY_PLAN)

    assert "QUORUM_RELEASE_TAG=v0.6.8 scripts/check_phase6_gate.sh" in text
    assert "phase6-gate-ready" in text
    assert "2026-05-14 UTC" in text
    assert "docs/PARALLEL_DEVELOPMENT.md" in text
    assert "scripts/new_worktree.sh agent/<lane>/<task>" in text


def test_phase6_entry_plan_defines_safe_first_lanes() -> None:
    text = _text(ENTRY_PLAN)

    assert "Read-only console polish" in text
    assert "GitHub actuator hardening" in text
    assert "Policy and proof documentation" in text
    assert "Operator proof tooling" in text
    assert "without changing API payloads or mutation behavior" in text
    assert "existing read-only APIs" in text


def test_phase6_entry_plan_blocks_shared_core_without_owner() -> None:
    text = _text(ENTRY_PLAN)

    assert "Do not start shared-core work in parallel" in text
    assert "one coordinating owner" in text
    assert "domain models or event payload shapes" in text
    assert "event-log append/verification semantics" in text
    assert "reducer or projector dispatch" in text
    assert "Alembic migrations or projection table shape" in text
    assert "new event types" in text
    assert "`fly.deploy` LLM voting" in text


def test_phase6_entry_plan_is_discoverable_from_operator_docs() -> None:
    path = "docs/design/phase-6-entry-plan.md"

    assert path in _text(CHECKLIST)
    assert path in _text(HANDOFF)
    assert path in _text(REPO_MAP)
