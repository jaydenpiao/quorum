"""Tests for Phase 2.5 argon2id API key authentication.

Covers:
- YAML-registry lookup with a valid hash
- Wrong plaintext rejected with 401
- Env-var registry still works alongside YAML registry
- bootstrap_keys CLI generates a hash and writes it to agents.yaml
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from argon2 import PasswordHasher

from apps.api.app.services import auth as auth_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_registries():
    """Always flush both registry caches before and after each test.

    Prevents stale lru_cache entries (from monkeypatched env-vars or YAML
    path overrides) leaking into the next test's auth lookups.
    """
    auth_module.reload_all_registries()
    yield
    auth_module.reload_all_registries()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_YAML_AGENT_ID = "yaml-test-agent"
_PLAINTEXT_KEY = "fake-test-plaintext"  # noqa: S105 — fixed test fixture, not a real secret


def _make_agents_yaml(tmp_path: Path, api_key_hash: str = "") -> Path:
    """Write a minimal agents.yaml to tmp_path and return the path."""
    data = {
        "agents": [
            {
                "id": _YAML_AGENT_ID,
                "role": "test",
                "can_vote": False,
                "can_propose": False,
                "scope": ["test"],
                "api_key_hash": api_key_hash,
            }
        ]
    }
    yaml_file = tmp_path / "agents.yaml"
    yaml_file.write_text(yaml.dump(data))
    return yaml_file


# ---------------------------------------------------------------------------
# Test: YAML hash authenticates correctly
# ---------------------------------------------------------------------------


def test_yaml_hash_authenticates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A correct plaintext key that matches a yaml-stored argon2id hash returns agent_id."""
    ph = PasswordHasher()
    known_hash = ph.hash(_PLAINTEXT_KEY)
    yaml_file = _make_agents_yaml(tmp_path, api_key_hash=known_hash)

    monkeypatch.setattr(auth_module, "_AGENTS_YAML_PATH", str(yaml_file))
    auth_module.reload_all_registries()

    result = auth_module._authenticate_bearer(_PLAINTEXT_KEY)
    assert result == _YAML_AGENT_ID


# ---------------------------------------------------------------------------
# Test: wrong key is rejected
# ---------------------------------------------------------------------------


def test_yaml_hash_wrong_key_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A wrong plaintext key does not match any yaml hash; raises 401."""
    ph = PasswordHasher()
    known_hash = ph.hash(_PLAINTEXT_KEY)
    yaml_file = _make_agents_yaml(tmp_path, api_key_hash=known_hash)

    monkeypatch.setattr(auth_module, "_AGENTS_YAML_PATH", str(yaml_file))
    # Clear env so only YAML registry is active.
    monkeypatch.setenv("QUORUM_API_KEYS", "")
    auth_module.reload_all_registries()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        auth_module._authenticate_bearer("wrong-plaintext-key")
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Test: env-var registry still works alongside YAML
# ---------------------------------------------------------------------------


def test_env_var_registry_still_works_alongside_yaml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Both registries are consulted; env-var match still returns the correct agent_id."""
    ph = PasswordHasher()
    known_hash = ph.hash(_PLAINTEXT_KEY)
    yaml_file = _make_agents_yaml(tmp_path, api_key_hash=known_hash)

    monkeypatch.setattr(auth_module, "_AGENTS_YAML_PATH", str(yaml_file))
    monkeypatch.setenv("QUORUM_API_KEYS", "env-agent:env-plaintext-key")
    auth_module.reload_all_registries()

    # Env-var key still authenticates.
    env_result = auth_module._authenticate_bearer("env-plaintext-key")
    assert env_result == "env-agent"

    # YAML key still authenticates.
    yaml_result = auth_module._authenticate_bearer(_PLAINTEXT_KEY)
    assert yaml_result == _YAML_AGENT_ID


# ---------------------------------------------------------------------------
# Test: bootstrap CLI
# ---------------------------------------------------------------------------


def test_bootstrap_generate_writes_hash_and_prints_plaintext_once(
    tmp_path: Path,
) -> None:
    """CLI generate: writes hash to yaml file; prints plaintext key once to stdout."""
    # Prepare a minimal agents.yaml in tmp_path.
    agent_id = "telemetry-agent"
    initial_data = {
        "agents": [
            {
                "id": agent_id,
                "role": "telemetry",
                "can_vote": True,
                "can_propose": True,
                "scope": ["metrics"],
                "api_key_hash": "",
            }
        ]
    }
    yaml_file = tmp_path / "agents.yaml"
    yaml_file.write_text(yaml.dump(initial_data))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "apps.api.app.tools.bootstrap_keys",
            "generate",
            "--agent-id",
            agent_id,
            "--config",
            str(yaml_file),
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )

    assert result.returncode == 0, f"CLI failed: {result.stderr}"

    # The plaintext key should appear exactly once in stdout.
    stdout = result.stdout
    assert "PLAINTEXT" in stdout.upper() or "KEY" in stdout.upper(), (
        "Expected a key banner in stdout"
    )

    # A hash should now appear in the yaml file.
    updated = yaml.safe_load(yaml_file.read_text())
    agent_entry = next(a for a in updated["agents"] if a["id"] == agent_id)
    stored_hash = agent_entry.get("api_key_hash", "")
    assert stored_hash.startswith("$argon2"), f"Expected argon2 hash, got: {stored_hash!r}"

    # Extract the plaintext from stdout: the CLI prints "  PLAINTEXT KEY: <token>"
    # or the JSON field "plaintext_key". Parse both forms.
    plaintext_line = None
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("PLAINTEXT KEY:"):
            plaintext_line = stripped.split(":", 1)[1].strip()
            break

    # Fallback: JSON output mode emits {"plaintext_key": "..."}
    if plaintext_line is None:
        import json as _json
        import re

        for line in stdout.splitlines():
            try:
                obj = _json.loads(line.strip())
                if "plaintext_key" in obj:
                    plaintext_line = obj["plaintext_key"]
                    break
            except (_json.JSONDecodeError, AttributeError):
                pass

        # Last resort: a standalone URL-safe token line.
        if plaintext_line is None:
            for line in stdout.splitlines():
                if re.match(r"^[A-Za-z0-9_\-]{20,}$", line.strip()):
                    plaintext_line = line.strip()
                    break

    assert plaintext_line is not None, f"Could not extract plaintext key from stdout:\n{stdout}"

    ph = PasswordHasher()
    assert ph.verify(stored_hash, plaintext_line), (
        "Stored hash does not verify against printed plaintext"
    )
