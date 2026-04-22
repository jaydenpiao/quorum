"""Unit tests for ``actions.rollback_open_pr`` (Phase 4 PR C).

Pairs with ``tests/test_github_open_pr.py``: same respx / RSA keypair
posture, covers the rollback side of the actuator contract.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.api.app.services.actuators.github import (
    GitHubApiError,
    GitHubAppClient,
    GitHubAppConfig,
    GitHubAppLimits,
    GitHubInstallation,
    OpenPrResult,
    RollbackImpossibleError,
    rollback_open_pr,
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


def _result(**overrides: object) -> OpenPrResult:
    base: dict[str, object] = {
        "owner": "jaydenpiao",
        "repo": "quorum",
        "pr_number": 42,
        "pr_url": "https://github.com/jaydenpiao/quorum/pull/42",
        "head_branch": "quorum/proposal_abc",
        "head_sha": "commit_sha_42",
        "base_branch": "feature/experiment",
        "commit_sha": "commit_sha_42",
        "files_written": ["a.py"],
    }
    base.update(overrides)
    return OpenPrResult.model_validate(base)


def _token_route(mock: respx.MockRouter) -> respx.Route:
    return mock.post("https://api.github.com/app/installations/7/access_tokens").mock(
        return_value=httpx.Response(
            200, json={"token": "ghs_t", "expires_at": "2099-01-01T00:00:00Z"}
        )
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_rollback_closes_open_pr_and_deletes_branch(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token_route(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/42").mock(
            return_value=httpx.Response(200, json={"state": "open", "merged": False, "number": 42})
        )
        close = mock.patch("https://api.github.com/repos/jaydenpiao/quorum/pulls/42").mock(
            return_value=httpx.Response(
                200, json={"state": "closed", "merged": False, "number": 42}
            )
        )
        delete = mock.delete(
            "https://api.github.com/repos/jaydenpiao/quorum/git/refs/heads/quorum/proposal_abc"
        ).mock(return_value=httpx.Response(204))

        summary = rollback_open_pr(client, _result())

    assert summary["pr_action"] == "closed"
    assert summary["branch_deleted"] == "quorum/proposal_abc"
    assert close.call_count == 1
    assert delete.call_count == 1


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_rollback_skips_close_when_pr_already_closed(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token_route(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/42").mock(
            return_value=httpx.Response(
                200, json={"state": "closed", "merged": False, "number": 42}
            )
        )
        close = mock.patch("https://api.github.com/repos/jaydenpiao/quorum/pulls/42")
        mock.delete(
            "https://api.github.com/repos/jaydenpiao/quorum/git/refs/heads/quorum/proposal_abc"
        ).mock(return_value=httpx.Response(204))

        summary = rollback_open_pr(client, _result())

    assert summary["pr_action"] == "already_closed"
    assert close.call_count == 0


def test_rollback_idempotent_on_branch_404(client: GitHubAppClient) -> None:
    """``delete_ref`` swallows 404/422 — rollback run twice still succeeds."""
    with respx.mock(assert_all_called=False) as mock:
        _token_route(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/42").mock(
            return_value=httpx.Response(
                200, json={"state": "closed", "merged": False, "number": 42}
            )
        )
        mock.delete(
            "https://api.github.com/repos/jaydenpiao/quorum/git/refs/heads/quorum/proposal_abc"
        ).mock(return_value=httpx.Response(422, json={"message": "Reference does not exist"}))

        summary = rollback_open_pr(client, _result())

    assert summary["pr_action"] == "already_closed"


def test_rollback_tolerates_missing_pr(client: GitHubAppClient) -> None:
    """If the PR itself is 404 (manually deleted), still try to clean branch."""
    with respx.mock(assert_all_called=False) as mock:
        _token_route(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/42").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        delete = mock.delete(
            "https://api.github.com/repos/jaydenpiao/quorum/git/refs/heads/quorum/proposal_abc"
        ).mock(return_value=httpx.Response(204))

        summary = rollback_open_pr(client, _result())

    assert summary["pr_action"] == "skipped_missing"
    assert delete.call_count == 1


# ---------------------------------------------------------------------------
# Terminal impossible cases
# ---------------------------------------------------------------------------


def test_rollback_impossible_when_pr_is_merged(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token_route(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/42").mock(
            return_value=httpx.Response(200, json={"state": "closed", "merged": True, "number": 42})
        )
        close = mock.patch("https://api.github.com/repos/jaydenpiao/quorum/pulls/42")
        delete = mock.delete(
            "https://api.github.com/repos/jaydenpiao/quorum/git/refs/heads/quorum/proposal_abc"
        )

        with pytest.raises(RollbackImpossibleError) as exc:
            rollback_open_pr(client, _result())

    assert "merged" in exc.value.reason.lower()
    assert exc.value.actuator_state["merged"] is True
    # We did NOT try to close or delete — merging is terminal.
    assert close.call_count == 0
    assert delete.call_count == 0


def test_rollback_impossible_when_install_config_missing(
    private_pem: str, http_client: httpx.Client
) -> None:
    """Config was tightened between open_pr and rollback — cannot proceed."""
    empty_cfg = GitHubAppConfig(app_id=42, installations=[], limits=GitHubAppLimits())
    client = GitHubAppClient(empty_cfg, private_key_pem=private_pem, http_client=http_client)

    with pytest.raises(RollbackImpossibleError) as exc:
        rollback_open_pr(client, _result())
    assert "no installation configured" in exc.value.reason


# ---------------------------------------------------------------------------
# Non-rollbackable API errors propagate
# ---------------------------------------------------------------------------


def test_rollback_propagates_non_404_get_errors(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token_route(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/42").mock(
            return_value=httpx.Response(502, json={"message": "bad gateway"})
        )

        with pytest.raises(GitHubApiError) as exc:
            rollback_open_pr(client, _result())

    assert exc.value.status_code == 502
