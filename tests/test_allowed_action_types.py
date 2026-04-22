"""Server-side per-agent allowed_action_types enforcement (Phase 4 LLM PR 3).

Agents that set ``allowed_action_types`` in ``config/agents.yaml`` can only
POST proposals whose ``action_type`` matches the list. The check runs in
``POST /api/v1/proposals`` **before** the event log records the proposal
so a rejected attempt is a 403, not an entry.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import apps.api.app.services.auth as auth_module
from apps.api.app.services.auth import allowed_action_types_for

from tests._helpers import AUTH, TEST_OPERATOR_KEY

# Ensure the name survives ruff's unused-import strip even if AUTH is
# only referenced once.
__all__ = ["AUTH", "TEST_OPERATOR_KEY"]


_YAML = """
agents:
  - id: allowlisted-agent
    role: telemetry
    api_key_hash: ""
    allowed_action_types:
      - github.comment_issue
      - github.add_labels

  - id: unrestricted-agent
    role: operator
    api_key_hash: ""

  - id: empty-allowlist-agent
    role: telemetry
    api_key_hash: ""
    allowed_action_types: []
"""


@pytest.fixture(autouse=True)
def _yaml_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "agents.yaml"
    path.write_text(_YAML, encoding="utf-8")
    monkeypatch.setattr(auth_module, "_AGENTS_YAML_PATH", str(path))
    auth_module._load_allowed_action_types.cache_clear()
    yield
    auth_module._load_allowed_action_types.cache_clear()


# ---------------------------------------------------------------------------
# Pure loader tests
# ---------------------------------------------------------------------------


def test_allowlisted_agent_has_tuple() -> None:
    assert allowed_action_types_for("allowlisted-agent") == (
        "github.comment_issue",
        "github.add_labels",
    )


def test_unrestricted_agent_is_none() -> None:
    """No ``allowed_action_types`` field → None → no restriction."""
    assert allowed_action_types_for("unrestricted-agent") is None


def test_empty_allowlist_is_empty_tuple() -> None:
    """Explicit empty list → empty tuple → every proposal 403s."""
    assert allowed_action_types_for("empty-allowlist-agent") == ()


def test_unknown_agent_is_none() -> None:
    assert allowed_action_types_for("not-in-yaml") is None


# ---------------------------------------------------------------------------
# Route-level enforcement (end-to-end through the FastAPI app)
# ---------------------------------------------------------------------------
#
# Using the existing TestClient + AUTH helpers for the live API server
# is heavy for a single route test. Since the dependency injection in
# routes.create_proposal calls the loader we patched above, we verify
# the integration by hitting the route directly with a stub request.


def test_route_returns_403_for_disallowed_action_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Proposal with an action_type outside the allow-list returns 403
    before the event log is touched."""
    # Seed env keys for 'allowlisted-agent' and the baseline operator.
    monkeypatch.setenv(
        "QUORUM_API_KEYS",
        f"test-operator:{TEST_OPERATOR_KEY},allowlisted-agent:llm-key-dev",
    )
    # Reload everything so the key resolution + the allow-list loader
    # both see the test YAML.
    auth_module.reload_all_registries()

    from apps.api.app.main import app

    client = TestClient(app)

    # First: seed an intent under the unrestricted operator.
    resp = client.post(
        "/api/v1/intents",
        headers=AUTH,
        json={"title": "x", "description": "y"},
    )
    assert resp.status_code == 200
    intent_id = resp.json()["id"]

    # Now: propose open_pr from the allow-listed agent — should 403.
    resp = client.post(
        "/api/v1/proposals",
        headers={"Authorization": "Bearer llm-key-dev"},
        json={
            "intent_id": intent_id,
            "title": "open PR",
            "action_type": "github.open_pr",  # NOT in allow-list
            "target": "owner/repo",
            "rationale": "x",
            "rollback_steps": ["y"],
            "payload": {
                "owner": "o",
                "repo": "r",
                "base": "dev",
                "title": "t",
                "commit_message": "c",
                "files": [{"path": "a", "content": "b"}],
            },
        },
    )
    assert resp.status_code == 403
    assert "not permitted" in resp.json()["detail"]
    assert "github.open_pr" in resp.json()["detail"]


def test_route_accepts_allowed_action_type(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Proposal with an allow-listed action_type passes through to the
    regular proposal flow (succeeds — the existing pipeline validates
    the payload)."""
    monkeypatch.setenv(
        "QUORUM_API_KEYS",
        f"test-operator:{TEST_OPERATOR_KEY},allowlisted-agent:llm-key-dev",
    )
    auth_module.reload_all_registries()

    from apps.api.app.main import app

    client = TestClient(app)

    intent_resp = client.post(
        "/api/v1/intents",
        headers=AUTH,
        json={"title": "x", "description": "y"},
    )
    intent_id = intent_resp.json()["id"]

    # comment_issue IS in the allow-list → passes the 403 gate.
    resp = client.post(
        "/api/v1/proposals",
        headers={"Authorization": "Bearer llm-key-dev"},
        json={
            "intent_id": intent_id,
            "title": "add comment",
            "action_type": "github.comment_issue",
            "target": "owner/repo#1",
            "rationale": "flag for human",
            "rollback_steps": ["delete comment"],
            "payload": {
                "owner": "owner",
                "repo": "repo",
                "issue_number": 1,
                "body": "ping",
            },
        },
    )
    assert resp.status_code == 200
    assert resp.json()["proposal"]["action_type"] == "github.comment_issue"


def test_route_does_not_block_unrestricted_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agents without an allowed_action_types field stay unrestricted."""
    monkeypatch.setenv(
        "QUORUM_API_KEYS",
        f"test-operator:{TEST_OPERATOR_KEY}",
    )
    auth_module.reload_all_registries()

    from apps.api.app.main import app

    client = TestClient(app)

    intent_resp = client.post(
        "/api/v1/intents",
        headers=AUTH,
        json={"title": "x", "description": "y"},
    )
    intent_id = intent_resp.json()["id"]

    # test-operator has no allow-list → any action_type proceeds.
    resp = client.post(
        "/api/v1/proposals",
        headers=AUTH,
        json={
            "intent_id": intent_id,
            "title": "anything",
            "action_type": "github.open_pr",
            "target": "owner/repo",
            "rationale": "x",
            "rollback_steps": ["y"],
            "payload": {
                "owner": "owner",
                "repo": "repo",
                "base": "feature/x",
                "title": "t",
                "commit_message": "c",
                "files": [{"path": "a", "content": "b"}],
            },
        },
    )
    assert resp.status_code == 200
