"""Static checks for the LLM voter design gate."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "docs" / "design" / "llm-voter-role.md"
ADAPTER_DESIGN = ROOT / "docs" / "design" / "llm-adapter.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_llm_voter_design_locks_safety_contract() -> None:
    text = _text(DESIGN)

    assert "design only" in text.lower()
    assert "no implementation" in text.lower()
    assert "per-action trust caps" in text
    assert "must never be sufficient alone" in text
    assert "protected/high-risk" in text
    assert "requires_human=true" in text
    assert "policy" in text.lower()
    assert "audit metadata" in text.lower()
    assert "system_prompt_sha256" in text
    assert "model" in text
    assert "allowed_action_types" in text
    assert "console" in text.lower()


def test_llm_adapter_design_points_to_voter_design() -> None:
    text = _text(ADAPTER_DESIGN)

    assert "docs/design/llm-voter-role.md" in text
