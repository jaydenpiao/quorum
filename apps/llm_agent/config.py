"""Config loader for LLM-backed agents.

Reads the ``llm:`` sub-block from ``config/agents.yaml``. Only agents
with an ``llm:`` block are eligible to be driven by this adapter —
everything else is either a human operator or a non-LLM programmatic
caller.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Default model when the config omits one. Opus 4.7 is the Quorum default
# for coding- / agentic-intelligence workloads per the project's shipped
# Claude configuration; operators tuning for cost can override per-agent
# (e.g. ``model: claude-sonnet-4-6``).
_DEFAULT_MODEL = "claude-opus-4-7"

# Cost caps. Chosen so a single runaway tick cannot exceed ~$1.50 on
# Opus 4.7 input pricing, and a stuck loop cannot exceed ~$60/day. Both
# values are config-editable per agent; these are just the defaults.
_DEFAULT_PER_TICK_INPUT_CAP = 50_000
_DEFAULT_DAILY_INPUT_CAP = 2_000_000


class LlmAgentConfig(BaseModel):
    """Typed shape of the ``llm:`` sub-block.

    Fields land here only if the operator opts an agent into LLM driving.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider: str = Field(default="anthropic", pattern=r"^anthropic$")
    model: str = Field(default=_DEFAULT_MODEL, min_length=1, max_length=128)
    system_prompt_ref: str = Field(min_length=1, max_length=256)
    daily_token_cap: int = Field(default=_DEFAULT_DAILY_INPUT_CAP, ge=1_000)
    per_tick_token_cap: int = Field(default=_DEFAULT_PER_TICK_INPUT_CAP, ge=500)
    poll_interval_seconds: float = Field(default=30.0, ge=5.0, le=3600.0)
    max_events_per_tick: int = Field(default=100, ge=1, le=10_000)

    @field_validator("system_prompt_ref")
    @classmethod
    def _no_traversal(cls, v: str) -> str:
        if v.startswith("/") or ".." in v.split("/"):
            raise ValueError(f"system_prompt_ref must be repo-relative: {v!r}")
        return v


class AgentProfile(BaseModel):
    """One agent from ``config/agents.yaml`` with its optional LLM block.

    The upstream YAML has many more fields (role, scope, api_key_hash,
    etc.) used by the API server. The adapter cares about ``id`` and
    the optional ``llm`` block only; unknown keys are ignored.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=128)
    llm: LlmAgentConfig | None = None


def load_agent_profile(path: str | Path, agent_id: str) -> AgentProfile:
    """Load one agent profile from ``config/agents.yaml``.

    Raises ``FileNotFoundError`` if the file is missing, ``KeyError``
    if no agent matches ``agent_id``, and ``pydantic.ValidationError``
    if the ``llm:`` sub-block is malformed.

    Agents without an ``llm:`` block load successfully — callers must
    check ``profile.llm is None`` before trying to drive the agent.
    """
    text = Path(path).read_text(encoding="utf-8")
    raw = cast(dict[str, Any], yaml.safe_load(text) or {})
    for entry in raw.get("agents", []):
        if entry.get("id") == agent_id:
            return AgentProfile.model_validate(entry)
    raise KeyError(f"agent_id {agent_id!r} not found in {path}")


def read_prompt(path: str | Path) -> str:
    """Read and return the full text of a prompt file."""
    return Path(path).read_text(encoding="utf-8")
