"""Tool schemas + tool-use dispatch for the LLM adapter.

PR 2 ships one tool: ``create_finding``. Each tool here has two pieces:

1. A JSON Schema (``*_TOOL_SCHEMA``) that Claude sees in the request
   body. The shape mirrors Quorum's ``FindingCreate`` DTO so an
   agent that writes a valid tool call writes a valid Quorum payload.
2. A dispatch path (``dispatch_tool_use``) that turns a Claude
   ``ToolUseBlock`` into a single authenticated POST against the
   Quorum API and wraps the outcome in a ``ToolDispatchResult`` for
   logging.

The dispatcher does **not** pre-validate the tool input locally. The
Quorum API already validates every mutating payload with pydantic —
doing it twice means the adapter ships a shadow DTO that can drift
from the server. Instead, the dispatcher forwards the input and
translates 4xx responses into a failed ``ToolDispatchResult``. Claude
sees the failure on the next turn (once the loop runs multi-turn in
PR 3+); the operator sees the same failure in the structlog
``llm_tool_dispatch_completed`` event.

Tool order is deterministic: the list ``TOOL_SCHEMAS`` is sorted by
``name`` so the rendered request body has stable bytes across ticks.
Prompt caching cares about stable tool lists — any reorder here
invalidates the entire system-prompt cache prefix.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import anthropic

from apps.llm_agent.quorum_api import QuorumApiClient, QuorumApiError

# Tool-dispatch handler signature.
_Handler = Callable[[str, dict[str, Any], QuorumApiClient], "ToolDispatchResult"]


# ---------------------------------------------------------------------------
# create_finding
# ---------------------------------------------------------------------------

# Quorum's FindingCreate DTO:
# - intent_id: str, max_length=128
# - summary: str, min_length=1, max_length=4000
# - evidence_refs: list[str], max_length=50
# - confidence: float in [0, 1], default 0.5
#
# agent_id is OMITTED from the schema — the Quorum server binds it
# server-side from the bearer token, and accepting a user-supplied
# agent_id would invite spoofing attempts (which the server rejects
# anyway with 403, per PR #14, but keeping it out of the schema
# avoids the Claude-side temptation).
FINDING_TOOL_SCHEMA: dict[str, Any] = {
    "name": "create_finding",
    "description": (
        "Record a structured finding about observed Quorum event-stream "
        "state. Use this when you spot a noteworthy pattern, regression, "
        "or anomaly. Keep summaries factual, semantically compact, and "
        "free of quoted secrets or large payload excerpts."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent_id": {
                "type": "string",
                "maxLength": 128,
                "description": (
                    "The intent this finding relates to. Copy from an "
                    "intent_created event in the stream."
                ),
            },
            "summary": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4000,
                "description": (
                    "1-4 sentences describing the observation. Factual, "
                    "operator-readable. Do NOT echo tokens, API keys, or "
                    "raw payload bytes."
                ),
            },
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 50,
                "description": (
                    "Up to 50 event ids / URLs supporting the finding. "
                    "Prefer event ids from the stream over URL strings."
                ),
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": (
                    "How confident you are that this finding is real and "
                    "worth operator attention. Default 0.5 when unsure."
                ),
            },
        },
        "required": ["intent_id", "summary"],
    },
}

# ---------------------------------------------------------------------------
# create_proposal
# ---------------------------------------------------------------------------

# Union of action types any LLM-driven agent may propose. The tool-schema
# enum gate is a UX / prompt-discipline boundary: it narrows what Claude
# can pick from. The **security** gate is per-agent, server-side —
# ``allowed_action_types`` in ``config/agents.yaml`` (loaded by
# ``apps/api/app/services/auth.py`` and enforced in
# ``apps/api/app/api/routes.py``). An agent whose allow-list omits a
# value here will 403 if it tries to use it, even if the schema lets
# Claude request it.
#
# Per-role subsets (v1):
# - ``telemetry-llm-agent`` → ``github.add_labels``, ``github.comment_issue``
# - ``deploy-llm-agent``    → ``fly.deploy`` (Phase 5)
#
# open_pr / close_pr remain operator-only — see the "voter role timing"
# open question in ``docs/design/llm-adapter.md``.
LLM_ALLOWED_PROPOSAL_ACTION_TYPES: tuple[str, ...] = (
    "fly.deploy",
    "github.add_labels",
    "github.comment_issue",
)

PROPOSAL_TOOL_SCHEMA: dict[str, Any] = {
    "name": "create_proposal",
    "description": (
        "Propose a reviewable action. The proposal is policy- and quorum-"
        "gated before execution; your call here submits it, nothing "
        "more. Your own allowed subset of action_types is narrower than "
        "this schema's enum — the server enforces per-agent "
        "allowed_action_types and returns 403 on a mismatch. Use the "
        "action types listed in your role's system prompt."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent_id": {
                "type": "string",
                "maxLength": 128,
                "description": (
                    "The intent this proposal serves. Copy from an "
                    "intent_created event in the stream."
                ),
            },
            "title": {
                "type": "string",
                "minLength": 1,
                "maxLength": 500,
                "description": "Short, operator-readable title.",
            },
            "action_type": {
                "type": "string",
                "enum": list(LLM_ALLOWED_PROPOSAL_ACTION_TYPES),
                "description": (
                    "One of the allowed action types. Attempting a "
                    "value outside the enum returns 403 server-side."
                ),
            },
            "target": {
                "type": "string",
                "minLength": 1,
                "maxLength": 256,
                "description": (
                    "Canonical target string, e.g. 'owner/repo#123' for "
                    "an issue or PR. Matches the payload below."
                ),
            },
            "environment": {
                "type": "string",
                "maxLength": 64,
                "description": (
                    "Runtime environment for policy and audit context, "
                    "for example 'staging', 'prod', or 'local'."
                ),
            },
            "risk": {
                "type": "string",
                "enum": ["low", "medium", "high", "critical"],
                "description": (
                    "Operator-facing risk level. Use 'high' or "
                    "'critical' only for actions that can mutate "
                    "production or cause broad service impact."
                ),
            },
            "rationale": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4000,
                "description": (
                    "Why this action is warranted. Operators reviewing "
                    "the proposal will read this; be factual and "
                    "evidence-grounded."
                ),
            },
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 50,
                "description": (
                    "Up to 50 event ids, workflow URLs, release refs, or "
                    "other operator-checkable evidence. Prefer event ids "
                    "from Quorum's stream when available."
                ),
            },
            "rollback_steps": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 50,
                "description": (
                    "Plain-text rollback instructions the actuator will automate where possible."
                ),
            },
            "health_checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "kind": {
                            "type": "string",
                            "enum": ["always_pass", "always_fail", "http", "github_check_run"],
                        },
                        "url": {"type": "string"},
                        "method": {"type": "string", "enum": ["GET", "HEAD"]},
                        "expected_status": {
                            "type": "integer",
                            "minimum": 100,
                            "maximum": 599,
                        },
                        "timeout_seconds": {
                            "type": "number",
                            "minimum": 0.1,
                            "maximum": 1800.0,
                        },
                    },
                    "required": ["name"],
                    "additionalProperties": True,
                },
                "maxItems": 20,
                "description": (
                    "Post-change checks Quorum should run after execution. "
                    "The API validates the final HealthCheckSpec shape."
                ),
            },
            "payload": {
                "type": "object",
                "description": (
                    "Action-type-specific payload. Shape depends on "
                    "action_type; see the Quorum docs for each. "
                    "Invalid payloads return 422."
                ),
            },
        },
        "required": ["intent_id", "title", "action_type", "target", "rationale", "payload"],
    },
}


# Ordered tool list. Sorted by name so body bytes are stable across
# ticks — prompt caching depends on exact-byte prefix match.
TOOL_SCHEMAS: list[dict[str, Any]] = sorted(
    [FINDING_TOOL_SCHEMA, PROPOSAL_TOOL_SCHEMA],
    key=lambda t: t["name"],
)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class LlmToolError(RuntimeError):
    """Raised when a tool call cannot even be attempted.

    Distinct from a dispatch that ran and failed — those return a
    ``ToolDispatchResult`` with ``ok=False``. ``LlmToolError`` is for
    "this tool name is unknown" / "this block isn't a tool_use".
    """


@dataclass(frozen=True)
class ToolDispatchResult:
    """Outcome of one ``ToolUseBlock`` → Quorum POST.

    Pure data, loggable. Passed back to the caller so the tick loop
    can emit one ``llm_tool_dispatch_completed`` event per tool_use.
    """

    tool_name: str
    tool_use_id: str
    ok: bool
    detail: str
    api_status_code: int | None = None
    quorum_entity_id: str | None = None


def dispatch_tool_use(
    block: anthropic.types.ToolUseBlock,
    quorum: QuorumApiClient,
) -> ToolDispatchResult:
    """Execute one tool_use block against the Quorum API.

    Returns a ``ToolDispatchResult`` describing the outcome. Raises
    ``LlmToolError`` only when the block is structurally unusable
    (unknown tool name, non-dict input); normal 4xx/5xx responses
    from Quorum come back as ``ok=False`` results.
    """
    if block.name not in _HANDLERS:
        raise LlmToolError(f"unknown tool {block.name!r}; supported: {sorted(_HANDLERS.keys())}")

    tool_input = block.input
    if not isinstance(tool_input, dict):
        raise LlmToolError(f"tool_use.input must be an object, got {type(tool_input).__name__}")

    handler = _HANDLERS[block.name]
    return handler(block.id, tool_input, quorum)


def _dispatch_create_finding(
    tool_use_id: str,
    tool_input: dict[str, Any],
    quorum: QuorumApiClient,
) -> ToolDispatchResult:
    try:
        response = quorum.create_finding(tool_input)
    except QuorumApiError as exc:
        return ToolDispatchResult(
            tool_name="create_finding",
            tool_use_id=tool_use_id,
            ok=False,
            detail=f"quorum rejected finding: {exc.status_code}: {exc.message}",
            api_status_code=exc.status_code,
        )

    finding_id = response.get("id") if isinstance(response, dict) else None
    if not isinstance(finding_id, str) or not finding_id:
        return ToolDispatchResult(
            tool_name="create_finding",
            tool_use_id=tool_use_id,
            ok=False,
            detail="quorum accepted the finding but returned no id",
            api_status_code=200,
        )

    return ToolDispatchResult(
        tool_name="create_finding",
        tool_use_id=tool_use_id,
        ok=True,
        detail=f"created finding {finding_id}",
        api_status_code=200,
        quorum_entity_id=finding_id,
    )


def _dispatch_create_proposal(
    tool_use_id: str,
    tool_input: dict[str, Any],
    quorum: QuorumApiClient,
) -> ToolDispatchResult:
    # Client-side allow-list check. The server enforces the same list
    # via allowed_action_types (agents.yaml), but gating here too gives
    # a faster failure path that doesn't bill a round trip.
    requested_action = tool_input.get("action_type")
    if requested_action not in LLM_ALLOWED_PROPOSAL_ACTION_TYPES:
        return ToolDispatchResult(
            tool_name="create_proposal",
            tool_use_id=tool_use_id,
            ok=False,
            detail=(
                f"action_type {requested_action!r} is not allowed for LLM-emitted "
                f"proposals; allowed: {list(LLM_ALLOWED_PROPOSAL_ACTION_TYPES)}"
            ),
        )

    try:
        response = quorum.create_proposal(tool_input)
    except QuorumApiError as exc:
        return ToolDispatchResult(
            tool_name="create_proposal",
            tool_use_id=tool_use_id,
            ok=False,
            detail=f"quorum rejected proposal: {exc.status_code}: {exc.message}",
            api_status_code=exc.status_code,
        )

    proposal_id = _proposal_id_from_response(response)
    if not isinstance(proposal_id, str) or not proposal_id:
        return ToolDispatchResult(
            tool_name="create_proposal",
            tool_use_id=tool_use_id,
            ok=False,
            detail="quorum accepted the proposal but returned no id",
            api_status_code=200,
        )

    return ToolDispatchResult(
        tool_name="create_proposal",
        tool_use_id=tool_use_id,
        ok=True,
        detail=f"created proposal {proposal_id}",
        api_status_code=200,
        quorum_entity_id=proposal_id,
    )


def _proposal_id_from_response(response: dict[str, Any]) -> str | None:
    """Extract a proposal id from both historical and current route shapes."""
    proposal_id = response.get("id")
    if isinstance(proposal_id, str) and proposal_id:
        return proposal_id
    proposal = response.get("proposal")
    if isinstance(proposal, dict):
        nested_id = proposal.get("id")
        if isinstance(nested_id, str) and nested_id:
            return nested_id
    return None


_HANDLERS: dict[str, _Handler] = {
    "create_finding": _dispatch_create_finding,
    "create_proposal": _dispatch_create_proposal,
}
