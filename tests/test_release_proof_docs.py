"""Static checks for archived release proof documents."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "docs" / "releases" / "v0.6.1-proof.md"
PROOF_062 = ROOT / "docs" / "releases" / "v0.6.2-proof.md"
PROOF_063 = ROOT / "docs" / "releases" / "v0.6.3-proof.md"
PROOF_064 = ROOT / "docs" / "releases" / "v0.6.4-proof.md"
PROOF_065 = ROOT / "docs" / "releases" / "v0.6.5-proof.md"
PROOF_066 = ROOT / "docs" / "releases" / "v0.6.6-proof.md"
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


def test_v063_release_proof_records_required_evidence() -> None:
    text = _text(PROOF_063)

    assert "v0.6.3" in text
    assert "https://github.com/jaydenpiao/quorum/releases/tag/v0.6.3" in text
    assert "quorum-v0.6.3.spdx.json" in text
    assert "33e0ea44261fc77f302a531674df2a7b19144137" in text
    assert "59c52433b67985587cd491b102c7dc2e0a8b226f" in text
    assert "25142095648" in text
    assert "evt_7d59f0836bc5" in text
    assert "imgpush_cc0195677b55" in text
    assert "sha256:5cb35f2aaaf0a720d9e0e31e72ae714524f26cdf300accc24b69a7c0846cc716" in text
    assert "proposal_86c8a3f8d2e6" in text
    assert "exec_2adb999b0c62" in text
    assert "hcr_294efe04a461" in text
    assert "hcr_963461660f01" in text
    assert "proposal_36ab7d5601e3" in text
    assert "vote_3bd1a8c7a780" in text
    assert "review-llm-agent" in text
    assert "031e0246ee1ed689de80763ad78e65118d9f3113e6474d2cc039bd64c2ace472" in text
    assert "ebf41d9d574f89905e4f93957b7d5b22cbe264d10ac8e3bf6913fb016566cf4d" in text
    assert "/tmp/quorum-proof.20260430T011848Z/proof.md" in text


def test_session_handoff_points_to_v063_release_proof_archive() -> None:
    text = _text(HANDOFF)

    assert "docs/releases/v0.6.3-proof.md" in text


def test_v064_release_proof_records_required_evidence() -> None:
    text = _text(PROOF_064)

    assert "v0.6.4" in text
    assert "https://github.com/jaydenpiao/quorum/releases/tag/v0.6.4" in text
    assert "quorum-v0.6.4.spdx.json" in text
    assert "2d093dbb539a4e7a3076330f0cecba99b3b3eca5" in text
    assert "ca7e38364fc02ea0e2c93384dc35c0e7f09b1005" in text
    assert "25158475015" in text
    assert "evt_0b0a4e245e0e" in text
    assert "imgpush_0a8e8981c4bf" in text
    assert "sha256:5113540f467afcc1fc32fc3cbbc9029791fbe8b9d10650e06719cbe59f1b9e8b" in text
    assert "proposal_cd52ff99d4f7" in text
    assert "exec_4590bf26d0a9" in text
    assert "hcr_c220bbc8192b" in text
    assert "hcr_e3789dabc541" in text
    assert "proposal_36ab7d5601e3" in text
    assert "vote_3bd1a8c7a780" in text
    assert "review-llm-agent" in text
    assert "031e0246ee1ed689de80763ad78e65118d9f3113e6474d2cc039bd64c2ace472" in text
    assert "365c04926d887735d8d2fbf9dbf44804b055c29f53d0e4d270937df7c522413e" in text
    assert "/tmp/quorum-proof.20260430T094222Z/proof.md" in text
    assert "/tmp/quorum-review-proof.20260430T095352Z/proof.md" in text


def test_session_handoff_points_to_v064_release_proof_archive() -> None:
    text = _text(HANDOFF)

    assert "docs/releases/v0.6.4-proof.md" in text


def test_v065_release_proof_records_required_evidence() -> None:
    text = _text(PROOF_065)

    assert "v0.6.5" in text
    assert "https://github.com/jaydenpiao/quorum/releases/tag/v0.6.5" in text
    assert "quorum-v0.6.5.spdx.json" in text
    assert "8fc02870b4d9441ad4e9ca967dd492bc960bdf5c" in text
    assert "2e53e243784fc3b2bfa1c847bac62e516b6e4c3e" in text
    assert "25201223624" in text
    assert "evt_709fdc3d1da3" in text
    assert "imgpush_9bc84b96e81a" in text
    assert "sha256:ac40b39b0c27d577ded4bce693da7fd2601483c4624bbade5b4abf770429d27f" in text
    assert "proposal_9d44bceef7c2" in text
    assert "exec_3b7609dee96e" in text
    assert "hcr_fa6dbe6d7666" in text
    assert "hcr_90168b761585" in text
    assert "96cbfc8d733b95000e79637ad1ae07d2388c8cec40ec8aa9b6ee9c85c1212588" in text
    assert "/tmp/quorum-proof.20260501T034718Z/proof.md" in text


def test_session_handoff_points_to_v065_release_proof_archive() -> None:
    text = _text(HANDOFF)

    assert "docs/releases/v0.6.5-proof.md" in text


def test_v066_release_proof_records_required_evidence() -> None:
    text = _text(PROOF_066)

    assert "v0.6.6" in text
    assert "https://github.com/jaydenpiao/quorum/releases/tag/v0.6.6" in text
    assert "quorum-v0.6.6.spdx.json" in text
    assert "5e3e079d5e3c50ddc61b5a78633e7b5f4248d80f" in text
    assert "8adaa3d16edf1eba54fcf3c8eef69e61dabaa047" in text
    assert "25312709393" in text
    assert "evt_03f694236356" in text
    assert "imgpush_584c907507e0" in text
    assert "sha256:cf78b045798ea25b36bde94373c62af3e8bb1bbdaf1d457a2ffd1212ca751a84" in text
    assert "proposal_cb746a0ccc20" in text
    assert "exec_6e59d56670ef" in text
    assert "hcr_bd67948ce2dc" in text
    assert "hcr_1ae20ff48ac3" in text
    assert "201db80194d1d073d15c1dc03bd221c816b34390fd8c900f2243a8fa69ddd00b" in text
    assert "phase6-gate-closed: not before 2026-05-14" in text
    assert "/tmp/quorum-proof.20260504T095935Z/proof.md" in text


def test_session_handoff_points_to_v066_release_proof_archive() -> None:
    text = _text(HANDOFF)

    assert "docs/releases/v0.6.6-proof.md" in text
