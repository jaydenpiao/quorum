"""Tests for ``github.comment_issue`` action + rollback (Phase 4 PR D)."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from apps.api.app.services.actuators.github import (
    CommentIssueResult,
    GitHubActionError,
    GitHubAppClient,
    GitHubAppConfig,
    GitHubAppLimits,
    GitHubCommentIssueSpec,
    GitHubInstallation,
    RollbackImpossibleError,
    comment_issue,
    rollback_comment_issue,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def private_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


@pytest.fixture
def http_client() -> Iterator[httpx.Client]:
    with httpx.Client() as c:
        yield c


def _config() -> GitHubAppConfig:
    return GitHubAppConfig(
        app_id=42,
        installations=[GitHubInstallation(owner="jaydenpiao", repo="quorum", installation_id=7)],
        limits=GitHubAppLimits(),
    )


@pytest.fixture
def client(private_pem: str, http_client: httpx.Client) -> GitHubAppClient:
    return GitHubAppClient(_config(), private_key_pem=private_pem, http_client=http_client)


def _spec(**overrides: object) -> GitHubCommentIssueSpec:
    defaults: dict[str, object] = {
        "owner": "jaydenpiao",
        "repo": "quorum",
        "issue_number": 99,
        "body": "automated note",
    }
    defaults.update(overrides)
    return GitHubCommentIssueSpec.model_validate(defaults)


def _token(mock: respx.MockRouter) -> None:
    mock.post("https://api.github.com/app/installations/7/access_tokens").mock(
        return_value=httpx.Response(
            200, json={"token": "ghs_t", "expires_at": "2099-01-01T00:00:00Z"}
        )
    )


# ---------------------------------------------------------------------------
# Spec boundary
# ---------------------------------------------------------------------------


def test_spec_rejects_empty_body() -> None:
    with pytest.raises(ValidationError):
        GitHubCommentIssueSpec.model_validate(
            {"owner": "o", "repo": "r", "issue_number": 1, "body": ""}
        )


def test_spec_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        GitHubCommentIssueSpec.model_validate(
            {"owner": "o", "repo": "r", "issue_number": 1, "body": "hi", "extra": True}
        )


def test_spec_enforces_issue_number_positive() -> None:
    with pytest.raises(ValidationError):
        GitHubCommentIssueSpec.model_validate(
            {"owner": "o", "repo": "r", "issue_number": 0, "body": "hi"}
        )


# ---------------------------------------------------------------------------
# Action happy path
# ---------------------------------------------------------------------------


def test_comment_issue_happy_path(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/issues/99/comments").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 12345,
                    "body": "automated note",
                    "html_url": "https://github.com/jaydenpiao/quorum/issues/99#issuecomment-12345",
                },
            )
        )

        result = comment_issue(client, _spec(), proposal_id="proposal_abc")

    assert result.comment_id == 12345
    assert "issuecomment-12345" in result.comment_url
    assert result.issue_number == 99


def test_comment_issue_rejects_missing_installation(client: GitHubAppClient) -> None:
    with pytest.raises(GitHubActionError, match="no installation configured"):
        comment_issue(client, _spec(owner="someone-else"), proposal_id="proposal_abc")


def test_comment_issue_errors_on_malformed_response(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/issues/99/comments").mock(
            return_value=httpx.Response(201, json={"body": "x"})
        )  # missing id + html_url

        with pytest.raises(GitHubActionError, match="'id'"):
            comment_issue(client, _spec(), proposal_id="proposal_abc")


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def _result() -> CommentIssueResult:
    return CommentIssueResult(
        owner="jaydenpiao",
        repo="quorum",
        issue_number=99,
        comment_id=12345,
        comment_url="https://github.com/jaydenpiao/quorum/issues/99#issuecomment-12345",
    )


def test_rollback_deletes_comment(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        delete = mock.delete(
            "https://api.github.com/repos/jaydenpiao/quorum/issues/comments/12345"
        ).mock(return_value=httpx.Response(204))

        summary = rollback_comment_issue(client, _result())

    assert summary["comment_deleted"] == 12345
    assert delete.call_count == 1


def test_get_issue_comment_returns_comment(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/issues/comments/12345").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 12345,
                    "body": "automated note",
                    "html_url": "https://github.com/jaydenpiao/quorum/issues/99#issuecomment-12345",
                },
            )
        )

        comment = client.get_issue_comment(7, "jaydenpiao", "quorum", 12345)

    assert comment["id"] == 12345
    assert comment["body"] == "automated note"


def test_rollback_idempotent_on_404(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.delete("https://api.github.com/repos/jaydenpiao/quorum/issues/comments/12345").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )

        summary = rollback_comment_issue(client, _result())

    assert summary["comment_deleted"] == 12345


def test_rollback_impossible_when_installation_missing(
    private_pem: str, http_client: httpx.Client
) -> None:
    empty_cfg = GitHubAppConfig(app_id=42, installations=[], limits=GitHubAppLimits())
    client = GitHubAppClient(empty_cfg, private_key_pem=private_pem, http_client=http_client)
    with pytest.raises(RollbackImpossibleError):
        rollback_comment_issue(client, _result())
