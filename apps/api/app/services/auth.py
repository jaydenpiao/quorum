"""Bearer-token authentication for Quorum's mutating routes.

The registry of valid (plaintext) keys is loaded from the environment variable
`QUORUM_API_KEYS`, formatted as `agent_id:key,agent_id:key,...`. This is a
Phase 2 MVP — Phase 2.5 replaces the env-var registry with argon2id hashes
stored in `config/agents.yaml`, and adds rotation tooling. Until then, keep
keys high-entropy and short-lived.

Read-only routes remain unauthenticated so the console and liveness probes
still work without credentials. Only the write routes use `require_agent`.
"""

from __future__ import annotations

import hmac
import os
from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def _load_registry() -> dict[str, str]:
    """Return {plaintext_key: agent_id}. Parsed once per process."""
    raw = os.environ.get("QUORUM_API_KEYS", "").strip()
    registry: dict[str, str] = {}
    if not raw:
        return registry
    for pair in raw.split(","):
        if ":" not in pair:
            continue
        agent_id, key = pair.split(":", 1)
        agent_id = agent_id.strip()
        key = key.strip()
        if agent_id and key:
            registry[key] = agent_id
    return registry


def reload_registry() -> None:
    """Force re-read of QUORUM_API_KEYS (useful for tests)."""
    _load_registry.cache_clear()


def require_agent(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Return the authenticated agent_id or raise 401.

    The bearer token is matched in constant time against every registered key
    so we do not leak which agent_id was nearly matched.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    registry = _load_registry()
    if not registry:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="no api keys configured; set QUORUM_API_KEYS",
            headers={"WWW-Authenticate": "Bearer"},
        )

    presented = credentials.credentials
    matched_agent: str | None = None
    for candidate_key, agent_id in registry.items():
        if hmac.compare_digest(presented, candidate_key):
            matched_agent = agent_id
    if matched_agent is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return matched_agent


def demo_allowed() -> bool:
    """Return True iff QUORUM_ALLOW_DEMO is set to a truthy value."""
    return os.environ.get("QUORUM_ALLOW_DEMO", "").strip().lower() in {"1", "true", "yes", "on"}
