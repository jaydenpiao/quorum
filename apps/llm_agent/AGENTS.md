# AGENTS.md — LLM adapter area

## Scope

This directory is the Claude-backed LLM agent. It runs in its own OS
process (one per `agent_id`) and talks to the Quorum API over HTTP —
**no in-process coupling** with `apps/api/`. Treat it as a second API
consumer.

## Rules for changes here

- Never bypass the authenticated `/api/v1/*` routes. The adapter has
  exactly the same permissions as any human-authored POST.
- Never echo LLM prompt content or Claude responses into structlog
  events. Keep `llm_call_completed` metadata-only (model, token counts,
  cache counts, `system_prompt_sha256`, latency, tool-call names).
  Prompts are reviewable in source; runtime content is not for the
  event log.
- Never log the `ANTHROPIC_API_KEY` or the adapter's Quorum bearer
  token. Scrub errors the same way `services/actuators/github/auth.py`
  does — exception type, not exception content.
- Token counts come from `response.usage` — do not estimate client-side.
- Adaptive thinking stays on (`thinking={"type": "adaptive"}`). The
  skill guidance is explicit: no `budget_tokens`, no sampling parameters
  on Opus 4.7.
- Prompt caching: top-level `cache_control={"type": "ephemeral"}` on the
  request builder so the system prompt is cached when long enough to
  qualify. If a future change adds dynamic content to the system prompt
  (e.g. current date, session id), put it **after** the cache breakpoint
  or invalidation will silently eat the cache hit rate.
- Stable content order in request bodies: tools → system → messages.
  Keep the ordering inside each list deterministic across ticks
  (sorted tool list, same system prompt bytes) — the prefix match is
  the only thing that makes caching work.

## Load-bearing files

- `config.py` — parses `llm:` sub-block from `config/agents.yaml`.
- `budget.py` — per-tick + daily token caps; the only enforcement.
- `claude_client.py` — body builder + Anthropic SDK wrapper.
- `quorum_api.py` — the adapter's HTTP client for Quorum.
- `loop.py` — tick orchestration (read → decide → act → persist cursor).
- `metrics.py` — Prometheus counters + optional sidecar metrics server.
- `run.py` — CLI entrypoint.

## Safe extension points

Good places to add behavior:
- New tool definitions in `tools.py` (PR 2+).
- New role-specific system prompts in `prompts/<role>.md`.
- Additional cap knobs in `budget.py`.

## Avoid

- Blocking the Quorum API from within the adapter (e.g. polling so fast
  you exhaust the rate limit pool). Respect `poll_interval_seconds`.
- Writing prompt or response content to `data/events.jsonl` via any
  path. That log is the control-plane's; the adapter is a mutation
  **cause**, not a mutation.
- Adding a second consumer of `ANTHROPIC_API_KEY` inside `apps/api/`.
  Keep LLM calls in this package.
