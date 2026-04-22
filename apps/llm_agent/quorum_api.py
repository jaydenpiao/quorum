"""HTTP client the adapter uses to talk to the Quorum control plane.

Deliberately narrow: this is *not* a full Quorum SDK. It exposes only
the endpoints the LLM loop needs in PR 1 (read events) and PR 2+
(emit findings / proposals). Everything else routes through the same
authenticated ``/api/v1/*`` surface as any other client — we never
bypass auth or actor-binding.

The adapter authenticates as its own `agent_id` using the standard
Phase 2.5 bearer-token flow. The API key lives in the environment
(``QUORUM_API_KEYS=<agent_id>:<plaintext>,...``) exactly like the API
server; the adapter just picks its entry out.
"""

from __future__ import annotations

import os
from types import TracebackType
from typing import Any, cast

import httpx


class QuorumApiError(RuntimeError):
    """Non-2xx response from the Quorum API. Carries status + message."""

    def __init__(self, *, method: str, url: str, status_code: int, message: str) -> None:
        super().__init__(f"{method} {url} -> {status_code}: {message}")
        self.method = method
        self.url = url
        self.status_code = status_code
        self.message = message


class QuorumApiClient:
    """Minimal Quorum API client for the LLM adapter."""

    def __init__(
        self,
        *,
        base_url: str,
        agent_id: str,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url must be non-empty")
        if not agent_id:
            raise ValueError("agent_id must be non-empty")
        self._base_url = base_url.rstrip("/")
        self._agent_id = agent_id
        self._api_key = api_key or _resolve_api_key_from_env(agent_id)
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=10.0),
        )

    # -- public surface ------------------------------------------------------

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def list_events(self, *, since_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Return events from the control plane.

        PR 1 note: `/api/v1/events` currently returns the full event log;
        the ``since_id`` and ``limit`` kwargs are forward-compatible
        shims that the adapter will honour once the server grows a
        cursor-based filter. For now we filter client-side.
        """
        response = self._request("GET", "/api/v1/events")
        events = cast(list[dict[str, Any]], response)
        if since_id is not None:
            idx = next((i for i, e in enumerate(events) if e.get("id") == since_id), -1)
            events = events[idx + 1 :] if idx >= 0 else events
        if limit > 0:
            events = events[:limit]
        return events

    def create_finding(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST a finding. Used by PR 2+."""
        return cast(dict[str, Any], self._request("POST", "/api/v1/findings", json_body=payload))

    def create_proposal(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST a proposal. Used by PR 3+."""
        return cast(dict[str, Any], self._request("POST", "/api/v1/proposals", json_body=payload))

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> QuorumApiClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- internals -----------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        try:
            response = self._http.request(method, url, json=json_body, headers=headers)
        except httpx.HTTPError as exc:
            raise QuorumApiError(
                method=method, url=url, status_code=599, message=type(exc).__name__
            ) from None

        if response.status_code >= 400:
            message = _extract_message(response)
            raise QuorumApiError(
                method=method,
                url=url,
                status_code=response.status_code,
                message=message,
            )
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_api_key_from_env(agent_id: str) -> str:
    """Pull the adapter's own key out of ``QUORUM_API_KEYS``.

    ``QUORUM_API_KEYS`` is the shared env variable the API server uses
    too; it's formatted as ``agent_id:plaintext,...``. The adapter
    looks for its own entry and raises if it isn't there.
    """
    raw = os.environ.get("QUORUM_API_KEYS", "").strip()
    if not raw:
        raise RuntimeError(
            f"QUORUM_API_KEYS is empty; set {agent_id}:<plaintext> so the adapter can authenticate"
        )
    for pair in raw.split(","):
        if ":" not in pair:
            continue
        entry_id, key = pair.split(":", 1)
        if entry_id.strip() == agent_id:
            plaintext = key.strip()
            if plaintext:
                return plaintext
    raise RuntimeError(
        f"QUORUM_API_KEYS has no entry for agent_id={agent_id!r}; "
        "add '<agent_id>:<plaintext>' to the comma-separated list"
    )


def _extract_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict):
        msg = body.get("detail") or body.get("message") or ""
        if isinstance(msg, str) and msg:
            return msg[:200]
    return str(body)[:200]
