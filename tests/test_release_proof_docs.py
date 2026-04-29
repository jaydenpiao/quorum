"""Static checks for archived release proof documents."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "docs" / "releases" / "v0.6.1-proof.md"
HANDOFF = ROOT / "docs" / "SESSION_HANDOFF.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v061_release_proof_records_required_evidence() -> None:
    text = _text(PROOF)

    assert "v0.6.1" in text
    assert "https://github.com/jaydenpiao/quorum/releases/tag/v0.6.1" in text
    assert "quorum-v0.6.1.spdx.json" in text
    assert "9cd149917e8a149112409ac60ca8c150135483ef" in text
    assert "654af766a296623e078e0072744fe7a11ecad41f" in text
    assert "25089406553" in text
    assert "evt_05d8cc15050d" in text
    assert "imgpush_5fe1b504f8e0" in text
    assert "sha256:07042758006860cf0fdd17be327a687b23e0334942fe50b33f400cc48bcdc299" in text
    assert "proposal_28f6c2af1fd1" in text
    assert "exec_5911a5fe499c" in text
    assert "hcr_307401d5767f" in text
    assert "hcr_f43a57519e22" in text
    assert "3bc246b36e4fea73b8746a27f9d2d1865e7f77da5b9e3a5194b693db84ca5e29" in text
    assert "/tmp/quorum-proof.20260429T033023Z/proof.md" in text


def test_session_handoff_points_to_v061_release_proof_archive() -> None:
    text = _text(HANDOFF)

    assert "docs/releases/v0.6.1-proof.md" in text
