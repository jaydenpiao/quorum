"""Unit tests for the GitHub App actuator auth scaffold (Phase 4 PR A).

Zero live GitHub traffic. All outbound HTTP is stubbed by ``respx``.
The App private key is generated at test-setup time with ``cryptography``
so no PEM literal ever touches the repo (sidesteps the gitleaks gotcha
documented in ``docs/SESSION_HANDOFF.md``).
"""

from __future__ import annotations

from collections.abc import Iterator
import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from apps.api.app.services.actuators.github.auth import (
    AppJWTSigner,
    GitHubAppAuthError,
    InstallationTokenCache,
)
from apps.api.app.services.actuators.github.client import GitHubAppClient
from apps.api.app.services.actuators.github.specs import (
    GitHubAppConfig,
    load_github_config,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def rsa_keypair() -> tuple[str, str]:
    """Generate a throwaway RSA keypair for signing + verifying App JWTs."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


@pytest.fixture
def private_pem(rsa_keypair: tuple[str, str]) -> str:
    return rsa_keypair[0]


@pytest.fixture
def public_pem(rsa_keypair: tuple[str, str]) -> str:
    return rsa_keypair[1]


@pytest.fixture
def signer(private_pem: str) -> AppJWTSigner:
    return AppJWTSigner(app_id=123, private_key_pem=private_pem)


@pytest.fixture
def http_client() -> Iterator[httpx.Client]:
    with httpx.Client() as client:
        yield client


@pytest.fixture
def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUORUM_GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("QUORUM_GITHUB_APP_PRIVATE_KEY_B64", raising=False)
    monkeypatch.delenv("QUORUM_GITHUB_APP_PRIVATE_KEY_PATH", raising=False)


def _token_response(
    *, token: str = "ghs_fake_installation_token", expires_in: int = 3600
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


# ---------------------------------------------------------------------------
# AppJWTSigner
# ---------------------------------------------------------------------------


def test_mint_jwt_includes_iat_exp_iss(signer: AppJWTSigner, public_pem: str) -> None:
    token = signer.mint_jwt()
    claims = jwt.decode(
        token,
        public_pem,
        algorithms=["RS256"],
        options={"verify_iat": False},
    )
    assert claims["iss"] == "123"
    # iat is slightly in the past (clock-skew margin), exp is ~9 minutes out.
    now = int(datetime.now(UTC).timestamp())
    assert now - 120 <= claims["iat"] <= now
    assert now + 8 * 60 <= claims["exp"] <= now + 10 * 60


def test_mint_jwt_rejects_missing_private_key(clear_env: None) -> None:
    with pytest.raises(GitHubAppAuthError, match="no private key configured"):
        AppJWTSigner(app_id=123)


def test_mint_jwt_reads_private_key_from_env(
    clear_env: None,
    monkeypatch: pytest.MonkeyPatch,
    private_pem: str,
    public_pem: str,
) -> None:
    monkeypatch.setenv("QUORUM_GITHUB_APP_PRIVATE_KEY", private_pem)
    token = AppJWTSigner(app_id=7).mint_jwt()
    claims = jwt.decode(token, public_pem, algorithms=["RS256"], options={"verify_iat": False})
    assert claims["iss"] == "7"


def test_mint_jwt_reads_private_key_from_base64_env(
    clear_env: None,
    monkeypatch: pytest.MonkeyPatch,
    private_pem: str,
    public_pem: str,
) -> None:
    encoded = base64.b64encode(private_pem.encode("utf-8")).decode("ascii")
    monkeypatch.setenv("QUORUM_GITHUB_APP_PRIVATE_KEY_B64", encoded)

    token = AppJWTSigner(app_id=8).mint_jwt()

    claims = jwt.decode(token, public_pem, algorithms=["RS256"], options={"verify_iat": False})
    assert claims["iss"] == "8"


def test_mint_jwt_rejects_invalid_base64_without_leaking_value(
    clear_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUORUM_GITHUB_APP_PRIVATE_KEY_B64", "not base64 private key")

    with pytest.raises(GitHubAppAuthError) as exc:
        AppJWTSigner(app_id=8)

    message = str(exc.value)
    assert "not base64 private key" not in message
    assert "base64" in message


def test_mint_jwt_reads_private_key_from_path(
    clear_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    private_pem: str,
    public_pem: str,
) -> None:
    pem_path = tmp_path / "app.pem"
    pem_path.write_text(private_pem, encoding="utf-8")
    monkeypatch.setenv("QUORUM_GITHUB_APP_PRIVATE_KEY_PATH", str(pem_path))
    token = AppJWTSigner(app_id=11).mint_jwt()
    claims = jwt.decode(token, public_pem, algorithms=["RS256"], options={"verify_iat": False})
    assert claims["iss"] == "11"


def test_mint_jwt_never_leaks_key_in_exception(private_pem: str) -> None:
    """A signing-time failure must not echo the PEM back to the caller."""
    signer = AppJWTSigner(app_id=1, private_key_pem=private_pem)
    # Corrupt the internal key to force jwt.encode to fail.
    signer._private_key_pem = (
        "-----BEGIN RSA PRIVATE KEY-----\nGARBAGE\n-----END RSA PRIVATE KEY-----"
    )
    with pytest.raises(GitHubAppAuthError) as exc:
        signer.mint_jwt()
    message = str(exc.value)
    assert "GARBAGE" not in message
    assert "PRIVATE KEY" not in message


def test_app_id_must_be_positive(private_pem: str) -> None:
    with pytest.raises(GitHubAppAuthError, match="app_id"):
        AppJWTSigner(app_id=0, private_key_pem=private_pem)


# ---------------------------------------------------------------------------
# InstallationTokenCache
# ---------------------------------------------------------------------------


def test_installation_token_cache_caches_within_ttl(
    signer: AppJWTSigner, http_client: httpx.Client
) -> None:
    cache = InstallationTokenCache(signer, http_client)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.github.com/app/installations/42/access_tokens").mock(
            return_value=_token_response()
        )

        first = cache.get(42)
        second = cache.get(42)

    assert first == second
    assert route.call_count == 1


def test_installation_token_cache_refetches_after_expiry(
    signer: AppJWTSigner, http_client: httpx.Client
) -> None:
    cache = InstallationTokenCache(signer, http_client)
    # Short-lived token: expires in 30s, well under the 60s refresh margin.
    short_response = _token_response(token="short_lived", expires_in=30)
    long_response = _token_response(token="long_lived", expires_in=3600)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.github.com/app/installations/42/access_tokens").mock(
            side_effect=[short_response, long_response]
        )

        first = cache.get(42)
        second = cache.get(42)

    assert first == "short_lived"
    assert second == "long_lived"
    assert route.call_count == 2


def test_installation_token_force_refresh_bypasses_cache(
    signer: AppJWTSigner, http_client: httpx.Client
) -> None:
    cache = InstallationTokenCache(signer, http_client)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.github.com/app/installations/42/access_tokens").mock(
            side_effect=[
                _token_response(token="t1"),
                _token_response(token="t2"),
                _token_response(token="t3"),
            ]
        )

        assert cache.get(42) == "t1"
        assert cache.get(42, force_refresh=True) == "t2"
        assert cache.get(42, force_refresh=True) == "t3"

    assert route.call_count == 3


def test_installation_token_cache_invalidate_drops_entry(
    signer: AppJWTSigner, http_client: httpx.Client
) -> None:
    cache = InstallationTokenCache(signer, http_client)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.github.com/app/installations/42/access_tokens").mock(
            side_effect=[_token_response(token="before"), _token_response(token="after")]
        )

        assert cache.get(42) == "before"
        cache.invalidate(42)
        assert cache.get(42) == "after"

    assert route.call_count == 2


def test_installation_token_cache_rejects_non_positive_id(
    signer: AppJWTSigner, http_client: httpx.Client
) -> None:
    cache = InstallationTokenCache(signer, http_client)
    with pytest.raises(GitHubAppAuthError, match="installation_id"):
        cache.get(0)


def test_installation_token_cache_rejects_http_error(
    signer: AppJWTSigner, http_client: httpx.Client
) -> None:
    cache = InstallationTokenCache(signer, http_client)
    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.github.com/app/installations/42/access_tokens").mock(
            return_value=httpx.Response(500, json={"message": "boom"})
        )
        with pytest.raises(GitHubAppAuthError, match="500"):
            cache.get(42)


# ---------------------------------------------------------------------------
# GitHubAppClient.installation_token_with_retry
# ---------------------------------------------------------------------------


def _make_client(private_pem: str, http_client: httpx.Client) -> GitHubAppClient:
    config = GitHubAppConfig(app_id=42, installations=[])
    return GitHubAppClient(
        config,
        private_key_pem=private_pem,
        http_client=http_client,
    )


def test_installation_token_with_retry_on_401(private_pem: str, http_client: httpx.Client) -> None:
    client = _make_client(private_pem, http_client)
    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.github.com/app/installations/7/access_tokens").mock(
            side_effect=[
                _token_response(token="first_token"),
                _token_response(token="second_token"),
            ]
        )

        call_tokens: list[str] = []

        def action(token: str) -> httpx.Response:
            call_tokens.append(token)
            if len(call_tokens) == 1:
                return httpx.Response(401)
            return httpx.Response(200)

        response = client.installation_token_with_retry(7, action)

    assert response.status_code == 200
    assert call_tokens == ["first_token", "second_token"]


def test_installation_token_with_retry_does_not_loop_on_persistent_401(
    private_pem: str, http_client: httpx.Client
) -> None:
    client = _make_client(private_pem, http_client)
    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.github.com/app/installations/7/access_tokens").mock(
            side_effect=[
                _token_response(token="t1"),
                _token_response(token="t2"),
            ]
        )

        call_count = 0

        def action(_token: str) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(401)

        with pytest.raises(GitHubAppAuthError, match="one renewal"):
            client.installation_token_with_retry(7, action)

    # Exactly two action calls: the initial one + one retry. No loop.
    assert call_count == 2


def test_installation_token_with_retry_passes_through_non_401(
    private_pem: str, http_client: httpx.Client
) -> None:
    """Non-401 responses propagate without any renewal attempt."""
    client = _make_client(private_pem, http_client)
    with respx.mock(assert_all_called=False) as mock:
        token_route = mock.post("https://api.github.com/app/installations/7/access_tokens").mock(
            return_value=_token_response(token="only")
        )

        def action(_token: str) -> httpx.Response:
            return httpx.Response(422, json={"message": "validation failed"})

        response = client.installation_token_with_retry(7, action)

    assert response.status_code == 422
    # A single token mint — no renewal.
    assert token_route.call_count == 1


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


_GOOD_YAML = """
app:
  app_id: 123456
  installations:
    - owner: jaydenpiao
      repo: quorum
      installation_id: 78910
limits:
  max_files_per_pr: 100
  max_file_bytes: 32768
  poll_interval_seconds: 10
"""


def test_load_github_config_parses_yaml(tmp_path: Path) -> None:
    path = tmp_path / "github.yaml"
    path.write_text(_GOOD_YAML, encoding="utf-8")

    cfg = load_github_config(path)

    assert cfg.app_id == 123456
    assert len(cfg.installations) == 1
    inst = cfg.installations[0]
    assert inst.owner == "jaydenpiao"
    assert inst.repo == "quorum"
    assert inst.installation_id == 78910
    assert cfg.limits.max_files_per_pr == 100
    assert cfg.limits.max_file_bytes == 32768
    assert cfg.limits.poll_interval_seconds == 10
    assert cfg.installation_for("jaydenpiao", "quorum") is inst
    assert cfg.installation_for("jaydenpiao", "other") is None


def test_load_github_config_rejects_extra_fields(tmp_path: Path) -> None:
    path = tmp_path / "github.yaml"
    path.write_text(
        """
app:
  app_id: 123
  unknown_field: "nope"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_github_config(path)


def test_load_github_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_github_config(tmp_path / "does-not-exist.yaml")


def test_load_github_config_rejects_placeholder_app_id(tmp_path: Path) -> None:
    """The loader must reject placeholder IDs rather than silently accept
    a half-configured file."""
    path = tmp_path / "github.yaml"
    path.write_text(
        """
app:
  app_id: 0
  installations: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_github_config(path)
