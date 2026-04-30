"""Tests for the review-llm-agent voter role wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

from apps.llm_agent.config import load_agent_profile


_AGENTS_YAML = Path("config/agents.yaml")
_REVIEW_AGENT_PROMPT = Path("apps/llm_agent/prompts/review-agent.md")


def _agents() -> list[dict[str, Any]]:
    data = yaml.safe_load(_AGENTS_YAML.read_text(encoding="utf-8"))
    return cast(list[dict[str, Any]], data["agents"])


def _agent(agent_id: str) -> dict[str, Any]:
    for entry in _agents():
        if entry.get("id") == agent_id:
            return entry
    raise AssertionError(f"missing agent {agent_id!r}")


def test_review_llm_agent_profile_loads() -> None:
    profile = load_agent_profile(_AGENTS_YAML, "review-llm-agent")

    assert profile.id == "review-llm-agent"
    assert profile.llm is not None
    assert profile.llm.provider == "anthropic"
    assert profile.llm.system_prompt_ref == "prompts/review-agent.md"
    assert profile.llm.max_events_per_tick <= 100


def test_review_llm_agent_is_vote_only_for_low_risk_github_actions() -> None:
    entry = _agent("review-llm-agent")

    assert entry["can_vote"] is True
    assert entry["can_propose"] is False
    assert entry["allowed_vote_action_types"] == [
        "github.add_labels",
        "github.comment_issue",
    ]
    assert "allowed_action_types" not in entry


def test_existing_llm_agents_remain_unable_to_vote() -> None:
    assert _agent("telemetry-llm-agent")["can_vote"] is False
    assert _agent("deploy-llm-agent")["can_vote"] is False


def test_review_agent_prompt_file_exists_and_scopes_votes() -> None:
    assert _REVIEW_AGENT_PROMPT.exists(), f"expected prompt at {_REVIEW_AGENT_PROMPT}"
    text = _REVIEW_AGENT_PROMPT.read_text(encoding="utf-8")

    assert text.lstrip().startswith("# Role:")
    assert "cast_vote" in text
    assert "github.add_labels" in text
    assert "github.comment_issue" in text
    assert "fly.deploy" in text
    assert "must not vote" in text.lower()
    assert "system_prompt_sha256" in text
    assert "observed_event_cursor" in text
    assert "never include agent_id" in text.lower()
