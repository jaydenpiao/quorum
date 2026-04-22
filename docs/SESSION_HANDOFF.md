# Session handoff

This document is the canonical "where we left off" note for AI coding agents
picking up Quorum across sessions. Read it before anything except `AGENTS.md`.

Updated after every substantial session; treat entries below as the
authoritative state of the project.

---

## Current state (as of the handoff)

- **Last tagged release:** [`v0.3.0-alpha.1`](https://github.com/jaydenpiao/quorum/releases/tag/v0.3.0-alpha.1) — Phase 4 continued (LLM adapter complete). SBOM attached as `quorum-v0.3.0-alpha.1.spdx.json`.
- **Test suite:** 296 passing + 11 integration-gated (excluded from CI by default; opt-in with `pytest -m integration` against a live Postgres).
- **Coverage:** 84.12% (gate floor: 60%).
- **Type check:** `mypy --strict` clean across 43 source files.
- **Required CI checks on `main`:** `lint + format + test`, `gitleaks`, `pip-audit`, `docker build`, `mypy`.
- **Branch protection:** required PR, linear history, force-push disabled, conversation resolution required.
- **Merged PR count:** 45.

## Phase status

- **✅ Phase 0** — Claude Code harness.
- **✅ Phase 1** — OSS hygiene.
- **✅ Phase 2** — core security (typed health checks, hash chain, bearer auth).
- **✅ Phase 2.5** — server-side actor binding, argon2id keys.
- **✅ Phase 3** — production foundation (Dockerfile, pytest-cov gate, structlog, Prometheus, mypy-strict, SBOM, OTel).
- **✅ Phase 3 capstone** — Postgres projection.
- **✅ Phase 4 GitHub actuator** — four actions end-to-end (`open_pr`, `comment_issue`, `close_pr`, `add_labels`), actuator-aware rollback, `rollback_impossible` event, `github_check_run` health check.
- **✅ Phase 4 LLM adapter** — Claude-backed `telemetry-llm-agent` with `create_finding` + `create_proposal` tools, server-side `allowed_action_types` gate, per-tick + daily token caps. Tagged `v0.3.0-alpha.1`.
- **⬜ Phase 4 remaining** — interactive console (SSE + forms), human approval entity + notifier.
- **⬜ Phase 5** — Fly.io deployment.
- **⬜ Phase 6** — parallel operator-agent worktrees.

All known doc-vs-code drift is closed. No known outstanding tech debt.

## What landed in the Phase 4 LLM-adapter arc

Seven PRs since `v0.2.0-alpha.1`:

- **PR #41** — `HealthCheckKind.github_check_run` (closed the actuator design doc).
- **PR #42** — `docs/design/llm-adapter.md` (no code).
- **PR #43** — LLM adapter scaffold (`apps/llm_agent/` package: config, budget, claude_client body builder, quorum_api client, tick-loop skeleton). No live Claude calls.
- **PR #44** — `create_finding` tool + the real tick: event poll → budget pre-flight → `claude.call_messages()` → record `usage.input_tokens` → dispatch `tool_use` blocks → POST `/api/v1/findings`. `stop_reason='refusal'` handled; metadata-only structlog.
- **PR #45** — `create_proposal` tool + server-side `allowed_action_types` 403 gate + graceful `DailyBudgetExceeded` back-off. LLM can propose `github.comment_issue` / `github.add_labels`; `github.open_pr` / `github.close_pr` stay operator-only with two independent gates (client enum + server list).
- **Release** — `v0.3.0-alpha.1` tag + SBOM + GitHub release notes.
- **PR #46 (this handoff)** — README LLM quickstart, ROADMAP + SESSION_HANDOFF refresh.

Non-blocking design-doc deferrals (suitable for a minor-cleanup PR):
- Prometheus counters (`quorum_llm_tokens_total{agent_id, model, kind}`, `quorum_llm_ticks_total{agent_id, outcome}`, `quorum_llm_proposals_created_total{agent_id, action_type}`). Structured logs already expose the raw counts via `llm_call_completed`.
- `demo_seed` spawning the LLM adapter process (feature-flagged). Currently the operator runs the adapter by hand — documented in the README.
- System-prompt hash in `llm_call_completed` events for audit reproducibility (open question from the design).

## Reading order for a fresh session

Canonical order — load these before touching code:

1. `AGENTS.md` — repo-wide operating rules and Definition of Done (binding).
2. **This file** (`docs/SESSION_HANDOFF.md`).
3. `docs/ROADMAP.md` — phase status with ✅/⏳/⬜/✂️ markers.
4. `CHANGELOG.md` — every feature since bootstrap under `[Unreleased]`.
5. `docs/design/llm-adapter.md` — LLM adapter design reference.
6. `docs/design/phase-4-github-actuator.md` — GitHub actuator design reference.
7. `docs/ARCHITECTURE.md` — system picture including the Actuators section.

Area-specific deep reads are already linked from `AGENTS.md`'s "Required reading by area" section.

## Known gotchas (earned the hard way)

1. **Ruff `PostToolUse` hook strips unused imports — hit ~10 times across this session.** Two workarounds both work: (a) add the import **and** its first usage in a single atomic Edit, or (b) for larger diffs, use `Write` to rewrite the file wholesale — the formatter sees only the final state and keeps every import that is used there. (b) is the safer default for multi-import refactors.
2. **`backend-engineer` subagent stalls on multi-file Python work.** All Phase 4 + LLM-adapter PRs were driven on the main thread.
3. **Gitleaks hits on API-key-shaped test fixtures.** Generate fake values at test setup (RSA via `cryptography`, short `test-key-ignored` literals for Anthropic). No PEM / JWT / argon2id literals in `tests/`.
4. **Output classifier can trip on aggregated security-heavy language.** Keep PR bodies lean.
5. **`.env.example` was blocked by an over-broad deny rule** (fixed in PR #29). Check `.claude/settings.json` if it regresses.
6. **`docs-writer` subagent has no `Bash` tool.** Dispatch, then finish git ops yourself.
7. **Subagent worktrees stay locked** after completion. Clean up with `git worktree remove --force ...`.
8. **Dispatch-completeness test in `tests/test_postgres_projector.py`** fails if a new event type lacks a projector handler. Add the handler in the same commit — this is now the template pattern (see PR C for `rollback_impossible`).
9. **`EventLog.append` is sync.** Keep `apply(event)` sync.
10. **Hash chain verification runs on startup.** A tampered `data/events.jsonl` refuses to boot. Reset with `make reset`.
11. **`allowed_action_types` cache leaks between tests.** `@lru_cache(maxsize=1)` on the loader is cleared by `reload_all_registries()`. Test fixtures that write a throwaway agents.yaml must call it (pattern in `tests/test_allowed_action_types.py`).
12. **Anthropic SDK in tests.** Construct with `api_key="test-key-ignored"` + `max_retries=0`; `respx` intercepts `https://api.anthropic.com/v1/messages`. Never hit the real API in CI.

## Next-session candidates (pick one, by priority)

### A — Interactive console (SSE + forms)

Medium scope (~800 LOC), self-contained, demo-visible:
- New SSE endpoint `GET /api/v1/events/stream` yielding `EventEnvelope` payloads as they land.
- Frontend: replace the read-only `<pre>` blocks with forms for `create_intent` / `create_finding` / `create_proposal` / `create_vote`. Live-tail the event stream instead of polling.
- Adds operator visibility into LLM agent activity (currently only structlog reports it).
- No new event types, no backend state machine changes.

### B — Human approval entity + notifier

Medium scope (~600 LOC), adds three new event types:
- `human_approval_requested` — emitted when policy says `requires_human=true`.
- `human_approval_granted` / `human_approval_denied` — operator decision.
- New route `POST /api/v1/approvals/{proposal_id}` with grant/deny.
- Quorum engine gate: `requires_human=true` proposals wait for an approval even when votes pass.
- Notifier protocol (log-only implementation for v1; Slack/email later).
- Needs the full 5-touch-point dance per `.claude/skills/create-event-type.md` — three times.

### C — Phase 5: Fly.io deployment

Bigger, operator-action-dependent:
- `fly.toml`, Fly Volume for canonical JSONL, Neon Postgres for projection.
- Staging + prod apps.
- Dog-food deploys: production deploys flow through the Quorum API itself (deploy-agent → code-agent votes → operator approves → executor calls `fly deploy ...@sha256:...`).
- Requires Fly account, DNS, secret provisioning. Operator-action-heavy — best in a dedicated session.

### D — Minor follow-ups worth batching into a single PR

- Prometheus counters for the LLM adapter (per `docs/design/llm-adapter.md` §Observability).
- `demo_seed` optionally spawns the LLM adapter process (feature-flagged).
- System-prompt hash in `llm_call_completed` (design open question #4).
- Richer context in `_log.warning("projector_status_update_for_missing_proposal", ...)`.
- `make clean-worktrees` target.

## Parallel development — my recommendation

Unchanged from prior sessions:

- **One main thread** drives each PR end-to-end. The v0.3 arc was seven PRs on main-thread.
- **Parallel `Agent` tool dispatches with `isolation: "worktree"`** for independent lanes — especially devops/docs work alongside a backend change.
- `run_in_background: true` on dispatched agents.
- **Main thread finishes git ops for any subagent without `Bash`** (notably `docs-writer`).
- **Genuine multi-terminal `claude` sessions per worktree** is Phase 6 territory.

## Maintenance notes

- **Dependabot:** weekly Python, monthly Actions.
- **CI cadence:** all 5 required checks run in parallel in ~15–40 s each. The v0.3 arc kept every PR inside this envelope.
- **Release cadence:** tag when a meaningful feature set accumulates under `[Unreleased]` in CHANGELOG. Alpha tags are `v0.N.0-alpha.M`. v0.2.0 cut at Phase 4 GitHub actuator complete; v0.3.0 at Phase 4 LLM adapter complete.

---

*Update this file at the end of every substantial session. Future-you reads it first.*
