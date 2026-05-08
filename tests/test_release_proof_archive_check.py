"""Static contract checks for the release proof archive checker."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_release_proof_archive.sh"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_release_proof_archive_script_is_shell_valid() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_release_proof_archive_embedded_python_compiles() -> None:
    text = _text()
    lines = text.splitlines()
    blocks: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        if "<<'PY'" not in lines[index]:
            index += 1
            continue
        start_line = index + 2
        index += 1
        block: list[str] = []
        while index < len(lines) and lines[index] != "PY":
            block.append(lines[index])
            index += 1
        blocks.append((start_line, "\n".join(block) + "\n"))
        index += 1

    assert blocks, "expected embedded Python validation block"
    for start_line, source in blocks:
        compile(source, f"{SCRIPT}:{start_line}", "exec")


def test_release_proof_archive_script_documents_operator_inputs() -> None:
    text = _text()

    assert "QUORUM_RELEASE_TAG" in text
    assert "v0.6.8" in text
    assert "QUORUM_GITHUB_REPO" in text
    assert "jaydenpiao/quorum" in text
    assert "QUORUM_RELEASE_PROOF_DOC" in text
    assert "docs/releases/${RELEASE_TAG}-proof.md" in text
    assert "QUORUM_MAIN_BRANCH" in text


def test_release_proof_archive_script_checks_release_and_git_truth() -> None:
    text = _text()

    assert "git cat-file -t" in text
    assert "git rev-parse" in text
    assert "${RELEASE_TAG}^{tag}" in text
    assert "${RELEASE_TAG}^{commit}" in text
    assert "BEGIN (PGP|SSH) SIGNATURE" in text
    assert "gh release view" in text
    assert "tagName,isDraft,url,assets" in text
    assert "quorum-{release_tag}.spdx.json" in text
    assert 'asset.get("digest")' in text
    assert "sha256:" in text


def test_release_proof_archive_script_checks_docs_and_live_monitor() -> None:
    text = _text()

    assert "scripts/check_live_release.sh" in text
    assert "live-release-ok" in text
    assert "docs/SESSION_HANDOFF.md" in text
    assert "docs/REPO_MAP.md" in text
    assert "proof archive" in text
    assert "release-proof-archive-ok:" in text
    assert "asset_digest" in text
    assert "tag_object" in text
    assert "tagged_commit" in text


def test_release_proof_archive_script_is_read_only() -> None:
    text = _text()

    assert "git push" not in text
    assert "git tag " not in text
    assert "git fetch" not in text
    assert "gh release create" not in text
    assert "gh workflow run" not in text
    assert "POST" not in text
