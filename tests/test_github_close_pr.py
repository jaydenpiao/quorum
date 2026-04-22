"""Tests for ``github.close_pr`` action + rollback (Phase 4 PR D)."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from apps.api.app.services.actuators.github import (
    ClosePrResult,
    GitHubActionError,
    GitHubAppClient,
    GitHubAppConfig,
    GitHubAppLimits,
    GitHubClosePrSpec,
    GitHubInstallation,
    RollbackImpossibleError,
    close_pr,
    rollback_close_pr,
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


def _spec() -> GitHubClosePrSpec:
    return GitHubClosePrSpec.model_validate(
        {"owner": "jaydenpiao", "repo": "quorum", "pr_number": 17}
    )


def _token(mock: respx.MockRouter) -> None:
    mock.post("https://api.github.com/app/installations/7/access_tokens").mock(
        return_value=httpx.Response(
            200, json={"token": "ghs_t", "expires_at": "2099-01-01T00:00:00Z"}
        )
    )


# ---------------------------------------------------------------------------
# Spec boundary
# ---------------------------------------------------------------------------


def test_spec_rejects_zero_pr_number() -> None:
    with pytest.raises(ValidationError):
        GitHubClosePrSpec.model_validate({"owner": "o", "repo": "r", "pr_number": 0})


def test_spec_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        GitHubClosePrSpec.model_validate(
            {"owner": "o", "repo": "r", "pr_number": 1, "title": "extra"}
        )


# ---------------------------------------------------------------------------
# Action — happy + precondition failures
# ---------------------------------------------------------------------------


def test_close_pr_happy_path(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/17").mock(
            return_value=httpx.Response(
                200,
                json={
                    "state": "open",
                    "merged": False,
                    "html_url": "https://github.com/jaydenpiao/quorum/pull/17",
                },
            )
        )
        patch = mock.patch("https://api.github.com/repos/jaydenpiao/quorum/pulls/17").mock(
            return_value=httpx.Response(
                200,
                json={
                    "state": "closed",
                    "merged": False,
                    "html_url": "https://github.com/jaydenpiao/quorum/pull/17",
                },
            )
        )

        result = close_pr(client, _spec(), proposal_id="proposal_abc")

    assert result.pr_number == 17
    assert result.previous_state == "open"
    assert patch.call_count == 1


def test_close_pr_rejects_merged_pr(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/17").mock(
            return_value=httpx.Response(
                200,
                json={
                    "state": "closed",
                    "merged": True,
                    "html_url": "https://github.com/jaydenpiao/quorum/pull/17",
                },
            )
        )
        patch = mock.patch("https://api.github.com/repos/jaydenpiao/quorum/pulls/17")

        with pytest.raises(GitHubActionError, match="merged"):
            close_pr(client, _spec(), proposal_id="proposal_abc")
    assert patch.call_count == 0


def test_close_pr_rejects_already_closed(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/17").mock(
            return_value=httpx.Response(
                200,
                json={
                    "state": "closed",
                    "merged": False,
                    "html_url": "https://github.com/jaydenpiao/quorum/pull/17",
                },
            )
        )
        with pytest.raises(GitHubActionError, match="not open"):
            close_pr(client, _spec(), proposal_id="proposal_abc")


# ---------------------------------------------------------------------------
# Rollback — reopen happy path + impossible cases
# ---------------------------------------------------------------------------


def _result() -> ClosePrResult:
    return ClosePrResult(
        owner="jaydenpiao",
        repo="quorum",
        pr_number=17,
        pr_url="https://github.com/jaydenpiao/quorum/pull/17",
        previous_state="open",
    )


def test_rollback_reopens_closed_pr(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/17").mock(
            return_value=httpx.Response(200, json={"state": "closed", "merged": False})
        )
        patch = mock.patch("https://api.github.com/repos/jaydenpiao/quorum/pulls/17").mock(
            return_value=httpx.Response(200, json={"state": "open", "merged": False})
        )

        summary = rollback_close_pr(client, _result())

    assert summary["pr_action"] == "reopened"
    assert patch.call_count == 1


def test_rollback_skips_when_pr_already_open(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/17").mock(
            return_value=httpx.Response(200, json={"state": "open", "merged": False})
        )
        patch = mock.patch("https://api.github.com/repos/jaydenpiao/quorum/pulls/17")

        summary = rollback_close_pr(client, _result())

    assert summary["pr_action"] == "already_open"
    assert patch.call_count == 0


def test_rollback_impossible_when_pr_merged(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/17").mock(
            return_value=httpx.Response(200, json={"state": "closed", "merged": True})
        )

        with pytest.raises(RollbackImpossibleError, match="merged"):
            rollback_close_pr(client, _result())


def test_rollback_impossible_when_reopen_returns_422(client: GitHubAppClient) -> None:
    """Race: PR pre-check says not merged but PATCH rejects. Treat as impossible."""
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/17").mock(
            return_value=httpx.Response(200, json={"state": "closed", "merged": False})
        )
        mock.patch("https://api.github.com/repos/jaydenpiao/quorum/pulls/17").mock(
            return_value=httpx.Response(
                422, json={"message": "Cannot reopen a merged pull request"}
            )
        )

        with pytest.raises(RollbackImpossibleError, match="reopen refused"):
            rollback_close_pr(client, _result())


def test_rollback_impossible_when_pr_deleted(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/17").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )

        with pytest.raises(RollbackImpossibleError, match="no longer exists"):
            rollback_close_pr(client, _result())
