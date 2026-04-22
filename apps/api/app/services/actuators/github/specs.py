"""Typed config schema and action payloads for the GitHub App actuator.

Two groups of models live here:

1. **App configuration** — ``GitHubAppConfig`` and friends describe the
   shape of ``config/github.yaml``.
2. **Action payloads** — ``GitHubOpenPrSpec`` and its helpers describe
   the typed ``Proposal.payload`` an agent submits when it wants to open
   a PR. Additional actions (``GitHubCommentSpec``, etc.) land alongside
   their action functions in subsequent PRs.

Keep validation boundary-heavy: reject unsafe input here so downstream
actuator code can assume all shape/size constraints already hold.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Hard safety caps (design-doc constants; enforced at the pydantic boundary)
# ---------------------------------------------------------------------------

# Max bytes per file after UTF-8 encoding.
MAX_FILE_BYTES = 65536
# Max files per PR.
MAX_FILES_PER_PR = 200
# Forbidden path-segment patterns inside file paths.
_FORBIDDEN_PATH_SEGMENTS = frozenset({"", ".", ".."})
# Branch names we never open PRs against directly. ``release/*`` handled below.
_RESERVED_BASE_BRANCHES = frozenset({"main", "master", "trunk", "develop", "development"})


# ---------------------------------------------------------------------------
# Config models (PR A)
# ---------------------------------------------------------------------------


class GitHubInstallation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    owner: str = Field(min_length=1, max_length=128)
    repo: str = Field(min_length=1, max_length=128)
    installation_id: int = Field(ge=1)


class GitHubAppLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_files_per_pr: int = Field(default=MAX_FILES_PER_PR, ge=1, le=1000)
    max_file_bytes: int = Field(default=MAX_FILE_BYTES, ge=1, le=1048576)
    poll_interval_seconds: float = Field(default=5.0, ge=0.5, le=60.0)


class GitHubAppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_id: int = Field(ge=1)
    installations: list[GitHubInstallation] = Field(default_factory=list, max_length=100)
    limits: GitHubAppLimits = Field(default_factory=GitHubAppLimits)

    def installation_for(self, owner: str, repo: str) -> GitHubInstallation | None:
        for inst in self.installations:
            if inst.owner == owner and inst.repo == repo:
                return inst
        return None


def load_github_config(path: str | Path) -> GitHubAppConfig:
    """Load and validate ``config/github.yaml``.

    Raises:
        FileNotFoundError: when ``path`` does not exist.
        pydantic.ValidationError: when the YAML contents do not match the
            schema (unknown keys, wrong types, out-of-range values).
    """
    text = Path(path).read_text(encoding="utf-8")
    raw = cast(dict[str, Any], yaml.safe_load(text) or {})
    app_block = cast(dict[str, Any], raw.get("app", {}))
    limits_block = raw.get("limits", {})
    return GitHubAppConfig.model_validate({**app_block, "limits": limits_block})


# ---------------------------------------------------------------------------
# Action payloads — `github.open_pr`
# ---------------------------------------------------------------------------


def _validate_repo_path(path: str) -> str:
    """Enforce the rules the GitHub git-data API + our safety rails require.

    - No leading slash (paths are repo-relative).
    - No ``..`` or empty path segments (blocks traversal + double-slashes).
    - No NUL / CR / LF bytes (GitHub rejects them and they confuse tooling).
    """
    if not path:
        raise ValueError("file path is empty")
    if path.startswith("/"):
        raise ValueError("file path must be repo-relative (no leading '/')")
    if any(c in path for c in ("\x00", "\r", "\n")):
        raise ValueError("file path contains control characters")
    segments = path.split("/")
    for seg in segments:
        if seg in _FORBIDDEN_PATH_SEGMENTS:
            raise ValueError(f"file path contains forbidden segment '{seg}'")
    return path


class GitHubFileSpec(BaseModel):
    """A single text file written into the PR's single commit."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=MAX_FILE_BYTES)

    @field_validator("path")
    @classmethod
    def _check_path(cls, v: str) -> str:
        return _validate_repo_path(v)

    @field_validator("content")
    @classmethod
    def _check_byte_size(cls, v: str) -> str:
        # ``max_length`` above bounds character count; we still need byte-size
        # check because UTF-8 can expand to up to 4 bytes per codepoint.
        if len(v.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError(f"file content exceeds {MAX_FILE_BYTES} bytes when UTF-8 encoded")
        return v


class GitHubOpenPrSpec(BaseModel):
    """Payload shape for a ``github.open_pr`` proposal.

    The action derives the head branch name from the proposal id — it is
    **not** accepted as input here. That guarantees rollback can always
    locate the branch by proposal id alone.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    owner: str = Field(min_length=1, max_length=128)
    repo: str = Field(min_length=1, max_length=128)
    base: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(default="", max_length=8000)
    commit_message: str = Field(min_length=1, max_length=1000)
    files: list[GitHubFileSpec] = Field(min_length=1, max_length=MAX_FILES_PER_PR)

    @field_validator("base")
    @classmethod
    def _base_not_reserved(cls, v: str) -> str:
        low = v.strip().lower()
        if low in _RESERVED_BASE_BRANCHES:
            raise ValueError(f"base branch '{v}' is reserved — open PRs against a feature branch")
        if low.startswith("release/") or low.startswith("releases/"):
            raise ValueError(f"base branch '{v}' matches a reserved release/* pattern")
        return v

    @field_validator("files")
    @classmethod
    def _paths_unique(cls, files: list[GitHubFileSpec]) -> list[GitHubFileSpec]:
        seen: set[str] = set()
        for f in files:
            if f.path in seen:
                raise ValueError(f"duplicate file path '{f.path}' in patch")
            seen.add(f.path)
        return files


def derive_head_branch(proposal_id: str) -> str:
    """Return the head branch name for a proposal id.

    The format is hard-coded so that rollback can deterministically find
    and delete the branch later given only the proposal id.
    """
    if not proposal_id or "/" in proposal_id or any(c.isspace() for c in proposal_id):
        raise ValueError(f"invalid proposal_id for branch derivation: {proposal_id!r}")
    return f"quorum/{proposal_id}"


# ---------------------------------------------------------------------------
# Action results — what the actuator returns to the executor
# ---------------------------------------------------------------------------


class OpenPrResult(BaseModel):
    """Typed result of a successful ``github.open_pr`` action.

    Stored on the ``ExecutionRecord`` so rollback and auditors can find
    the PR without re-querying GitHub. ``owner`` + ``repo`` are
    duplicated from the spec (rather than parsed out of ``pr_url``) so
    rollback does not depend on a stable URL format.
    """

    model_config = ConfigDict(extra="forbid")

    owner: str = Field(min_length=1, max_length=128)
    repo: str = Field(min_length=1, max_length=128)
    pr_number: int = Field(ge=1)
    pr_url: str = Field(min_length=1, max_length=512)
    head_branch: str = Field(min_length=1, max_length=256)
    head_sha: str = Field(min_length=1, max_length=64)
    base_branch: str = Field(min_length=1, max_length=256)
    commit_sha: str = Field(min_length=1, max_length=64)
    files_written: list[str] = Field(default_factory=list, max_length=MAX_FILES_PER_PR)
