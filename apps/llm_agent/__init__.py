"""Claude-backed LLM agent for Quorum.

Runs as its own process (one per ``agent_id``). Reads the Quorum event
stream, synthesises findings / proposals, and POSTs them back through
the same authenticated ``/api/v1/*`` routes any other caller uses. The
adapter never bypasses auth, policy, or quorum — every mutation still
flows through the control plane's safety primitives.

PR 1 (this PR) ships scaffolding only:
- Config loader for the ``llm:`` sub-block in ``config/agents.yaml``
- Budget accounting (per-tick + daily token caps; JSON-checkpoint
  persistence under ``data/llm_usage/``)
- ``ClaudeClient`` body builder with prompt-caching + adaptive-thinking
  wiring (no live calls yet — tested via respx)
- ``QuorumApiClient`` httpx wrapper (GET events / POST findings / POST
  proposals)
- ``tick()`` + ``run.py`` CLI skeleton

PR 2 will add the ``create_finding`` tool + one system prompt + the
full tick loop that actually calls Claude. PR 3 adds ``create_proposal``,
cost-cap hard enforcement, demo wiring.

See ``docs/design/llm-adapter.md`` for the full design.
"""
