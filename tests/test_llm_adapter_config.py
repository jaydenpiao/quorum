"""Config loader for the LLM adapter (Phase 4 LLM PR 1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.llm_agent.config import LlmAgentConfig, load_agent_profile


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "agents.yaml"
    path.write_text(body, encoding="utf-8")
    return path


_GOOD_BODY = """
agents:
  - id: telemetry-llm-agent
    role: telemetry
    can_propose: true
    api_key_hash: "$argon2id$v=19$m=65536,t=3,p=4$abc"
    llm:
      provider: anthropic
      model: claude-opus-4-7
      system_prompt_ref: prompts/telemetry-agent.md
      daily_token_cap: 500000
      per_tick_token_cap: 20000
      poll_interval_seconds: 15.0
      max_events_per_tick: 50
  - id: operator
    role: human
    can_propose: false
"""


def test_load_llm_enabled_agent(tmp_path: Path) -> None:
    profile = load_agent_profile(_write(tmp_path, _GOOD_BODY), "telemetry-llm-agent")
    assert profile.id == "telemetry-llm-agent"
    assert profile.llm is not None
    assert profile.llm.model == "claude-opus-4-7"
    assert profile.llm.system_prompt_ref == "prompts/telemetry-agent.md"
    assert profile.llm.daily_token_cap == 500_000
    assert profile.llm.per_tick_token_cap == 20_000


def test_load_non_llm_agent_returns_llm_none(tmp_path: Path) -> None:
    """Operator has no ``llm:`` block; profile loads successfully."""
    profile = load_agent_profile(_write(tmp_path, _GOOD_BODY), "operator")
    assert profile.llm is None


def test_unknown_agent_raises_key_error(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="not-a-real-agent"):
        load_agent_profile(_write(tmp_path, _GOOD_BODY), "not-a-real-agent")


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_agent_profile(tmp_path / "missing.yaml", "telemetry-llm-agent")


def test_llm_block_rejects_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        LlmAgentConfig.model_validate(
            {
                "provider": "openai",
                "system_prompt_ref": "prompts/x.md",
            }
        )


def test_llm_block_rejects_too_aggressive_poll() -> None:
    with pytest.raises(ValidationError):
        LlmAgentConfig.model_validate(
            {
                "system_prompt_ref": "prompts/x.md",
                "poll_interval_seconds": 0.5,
            }
        )


def test_system_prompt_ref_rejects_path_traversal() -> None:
    for bad in ["/etc/passwd", "../../../secret.md", "a/../b"]:
        with pytest.raises(ValidationError):
            LlmAgentConfig.model_validate({"system_prompt_ref": bad})


def test_llm_block_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LlmAgentConfig.model_validate(
            {
                "system_prompt_ref": "prompts/x.md",
                "unknown_knob": 42,
            }
        )
