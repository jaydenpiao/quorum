"""Typed config schema for the GitHub App actuator.

PR A scope: the shape of ``config/github.yaml`` — App ID, per-install
records, per-install action limits. Action payload specs
(``GitHubOpenPrSpec``, ``GitHubCommentSpec``, etc.) are deferred to PR B
when the actual actions are wired into the executor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field


class GitHubInstallation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    owner: str = Field(min_length=1, max_length=128)
    repo: str = Field(min_length=1, max_length=128)
    installation_id: int = Field(ge=1)


class GitHubAppLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_files_per_pr: int = Field(default=200, ge=1, le=1000)
    max_file_bytes: int = Field(default=65536, ge=1, le=1048576)
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
