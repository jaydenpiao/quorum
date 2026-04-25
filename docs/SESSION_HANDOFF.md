# Session handoff

This document is the canonical "where we left off" note for AI coding agents
picking up Quorum across sessions. Read it before anything except `AGENTS.md`.

Updated after every substantial session; treat entries below as the
authoritative state of the project.

---

## Current state (as of the handoff)

- **Last tagged release:** [`v0.5.0-alpha.1`](https://github.com/jaydenpiao/quorum/releases/tag/v0.5.0-alpha.1) — Phase 5 complete.
  SBOM attached as `quorum-v0.5.0-alpha.1.spdx.json`. Post-tag tidy:
  PR #58 (release workflow now auto-creates the GitHub release), PR #59
  (`make clean-worktrees`), and runtime hardening that pins the Docker
  base image / `uv` / `flyctl` so `fly.deploy` can run inside the
  production container. Live flyctl smoke uncovered that pinned
  `flyctl` v0.4.39 has no `fly releases --limit` flag; the Fly client
  now calls `fly releases --app <app> --json` and slices locally.
- **Test suite:** 364 passing + 12 integration-gated (excluded from CI
  by default; opt-in with `pytest -m integration` against a live
  Postgres or Fly.io, with additional env gates for destructive tests).
- **Coverage:** 84% (gate floor: 60%).
- **Type check:** `mypy --strict` clean across 47 source files.
- **Required CI checks on `main`:** `lint + format + test`, `gitleaks`, `pip-audit`, `docker build`, `mypy`. All 5 pass on every PR in the series.
- **Branch protection:** required PR, linear history, force-push disabled, conversation resolution required.
- **Merged PR count:** 66. Phase 5 added #50 design doc, #54 fly.toml + /readiness (replaced auto-closed #51), #52 fly.deploy actuator, #53 mid-phase handoff, #55 deploy-llm-agent, #56 image-push CI, #57 CHANGELOG + v0.5.0-alpha.1 handoff, #58 release-workflow fix, #59 `make clean-worktrees`, #61 runtime `flyctl` hardening, #62 image-push staging/prod follow-up, #63 pinned-flyctl release-list compatibility, #64 staging bootstrap handoff/docs, #65 opt-in live Fly deploy/rollback integration coverage, and #66 same-app Fly deploy guard.
- **Fly operational state:** `FLY_API_TOKEN` is configured as a GitHub
  Actions repo secret; `quorum-staging` and `quorum-prod` exist with
  app-scoped 1 GiB `iad` volumes named `quorum_data` (staging:
  `vol_4qly1wq329gwx56r`, prod: `vol_v8emwyn2gj70k11v`). The initial
  app-specific volumes were unattached and destroyed to avoid drift
  from `fly.toml`.
- **Staging deployment state:** `quorum-staging` is deployed from the
  pushed main image
  `registry.fly.io/quorum-staging@sha256:96ea324970bd369e86422e6d92764d35290e636cb9a2c7b0fe0cf2f3c415f677`;
  Fly release v7 currently reports image ref
  `registry.fly.io/quorum-staging@sha256:6bcea0b7426c60fe21c2000d837f08ef195aa48345d34c7fda603df308da74e0`.
  Machine `e2862467be9d78` is started in `iad` with 2/2 checks
  passing. `/readiness`, `/api/v1/health`, `/metrics`, and `/console`
  returned HTTP 200. `QUORUM_API_KEYS` (operator, code-agent,
  deploy-agent), `FLY_API_TOKEN`, and `QUORUM_ALLOW_DEMO=1` are
  deployed only on staging; `DATABASE_URL` and
  `QUORUM_GITHUB_APP_PRIVATE_KEY` are still unset, so the Postgres
  projection and GitHub actuator are disabled there for now.
- **Staging persistence evidence:** an authenticated
  `POST /api/v1/intents` created `intent_f40d2794ee55`; before and
  after `fly machine restart e2862467be9d78 --app quorum-staging`,
  `GET /api/v1/events/verify` returned `event_count=1` and
  `last_hash=3b8f54fef545d63b23069ed1daa5877ad9fbb951a78767d20682155c6dd8c7ff`.
  This verifies the Fly Volume is mounted at `/app/data`.
- **Prod deployment state:** `quorum-prod` exists with the correct
  `quorum_data` volume but no machine/release yet. `QUORUM_ALLOW_DEMO`
  is unset in prod.
- **Live Fly deploy/rollback evidence:** an operator-run live actuator
  smoke deployed staging to pushed digest
  `sha256:758395f657f1abcdcbd18bffb0cba1261184cc2d8af7320bcb94602e5223092e`,
  captured previous release digest
  `sha256:6bcea0b7426c60fe21c2000d837f08ef195aa48345d34c7fda603df308da74e0`,
  then `rollback_deploy` returned staging to that previous digest.
  `/readiness`, `/api/v1/health`, and `/api/v1/events/verify` returned
  HTTP 200 after rollback.
- **Same-app deploy invariant:** `fly.deploy` now refuses to run when
  `FLY_APP_NAME` matches the proposal payload's target app. A
  single-machine Quorum app must deploy a peer app or run from an
  external runner; it must not replace the process that is responsible
  for appending terminal execution and health-check events.
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
  - **Post-tag hardening** — Dockerfile runtime now carries pinned,
    checksummed `flyctl` as `/usr/local/bin/fly`; Python base image and
    `uv` bootstrap are pinned for reproducible builds.
  - **Post-tag image supply** — image-push CI now publishes the same
    commit image to both `quorum-staging` and `quorum-prod` Fly
    Registry namespaces and records both digests in the job summary.
  - **Post-tag execution safety** — same-app `fly.deploy` is blocked
    when Fly exposes `FLY_APP_NAME`, preserving terminal event writes
    for single-machine apps.
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
4. Optional: set `FLY_API_TOKEN` as a repo secret; every merge to
   `main` pushes tagged images to `registry.fly.io/quorum-staging` and
   `registry.fly.io/quorum-prod`.
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
4. `CHANGELOG.md` — every feature since bootstrap under `[Unreleased]`
   (post-v0.5 entries currently include release workflow, worktree
   cleanup, and runtime deployability hardening).
5. `docs/design/phase-4-github-actuator.md` — reference (done, but the patterns are reusable).
6. `docs/design/llm-adapter.md` — reference.
7. `docs/ARCHITECTURE.md` — current system picture including the Actuators section.

Area-specific deep reads are already linked from `AGENTS.md`'s "Required reading by area" section.

## Known gotchas (earned the hard way)

Gotchas marked **[Claude-only]** are specific to the Claude Code
harness under `.claude/`. Codex and other agents can ignore them.

1. **[Repo-wide]** Gitleaks hits on API-key-shaped test fixtures.
   Generate fake values at test setup (RSA via `cryptography`, short
   `test-key-ignored` literals for Anthropic). No PEM / JWT / argon2id
   literals in `tests/`.
2. **[Repo-wide]** Dispatch-completeness test fails if a new event
   type lacks a projector handler. Add the handler in the same commit
   — already hit for `rollback_impossible` and the
   `human_approval_*` family.
3. **[Repo-wide]** `EventLog.append` is sync. Keep `apply(event)` sync.
   Subscribers are sync callbacks fan-out; they marshal to async via
   their own queue (see the SSE route).
4. **[Repo-wide]** Hash chain verification runs on startup. Tampered
   or truncated `data/events.jsonl` refuses to boot — uvicorn raises
   at import. `make reset` wipes it.
5. **[Repo-wide]** `allowed_action_types` + other YAML caches leak
   between tests. `@lru_cache(maxsize=1)` loaders are cleared by
   `auth_module.reload_all_registries()`. Test fixtures that write
   throwaway YAMLs must call it — pattern in
   `tests/test_allowed_action_types.py` and
   `tests/test_human_approval.py`.
6. **[Repo-wide]** Anthropic SDK in tests: construct with
   `api_key="test-key-ignored"` + `max_retries=0`; `respx` intercepts
   `https://api.anthropic.com/v1/messages`.
7. **[Repo-wide]** `TestClient.stream()` hangs on infinite SSE
   generators. The stream never naturally terminates and context-exit
   blocks on drain. Don't try to end-to-end test the SSE endpoint
   through TestClient; assert route registration + use
   `EventLog.subscribe` tests for the delivery contract. Real
   integration tests (if needed later) belong under
   `pytest -m integration` with a uvicorn subprocess + curl.
8. **[Repo-wide]** When modifying any route handler, re-check that the
   test for it doesn't import `AUTH['agent_id']` / `AUTH['plaintext']`
   — `tests/_helpers.py` exports `AUTH` as
   `{"Authorization": f"Bearer {TEST_OPERATOR_KEY}"}`, *not* a dict
   of agent/key components.
9. **[Repo-wide]** GitHub auto-closes stacked PRs when their base
   branch is deleted on squash-merge. You cannot reopen once the base
   is gone. Either merge *without* `--delete-branch` and clean up
   afterward, or merge main into the stacked branch (regular
   fast-forward push, no force needed) + `gh pr edit <N> --base main`
   before the parent merges.
10. **[Repo-wide]** The repo's pre-tool-use hook blocks
    `git push --force*` (including `--force-with-lease`). For stacked
    PRs, prefer merging `main` into the feature branch as a regular
    push over rebase + force-push.
11. **[Repo-wide]** The repo's pre-tool-use hook blocks force-removing
    git worktrees outside the project tree. Run `make clean-worktrees`
    (added in PR #59) only when no subagents are active.
12. **[Claude-only]** Ruff `PostToolUse` hook strips unused imports
    between Edits. Workarounds: (a) add import + first usage in a
    single atomic Edit, or (b) for multi-import diffs, use `Write` to
    rewrite the file wholesale — the formatter sees only the final
    state.
13. **[Claude-only]** `backend-engineer` subagent stalls on multi-file
    Python work. Stay main-thread for complex Python changes.
14. **[Claude-only]** Output classifier trips on aggregated
    security-heavy language. Keep PR bodies lean.
15. **[Claude-only]** `docs-writer` subagent has no `Bash` tool.
    Dispatch, then finish git ops yourself.
16. **[Claude-only]** Subagent worktrees stay locked after completion.
    Use `make clean-worktrees` (PR #59) when no agents are active.
17. **[Claude-only]** `.env.example` was blocked by an over-broad deny
    rule in an older `.claude/settings.json`; fixed in PR #29.
18. **[Repo-wide]** Pinned `flyctl` v0.4.39 supports
    `fly releases --app <app> --json`, but not `--limit`. Keep release
    limiting in Quorum code/tests, not in the subprocess argv. Live
    smoke against `quorum-staging` returns `[]` before the first deploy.
19. **[Repo-wide]** `fly.toml` mounts `source = "quorum_data"`.
    Volume names are app-scoped on Fly, so both staging and prod should
    create a volume named exactly `quorum_data`. App-specific names like
    `quorum_staging_data` do not satisfy the shared config.
20. **[Repo-wide]** Same-app `fly.deploy` is blocked when
    `FLY_APP_NAME` equals the proposal payload's `app`. The safe
    near-term dog-food shape is a peer controller app or external
    runner deploying the target app. Do not remove this guard unless a
    separate executor lifecycle has been designed and live-proven.

## Next-session candidates (pick one, by priority)

### A — Prove the peer-controller dog-food deploy path

Same-app self-deploy is blocked; the next operator-value smoke is a
real Quorum API-gated deploy from `quorum-staging` into `quorum-prod`:

- Bootstrap `quorum-prod` with `QUORUM_API_KEYS` and `FLY_API_TOKEN`
  only; keep `QUORUM_ALLOW_DEMO` unset.
- Use two known prod registry digests from image-push.
- From `quorum-staging`, create an intent + `fly.deploy` proposal
  targeting `quorum-prod`, cast two votes, grant human approval, and
  execute.
- Verify `execution_started`, `health_check_completed`, and
  `execution_succeeded` are present in staging's event log, and
  `/readiness` + `/api/v1/health` return 200 on prod.

### B — Minor follow-ups worth batching into a single PR

- Configure real staging `DATABASE_URL` (Neon branch) and
  `QUORUM_GITHUB_APP_PRIVATE_KEY`; then re-verify `/readiness` with
  Postgres enabled and the GitHub actuator booting.
- Bootstrap `quorum-prod` only after staging has the DB/GitHub secrets
  and live deploy/rollback evidence. Keep `QUORUM_ALLOW_DEMO` unset.
- Prometheus counters for the LLM adapter (design-doc §Observability): `quorum_llm_tokens_total{agent_id, model, kind}`, `quorum_llm_ticks_total{agent_id, outcome}`, `quorum_llm_proposals_created_total{agent_id, action_type}`. Needs the adapter process to run a Prometheus endpoint on a separate port.
- `demo_seed` optionally spawns the LLM adapter process (feature-flagged).
- Richer context in `_log.warning("projector_status_update_for_missing_proposal", ...)`.
- System-prompt hash in `llm_call_completed` events for audit reproducibility (design-doc open question #4).

### C — LLM adapter voter role

Open question from `docs/design/llm-adapter.md`. Requires its own design pass first:
- Per-action trust caps (e.g. vote on `github.add_labels` but not `github.open_pr`).
- Policy rule: LLM-emitted votes count toward quorum but can't unanimously carry a decision without a human vote.
- Audit: log the agent's prompt hash + model for every vote.

## Cross-tool onboarding

This repo follows the [AGENTS.md](https://agents.md/) convention —
Codex, Claude Code, Cursor, Windsurf, and any other tool that honors
it reads `AGENTS.md` automatically.

- **Codex**: drop into the repo and let it read `AGENTS.md`. No extra
  config. The first Codex session prompt should point at the reading
  order in `INIT.md`.
- **Claude Code**: reads `CLAUDE.md` (pointer to `AGENTS.md`). Extra
  batteries (`.claude/settings.json`, hooks, subagents, skills, slash
  commands) live under `.claude/`. Gotchas #12–#17 above apply.
- **Other agents**: read `AGENTS.md`; ignore tool-specific
  directories.

The repo's pre-tool-use hooks apply to all tools equally:
- `git push --force*` is blocked.
- Force-removing worktrees outside the project tree is blocked.
- The event log path (`data/events.jsonl`) is append-only.

## Parallel development

**Stay single-thread** until Phase 6's gate is met (≥2 weeks of
event-schema stability per ROADMAP). The pattern that works:

- One main thread drives each PR end-to-end (branch → code → tests
  → push → PR → CI → pause for merge).
- Stacked PRs where one depends on another; merge `main` into the
  stacked branch after the parent merges (regular fast-forward push).
- No force-pushes. No rebasing a published branch.

When Phase 6 opens, follow `docs/PARALLEL_DEVELOPMENT.md`.

## Maintenance notes

- **Dependabot:** weekly Python, monthly Actions.
- **CI cadence:** all 5 required checks run in parallel in ~15–40 s each.
- **Release cadence:** tag when a meaningful feature set accumulates under `[Unreleased]`. Alpha tags are `v0.N.0-alpha.M`. v0.2.0 = Phase 4 GitHub actuator; v0.3.0 = Phase 4 LLM adapter; v0.4.0 = Phase 4 complete.

---

*Update this file at the end of every substantial session. Future-you reads it first.*
