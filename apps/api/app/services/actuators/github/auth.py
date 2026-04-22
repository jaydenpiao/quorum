"""GitHub App authentication.

Two primitives, both sync:

- ``AppJWTSigner`` — RS256-sign a short-lived App JWT from the configured
  private key (loaded from kwarg → ``QUORUM_GITHUB_APP_PRIVATE_KEY`` env →
  ``QUORUM_GITHUB_APP_PRIVATE_KEY_PATH`` env). The JWT is used to mint
  per-installation access tokens.

- ``InstallationTokenCache`` — caches per-installation access tokens with
  a 60-second safety margin under GitHub's reported ``expires_at``, mints
  a fresh one on miss or on ``force_refresh=True``. Thread-safe; callers
  invalidate the cached entry before a single 401 retry in ``client.py``.

Safety posture: the private key never appears in log output, never leaks
into raised exception messages, and is loaded exactly once per signer.
Compare ``apps/api/app/services/auth.py``'s no-leak error handling — this
module mirrors that discipline.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import jwt


class GitHubAppAuthError(RuntimeError):
    """Raised for auth failures. Messages never contain key material."""


_ENV_KEY_PEM = "QUORUM_GITHUB_APP_PRIVATE_KEY"
_ENV_KEY_PATH = "QUORUM_GITHUB_APP_PRIVATE_KEY_PATH"

# GitHub caps App JWT ``exp`` at 10 minutes; leave a 1-minute safety margin.
_JWT_EXP_SECONDS = 9 * 60
# GitHub docs recommend iat slightly in the past to absorb clock skew.
_JWT_IAT_SKEW_SECONDS = 60
# Refresh installation tokens this many seconds before GitHub's expires_at.
_TOKEN_REFRESH_MARGIN_SECONDS = 60


def _load_private_key_pem(explicit: str | None) -> str:
    """Return the App private key in PEM form or raise.

    Precedence: explicit kwarg → env PEM → env path → error.
    """
    if explicit:
        return explicit
    env_pem = os.environ.get(_ENV_KEY_PEM, "").strip()
    if env_pem:
        return env_pem
    env_path = os.environ.get(_ENV_KEY_PATH, "").strip()
    if env_path:
        try:
            return Path(env_path).read_text(encoding="utf-8")
        except OSError as exc:
            # Expose the error *type* but not the file contents.
            raise GitHubAppAuthError(
                f"could not read private key file: {type(exc).__name__}"
            ) from None
    raise GitHubAppAuthError(f"no private key configured; set {_ENV_KEY_PEM} or {_ENV_KEY_PATH}")


class AppJWTSigner:
    """Mint short-lived App JWTs signed with the App's private key (RS256)."""

    def __init__(self, app_id: int, *, private_key_pem: str | None = None) -> None:
        if app_id < 1:
            raise GitHubAppAuthError("app_id must be a positive integer")
        self._app_id = app_id
        self._private_key_pem = _load_private_key_pem(private_key_pem)

    @property
    def app_id(self) -> int:
        return self._app_id

    def mint_jwt(self, *, now: datetime | None = None) -> str:
        """Return an RS256-signed JWT with ``iat`` / ``exp`` / ``iss`` claims."""
        current = now or datetime.now(UTC)
        iat = current - timedelta(seconds=_JWT_IAT_SKEW_SECONDS)
        exp = current + timedelta(seconds=_JWT_EXP_SECONDS)
        payload = {
            "iat": int(iat.timestamp()),
            "exp": int(exp.timestamp()),
            "iss": str(self._app_id),
        }
        try:
            return jwt.encode(payload, self._private_key_pem, algorithm="RS256")
        except Exception as exc:  # noqa: BLE001 — scrub all PyJWT / cryptography errors
            # Scrub: never echo the private key back through an exception.
            raise GitHubAppAuthError(
                f"failed to sign github app jwt: {type(exc).__name__}"
            ) from None


@dataclass(frozen=True)
class CachedToken:
    token: str
    expires_at: datetime

    def is_fresh(self, now: datetime, margin_seconds: int = _TOKEN_REFRESH_MARGIN_SECONDS) -> bool:
        return now < self.expires_at - timedelta(seconds=margin_seconds)


class InstallationTokenCache:
    """Per-installation GitHub App access-token cache.

    Mints a token on miss via ``POST /app/installations/{id}/access_tokens``
    (authenticated with a freshly-minted App JWT). Caches the returned
    token until 60 seconds before its ``expires_at``. Thread-safe.
    """

    def __init__(
        self,
        signer: AppJWTSigner,
        http_client: httpx.Client,
        *,
        base_url: str = "https://api.github.com",
    ) -> None:
        self._signer = signer
        self._http = http_client
        self._base_url = base_url.rstrip("/")
        self._cache: dict[int, CachedToken] = {}
        self._lock = threading.Lock()

    def get(
        self,
        installation_id: int,
        *,
        force_refresh: bool = False,
        now: datetime | None = None,
    ) -> str:
        current = now or datetime.now(UTC)
        with self._lock:
            cached = self._cache.get(installation_id)
            if not force_refresh and cached is not None and cached.is_fresh(current):
                return cached.token

        # Mint outside the lock so concurrent callers for *different*
        # installations do not serialize on network I/O.
        fresh = self._mint(installation_id)
        with self._lock:
            self._cache[installation_id] = fresh
        return fresh.token

    def invalidate(self, installation_id: int) -> None:
        with self._lock:
            self._cache.pop(installation_id, None)

    def _mint(self, installation_id: int) -> CachedToken:
        if installation_id < 1:
            raise GitHubAppAuthError("installation_id must be a positive integer")
        app_jwt = self._signer.mint_jwt()
        url = f"{self._base_url}/app/installations/{installation_id}/access_tokens"
        try:
            response = self._http.post(
                url,
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0),
            )
        except httpx.HTTPError as exc:
            raise GitHubAppAuthError(
                f"installation token request failed: {type(exc).__name__}"
            ) from None

        if response.status_code >= 400:
            raise GitHubAppAuthError(f"installation token request returned {response.status_code}")

        data = cast(dict[str, Any], response.json())
        token = data.get("token")
        expires_raw = data.get("expires_at")
        if not isinstance(token, str) or not token:
            raise GitHubAppAuthError("installation token response missing 'token'")
        if not isinstance(expires_raw, str) or not expires_raw:
            raise GitHubAppAuthError("installation token response missing 'expires_at'")

        try:
            # GitHub returns ``expires_at`` as an ISO-8601 string ending in "Z".
            expires_at = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise GitHubAppAuthError(
                f"installation token 'expires_at' not ISO-8601: {type(exc).__name__}"
            ) from None

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        return CachedToken(token=token, expires_at=expires_at)
