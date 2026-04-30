"""Claude-backed LLM agent for Quorum.

Runs as its own process (one per ``agent_id``). Reads the Quorum event
stream, synthesises findings / proposals, and POSTs them back through
the same authenticated ``/api/v1/*`` routes any other caller uses. The
adapter never bypasses auth, policy, or quorum — every mutation still
flows through the control plane's safety primitives.

Current capabilities:
- Config loader for the ``llm:`` sub-block in ``config/agents.yaml``
- Budget accounting (per-tick + daily token caps; JSON-checkpoint
  persistence under ``data/llm_usage/``)
- ``ClaudeClient`` body builder with prompt-caching + adaptive-thinking
  wiring
- ``QuorumApiClient`` httpx wrapper (GET events / POST findings / POST
  proposals / POST votes)
- ``run_tick()`` + ``run.py`` CLI loop
- ``create_finding``, ``create_proposal``, and ``cast_vote`` tool
  dispatch

See ``docs/design/llm-adapter.md`` for the full design.
"""
