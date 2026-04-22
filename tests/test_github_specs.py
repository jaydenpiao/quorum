"""Boundary validation for GitHub actuator specs (Phase 4 PR B1).

Pure-pydantic tests — no HTTP, no fixtures, no async. They pin down the
safety rails the actuator assumes when it receives a spec at runtime.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.api.app.services.actuators.github.specs import (
    MAX_FILE_BYTES,
    MAX_FILES_PER_PR,
    GitHubFileSpec,
    GitHubOpenPrSpec,
    derive_head_branch,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _file(path: str = "src/ok.py", content: str = "x = 1\n") -> GitHubFileSpec:
    return GitHubFileSpec(path=path, content=content)


def _open_pr(**overrides: object) -> GitHubOpenPrSpec:
    defaults: dict[str, object] = {
        "owner": "jaydenpiao",
        "repo": "quorum",
        "base": "feature/experiment",
        "title": "Automated patch",
        "body": "",
        "commit_message": "chore: quorum-applied patch",
        "files": [_file()],
    }
    defaults.update(overrides)
    return GitHubOpenPrSpec.model_validate(defaults)


# ---------------------------------------------------------------------------
# GitHubFileSpec
# ---------------------------------------------------------------------------


def test_file_spec_happy_path() -> None:
    f = _file("src/a/b.py", "print('hi')\n")
    assert f.path == "src/a/b.py"


@pytest.mark.parametrize(
    "bad_path",
    [
        "/etc/passwd",  # absolute
        "..",  # traversal
        "a/../b",  # traversal segment
        "a//b",  # empty segment
        "src/./x",  # dot segment
        "with\x00nul",  # NUL
        "with\ncr",  # newline
    ],
)
def test_file_spec_rejects_unsafe_paths(bad_path: str) -> None:
    with pytest.raises(ValidationError):
        GitHubFileSpec(path=bad_path, content="x")


def test_file_spec_rejects_over_byte_cap() -> None:
    # Pure-ASCII string equal to MAX_FILE_BYTES is fine; one more byte trips.
    ok = "a" * MAX_FILE_BYTES
    assert GitHubFileSpec(path="ok.txt", content=ok).content == ok
    with pytest.raises(ValidationError):
        GitHubFileSpec(path="too-big.txt", content="a" * (MAX_FILE_BYTES + 1))


def test_file_spec_byte_cap_accounts_for_utf8_expansion() -> None:
    # Each '❤' is 3 UTF-8 bytes; picking just under half the cap trips the
    # byte-level check even though char-count is well under.
    chars = (MAX_FILE_BYTES // 3) + 1
    with pytest.raises(ValidationError):
        GitHubFileSpec(path="hearts.txt", content="❤" * chars)


def test_file_spec_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        GitHubFileSpec.model_validate({"path": "a", "content": "b", "mode": "100644"})


# ---------------------------------------------------------------------------
# GitHubOpenPrSpec
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reserved",
    ["main", "Main", "master", "trunk", "develop", "development", "release/2024", "releases/x"],
)
def test_open_pr_spec_rejects_reserved_base(reserved: str) -> None:
    with pytest.raises(ValidationError):
        _open_pr(base=reserved)


def test_open_pr_spec_allows_feature_branches() -> None:
    for ok in ["feature/experiment", "dev/nightly", "hotfix/memo", "quorum/staging"]:
        spec = _open_pr(base=ok)
        assert spec.base == ok


def test_open_pr_spec_rejects_duplicate_paths() -> None:
    with pytest.raises(ValidationError):
        _open_pr(
            files=[
                _file("a.py", "1"),
                _file("b.py", "2"),
                _file("a.py", "3"),
            ]
        )


def test_open_pr_spec_requires_at_least_one_file() -> None:
    with pytest.raises(ValidationError):
        _open_pr(files=[])


def test_open_pr_spec_rejects_over_max_files_per_pr() -> None:
    too_many = [_file(path=f"f{i}.txt", content=str(i)) for i in range(MAX_FILES_PER_PR + 1)]
    with pytest.raises(ValidationError):
        _open_pr(files=too_many)


def test_open_pr_spec_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        GitHubOpenPrSpec.model_validate(
            {
                "owner": "o",
                "repo": "r",
                "base": "dev",
                "title": "t",
                "commit_message": "c",
                "files": [{"path": "a", "content": "b"}],
                "undocumented": True,
            }
        )


# ---------------------------------------------------------------------------
# derive_head_branch
# ---------------------------------------------------------------------------


def test_derive_head_branch_happy() -> None:
    assert derive_head_branch("proposal_abc123") == "quorum/proposal_abc123"


@pytest.mark.parametrize("bad", ["", "has/slash", "has space", "with\ttab"])
def test_derive_head_branch_rejects_unsafe(bad: str) -> None:
    with pytest.raises(ValueError):
        derive_head_branch(bad)
