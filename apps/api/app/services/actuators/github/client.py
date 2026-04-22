"""Thin GitHub REST client bound to the App actuator's auth flow.

Two concentric layers:

1. Token minting + single-retry-on-401 (``installation_token_with_retry``)
   — the contract was locked down in PR A.
2. REST methods for the Git Data + Pulls APIs that ``actions.open_pr``
   needs to string together an atomic "PR with N files" flow: branch
   lookup, blob, tree, commit, ref, pull request. Each method routes
   through the 401-retry wrapper so a rolled installation token is
   recovered transparently mid-flow.

The client intentionally stays narrow — one method per REST call,
typed return values, centralized error translation. Higher-level
orchestration lives in ``actions.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any, cast

import httpx

from apps.api.app.services.actuators.github.auth import (
    AppJWTSigner,
    GitHubAppAuthError,
    InstallationTokenCache,
)
from apps.api.app.services.actuators.github.specs import GitHubAppConfig


class GitHubApiError(RuntimeError):
    """Non-auth failure from the GitHub REST API.

    Carries ``method``, ``url``, ``status_code``, and a short
    (truncated) ``message`` extracted from the response body. The full
    response body is deliberately not echoed to avoid log bloat.
    """

    def __init__(self, *, method: str, url: str, status_code: int, message: str) -> None:
        super().__init__(f"{method} {url} -> {status_code}: {message}")
        self.method = method
        self.url = url
        self.status_code = status_code
        self.message = message


class GitHubAppClient:
    """Installation-aware REST client for the configured GitHub App."""

    def __init__(
        self,
        config: GitHubAppConfig,
        *,
        private_key_pem: str | None = None,
        http_client: httpx.Client | None = None,
        base_url: str = "https://api.github.com",
    ) -> None:
        self._config = config
        self._base_url = base_url.rstrip("/")
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0),
        )
        self._signer = AppJWTSigner(config.app_id, private_key_pem=private_key_pem)
        self._tokens = InstallationTokenCache(self._signer, self._http, base_url=base_url)

    # -- public helpers ------------------------------------------------------

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

    # -- internal request plumbing ------------------------------------------

    def _request(
        self,
        installation_id: int,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> dict[str, Any]:
        """Make a REST request, handle 401 renewal, raise on non-expected.

        Returns the parsed JSON body (always an object for the routes we
        touch). Raises ``GitHubApiError`` on unexpected status codes,
        ``GitHubAppAuthError`` on persistent 401.
        """
        url = f"{self._base_url}{path}"

        def do(token: str) -> httpx.Response:
            try:
                return self._http.request(
                    method,
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json=json_body,
                )
            except httpx.HTTPError as exc:
                # Surface transport failures as a synthetic 599 so the
                # retry wrapper does not mistake them for auth failures.
                return httpx.Response(599, json={"message": type(exc).__name__})

        response = self.installation_token_with_retry(installation_id, do)

        if response.status_code not in expected:
            message = _extract_message(response)
            raise GitHubApiError(
                method=method,
                url=url,
                status_code=response.status_code,
                message=message,
            )

        # 204 No Content (common on DELETE) has no body; callers that only
        # care about success can ignore the empty dict.
        if response.status_code == 204 or not response.content:
            return {}
        return cast(dict[str, Any], response.json())

    # -- REST methods used by actions.open_pr --------------------------------

    def get_branch(
        self, installation_id: int, owner: str, repo: str, branch: str
    ) -> dict[str, Any]:
        """Return branch metadata (``commit.sha``, ``protected`` flag)."""
        return self._request(
            installation_id,
            "GET",
            f"/repos/{owner}/{repo}/branches/{branch}",
            expected=(200,),
        )

    def create_blob(self, installation_id: int, owner: str, repo: str, content: str) -> str:
        """Create a blob with UTF-8 content. Returns blob SHA."""
        data = self._request(
            installation_id,
            "POST",
            f"/repos/{owner}/{repo}/git/blobs",
            json_body={"content": content, "encoding": "utf-8"},
            expected=(201,),
        )
        sha = data.get("sha")
        if not isinstance(sha, str) or not sha:
            raise GitHubApiError(
                method="POST",
                url=f"/repos/{owner}/{repo}/git/blobs",
                status_code=201,
                message="blob response missing 'sha'",
            )
        return sha

    def create_tree(
        self,
        installation_id: int,
        owner: str,
        repo: str,
        *,
        base_tree_sha: str,
        entries: list[dict[str, str]],
    ) -> str:
        """Create a tree layered on ``base_tree_sha``. Returns tree SHA.

        Each entry: ``{"path": ..., "mode": "100644", "type": "blob", "sha": ...}``.
        """
        data = self._request(
            installation_id,
            "POST",
            f"/repos/{owner}/{repo}/git/trees",
            json_body={"base_tree": base_tree_sha, "tree": entries},
            expected=(201,),
        )
        sha = data.get("sha")
        if not isinstance(sha, str) or not sha:
            raise GitHubApiError(
                method="POST",
                url=f"/repos/{owner}/{repo}/git/trees",
                status_code=201,
                message="tree response missing 'sha'",
            )
        return sha

    def create_commit(
        self,
        installation_id: int,
        owner: str,
        repo: str,
        *,
        message: str,
        tree_sha: str,
        parent_shas: list[str],
    ) -> str:
        """Create a commit. Returns commit SHA."""
        data = self._request(
            installation_id,
            "POST",
            f"/repos/{owner}/{repo}/git/commits",
            json_body={
                "message": message,
                "tree": tree_sha,
                "parents": parent_shas,
            },
            expected=(201,),
        )
        sha = data.get("sha")
        if not isinstance(sha, str) or not sha:
            raise GitHubApiError(
                method="POST",
                url=f"/repos/{owner}/{repo}/git/commits",
                status_code=201,
                message="commit response missing 'sha'",
            )
        return sha

    def create_ref(
        self,
        installation_id: int,
        owner: str,
        repo: str,
        *,
        ref: str,
        sha: str,
    ) -> str:
        """Create a ref (e.g. ``refs/heads/quorum/<id>``). Returns the ref."""
        data = self._request(
            installation_id,
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            json_body={"ref": ref, "sha": sha},
            expected=(201,),
        )
        ref_name = data.get("ref")
        if not isinstance(ref_name, str) or not ref_name:
            raise GitHubApiError(
                method="POST",
                url=f"/repos/{owner}/{repo}/git/refs",
                status_code=201,
                message="ref response missing 'ref'",
            )
        return ref_name

    def create_pull_request(
        self,
        installation_id: int,
        owner: str,
        repo: str,
        *,
        title: str,
        head: str,
        base: str,
        body: str = "",
    ) -> dict[str, Any]:
        """Open a pull request. Returns the full PR JSON.

        Callers typically need ``number`` and ``html_url``.
        """
        return self._request(
            installation_id,
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json_body={"title": title, "head": head, "base": base, "body": body},
            expected=(201,),
        )

    # -- REST methods used by actions.rollback_open_pr -----------------------

    def get_pull_request(
        self, installation_id: int, owner: str, repo: str, pr_number: int
    ) -> dict[str, Any]:
        """Fetch PR state + merged flag. Raises GitHubApiError on 404.

        Callers use ``state`` ("open"/"closed") and ``merged`` (bool) to
        decide whether a rollback attempt is still meaningful.
        """
        return self._request(
            installation_id,
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            expected=(200,),
        )

    def close_pull_request(
        self, installation_id: int, owner: str, repo: str, pr_number: int
    ) -> dict[str, Any]:
        """PATCH the PR to ``state="closed"``. Safe to call on already-closed PRs.

        Returns the updated PR JSON. A PR that was merged will return 200
        with ``merged=True``; the rollback action checks that separately
        via ``get_pull_request`` before attempting the close.
        """
        return self._request(
            installation_id,
            "PATCH",
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            json_body={"state": "closed"},
            expected=(200,),
        )

    def delete_ref(self, installation_id: int, owner: str, repo: str, ref: str) -> None:
        """Delete a ref (e.g. ``heads/quorum/<id>``). 204 on success.

        ``ref`` is the path *after* ``refs/``, matching the GitHub REST
        convention. 422 (ref not found) is idempotent and gets swallowed
        here so rollback can be run twice without a noisy failure — the
        caller just sees success.
        """
        try:
            self._request(
                installation_id,
                "DELETE",
                f"/repos/{owner}/{repo}/git/refs/{ref}",
                expected=(204,),
            )
        except GitHubApiError as exc:
            # GitHub returns 422 "Reference does not exist" rather than
            # 404 when the branch was already deleted. 404 appears for
            # malformed paths. Treat both as idempotent success — there
            # is nothing to undo.
            if exc.status_code in (404, 422):
                return
            raise

    # -- lifecycle -----------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_message(response: httpx.Response) -> str:
    """Pull a short ``message`` out of a GitHub error response body.

    Truncated to 200 chars so a verbose body cannot bloat logs. Falls
    back to the raw (truncated) text if the body is not JSON.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict):
        msg = body.get("message", "")
        if isinstance(msg, str) and msg:
            return msg[:200]
    return str(body)[:200]
