"""Static checks for archived release proof documents."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "docs" / "releases" / "v0.6.1-proof.md"
PROOF_062 = ROOT / "docs" / "releases" / "v0.6.2-proof.md"
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


def test_v062_release_proof_records_required_evidence() -> None:
    text = _text(PROOF_062)

    assert "v0.6.2" in text
    assert "https://github.com/jaydenpiao/quorum/releases/tag/v0.6.2" in text
    assert "quorum-v0.6.2.spdx.json" in text
    assert "46d6db147c65eebfe45c17d6f6152f873911bc6f" in text
    assert "36b786ef8e0d8b5f7e87b83e78821eb132c962ac" in text
    assert "25138184450" in text
    assert "evt_c5e2a3a30cb1" in text
    assert "imgpush_d20804ead766" in text
    assert "sha256:2ffcf11f6929cfde9d6277fb55730c4f9834fff9f57a684cec95d2024ae5bcb3" in text
    assert "proposal_55eed6fa8e13" in text
    assert "exec_22293b78a7d9" in text
    assert "hcr_44c44649cafa" in text
    assert "hcr_c39b211c47e3" in text
    assert "695f3e103cee7d102a21410e5e179f18d2068377924ba9e7c9e11d758ac33a5a" in text
    assert "/tmp/quorum-proof.20260429T230015Z/proof.md" in text


def test_session_handoff_points_to_v062_release_proof_archive() -> None:
    text = _text(HANDOFF)

    assert "docs/releases/v0.6.2-proof.md" in text
