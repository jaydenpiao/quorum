"""Tests for the Phase 5 deploy-llm-agent role.

Verifies that the real ``config/agents.yaml`` parses cleanly, the
``deploy-llm-agent`` entry is present with the expected allow-list
and LLM config, and the tool-schema enum includes ``fly.deploy``.

The server-side enforcement of ``allowed_action_types`` is covered by
``tests/test_allowed_action_types.py``; this file tests the wiring
(YAML + config loader + tool schema), not the route.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.llm_agent.config import load_agent_profile
from apps.llm_agent.tools import (
    LLM_ALLOWED_PROPOSAL_ACTION_TYPES,
    PROPOSAL_TOOL_SCHEMA,
)


_AGENTS_YAML = "config/agents.yaml"
_DEPLOY_AGENT_PROMPT = Path("apps/llm_agent/prompts/deploy-agent.md")


def test_fly_deploy_is_in_llm_action_type_union() -> None:
    """Tool-schema enum exposes fly.deploy alongside the github actions."""
    assert "fly.deploy" in LLM_ALLOWED_PROPOSAL_ACTION_TYPES
    # Existing github entries must survive.
    assert "github.add_labels" in LLM_ALLOWED_PROPOSAL_ACTION_TYPES
    assert "github.comment_issue" in LLM_ALLOWED_PROPOSAL_ACTION_TYPES


def test_proposal_tool_schema_enum_includes_fly_deploy() -> None:
    """Claude sees fly.deploy in the action_type enum."""
    enum = PROPOSAL_TOOL_SCHEMA["input_schema"]["properties"]["action_type"]["enum"]
    assert "fly.deploy" in enum


def test_deploy_llm_agent_profile_loads() -> None:
    profile = load_agent_profile(_AGENTS_YAML, "deploy-llm-agent")
    assert profile.id == "deploy-llm-agent"
    assert profile.llm is not None
    assert profile.llm.provider == "anthropic"
    assert profile.llm.system_prompt_ref == "prompts/deploy-agent.md"
    # Tick cadence is coarser than telemetry — deploys are rare events.
    assert profile.llm.poll_interval_seconds >= 30.0


def test_deploy_agent_prompt_file_exists() -> None:
    """system_prompt_ref resolves to a real file relative to apps/llm_agent/."""
    path = _DEPLOY_AGENT_PROMPT
    assert path.exists(), f"expected prompt at {path}"
    # A non-empty role header confirms it's a real prompt, not a stub.
    text = path.read_text(encoding="utf-8")
    assert text.lstrip().startswith("# Role:")
    assert "fly.deploy" in text


def test_deploy_agent_prompt_requires_image_push_evidence() -> None:
    text = _DEPLOY_AGENT_PROMPT.read_text(encoding="utf-8")

    assert "image_push_completed" in text
    assert "staging_image_ref" in text
    assert "prod_image_ref" in text
    assert "propose staging first" in text
    assert "prod waits for staging" in text


def test_deploy_agent_prompt_forbids_same_control_plane_staging_deploys() -> None:
    text = _DEPLOY_AGENT_PROMPT.read_text(encoding="utf-8")

    assert "same control-plane app" in text
    assert "same_app_fly_deploy_allowed" in text
    assert "create_finding" in text


def test_deploy_agent_prompt_requires_health_checks_on_proposals() -> None:
    text = _DEPLOY_AGENT_PROMPT.read_text(encoding="utf-8")

    assert "health_checks" in text
    assert "never leave health_checks empty" in text
    assert 'kind": "http"' in text
    assert 'expected_status": 200' in text
    assert 'timeout_seconds": 10.0' in text


def test_deploy_agent_prompt_names_staging_and_prod_health_checks() -> None:
    text = _DEPLOY_AGENT_PROMPT.read_text(encoding="utf-8")

    for expected in (
        "staging-readiness",
        "staging-api-health",
        "prod-readiness",
        "prod-api-health",
        "https://quorum-staging.fly.dev/readiness",
        "https://quorum-staging.fly.dev/api/v1/health",
        "https://quorum-prod.fly.dev/readiness",
        "https://quorum-prod.fly.dev/api/v1/health",
    ):
        assert expected in text


def test_telemetry_agent_profile_still_loads() -> None:
    """Regression: the existing telemetry-llm-agent entry must keep working."""
    profile = load_agent_profile(_AGENTS_YAML, "telemetry-llm-agent")
    assert profile.id == "telemetry-llm-agent"
    assert profile.llm is not None
    assert profile.llm.system_prompt_ref == "prompts/telemetry-agent.md"


def test_missing_agent_still_raises_key_error() -> None:
    """Defensive: loader behavior unchanged for an unknown id."""
    with pytest.raises(KeyError):
        load_agent_profile(_AGENTS_YAML, "does-not-exist")
