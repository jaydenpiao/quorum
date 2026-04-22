# Session handoff

This document is the canonical "where we left off" note for AI coding agents
picking up Quorum across sessions. Read it before anything except `AGENTS.md`.

Updated after every substantial session; treat entries below as the
authoritative state of the project.

---

## Current state (as of the handoff)

- **Last tagged release:** [`v0.4.0-alpha.1`](https://github.com/jaydenpiao/quorum/releases/tag/v0.4.0-alpha.1) — Phase 4 complete. SBOM attached as `quorum-v0.4.0-alpha.1.spdx.json`. **Phase 5 in flight**, three stacked PRs awaiting merge (see below).
- **Test suite:** 349 passing + 11 integration-gated (excluded from CI by default; opt-in with `pytest -m integration` against a live Postgres).
- **Coverage:** 84% (gate floor: 60%).
- **Type check:** `mypy --strict` clean across 47 source files.
- **Required CI checks on `main`:** `lint + format + test`, `gitleaks`, `pip-audit`, `docker build`, `mypy`. All 5 pass on every PR in the series.
- **Branch protection:** required PR, linear history, force-push disabled, conversation resolution required.
- **Merged PR count:** 49. **Open / in-flight:** 3 (stacked — PRs #50 → #51 → #52).
- **Event types dispatched:** 20 — `intent_created`, `finding_created`, `proposal_created`, `policy_evaluated`, `proposal_voted`, `proposal_approved`, `proposal_blocked`, `execution_started`, `execution_succeeded`, `execution_failed`, `health_check_completed`, `rollback_started`, `rollback_completed`, `rollback_impossible`, `human_approval_requested`, `human_approval_granted`, `human_approval_denied`. (No Phase 5 event types added yet — `fly.deploy` reuses the existing `proposal_created` / `execution_*` / `rollback_*` chain.)

## Phase status

- **✅ Phase 0** — Claude Code harness.
- **✅ Phase 1** — OSS hygiene.
- **✅ Phase 2** — core security (typed health checks, hash chain, bearer auth).
- **✅ Phase 2.5** — server-side actor binding, argon2id keys.
- **✅ Phase 3** — production foundation (Dockerfile, pytest-cov gate, structlog, Prometheus, mypy-strict, SBOM, OTel).
- **✅ Phase 3 capstone** — Postgres projection.
- **✅ Phase 4** — GitHub App actuator (4 actions + rollback + `rollback_impossible` event + `github_check_run` health check); LLM adapter (telemetry-llm-agent with `create_finding` + `create_proposal` + `allowed_action_types` gate); **human approval entity + 3 events**; **interactive console with SSE live-tail + forms**. All four Phase 4 roadmap items shipped. Tagged `v0.4.0-alpha.1`.
- **⏳ Phase 5** — Fly.io deployment. **Three stacked PRs awaiting merge:**
  - **PR #50** — `docs/design/fly-deployment.md`. Design doc. CI green.
  - **PR #51** — `fly.toml` + `GET /readiness` + readiness tests. CI green. Stacked on #50.
  - **PR #52** — `fly.deploy` actuator (FlyDeploySpec, flyctl-subprocess FlyClient, deploy/rollback actions) + executor dispatch refactor for prefix-based routing + policy rule (2 votes + requires_human) + design-doc amendment on open question #2 (flyctl > Machines API). 27 new tests. CI green. Stacked on #51.
- **⬜ Phase 6** — parallel operator-agent worktrees.

All known doc-vs-code drift is closed. No known outstanding tech debt.

## What landed since v0.3.0-alpha.1

Three PRs close the last two Phase 4 roadmap items:

- **PR #46** — README LLM quickstart + ROADMAP/HANDOFF refresh for v0.3.
- **PR #47** — Human approval entity. Three new event types (`human_approval_requested` / `_granted` / `_denied`), new `POST /api/v1/approvals/{proposal_id}` route, execute-time gate, terminal `ProposalStatus.approval_denied`, Alembic 0004 + projector handlers + dispatch-completeness update.
- **PR #48** — SSE event stream + interactive console forms. `EventLog.subscribe()` pub/sub; `GET /api/v1/events/stream`; bearer-token + `create_intent` + cast-vote + grant/deny-approval forms; EventSource live-tail.

## What is in flight (Phase 5, three stacked PRs)

Opened in order; each passes all 5 required CI checks; each awaits operator merge.

- **PR #50** — `docs/design/fly-deployment.md`. Single file. Covers app topology, Fly Volume sizing, Neon-vs-Fly-Postgres, secrets, readiness wiring, dog-food deploy flow, operator pre-reqs, open questions.
- **PR #51** — `fly.toml` at repo root (primary_region=iad, volume mount at /app/data, http_checks on /api/v1/health + /readiness) + new `GET /readiness` endpoint (200 when chain verified — implicit via module import — and `SELECT 1` on DATABASE_URL succeeds; 503 otherwise; detail never leaks exception text) + 4 tests. No new Python deps. Dockerfile digest-pin deferred to a later tiny PR.
- **PR #52** — `fly.deploy` actuator. `apps/api/app/services/actuators/fly/` with typed FlyDeploySpec (Literal app, sha256-only image_digest, tags rejected at pydantic boundary), FlyClient (flyctl subprocess wrapper with captured stdout/stderr and typed errors), deploy + rollback_deploy orchestration. Executor refactored from GitHub-coupled dispatch to prefix-based (`github.*` vs `fly.*` vs passthrough). New policy rule: `fly.deploy` requires 2 votes + explicit human approval (strictest we have). Design-doc amendment flips open question #2 from "Machines API" to "flyctl subprocess" — two-surface API (GraphQL + REST) doubled LOC vs subprocess's 170-line total. 27 new tests.

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

### A — Finish Phase 5 (deploy-agent + image-push CI)

After PRs #50 / #51 / #52 merge, two pieces remain before dog-food deploys work end-to-end:

- **Deploy-agent LLM role.** New `deploy-agent` with `allowed_action_types: ["fly.deploy"]` in `config/allowed_action_types.yaml`. Its system prompt watches for new images in `registry.fly.io/quorum-prod` (or a hook off the CI workflow below) and creates proposals with `action_type=fly.deploy` and the current commit's digest.
- **Image-push CI workflow.** `.github/workflows/image-push.yml` builds a Docker image on every merge to `main`, pushes to `registry.fly.io/quorum-prod` tagged with the commit SHA. Needs a Fly API token as a repo secret.
- **Integration tests.** Gated behind `QUORUM_FLY_LIVE_TESTS=1` — propose a fly.deploy against a throwaway Fly app, assert rollback redeploys the previous digest. Skipped in CI by default.

**Operator pre-reqs before the stacked PRs can be deployed (not before they merge):**
1. Fly CLI installed (`curl -L https://fly.io/install.sh | sh`).
2. `fly auth signup` / `fly auth login`.
3. `fly apps create quorum-staging` and `fly apps create quorum-prod`.
4. `fly volumes create quorum_data --size 1 --region iad --app quorum-{staging,prod}`.
5. A Neon Postgres project (free tier) with a branch for staging.
6. `fly secrets set QUORUM_API_KEYS=... QUORUM_GITHUB_APP_PRIVATE_KEY=... DATABASE_URL=... --app quorum-{staging,prod}`.

After that: `fly deploy --app quorum-staging` should produce a running instance that passes both http_checks.

### B — Version bump + SBOM (v0.5.0-alpha.1)

Once all three Phase 5 PRs merge, cut `v0.5.0-alpha.1`:

- Update the `[Unreleased]` section of `CHANGELOG.md` with the three Phase 5 PRs.
- `git tag -s v0.5.0-alpha.1 -m "Phase 5 — Fly.io deployment (deploy-agent pending)"`.
- `git push origin v0.5.0-alpha.1` triggers the release workflow, which attaches an SPDX SBOM.

### C — Minor follow-ups worth batching into a single PR

- Prometheus counters for the LLM adapter (design-doc §Observability): `quorum_llm_tokens_total{agent_id, model, kind}`, `quorum_llm_ticks_total{agent_id, outcome}`, `quorum_llm_proposals_created_total{agent_id, action_type}`. Needs the adapter process to run a Prometheus endpoint on a separate port.
- `demo_seed` optionally spawns the LLM adapter process (feature-flagged).
- SBOM release-asset versioning: fix the `anchore/sbom-action@v0` override so the asset ships as `quorum-vX.Y.Z-alpha.N.spdx.json` directly instead of the current two-step rename.
- Richer context in `_log.warning("projector_status_update_for_missing_proposal", ...)`.
- `make clean-worktrees` target.
- System-prompt hash in `llm_call_completed` events for audit reproducibility (design-doc open question #4).

### D — LLM adapter voter role

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
