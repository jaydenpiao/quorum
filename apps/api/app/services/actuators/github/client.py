"""Thin GitHub REST client bound to the App actuator's auth flow.

PR A scope: just enough surface to mint installation tokens for a
configured ``GitHubAppConfig`` and expose the 401-retry pattern that
PR B's action methods will wrap around each mutation call.

The client deliberately does **not** build action methods (open PR,
comment, etc.) — those land in PR B alongside the action payload specs.
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType

import httpx

from apps.api.app.services.actuators.github.auth import (
    AppJWTSigner,
    GitHubAppAuthError,
    InstallationTokenCache,
)
from apps.api.app.services.actuators.github.specs import GitHubAppConfig


class GitHubAppClient:
    """Installation-token-minting client for the configured GitHub App.

    The client owns an ``httpx.Client`` (constructed internally unless
    injected) and an ``InstallationTokenCache``. PR B will add action
    methods (open PR, comment, etc.); each will re-use the same cache
    and the ``_token_with_retry`` pattern exposed below.
    """

    def __init__(
        self,
        config: GitHubAppConfig,
        *,
        private_key_pem: str | None = None,
        http_client: httpx.Client | None = None,
        base_url: str = "https://api.github.com",
    ) -> None:
        self._config = config
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0),
        )
        self._signer = AppJWTSigner(config.app_id, private_key_pem=private_key_pem)
        self._tokens = InstallationTokenCache(self._signer, self._http, base_url=base_url)

    @property
    def config(self) -> GitHubAppConfig:
        return self._config

    @property
    def token_cache(self) -> InstallationTokenCache:
        return self._tokens

    def installation_token(self, installation_id: int) -> str:
        """Return a cached installation token, minting one on miss."""
        return self._tokens.get(installation_id)

    def installation_token_with_retry(
        self,
        installation_id: int,
        action: Callable[[str], httpx.Response],
    ) -> httpx.Response:
        """Run ``action(token)`` exactly once, retry once on a 401.

        ``action`` receives the installation access token and must return
        the ``httpx.Response`` from the downstream call. On a 401 the
        cache entry for ``installation_id`` is invalidated, a fresh token
        is minted, and ``action`` is invoked one more time. A second 401
        raises ``GitHubAppAuthError`` — we do not loop.

        Used by PR B's action methods to keep the renewal pattern in one
        place; in PR A it exists so the unit tests can pin down the
        single-retry contract before we have a second caller.
        """
        token = self._tokens.get(installation_id)
        response = action(token)
        if response.status_code != 401:
            return response

        self._tokens.invalidate(installation_id)
        fresh = self._tokens.get(installation_id, force_refresh=True)
        retry = action(fresh)
        if retry.status_code == 401:
            raise GitHubAppAuthError("installation token rejected after one renewal; aborting")
        return retry

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> GitHubAppClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
