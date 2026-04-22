"""End-to-end tests for ``actions.open_pr`` (Phase 4 PR B1).

All GitHub calls are stubbed by ``respx``; the installation token is
minted against a locally generated RSA keypair so no PEM ever lands in
the repo (same posture as ``tests/test_github_actuator_auth.py``).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.api.app.services.actuators.github import (
    GitHubActionError,
    GitHubApiError,
    GitHubAppClient,
    GitHubAppConfig,
    GitHubAppLimits,
    GitHubFileSpec,
    GitHubInstallation,
    GitHubOpenPrSpec,
    open_pr,
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


def _config(limits: GitHubAppLimits | None = None) -> GitHubAppConfig:
    return GitHubAppConfig(
        app_id=42,
        installations=[GitHubInstallation(owner="jaydenpiao", repo="quorum", installation_id=7)],
        limits=limits or GitHubAppLimits(),
    )


@pytest.fixture
def client(private_pem: str, http_client: httpx.Client) -> GitHubAppClient:
    return GitHubAppClient(_config(), private_key_pem=private_pem, http_client=http_client)


def _spec(**overrides: object) -> GitHubOpenPrSpec:
    defaults: dict[str, object] = {
        "owner": "jaydenpiao",
        "repo": "quorum",
        "base": "feature/experiment",
        "title": "Automated patch",
        "body": "opened by quorum",
        "commit_message": "chore: quorum-applied patch",
        "files": [
            GitHubFileSpec(path="src/a.py", content="print('a')\n"),
            GitHubFileSpec(path="src/b.py", content="print('b')\n"),
        ],
    }
    defaults.update(overrides)
    return GitHubOpenPrSpec.model_validate(defaults)


def _token_response(
    token: str = "ghs_fake_installation_token", expires_in: int = 3600
) -> httpx.Response:
    expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return httpx.Response(
        200,
        json={
            "token": token,
            "expires_at": expires_at,
            "permissions": {"contents": "write", "pull_requests": "write"},
        },
    )


def _base_branch_response(
    *, protected: bool = False, commit_sha: str = "base_commit_sha", tree_sha: str = "base_tree_sha"
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "name": "feature/experiment",
            "protected": protected,
            "commit": {
                "sha": commit_sha,
                "commit": {"tree": {"sha": tree_sha}},
            },
        },
    )


def _install_route(mock: respx.MockRouter) -> respx.Route:
    return mock.post("https://api.github.com/app/installations/7/access_tokens").mock(
        return_value=_token_response()
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_open_pr_happy_path(client: GitHubAppClient) -> None:
    spec = _spec()
    proposal_id = "proposal_abc123"

    with respx.mock(assert_all_called=False) as mock:
        _install_route(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/branches/feature/experiment").mock(
            return_value=_base_branch_response()
        )
        blob_route = mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/blobs").mock(
            side_effect=[
                httpx.Response(201, json={"sha": "blob_a"}),
                httpx.Response(201, json={"sha": "blob_b"}),
            ]
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/trees").mock(
            return_value=httpx.Response(201, json={"sha": "tree_xyz"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/commits").mock(
            return_value=httpx.Response(201, json={"sha": "commit_xyz"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/refs").mock(
            return_value=httpx.Response(201, json={"ref": f"refs/heads/quorum/{proposal_id}"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/pulls").mock(
            return_value=httpx.Response(
                201,
                json={
                    "number": 42,
                    "html_url": "https://github.com/jaydenpiao/quorum/pull/42",
                },
            )
        )

        result = open_pr(client, spec, proposal_id=proposal_id)

    assert result.pr_number == 42
    assert result.pr_url.endswith("/pull/42")
    assert result.head_branch == f"quorum/{proposal_id}"
    assert result.head_sha == "commit_xyz"
    assert result.commit_sha == "commit_xyz"
    assert result.base_branch == "feature/experiment"
    assert result.files_written == ["src/a.py", "src/b.py"]
    # Two blobs uploaded in order.
    assert blob_route.call_count == 2


# ---------------------------------------------------------------------------
# Precondition failures
# ---------------------------------------------------------------------------


def test_open_pr_rejects_unknown_installation(client: GitHubAppClient) -> None:
    spec = _spec(owner="someone-else", repo="other")
    with pytest.raises(GitHubActionError, match="no installation configured"):
        open_pr(client, spec, proposal_id="proposal_abc")


def test_open_pr_rejects_protected_base(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _install_route(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/branches/feature/experiment").mock(
            return_value=_base_branch_response(protected=True)
        )

        with pytest.raises(GitHubActionError, match="protected"):
            open_pr(client, _spec(), proposal_id="proposal_abc")


def test_open_pr_translates_404_on_base(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _install_route(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/branches/feature/experiment").mock(
            return_value=httpx.Response(404, json={"message": "Branch not found"})
        )

        with pytest.raises(GitHubActionError, match="does not exist"):
            open_pr(client, _spec(), proposal_id="proposal_abc")


def test_open_pr_propagates_non_404_base_errors(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _install_route(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/branches/feature/experiment").mock(
            return_value=httpx.Response(502, json={"message": "bad gateway"})
        )

        with pytest.raises(GitHubApiError) as exc:
            open_pr(client, _spec(), proposal_id="proposal_abc")
    assert exc.value.status_code == 502


def test_open_pr_errors_on_missing_commit_sha(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _install_route(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/branches/feature/experiment").mock(
            return_value=httpx.Response(
                200,
                json={
                    "name": "feature/experiment",
                    "protected": False,
                    "commit": {"commit": {"tree": {"sha": "t"}}},
                },
            )
        )
        with pytest.raises(GitHubActionError, match="commit sha"):
            open_pr(client, _spec(), proposal_id="proposal_abc")


def test_open_pr_errors_on_missing_tree_sha(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _install_route(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/branches/feature/experiment").mock(
            return_value=httpx.Response(
                200,
                json={
                    "name": "feature/experiment",
                    "protected": False,
                    "commit": {"sha": "base"},
                },
            )
        )
        with pytest.raises(GitHubActionError, match="tree sha"):
            open_pr(client, _spec(), proposal_id="proposal_abc")


# ---------------------------------------------------------------------------
# Config-driven limits
# ---------------------------------------------------------------------------


def test_open_pr_rejects_file_count_over_configured_limit(
    private_pem: str, http_client: httpx.Client
) -> None:
    cfg = GitHubAppConfig(
        app_id=42,
        installations=[GitHubInstallation(owner="jaydenpiao", repo="quorum", installation_id=7)],
        limits=GitHubAppLimits(max_files_per_pr=1),
    )
    client_tight = GitHubAppClient(cfg, private_key_pem=private_pem, http_client=http_client)
    with pytest.raises(GitHubActionError, match="max_files_per_pr"):
        open_pr(client_tight, _spec(), proposal_id="proposal_abc")


def test_open_pr_rejects_file_bytes_over_configured_limit(
    private_pem: str, http_client: httpx.Client
) -> None:
    cfg = GitHubAppConfig(
        app_id=42,
        installations=[GitHubInstallation(owner="jaydenpiao", repo="quorum", installation_id=7)],
        limits=GitHubAppLimits(max_file_bytes=8),
    )
    client_tight = GitHubAppClient(cfg, private_key_pem=private_pem, http_client=http_client)
    with pytest.raises(GitHubActionError, match="max_file_bytes"):
        open_pr(client_tight, _spec(), proposal_id="proposal_abc")


# ---------------------------------------------------------------------------
# 401 renewal mid-flow
# ---------------------------------------------------------------------------


def test_open_pr_recovers_from_401_mid_flow(client: GitHubAppClient) -> None:
    spec = _spec()
    with respx.mock(assert_all_called=False) as mock:
        # Token endpoint: one initial mint, one renewal after 401.
        mock.post("https://api.github.com/app/installations/7/access_tokens").mock(
            side_effect=[
                _token_response(token="first"),
                _token_response(token="second"),
            ]
        )
        # Base branch: first call 401 (token expired), second call 200.
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/branches/feature/experiment").mock(
            side_effect=[
                httpx.Response(401, json={"message": "Bad credentials"}),
                _base_branch_response(),
            ]
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/blobs").mock(
            side_effect=[
                httpx.Response(201, json={"sha": "blob_a"}),
                httpx.Response(201, json={"sha": "blob_b"}),
            ]
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/trees").mock(
            return_value=httpx.Response(201, json={"sha": "tree"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/commits").mock(
            return_value=httpx.Response(201, json={"sha": "commit"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/refs").mock(
            return_value=httpx.Response(201, json={"ref": "refs/heads/quorum/x"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/pulls").mock(
            return_value=httpx.Response(
                201, json={"number": 7, "html_url": "https://github.com/p/p/pull/7"}
            )
        )

        result = open_pr(client, spec, proposal_id="proposal_xyz")

    assert result.pr_number == 7


# ---------------------------------------------------------------------------
# Mid-flow API error propagation
# ---------------------------------------------------------------------------


def test_open_pr_surfaces_ref_creation_422(client: GitHubAppClient) -> None:
    """Branch already exists → GitHub returns 422. Surface as GitHubApiError."""
    with respx.mock(assert_all_called=False) as mock:
        _install_route(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/branches/feature/experiment").mock(
            return_value=_base_branch_response()
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/blobs").mock(
            side_effect=[
                httpx.Response(201, json={"sha": "blob_a"}),
                httpx.Response(201, json={"sha": "blob_b"}),
            ]
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/trees").mock(
            return_value=httpx.Response(201, json={"sha": "tree"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/commits").mock(
            return_value=httpx.Response(201, json={"sha": "commit"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/refs").mock(
            return_value=httpx.Response(422, json={"message": "Reference already exists"})
        )

        with pytest.raises(GitHubApiError) as exc:
            open_pr(client, _spec(), proposal_id="proposal_xyz")

    assert exc.value.status_code == 422
    assert "already exists" in exc.value.message.lower()


def test_open_pr_errors_on_malformed_pr_response(client: GitHubAppClient) -> None:
    """PR POST returns 201 but missing required fields → GitHubActionError."""
    with respx.mock(assert_all_called=False) as mock:
        _install_route(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/branches/feature/experiment").mock(
            return_value=_base_branch_response()
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/blobs").mock(
            side_effect=[
                httpx.Response(201, json={"sha": "blob_a"}),
                httpx.Response(201, json={"sha": "blob_b"}),
            ]
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/trees").mock(
            return_value=httpx.Response(201, json={"sha": "tree"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/commits").mock(
            return_value=httpx.Response(201, json={"sha": "commit"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/refs").mock(
            return_value=httpx.Response(201, json={"ref": "refs/heads/quorum/x"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/pulls").mock(
            return_value=httpx.Response(201, json={"html_url": "url-only"})
        )

        with pytest.raises(GitHubActionError, match="'number'"):
            open_pr(client, _spec(), proposal_id="proposal_xyz")
