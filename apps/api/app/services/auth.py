"""Bearer-token authentication for Quorum's mutating routes.

Two registries are consulted in order on each request:

1. **Env-var registry** — `QUORUM_API_KEYS=agent_id:plaintext,...`
   Compared in constant time via `hmac.compare_digest`. Retained for dev
   parity and zero-downtime migration.

2. **YAML registry** — `config/agents.yaml`, field `api_key_hash: <argon2id>`
   Verified via `argon2.PasswordHasher().verify()`. Only entries with a
   non-empty `api_key_hash` are loaded. This is the Phase 2.5 production path.

A 401 is returned if neither registry matches. The response never reveals
which registry was consulted, which key was nearly matched, or any plaintext.

Read-only routes remain unauthenticated so the console and liveness probes
still work without credentials. Only the write routes use `require_agent`.
"""

from __future__ import annotations

import hmac
import os
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)

# Path to the agents config; overrideable in tests via monkeypatch.
_AGENTS_YAML_PATH: str = str(Path(__file__).parents[4] / "config" / "agents.yaml")


# ---------------------------------------------------------------------------
# Env-var registry (Phase 2 MVP)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# YAML registry (Phase 2.5)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_yaml_registry() -> list[tuple[str, str]]:
    """Return [(agent_id, argon2id_hash), ...] for entries with a non-empty hash.

    Reads _AGENTS_YAML_PATH at call time (cached). Returns an empty list if
    the file is missing or malformed rather than raising — the env-var registry
    is the fallback.
    """
    import yaml  # local import to keep top-level deps minimal

    path = _AGENTS_YAML_PATH
    try:
        with open(path) as fh:
            data = yaml.safe_load(fh)
    except (FileNotFoundError, OSError, yaml.YAMLError):
        return []

    if not isinstance(data, dict):
        return []

    result: list[tuple[str, str]] = []
    for agent in data.get("agents", []):
        agent_id = agent.get("id", "").strip()
        api_key_hash = agent.get("api_key_hash", "").strip()
        if agent_id and api_key_hash:
            result.append((agent_id, api_key_hash))
    return result


def _reload_yaml_registry() -> None:
    """Force re-read of the YAML registry (useful for tests)."""
    _load_yaml_registry.cache_clear()


def reload_all_registries() -> None:
    """Force re-read of both registries. Called by tests after monkeypatching."""
    _load_registry.cache_clear()
    _load_yaml_registry.cache_clear()
    _load_allowed_action_types.cache_clear()


# ---------------------------------------------------------------------------
# Per-agent action_type allow-list (Phase 4 LLM PR 3)
# ---------------------------------------------------------------------------
#
# Agents with an ``allowed_action_types`` field in ``config/agents.yaml``
# can only submit proposals whose ``action_type`` matches the list. Agents
# without the field are unrestricted (existing human + operator behaviour).
# The check happens in the ``POST /api/v1/proposals`` route before the
# event log sees the proposal — a mismatch is a 403, not an event.


@lru_cache(maxsize=1)
def _load_allowed_action_types() -> dict[str, tuple[str, ...]]:
    """Return ``{agent_id: (allowed_action_type, ...)}`` for agents that set the field."""
    import yaml  # local import to keep top-level deps minimal

    path = _AGENTS_YAML_PATH
    try:
        with open(path) as fh:
            data = yaml.safe_load(fh)
    except (FileNotFoundError, OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}

    result: dict[str, tuple[str, ...]] = {}
    for agent in data.get("agents", []):
        agent_id = (agent.get("id") or "").strip()
        raw = agent.get("allowed_action_types")
        if not agent_id or not isinstance(raw, list):
            continue
        cleaned: list[str] = []
        for item in raw:
            if isinstance(item, str) and item:
                cleaned.append(item)
        result[agent_id] = tuple(cleaned)
    return result


def allowed_action_types_for(agent_id: str) -> tuple[str, ...] | None:
    """Return the per-agent action-type allow-list, or None for unrestricted.

    - None → agent has no ``allowed_action_types`` field; any action_type
      the policy engine accepts is fair game.
    - tuple() → agent explicitly allows zero actions; every proposal
      from this agent is rejected with 403.
    - non-empty tuple → proposals whose action_type is in the tuple are
      allowed through; others are rejected with 403.
    """
    registry = _load_allowed_action_types()
    return registry.get(agent_id)


# ---------------------------------------------------------------------------
# Core authentication logic
# ---------------------------------------------------------------------------


def _authenticate_bearer(presented: str) -> str:
    """Return authenticated agent_id or raise 401.

    Tries env-var registry first (constant-time compare), then YAML hashes
    (argon2 verify). Never reveals which registry was consulted.
    """
    env_registry = _load_registry()
    yaml_registry = _load_yaml_registry()

    if not env_registry and not yaml_registry:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="no api keys configured; set QUORUM_API_KEYS",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- Env-var registry: constant-time compare over all keys ---
    matched_agent: str | None = None
    for candidate_key, agent_id in env_registry.items():
        if hmac.compare_digest(presented, candidate_key):
            matched_agent = agent_id

    if matched_agent is not None:
        return matched_agent

    # --- YAML registry: argon2 verify (already constant-time per hash) ---
    ph = PasswordHasher()
    for agent_id, stored_hash in yaml_registry:
        try:
            if ph.verify(stored_hash, presented):
                return agent_id
        except VerifyMismatchError:
            pass
        except Exception:  # noqa: BLE001 — other argon2 errors (InvalidHash etc.)
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid api key",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def require_agent(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Return the authenticated agent_id or raise 401.

    The bearer token is checked against the env-var registry first (constant-
    time compare), then against each argon2id hash in config/agents.yaml.
    A 401 is raised if no registry matches; the response never reveals which
    registry was consulted.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _authenticate_bearer(credentials.credentials)


# ---------------------------------------------------------------------------
# Demo flag helper
# ---------------------------------------------------------------------------


def demo_allowed() -> bool:
    """Return True iff QUORUM_ALLOW_DEMO is set to a truthy value."""
    return os.environ.get("QUORUM_ALLOW_DEMO", "").strip().lower() in {"1", "true", "yes", "on"}
