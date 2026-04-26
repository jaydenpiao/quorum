"""Opt-in live GitHub App actuator integration tests.

These tests intentionally mutate ``jaydenpiao/quorum-actuator-fixtures``
and are skipped in default CI by both the global ``-m 'not integration'``
addopt and the ``QUORUM_GITHUB_LIVE_TESTS=1`` guard below.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.api.app.services.actuators.github import (
    CommentIssueResult,
    GitHubApiError,
    GitHubAppClient,
    GitHubAppConfig,
    GitHubCommentIssueSpec,
    comment_issue,
    load_github_config,
    rollback_comment_issue,
)

pytestmark = pytest.mark.integration

_DEFAULT_OWNER = "jaydenpiao"
_DEFAULT_REPO = "quorum-actuator-fixtures"
_DEFAULT_ISSUE_NUMBER = 1


@dataclass(frozen=True)
class _LiveGitHubConfig:
    config: GitHubAppConfig
    owner: str
    repo: str
    issue_number: int
    installation_id: int


def _github_key_env_present() -> bool:
    return any(
        os.environ.get(name, "").strip()
        for name in (
            "QUORUM_GITHUB_APP_PRIVATE_KEY",
            "QUORUM_GITHUB_APP_PRIVATE_KEY_B64",
            "QUORUM_GITHUB_APP_PRIVATE_KEY_PATH",
        )
    )


def _live_config() -> _LiveGitHubConfig:
    if os.environ.get("QUORUM_GITHUB_LIVE_TESTS") != "1":
        pytest.skip("set QUORUM_GITHUB_LIVE_TESTS=1 to run live GitHub tests")
    if not _github_key_env_present():
        pytest.skip("GitHub App private key env not set; skipping live GitHub test")

    config_path = Path(os.environ.get("QUORUM_GITHUB_CONFIG_PATH", "config/github.yaml"))
    if not config_path.is_file():
        pytest.skip(f"GitHub config file not found: {config_path}")

    owner = os.environ.get("QUORUM_GITHUB_LIVE_OWNER", _DEFAULT_OWNER).strip()
    repo = os.environ.get("QUORUM_GITHUB_LIVE_REPO", _DEFAULT_REPO).strip()
    issue_raw = os.environ.get("QUORUM_GITHUB_LIVE_ISSUE", str(_DEFAULT_ISSUE_NUMBER))
    try:
        issue_number = int(issue_raw)
    except ValueError as exc:
        raise AssertionError("QUORUM_GITHUB_LIVE_ISSUE must be an integer") from exc
    if issue_number < 1:
        raise AssertionError("QUORUM_GITHUB_LIVE_ISSUE must be positive")

    config = load_github_config(config_path)
    installation = config.installation_for(owner, repo)
    if installation is None:
        pytest.skip(f"config has no GitHub App installation for {owner}/{repo}")

    return _LiveGitHubConfig(
        config=config,
        owner=owner,
        repo=repo,
        issue_number=issue_number,
        installation_id=installation.installation_id,
    )


def test_live_github_comment_issue_rolls_back_and_disappears() -> None:
    cfg = _live_config()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    body = f"Quorum live GitHub actuator integration smoke {run_id}"
    result: CommentIssueResult | None = None

    with GitHubAppClient(cfg.config) as client:
        try:
            result = comment_issue(
                client,
                GitHubCommentIssueSpec(
                    owner=cfg.owner,
                    repo=cfg.repo,
                    issue_number=cfg.issue_number,
                    body=body,
                ),
                proposal_id=f"proposal_live_github_comment_{run_id}",
            )

            created = client.get_issue_comment(
                cfg.installation_id, cfg.owner, cfg.repo, result.comment_id
            )
            assert created["id"] == result.comment_id
            assert created["body"] == body

            summary = rollback_comment_issue(client, result)
            assert summary["comment_deleted"] == result.comment_id

            with pytest.raises(GitHubApiError) as excinfo:
                client.get_issue_comment(
                    cfg.installation_id, cfg.owner, cfg.repo, result.comment_id
                )
            assert excinfo.value.status_code == 404
        finally:
            if result is not None:
                rollback_comment_issue(client, result)
