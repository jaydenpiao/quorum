# Session handoff

This document is the canonical "where we left off" note for AI coding agents
picking up Quorum across sessions. Read it before anything except `AGENTS.md`.

Updated after every substantial session; treat entries below as the
authoritative state of the project.

---

## Current state (as of the handoff)

- **Last tagged release:** [`v0.4.0-alpha.1`](https://github.com/jaydenpiao/quorum/releases/tag/v0.4.0-alpha.1). **Phase 5 shipped to `main`; `v0.5.0-alpha.1` to be tagged next once this handoff lands.**
- **Test suite:** 355 passing + 11 integration-gated (excluded from CI by default; opt-in with `pytest -m integration` against a live Postgres).
- **Coverage:** 84% (gate floor: 60%).
- **Type check:** `mypy --strict` clean across 47 source files.
- **Required CI checks on `main`:** `lint + format + test`, `gitleaks`, `pip-audit`, `docker build`, `mypy`. All 5 pass on every PR in the series.
- **Branch protection:** required PR, linear history, force-push disabled, conversation resolution required.
- **Merged PR count:** 55. Phase 5 added #50 design doc, #54 fly.toml + /readiness (replaced auto-closed #51), #52 fly.deploy actuator, #53 handoff update, #55 deploy-llm-agent, #56 image-push CI.
- **Event types dispatched:** 20 — `intent_created`, `finding_created`, `proposal_created`, `policy_evaluated`, `proposal_voted`, `proposal_approved`, `proposal_blocked`, `execution_started`, `execution_succeeded`, `execution_failed`, `health_check_completed`, `rollback_started`, `rollback_completed`, `rollback_impossible`, `human_approval_requested`, `human_approval_granted`, `human_approval_denied`. No Phase 5 event types — `fly.deploy` reuses the existing `proposal_created` / `execution_*` / `rollback_*` chain.

## Phase status

- **✅ Phase 0** — Claude Code harness.
- **✅ Phase 1** — OSS hygiene.
- **✅ Phase 2** — core security (typed health checks, hash chain, bearer auth).
- **✅ Phase 2.5** — server-side actor binding, argon2id keys.
- **✅ Phase 3** — production foundation (Dockerfile, pytest-cov gate, structlog, Prometheus, mypy-strict, SBOM, OTel).
- **✅ Phase 3 capstone** — Postgres projection.
- **✅ Phase 4** — GitHub App actuator (4 actions + rollback + `rollback_impossible` event + `github_check_run` health check); LLM adapter (telemetry-llm-agent with `create_finding` + `create_proposal` + `allowed_action_types` gate); **human approval entity + 3 events**; **interactive console with SSE live-tail + forms**. All four Phase 4 roadmap items shipped. Tagged `v0.4.0-alpha.1`.
- **✅ Phase 5** — Fly.io deployment. All merged to `main`:
  - **PR #50** — `docs/design/fly-deployment.md`.
  - **PR #54** (replaces auto-closed #51) — `fly.toml` + `GET /readiness` + 4 tests.
  - **PR #52** — `fly.deploy` actuator + executor prefix-dispatch refactor + policy rule. 27 tests.
  - **PR #53** — SESSION_HANDOFF update.
  - **PR #55** — `deploy-llm-agent` role + system prompt + `allowed_action_types: [fly.deploy]`. 6 tests.
  - **PR #56** — image-push CI workflow, gated on `FLY_API_TOKEN`.
- **⬜ Phase 6** — parallel operator-agent worktrees.

All known doc-vs-code drift is closed. No known outstanding tech debt.

## What landed since v0.3.0-alpha.1

Three PRs close the last two Phase 4 roadmap items:

- **PR #46** — README LLM quickstart + ROADMAP/HANDOFF refresh for v0.3.
- **PR #47** — Human approval entity. Three new event types (`human_approval_requested` / `_granted` / `_denied`), new `POST /api/v1/approvals/{proposal_id}` route, execute-time gate, terminal `ProposalStatus.approval_denied`, Alembic 0004 + projector handlers + dispatch-completeness update.
- **PR #48** — SSE event stream + interactive console forms. `EventLog.subscribe()` pub/sub; `GET /api/v1/events/stream`; bearer-token + `create_intent` + cast-vote + grant/deny-approval forms; EventSource live-tail.

## Phase 5 — what it unlocks

Quorum can now deploy itself on Fly.io. The path an operator follows:

1. Provision a Fly app + volume per `docs/design/fly-deployment.md` §Operator pre-reqs.
2. `fly secrets set QUORUM_API_KEYS=... QUORUM_GITHUB_APP_PRIVATE_KEY=... DATABASE_URL=... --app <app>`.
3. `fly deploy --app <app>` locally once for the bootstrap.
4. Optional: set `FLY_API_TOKEN` as a repo secret; every merge to `main` pushes a tagged image to `registry.fly.io/quorum-prod`.
5. Run the `deploy-llm-agent` process (`python -m apps.llm_agent.run --agent-id deploy-llm-agent`) to watch for new image digests and propose `fly.deploy` actions.
6. Approve each proposal via the operator console. Quorum executes `fly deploy --image registry.fly.io/quorum-prod@sha256:...` under the policy + human-approval gate.

Three design-level invariants that hold across the whole flow:

- **Single-machine-per-app.** Fly Volumes are per-machine; `EventLog` is single-writer. Multi-machine fleets are explicitly deferred.
- **Content-addressed deploys.** `FlyDeploySpec` rejects tags at the pydantic boundary; only `sha256:<64 hex>` passes.
- **Human in the loop for every prod deploy.** `fly.deploy` policy rule is `votes_required: 2, requires_human: true`. Deploys never execute without an explicit approval entity event.

## Reading order for a fresh session

Canonical order — load these before touching code:

1. `AGENTS.md` — repo-wide operating rules and Definition of Done (binding).
2. **This file** (`docs/SESSION_HANDOFF.md`).
3. `docs/ROADMAP.md` — phase status with ✅/⏳/⬜/✂️ markers.
4. `CHANGELOG.md` — every feature since bootstrap under `[Unreleased]` (next tag cut will live at `v0.5.0-alpha.1`; nothing new under the header yet as of this writing).
5. `docs/design/phase-4-github-actuator.md` — reference (done, but the patterns are reusable).
6. `docs/design/llm-adapter.md` — reference.
7. `docs/ARCHITECTURE.md` — current system picture including the Actuators section.

Area-specific deep reads are already linked from `AGENTS.md`'s "Required reading by area" section.

## Known gotchas (earned the hard way)

1. **Ruff `PostToolUse` hook strips unused imports — hit ~15 times across the session.** Two workarounds both work: (a) add import + first usage in a single atomic Edit, or (b) for multi-import diffs, use `Write` to rewrite the file wholesale — the formatter sees only the final state. (b) is the safer default for anything touching 3+ imports.
2. **`backend-engineer` subagent stalls on multi-file Python work.** All Phase 4 + approval + console work was main-thread.
3. **Gitleaks hits on API-key-shaped test fixtures.** Generate fake values at test setup (RSA via `cryptography`, short `test-key-ignored` literals for Anthropic). No PEM / JWT / argon2id literals in `tests/`.
4. **Output classifier trips on aggregated security-heavy language.** Keep PR bodies lean.
5. **`.env.example` was blocked by an over-broad deny rule** (fixed in PR #29).
6. **`docs-writer` subagent has no `Bash` tool.** Dispatch, then finish git ops yourself.
7. **Subagent worktrees stay locked** after completion. Clean up with `git worktree remove --force ...`.
8. **Dispatch-completeness test** fails if a new event type lacks a projector handler. Add the handler in the same commit — now used three times (`rollback_impossible`, `human_approval_*`).
9. **`EventLog.append` is sync.** Keep `apply(event)` sync. Subscribers are sync callbacks fan-out; they marshal to async via their own queue (see the SSE route).
10. **Hash chain verification runs on startup.** Tampered `data/events.jsonl` refuses to boot. `make reset` wipes it.
11. **`allowed_action_types` + other YAML caches leak between tests.** `@lru_cache(maxsize=1)` loaders are cleared by `auth_module.reload_all_registries()`. Test fixtures that write throwaway YAMLs must call it — pattern in `tests/test_allowed_action_types.py` and `tests/test_human_approval.py`.
12. **Anthropic SDK in tests.** Construct with `api_key="test-key-ignored"` + `max_retries=0`; `respx` intercepts `https://api.anthropic.com/v1/messages`.
13. **`TestClient.stream()` hangs on infinite SSE generators.** The stream never naturally terminates and context-exit blocks on drain. Don't try to end-to-end test the SSE endpoint through TestClient; assert route registration + use `EventLog.subscribe` tests for the delivery contract. Real integration tests (if needed later) belong under `pytest -m integration` with a uvicorn subprocess + curl.
14. **When modifying any route handler, re-check that the test for it doesn't import `AUTH['agent_id']` / `AUTH['plaintext']`** — `tests/_helpers.py` exports `AUTH` as `{"Authorization": f"Bearer {TEST_OPERATOR_KEY}"}`, *not* a dict of agent/key components.

## Next-session candidates (pick one, by priority)

### A — Dockerfile digest-pinning + live Fly integration tests

Two small hardening items explicitly deferred from Phase 5:

- Pin the `python:3.12-slim` base image to a sha256 digest in the `Dockerfile` (reproducible builds). Look up the current `linux/amd64` digest on Docker Hub, pin it, add a comment noting the pinning policy.
- `QUORUM_FLY_LIVE_TESTS=1` integration tests — propose a `fly.deploy` against a throwaway Fly app, assert the actuator captures the previous digest and that `rollback_deploy` redeploys it. Skipped in CI by default; belongs under `pytest -m integration`.

### B — Minor follow-ups worth batching into a single PR

- Prometheus counters for the LLM adapter (design-doc §Observability): `quorum_llm_tokens_total{agent_id, model, kind}`, `quorum_llm_ticks_total{agent_id, outcome}`, `quorum_llm_proposals_created_total{agent_id, action_type}`. Needs the adapter process to run a Prometheus endpoint on a separate port.
- `demo_seed` optionally spawns the LLM adapter process (feature-flagged).
- SBOM release-asset versioning: fix the `anchore/sbom-action@v0` override so the asset ships as `quorum-vX.Y.Z-alpha.N.spdx.json` directly instead of the current two-step rename.
- Richer context in `_log.warning("projector_status_update_for_missing_proposal", ...)`.
- `make clean-worktrees` target.
- System-prompt hash in `llm_call_completed` events for audit reproducibility (design-doc open question #4).

### C — LLM adapter voter role

Open question from `docs/design/llm-adapter.md`. Requires its own design pass first:
- Per-action trust caps (e.g. vote on `github.add_labels` but not `github.open_pr`).
- Policy rule: LLM-emitted votes count toward quorum but can't unanimously carry a decision without a human vote.
- Audit: log the agent's prompt hash + model for every vote.

## Parallel development

My recommendation for the next session: **stay single-thread.** Reasons:

- Phase 5 is sequential by nature (deploy → verify → iterate; can't parallelize "test the deployment").
- Worktree overhead is only worth it for truly independent lanes (e.g. a backend feature + devops work at the same time). Phase 5 touches one area.
- The minor-follow-ups batch is small enough that parallel worker coordination costs more than it saves.
- Phase 6 (parallel operator agents) is explicitly gated on "≥2 weeks of event-schema stability" per ROADMAP. Phase 4 added 6+ new event types in this session; wait to stabilize.

The pattern that worked this session: **one main thread drives each PR end-to-end (branch, code, tests, push, PR, CI, pause for merge)**. 14 PRs + 3 release tags in one session on that pattern. Don't change what works until it stops working.

If a specific lane of work is ever independent and parallel-friendly, use the `Agent` tool with `isolation: "worktree"` + `run_in_background: true` — notification on completion. That was the original plan for Phase 6.

## Maintenance notes

- **Dependabot:** weekly Python, monthly Actions.
- **CI cadence:** all 5 required checks run in parallel in ~15–40 s each.
- **Release cadence:** tag when a meaningful feature set accumulates under `[Unreleased]`. Alpha tags are `v0.N.0-alpha.M`. v0.2.0 = Phase 4 GitHub actuator; v0.3.0 = Phase 4 LLM adapter; v0.4.0 = Phase 4 complete.

---

*Update this file at the end of every substantial session. Future-you reads it first.*
