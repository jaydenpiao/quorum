# Design: LLM adapter (Phase 4 continuation)

Status: design proposal — no code in this PR. Target: 3 implementation
PRs after review.

## Context and goal

Quorum today is a control plane without any agents. The event stream,
policy engine, and actuator layer are real; the agents that populate
them are humans or demo seeders. To deliver the product promise — "AI
agents operate safely under quorum" — we need at least one LLM-backed
agent that reads the event stream and produces structured proposals,
then stands in the same quorum queue as human operators.

Claude is the lowest-friction first adapter:

- Anthropic's SDK is well-typed and ships prompt caching + native tool use
- The agent's entire job (read events, emit findings/proposals) maps
  cleanly onto tool use
- Cost is bounded by per-turn + daily token caps
- No mutation happens inside the adapter — it exclusively POSTs through
  the existing authenticated `/api/v1/*` routes, so every safety
  primitive (auth, actor binding, policy, quorum) remains the only
  path to side-effects

Out of scope here: autonomous voting, autonomous execution, local
models, multi-agent dialogue. Those are deferred to later phases or
cut entirely.

## Non-goals

- **Replace human operators.** The LLM emits *proposals*; quorum
  approval stays human until the safety posture around AI votes is
  explicitly designed (open question).
- **Autonomous execution.** The adapter does not call execute
  endpoints. Only operators trigger execution today; no change here.
- **Local / open-weights models.** Keep the Anthropic SDK as the one
  v1 backend, but design for pluggability so a future adapter can
  target another API-compatible provider.
- **Multi-turn dialogue.** Each tick is stateless: last-N events in,
  zero-or-more tool calls out. No conversation history beyond the
  current tick.

## Agent role in v1

**Proposer-only.** A single `telemetry-llm-agent` identity that:

- Observes the event stream
- Emits `finding_created` events when it spots something novel
- Emits `proposal_created` events when a finding warrants action
- Does **not** vote. Does **not** execute. Does **not** comment on
  existing proposals.

Why start here: proposer is the lowest-blast-radius role — every
downstream mutation still requires a human vote, so a misbehaving LLM
costs a few bytes of event log and a human reading the output. Voting
adds policy-bypass risk if the LLM colludes with itself or operators
coerce it; design that in its own PR.

Later roles (in order of likely sequencing):

1. Voter with explicit per-action trust caps (e.g. can vote on
   `github.add_labels` but not `github.open_pr`)
2. Human-proxy escalator (emits a `human_approval_requested` event
   when it thinks something needs a human, once that entity lands)

## Authentication

**Decision: reuse the Phase 2.5 argon2id-hashed API keys in
`config/agents.yaml`.** The LLM adapter authenticates as a specific
agent_id like any other caller; server-side actor binding (PR #14)
already prevents spoofing.

Config additions to `config/agents.yaml`:

```yaml
agents:
  - id: telemetry-llm-agent
    role: telemetry
    can_vote: false           # v1: proposer only
    can_propose: true
    scope: [metrics, traces, logs]
    api_key_hash: "<argon2id>"
    # New fields for LLM-backed agents:
    llm:
      provider: anthropic
      model: claude-sonnet-4-6
      system_prompt_ref: prompts/telemetry-agent.md
      daily_token_cap: 2_000_000
      per_tick_token_cap: 50_000
```

Secrets stay in env:

- `ANTHROPIC_API_KEY` — Claude API key for the adapter process.
- `QUORUM_API_KEYS` — the adapter's own Quorum credentials
  (`telemetry-llm-agent:<plaintext>` entry).

The adapter process never sees another agent's key, and it talks to
the Quorum API over localhost (or TLS in prod) like any other client.

## Process topology

**One process per LLM agent_id.** Runs as its own Python entrypoint
(`python -m apps.llm_agent.run --agent-id telemetry-llm-agent`).
Stateless between ticks. In prod this is a systemd/Fly.io worker; in
dev it's a terminal.

Why separate from the API server:

- Different crash domain: an LLM agent that OOMs does not crash the
  event log.
- Different scaling: API server is latency-bound; LLM agent is
  tick-bound.
- Different resource contracts: agent can run without a projector,
  without Postgres, without the console — just the API.

The API is the only coupling, and it's HTTP — so the adapter is a
genuine second consumer of `require_agent` auth rather than an
in-process import.

## Loop shape

Every tick:

1. **Poll events.** GET `/api/v1/events?since_id=<cursor>` since the
   last-seen event id. Cursor is persisted on disk (for v1; move to
   a DB row later). Start-of-day cursor = latest event id at
   startup, so new agents don't replay the whole log.
2. **Decide whether to act.** If zero new events, skip the tick. If
   the new events include no events the agent is configured to react
   to (scope filter), skip. This keeps idle cost at zero.
3. **Build a request.** System prompt + last-N events as a compact
   JSON array in the user message. Tools are `create_finding` and
   `create_proposal` (see below).
4. **Call Claude.** Stream or block; for v1 block. Enforce
   `per_tick_token_cap` on the input side; the SDK errors if output
   would exceed Claude's context.
5. **Run tool calls.** Each tool call translates to one authenticated
   POST to `/api/v1/findings` or `/api/v1/proposals`. 4xx responses
   from Quorum are re-surfaced to the LLM in the next turn (if any)
   as a tool-result — for v1 the turn ends after first tool use, so
   4xx just logs + aborts the tick.
6. **Update cursor.** Persist the last-processed event id.
7. **Emit structured log.** `llm_call_completed` event with
   `agent_id`, `model`, `input_tokens`, `output_tokens`,
   `cache_read_tokens`, `cache_write_tokens`, `latency_ms`,
   `tool_calls`. No PII, no prompt content.

Tick cadence starts at 30 s. Tunable via config; no runtime
back-pressure signal yet.

## Tool schema

Two tools in v1, both thin wrappers over existing API routes:

### `create_finding`

```json
{
  "name": "create_finding",
  "description": "Record a structured finding about observed state.",
  "input_schema": {
    "type": "object",
    "properties": {
      "intent_id":     { "type": "string" },
      "summary":       { "type": "string", "minLength": 1, "maxLength": 4000 },
      "evidence_refs": { "type": "array",  "items": { "type": "string" }, "maxItems": 50 },
      "confidence":    { "type": "number", "minimum": 0.0, "maximum": 1.0 }
    },
    "required": ["intent_id", "summary"]
  }
}
```

### `create_proposal`

```json
{
  "name": "create_proposal",
  "description": "Propose an action against a target; will be quorum-voted.",
  "input_schema": {
    "type": "object",
    "properties": {
      "intent_id":       { "type": "string" },
      "title":           { "type": "string", "maxLength": 500 },
      "action_type":     { "type": "string", "enum": ["github.comment_issue", "github.add_labels"] },
      "target":          { "type": "string", "maxLength": 256 },
      "rationale":       { "type": "string", "maxLength": 4000 },
      "rollback_steps":  { "type": "array",  "items": { "type": "string" }, "maxItems": 50 },
      "health_checks":   { "type": "array",  "items": { "type": "object" }, "maxItems": 20 },
      "payload":         { "type": "object" }
    },
    "required": ["intent_id", "title", "action_type", "target", "rationale", "payload"]
  }
}
```

**Deliberately restricted action_type enum.** v1 only lets the LLM
propose low-risk actions (`comment_issue`, `add_labels`). `open_pr`
and `close_pr` require an operator. This is enforced client-side
(tool schema) and server-side can add a same-day follow-up — a per-
agent `allowed_action_types` list in `config/agents.yaml` that
`routes.create_proposal` honours.

Tool-input validation matches the Quorum DTOs exactly (same pydantic
constraints, pydantic-derived JSON Schema if possible — open question
on the right library to do that cleanly).

## Prompt architecture

Prompt caching is critical for cost. Claude's cache bills ~10% of
input tokens on reads; without it a chatty system prompt dominates
costs.

### Caching structure

```
[system]      ← stable; cached with `cache_control: ephemeral`
  - agent role + quorum vocabulary
  - action_type catalogue
  - tool schemas (sent separately; cached automatically)
  - a few-shot examples of good findings / proposals

[user]        ← per-tick; NOT cached
  - cursor: "events since evt_abc123"
  - events: [...]
  - ask: "emit zero or more tool calls"
```

Cache breakpoint sits between system and user. Short system prompts
below ~1024 tokens aren't eligible (Claude's cache minimum); v1 will
have a larger system prompt (vocabulary + examples) to push past that
threshold intentionally.

### Turning the system prompt into an asset

Ship each agent's system prompt as a Markdown file at
`apps/llm_agent/prompts/<role>.md`. Version-controlled, reviewable,
templateable by the operator. The adapter renders placeholders
(e.g. `{quorum_version}`) at startup. No template logic per-tick so
the cache stays warm.

## Model choice

**Default: `claude-sonnet-4-6`** — cheapest sensible tier; good at
structured JSON output with tools.

- **Opus** (`claude-opus-4-7`) via env override (`QUORUM_LLM_MODEL`)
  when debugging a specific tick. Not for steady-state — too
  expensive for a polling loop.
- **Haiku** (`claude-haiku-4-5`) if cost drops further; haiku is
  probably too small for reasoning about events but worth a
  measurement when the adapter is running.

Leave the model in config per agent so one deployment can mix
(e.g., telemetry-agent on Haiku, deploy-agent on Sonnet). Do not
pin a single `ANTHROPIC_MODEL` at the process level — that's a
leaky abstraction if a second agent class lands.

## Cost caps

Two caps, both hard (adapter halts / no-ops on exceed):

| Cap | Scope | Default | Enforcement |
|-----|-------|---------|-------------|
| `per_tick_token_cap`   | One adapter call | 50_000 input  | Reject tick before call if estimated input > cap (truncate event window until it fits) |
| `daily_token_cap`      | Per agent_id    | 2_000_000 input | Adapter refuses new ticks once cumulative day exceeds cap |

Accounting is in-memory for v1 with a local JSON checkpoint at
`data/llm_usage/<agent_id>-<YYYY-MM-DD>.json`. Move to Postgres
projection later if multi-process deployment lands.

Also emit a `structlog` event `llm_call_completed` per tick with all
token counts + `cache_read_tokens` / `cache_write_tokens`. Surface
this as a Prometheus counter (`quorum_llm_tokens_total{agent_id,
model, kind}`) so operators see the spend live.

## Testing

Three layers, mirroring the Phase 4 actuator plan:

1. **Unit (fast, always on)** — mock the Anthropic HTTP surface with
   `respx` (already a dev dep from PR #35). Cover: cursor advance,
   cap enforcement, tool-call → POST translation, 4xx handling,
   system-prompt caching-control marker correctness.
2. **Contract** — validate that the adapter's synthesised POST
   bodies round-trip through the same pydantic DTOs the API uses
   (`FindingCreate`, `ProposalCreate`) so the adapter can never send
   a body the API would reject at the boundary.
3. **Replay** — a small set of recorded Claude responses under
   `tests/fixtures/llm_adapter/*.json` covering happy path, refusal,
   tool-call + text mix, and over-cap. Respx plays them back; no
   live API calls in CI.

We do **not** test live against api.anthropic.com in CI. An opt-in
`QUORUM_LLM_LIVE_TESTS=1` gate can replay two fixtures against the
real API during demo prep — same pattern as `QUORUM_GITHUB_LIVE_TESTS=1`.

## Module layout

```
apps/llm_agent/
  __init__.py
  AGENTS.md                   # area-specific rules for this codepath
  run.py                      # CLI entrypoint; argparse; loads config
  loop.py                     # the tick loop; cursor persistence
  claude_client.py            # thin wrapper over anthropic.Anthropic
  tools.py                    # tool schemas + tool-call dispatch
  prompts/
    telemetry-agent.md        # system prompt
  quorum_api.py               # HTTP client over /api/v1 (requests/httpx)
  budget.py                   # per-tick + daily cap enforcement + accounting
```

Three tests files:

```
tests/test_llm_adapter_budget.py       # cap math
tests/test_llm_adapter_tools.py        # tool-call → POST translation
tests/test_llm_adapter_loop.py         # cursor advance + idle skip
```

## Policy interaction

The LLM agent posts through the existing authenticated routes; the
policy engine is unchanged. Two additions worth planning for:

1. **Per-agent action_type allow-list** — a `config/agents.yaml`
   field `allowed_action_types: [github.comment_issue, github.add_labels]`.
   Route handlers reject mismatched proposals with 403 before the
   event log sees them. Lands in implementation PR 2.
2. **LLM-emitted proposals may demand `requires_human=true`** — open
   question below. If we decide yes, add a policy rule:
   `proposals emitted by llm:* agents are forced to requires_human=true`.
   This is a one-line change in `policy_engine.evaluate`.

## Rollout plan (3 PRs)

**PR 1 — scaffold + auth + config + loop skeleton** (~600 LOC)
- `apps/llm_agent/` package with `run.py`, `loop.py`, `budget.py`,
  `quorum_api.py`.
- `config/agents.yaml` extended with the `llm:` sub-block.
- Budget accounting (JSON checkpoint; in-memory cache).
- `claude_client.py` with prompt-caching-marker wiring (no live
  calls yet — just body construction + respx tests).
- `tests/test_llm_adapter_budget.py`. No Anthropic calls.

**PR 2 — first tool: `create_finding` end-to-end** (~700 LOC)
- `tools.py` with `create_finding` schema + dispatch.
- One system prompt (`prompts/telemetry-agent.md`) — small, 1-page.
- End-to-end tick: poll events → build request → (respx-mocked) call
  Claude → run tool → POST `/api/v1/findings`.
- Per-agent `allowed_action_types` check on the server side (for
  proposals, lands empty-list for telemetry).
- `tests/test_llm_adapter_tools.py` + `tests/test_llm_adapter_loop.py`.

**PR 3 — `create_proposal` + cost cap hard-enforcement + demo wiring** (~500 LOC)
- `create_proposal` tool; restricted action_type enum.
- Hard-stop on daily cap exceeded.
- `llm_call_completed` structlog event + Prometheus counter.
- `demo_seed` optionally spawns the LLM agent process (feature-flagged).
- Docs: README quickstart for "run the LLM agent against your local
  Quorum server".

Each PR passes the existing 5 required CI checks, no event-log
schema change, no auth change.

## Observability

- **Traces.** One OTel span per tick (`llm_agent.tick`) with child
  spans `llm_agent.anthropic_call` and `llm_agent.quorum_post`.
  Attributes: `quorum.agent_id`, `llm.model`, `llm.input_tokens`,
  `llm.output_tokens`, `llm.cache_read_tokens`,
  `llm.cache_write_tokens`, `quorum.events_consumed`.
- **Metrics (Prometheus).**
  - `quorum_llm_tokens_total{agent_id, model, kind}` where kind ∈
    `{input, output, cache_read, cache_write}`.
  - `quorum_llm_ticks_total{agent_id, outcome}` where outcome ∈
    `{acted, skipped_idle, skipped_cap, error}`.
  - `quorum_llm_proposals_created_total{agent_id, action_type}`.
- **Logs (structlog JSON).**
  - `llm_tick_started` / `llm_tick_completed` bookending each tick.
  - `llm_call_completed` with token counts + latency. No prompt /
    response content.
  - `llm_cap_exceeded` when the daily cap blocks a tick.

## Open questions (for review)

1. **Voter role timing.** Should we skip voter entirely for v1 and
   revisit after observing a month of proposer-only activity? Lean:
   yes — the attack surface is materially larger and we can't write
   a useful design until we see what LLM proposers actually submit.
2. **`requires_human=true` for all LLM-origin proposals.** Safest
   default, but slows the demo. Lean: make it per-action_type — LLM-
   emitted `comment_issue` / `add_labels` stay
   `requires_human=false`; any new higher-risk action flips to
   `true`. Codify as a policy rule, not hard-coded.
3. **Cursor persistence on crash.** JSON checkpoint is fine for dev
   but racy with concurrent adapter processes. Defer concurrency
   story to Phase 6 (worktrees) and keep JSON for v1.
4. **System prompt versioning.** Check hashes of the rendered
   prompt into `llm_call_completed` so audits can trace which
   prompt a given call used. Lean: yes — one extra field, one extra
   assertion in tests.
5. **Model auto-pin.** The repo's `AGENTS.md` already names Opus 4.7
   / Sonnet 4.6 / Haiku 4.5. Hard-code the version? Lean: version-
   pinned in `agents.yaml` per-agent; env override for debugging.
   Explicit upgrade is a config edit — no auto-bumps.

## Dependencies landing this brings

- `anthropic>=0.45.0` (runtime). BSD/MIT license; compatible with
  Apache-2.0.
- `respx` is already dev-only (PR #35).
- `types-requests` is **not** needed — use `httpx` which ships
  `py.typed`.

## Success criteria (for review approval)

A reviewer reading this doc top-to-bottom can state:

- Whether the LLM agent runs in-process with the API server (no)
- Which authentication mechanism it uses (argon2id keys from
  `config/agents.yaml`)
- Which actions v1 allows the LLM to propose (`comment_issue`,
  `add_labels`)
- How caching is structured (system prompt cached; per-tick user
  message not cached)
- What the budget caps are and how they're enforced
- How tests avoid hitting api.anthropic.com in CI
- What the three-PR breakdown looks like

An implementing agent, handed PR 1's spec above, can complete it
without re-reading this doc or re-opening closed decisions.
