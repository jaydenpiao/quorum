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
- **Test suite:** 392 passing + 13 integration-gated (excluded from CI
  by default; opt-in with `pytest -m integration` against a live
  Postgres, Fly.io, or GitHub, with additional env gates for destructive
  tests).
- **Coverage:** 81% (gate floor: 60%).
- **Type check:** `mypy --strict` clean across 49 source files.
- **Required CI checks on `main`:** `lint + format + test`, `gitleaks`, `pip-audit`, `docker build`, `mypy`. All 5 pass on every PR in the series.
- **pip-audit note:** CI temporarily ignores `CVE-2026-3219` because
  it affects the latest published PyPI `pip` (`26.0.1`) and pip-audit
  reports no fixed version. Keep `pip-audit --strict`; remove the
  single ignore in `.github/workflows/ci.yml` once pip publishes a fix.
- **Branch protection:** required PR, linear history, force-push disabled, conversation resolution required.
- **Merged PR count:** 81. Phase 5 added #50 design doc, #54 fly.toml + /readiness (replaced auto-closed #51), #52 fly.deploy actuator, #53 mid-phase handoff, #55 deploy-llm-agent, #56 image-push CI, #57 CHANGELOG + v0.5.0-alpha.1 handoff, #58 release-workflow fix, #59 `make clean-worktrees`, #61 runtime `flyctl` hardening, #62 image-push staging/prod follow-up, #63 pinned-flyctl release-list compatibility, #64 staging bootstrap handoff/docs, #65 opt-in live Fly deploy/rollback integration coverage, #66 same-app Fly deploy guard, #67 peer-controller deploy evidence, #68 Fly release digest wording, #69 Neon URL normalization, #70 Neon Fly bootstrap evidence, #71 GitHub App bootstrap helper, #72 live GitHub actuator Fly proof, #73 image-push evidence events, #74 image-push evidence proof handoff, #75 LLM proposal dispatch envelope fix, #76 deploy-agent health-check prompt contract, #77 health-checked deploy-agent proof handoff, #78 API/executor health-check gate for `fly.deploy`, #79 LLM prompt hash audit metadata, #80 opt-in live GitHub actuator rollback coverage, and #81 LLM adapter Prometheus metrics.
- **Fly operational state:** `FLY_API_TOKEN` is configured as a GitHub
  Actions repo secret; `quorum-staging` and `quorum-prod` exist with
  app-scoped 1 GiB `iad` volumes named `quorum_data` (staging:
  `vol_4qly1wq329gwx56r`, prod: `vol_v8emwyn2gj70k11v`). The initial
  app-specific volumes were unattached and destroyed to avoid drift
  from `fly.toml`. Image-push CI now has an optional best-effort
  `POST /api/v1/image-pushes` notifier controlled by repo secrets
  `QUORUM_IMAGE_PUSH_API_URL` and `QUORUM_IMAGE_PUSH_API_KEY`; those
  secrets point at `https://quorum-staging.fly.dev` and the staging
  `deploy-agent` API key.
- **Neon operational state:** project `square-tree-95302760` in the
  `Jayden` org has prod branch `main` (`br-wild-dream-ajhrmye0`) and
  staging branch `quorum-staging` (`br-still-dust-aj7z7vra`), database
  `neondb`, role `neondb_owner`. Both branches are migrated to Alembic
  `0004 (head)`. Local operator Keychain service names:
  `quorum-neon-prod-database-url` and
  `quorum-neon-staging-database-url`.
- **GitHub actuator bootstrap state:** GitHub App `quorum-actuator`
  exists with non-secret App ID `3496381`; it is installed on fixture
  repo `jaydenpiao/quorum-actuator-fixtures` with installation ID
  `126887427`. The fixture repo has smoke issue #1 and label
  `quorum-smoke`. The generated PEM is stored base64-encoded in local
  Keychain service `quorum-github-app-private-key-b64`.
  `config/github.yaml` points at the fixture installation.
  `QUORUM_GITHUB_APP_PRIVATE_KEY_B64` is deployed on both
  `quorum-staging` and `quorum-prod`. Both Fly apps have executed
  `github.comment_issue` against fixture issue #1 through Quorum's
  proposal/vote/execute path; keep the App installed only on the
  fixture repo until a separate PR moves the actuator to a production
  target. Opt-in live pytest coverage also proves the direct actuator
  helper creates a fixture comment, rolls it back, and observes the
  deleted comment as 404.
- **Staging deployment state:** `quorum-staging` is running Fly
  release v14, which reports platform image ref
  `registry.fly.io/quorum-staging@sha256:4cecb6bebf72e0c0fa75fc347854c1196947b7b07de25ee63c475d3265ee8828`.
  That release was manually deployed from the PR #73 `main`
  image-push manifest-list digest
  `sha256:8656839129464b349f971b76c6de5caad3a5b1687925d586192b49283fc8989b`
  to bootstrap the new evidence route. A follow-up image-push rerun
  for the same commit emitted manifest-list digest
  `sha256:1d4f28ffaf52e71d7c82a6e154c68267edcb2ea4bd01c82c9a046df72725ae4a`
  and the same platform image ref. Machine `e2862467be9d78` is the
  single staging machine in `iad`; `/readiness`, `/api/v1/health`,
  `/metrics`, and `/console` returned HTTP 200 after wake.
  `QUORUM_API_KEYS` (operator, code-agent, deploy-agent,
  deploy-llm-agent), `FLY_API_TOKEN`, `DATABASE_URL`, and
  `QUORUM_ALLOW_DEMO=1` are deployed only on staging;
  `QUORUM_GITHUB_APP_PRIVATE_KEY_B64` is deployed on staging. Local
  operator Keychain service names for the LLM proof are
  `quorum-staging-deploy-llm-agent-api-key` and
  `quorum-anthropic-api-key`.
- **Staging persistence evidence:** an authenticated
  `POST /api/v1/intents` created `intent_f40d2794ee55`; before and
  after `fly machine restart e2862467be9d78 --app quorum-staging`,
  `GET /api/v1/events/verify` returned `event_count=1` and
  `last_hash=3b8f54fef545d63b23069ed1daa5877ad9fbb951a78767d20682155c6dd8c7ff`.
  This verifies the Fly Volume is mounted at `/app/data`.
- **Staging Postgres projection evidence:** after enabling
  `DATABASE_URL`, `quorum-staging` reconciled 13 existing events from
  JSONL into Neon with zero errors, then accepted a live smoke intent
  `intent_ca2cf96dfc15`. Current staging event verification reports
  `event_count=75` and
  `last_hash=70d4d19f84050acd8a547f93f27e6407bd010b9fd19f5ccf9d26802389e9fa1c`.
  Reduced state counts are `intents=10`, `proposals=8`, `votes=10`,
  `executions=5`, and `image_pushes=4`.
- **Image-push evidence proof:** workflow run
  `24925601409` posted `image_push_completed` into staging as
  `evt_fd0e051dca4b` / `imgpush_2e6a1c26fdd3`, reported by
  `deploy-agent`, for commit
  `4189cebdf556b116d4fb870e4442f7f6a82da503`. The payload carries
  `registry.fly.io/quorum-staging@sha256:1d4f28ffaf52e71d7c82a6e154c68267edcb2ea4bd01c82c9a046df72725ae4a`
  and
  `registry.fly.io/quorum-prod@sha256:1d4f28ffaf52e71d7c82a6e154c68267edcb2ea4bd01c82c9a046df72725ae4a`.
  Staging `/api/v1/events/verify` advanced from `event_count=47` to
  `event_count=48` with
  `last_hash=8efdf62df7635b0cacd20856c0c171fbfff9c4a64565e1829f41b4fe6988301b`
  immediately after the notifier.
- **Live `deploy-llm-agent` proposal proof:** workflow run
  `24925781387` later posted `image_push_completed` into staging as
  `evt_74ef7a99cb5d` / `imgpush_eadad713af0b` for commit
  `52c3802fbd18e38f0542f5176b468f7bf6950b72`, carrying staging/prod
  digest
  `sha256:3f3a144ec2145b6bc8be2b8cd7a4ca3e3c3742231c48e85832b5e95f60d76971`.
  The operator created intent `intent_8b92f439d2c0`, then ran the real
  Anthropic-backed adapter once as `deploy-llm-agent` against
  `https://quorum-staging.fly.dev`. The call completed against
  `claude-opus-4-7` and submitted `proposal_b07ba69ae657`
  (`fly.deploy` target `quorum-staging`) plus human-approval request
  `approval_req_4fc1b863ca1f`. No execution was claimed or attempted;
  same-app staging deploy remains blocked by invariant. The adapter
  initially logged the tool dispatch as `ok=False` because it expected
  a top-level `id`; PR #75 fixes the dispatcher to recognize the
  current `POST /api/v1/proposals` response envelope. After PR #75
  merged, image-push run `24949609883` posted `evt_761753baf9b7`
  for commit `9bd15cfb1272c8a3cb8581009395010fca1a308f`; a follow-up
  local adapter tick saw intent `intent_5dafd2b01ad5`, logged
  `ok=True` / `tools_ok=1`, and created
  `proposal_524793d66925`. That proposal had strong evidence refs but
  an empty `health_checks` list, so PR #76 hardens the deploy-agent
  prompt to require target-specific `/readiness` and `/api/v1/health`
  checks on every `fly.deploy` proposal.
- **Health-checked `deploy-llm-agent` proposal proof:** after PR #76
  merged, image-push run `24949842912` posted `image_push_completed`
  into staging as `evt_112ad64b8cc1` / `imgpush_a2f29f5cacee` for
  commit `f33c2e5b17bdfb49f440df6867ae57c08c20033b`, carrying
  staging/prod digest
  `sha256:8f1ddd83795d1fcfd9bf4cd629d19e381f26907486c2cf689c20eeed5ac83a0d`.
  The operator created intent `intent_1c7609faa698`, then ran the
  real Anthropic-backed adapter once as `deploy-llm-agent`. The tick
  logged `llm_tool_dispatch_completed ok=True` and `tools_ok=1`, and
  created `proposal_7e096a4d63fe` for `fly.deploy` targeting
  `quorum-staging`. The proposal includes `staging-readiness`
  (`https://quorum-staging.fly.dev/readiness`) and
  `staging-api-health`
  (`https://quorum-staging.fly.dev/api/v1/health`) HTTP checks with
  expected status 200 and 10s timeouts. Policy evaluated it as
  `allowed=true`, `requires_human=true`, `votes_required=2`, and
  opened human approval request `approval_req_e534744bce80`. No
  execution was claimed or attempted; this same-app staging proposal
  should remain pending unless a separate external/peer executor plan
  is intentionally run.
- **Prod deployment state:** `quorum-prod` is running Fly release v7,
  which reports platform image ref
  `registry.fly.io/quorum-prod@sha256:4cecb6bebf72e0c0fa75fc347854c1196947b7b07de25ee63c475d3265ee8828`.
  That release was requested from image-push manifest-list digest
  `sha256:1d4f28ffaf52e71d7c82a6e154c68267edcb2ea4bd01c82c9a046df72725ae4a`
  through staging proposal `proposal_f7122b5cbc2a`, not a direct local
  `fly deploy`.
  Machine `e829625b579d78` is started in `iad` with 2/2 checks
  passing, mounted volume `vol_v8emwyn2gj70k11v`, and `autostop:
  false` restored after the deploy reset it to `true`. `/readiness`
  and `/api/v1/health` returned HTTP 200. `QUORUM_API_KEYS`,
  `FLY_API_TOKEN`, and `DATABASE_URL` are deployed;
  `QUORUM_GITHUB_APP_PRIVATE_KEY_B64` is deployed in prod;
  `QUORUM_ALLOW_DEMO` is unset in prod.
- **Prod Postgres projection evidence:** prod now has live actuator
  smoke events. Prod `/api/v1/events/verify` returns `event_count=20`
  and
  `last_hash=273e0dbfbbb9f2733370933405a47c6425c2f3b1668feba8435880d3db0197a2`.
  Neon-backed history endpoint counts: `intents=2`, `proposals=2`,
  `votes=4`, `executions=4`.
- **Live Fly deploy/rollback evidence:** an operator-run live actuator
  smoke deployed staging to pushed digest
  `sha256:758395f657f1abcdcbd18bffb0cba1261184cc2d8af7320bcb94602e5223092e`,
  captured previous release digest
  `sha256:6bcea0b7426c60fe21c2000d837f08ef195aa48345d34c7fda603df308da74e0`,
  then `rollback_deploy` returned staging to that previous digest.
  `/readiness`, `/api/v1/health`, and `/api/v1/events/verify` returned
  HTTP 200 after rollback.
- **Peer-controller dog-food evidence:** `quorum-staging` executed a
  real Quorum API-gated `fly.deploy` into `quorum-prod` with intent
  `intent_bead5a2f36fd` and proposal `proposal_a8803f47488e`.
  Policy allowed the action with `requires_human=true` and 2 votes
  required; `code-agent` and `operator` voted; the operator granted
  human approval. The execution deployed requested digest
  `sha256:70af699bb5bcf68f0173181eb80ece15dfe5df767d6166c9b97c212a22d46e67`,
  captured previous prod digest
  `sha256:07167f6706325481c902c5f79e95f9ca18389e9624abfa8e28bcab68961f4999`,
  verified `prod-readiness` and `prod-api-health` as HTTP 200, and
  appended this proposal chain in staging:
  `proposal_created`, `policy_evaluated`, `human_approval_requested`,
  two `proposal_voted`, `proposal_approved`,
  `human_approval_granted`, `execution_started`, two
  `health_check_completed`, `execution_succeeded`. Staging
  `/api/v1/events/verify` returned `event_count=13` and
  `last_hash=014293237212070b61472bb5577cd47317625067633d26331b50bcdfb574dbd4`.
  The latest peer-controller deploy repeated the same gated path with
  intent `intent_91a13c2a90e3` and proposal
  `proposal_7ea9efc0cc32`, deploying requested manifest-list digest
  `sha256:aa267ec52be093acd5b2e8a39c658d073f1927ceeeada5aef55c28fbe7f90f6e`
  into prod and capturing previous prod digest
  `sha256:36809cd455123b89a592a70dcf31cc91a27bb8eddb9b9ccd154830bfa0f9bcce`.
  Prod readiness and API health both passed as HTTP 200.
  The latest peer-controller deploy used the image-push evidence event
  from PR #73: intent `intent_9237553877de`, proposal
  `proposal_f7122b5cbc2a`, policy `allowed=true`,
  `requires_human=true`, `votes_required=2`, code-agent + operator
  approvals, human approval, and execution by `deploy-agent`. It
  deployed requested digest
  `sha256:1d4f28ffaf52e71d7c82a6e154c68267edcb2ea4bd01c82c9a046df72725ae4a`,
  captured previous prod digest
  `sha256:698e0ca0774a1c31c043a3c11dc698693822c22790509d7aca67b352f87952a0`,
  and recorded passing `prod-readiness` and `prod-api-health` checks.
- **Live GitHub actuator evidence:** the config-bearing image from
  PR #71 was deployed to staging, then prod was updated through
  staging's audited `fly.deploy` path. Staging proposal
  `proposal_3b0dfe573bb9` executed `github.comment_issue` against
  fixture issue #1 and created comment
  `https://github.com/jaydenpiao/quorum-actuator-fixtures/issues/1#issuecomment-4317876371`;
  the execution recorded one post-change HTTP health check as passed.
  Prod proposal `proposal_53414b49eb06` executed the same action with
  `environment=prod`; policy required two votes and human approval,
  the operator granted approval, the action created comment
  `https://github.com/jaydenpiao/quorum-actuator-fixtures/issues/1#issuecomment-4317901186`,
  and the post-change health check passed. There is also an earlier
  prod fixture comment from `proposal_1d5c2538f403` with
  `environment=staging`; keep `proposal_53414b49eb06` as the canonical
  protected-prod proof. `tests/test_github_live_integration.py` is now
  the skipped-by-default regression for the fixture comment path; run
  it with `QUORUM_GITHUB_LIVE_TESTS=1` and the Keychain-backed
  `QUORUM_GITHUB_APP_PRIVATE_KEY_B64` env when you need fresh live
  rollback evidence.
- **Same-app deploy invariant:** `fly.deploy` now refuses to run when
  `FLY_APP_NAME` matches the proposal payload's target app. A
  single-machine Quorum app must deploy a peer app or run from an
  external runner; it must not replace the process that is responsible
  for appending terminal execution and health-check events.
- **Event types dispatched:** 18 — `intent_created`, `finding_created`, `proposal_created`, `policy_evaluated`, `proposal_voted`, `proposal_approved`, `proposal_blocked`, `execution_started`, `execution_succeeded`, `execution_failed`, `health_check_completed`, `rollback_started`, `rollback_completed`, `rollback_impossible`, `human_approval_requested`, `human_approval_granted`, `human_approval_denied`, `image_push_completed`. `fly.deploy` reuses the existing `proposal_created` / `execution_*` / `rollback_*` chain; `image_push_completed` is evidence only and never executes a deploy.

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
  - **Post-tag image-push evidence** — image-push CI can optionally
    post a signed `image_push_completed` evidence event into Quorum
    once `QUORUM_IMAGE_PUSH_API_URL` and `QUORUM_IMAGE_PUSH_API_KEY`
    repo secrets are set. The notifier is configured against staging
    and workflow run `24925601409` proved it appends hash-chained
    evidence.
  - **Post-tag LLM proposal proof** — `deploy-llm-agent` has run
    against the live staging event stream with a real Anthropic call
    and created a `fly.deploy` proposal from `image_push_completed`
    evidence. PR #75 fixed the adapter-side result parsing so the
    current proposal response envelope logs as a successful tool
    dispatch. PR #76 fixed the prompt contract so future `fly.deploy`
    proposals include target-specific readiness and API health checks
    instead of leaving `health_checks` empty. PR #77 records the live
    proof: `proposal_7e096a4d63fe` carries the standard staging
    readiness and API-health checks. PR #78 turns that prompt contract
    into a server-side safety gate: new `fly.deploy` proposals with no
    health checks are rejected before `proposal_created`, and older
    empty-check proposals fail before the executor calls Fly.
  - **Post-tag execution safety** — same-app `fly.deploy` is blocked
    when Fly exposes `FLY_APP_NAME`, preserving terminal event writes
    for single-machine apps.
  - **Post-tag dog-food proof** — `quorum-staging` executed a real
    policy-gated, human-approved `fly.deploy` into `quorum-prod`; prod
    health checks passed and staging recorded terminal execution events.
  - **Post-tag Neon projection** — staging and prod Fly apps now have
    Neon-backed `DATABASE_URL` secrets; both DB branches are migrated
    to Alembic head, staging was reconciled from JSONL and smoke-tested
    through the Postgres-backed history API, and prod was verified
    empty but reachable.
  - **Post-tag GitHub App bootstrap** — the fixture repo exists, the
    GitHub App is registered/installed on that fixture, and the helper
    can repeat the manifest flow without printing the generated PEM.
  - **Post-tag GitHub actuator Fly proof** — staging and prod carry
    `QUORUM_GITHUB_APP_PRIVATE_KEY_B64`, run the config-bearing image,
    and executed fixture `github.comment_issue` smokes through Quorum.
    The prod proof used the protected `prod` environment gate with
    human approval.
  - **Post-tag LLM audit metadata** — `llm_call_completed` logs now
    include `system_prompt_sha256`, a SHA-256 hash of the exact system
    prompt bytes used for the tick. Prompt content remains out of
    runtime logs.
  - **Post-tag LLM adapter metrics** — the standalone adapter records
    `quorum_llm_tokens_total`, `quorum_llm_ticks_total`, and
    `quorum_llm_proposals_created_total`; operators expose them with
    `--metrics-port` or `QUORUM_LLM_METRICS_PORT`.
- **⬜ Phase 6** — parallel operator-agent worktrees.

All known doc-vs-code drift is closed. No known outstanding tech debt.

## What landed since v0.3.0-alpha.1

Three PRs close the last two Phase 4 roadmap items:

- **PR #46** — README LLM quickstart + ROADMAP/HANDOFF refresh for v0.3.
- **PR #47** — Human approval entity. Three new event types (`human_approval_requested` / `_granted` / `_denied`), new `POST /api/v1/approvals/{proposal_id}` route, execute-time gate, terminal `ProposalStatus.approval_denied`, Alembic 0004 + projector handlers + dispatch-completeness update.
- **PR #48** — SSE event stream + interactive console forms. `EventLog.subscribe()` pub/sub; `GET /api/v1/events/stream`; bearer-token + `create_intent` + cast-vote + grant/deny-approval forms; EventSource live-tail.

## Phase 5 — what it unlocks

Quorum can now dog-food Fly.io deploys through a peer-controller shape.
The path an operator follows:

1. Provision a Fly app + volume per `docs/design/fly-deployment.md` §Operator pre-reqs.
2. `fly secrets set QUORUM_API_KEYS=... QUORUM_GITHUB_APP_PRIVATE_KEY_B64=... DATABASE_URL=... --app <app>`.
3. `fly deploy --app <app>` locally once for the bootstrap.
4. Optional: set `FLY_API_TOKEN` as a repo secret; every merge to
   `main` pushes tagged images to `registry.fly.io/quorum-staging` and
   `registry.fly.io/quorum-prod`.
5. Run the `deploy-llm-agent` process (`python -m apps.llm_agent.run --agent-id deploy-llm-agent`) to watch for new image digests and propose `fly.deploy` actions.
6. Approve each proposal via the operator console. The peer Quorum app
   executes `fly deploy --image registry.fly.io/quorum-prod@sha256:...`
   under the policy + human-approval gate. Same-app deploys are blocked
   until a separate executor lifecycle is designed and proven.

Three design-level invariants that hold across the whole flow:

- **Single-machine-per-app.** Fly Volumes are per-machine; `EventLog` is single-writer. Multi-machine fleets are explicitly deferred.
- **Content-addressed deploys.** `FlyDeploySpec` rejects tags at the pydantic boundary; only `sha256:<64 hex>` passes.
- **Human in the loop for every prod deploy.** `fly.deploy` policy rule is `votes_required: 2, requires_human: true`. Deploys never execute without an explicit approval entity event.
- **Peer controller for live dog-food.** A single-machine Fly app does
  not deploy itself; it deploys the peer app so terminal execution
  events survive machine replacement.

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
21. **[Repo-wide]** Prod always-on requires disabling Fly machine
    autostop, not just keeping one machine in the app. The verified
    command shape is `fly machine update <machine-id> --app quorum-prod
    --autostop=off --autostart --yes`. Use `--autostop=off`; pinned
    `flyctl` parses `--autostop off` as an extra positional argument.
    Re-check and reapply this after `fly deploy` or `fly secrets set`;
    the prod `DATABASE_URL` secret update reset autostop to `true`.
22. **[Repo-wide]** Do not confuse image-push manifest-list digests
    with the platform image ref reported by `fly releases`. A docs-only
    merge can push a fresh registry digest without changing or
    deploying the running Fly release. Treat `fly releases --json` and
    `fly machine status --display-config` as the source of truth for
    what is actually deployed.
23. **[Repo-wide]** `pip-audit` currently ignores only
    `CVE-2026-3219` in CI because the advisory affects the latest
    published PyPI `pip` and has no fixed version. Do not add broad
    ignores; remove this one as soon as a fixed pip release exists.
24. **[Repo-wide]** Neon emits default `postgresql://` connection URIs.
    Quorum must normalize those to `postgresql+psycopg://` because the
    repo ships `psycopg`, not `psycopg2`. Keep runtime engine creation
    and Alembic migrations on the same normalization helper.
25. **[Repo-wide]** Shell one-command env assignments do not affect
    expansions in the same command. `VAR=... fly secrets set
    DATABASE_URL="$VAR"` sends an empty value; assign first with
    `VAR=...; fly secrets set DATABASE_URL="$VAR"` or export the var.
26. **[Repo-wide]** `fly ssh console -C` does not inherit app secrets
    into ad-hoc commands, and it execs the given command directly
    rather than through a shell. To run one-off DB tooling inside the
    machine, inject the secret from Keychain explicitly and wrap with
    `sh -lc`, e.g. `fly ssh console -C "sh -lc 'DATABASE_URL=... python
    -m apps.api.app.tools.reconcile --output json'"`.
27. **[Repo-wide]** GitHub App manifest callback codes expire after
    one hour. If `bootstrap_github_app` captures the App but times out
    before repository installation, keep the Keychain PEM, install the
    App from the printed install URL, then use the App JWT path to
    recover `installation_id`; do not rerun and create duplicate Apps
    unless the PEM was lost.
28. **[Repo-wide]** When proving a prod runtime path, set the proposal
    `environment` to `prod` even if the target resource is a fixture.
    Otherwise the action can succeed but will not exercise the
    protected-environment human-approval gate. The canonical prod
    GitHub actuator proof is `proposal_53414b49eb06`, not the earlier
    non-protected smoke `proposal_1d5c2538f403`.
29. **[Repo-wide]** The image-push evidence notifier is intentionally
    best-effort. If the notifier secrets are missing the step is
    skipped; if staging is unavailable the step can warn instead of
    failing the image supply path. Do not treat a successful image-push
    workflow as Quorum-ingested evidence unless staging's event stream
    contains `image_push_completed`.
30. **[Repo-wide]** Older checkouts before PR #75 log a successful
    `deploy-llm-agent` proposal tool call as `ok=False` if
    `POST /api/v1/proposals` returns the current
    `{proposal, policy_decision}` envelope. Inspect the event log for
    `proposal_created` before assuming the proposal failed. The
    staging key and local Anthropic key now exist in Keychain; do not
    print them in logs or docs.
31. **[Repo-wide]** Older deploy-agent prompts before PR #76 can
    create valid `fly.deploy` proposals with strong evidence refs but
    empty `health_checks`. Before approving any LLM-authored deploy
    proposal, verify it includes the target app's `/readiness` and
    `/api/v1/health` checks. Same-app staging proposals should still
    remain pending unless run from a proven external or peer executor.
32. **[Repo-wide]** New `fly.deploy` proposals without
    `health_checks` are rejected before the event log is mutated, and
    the executor refuses historical empty-check Fly deploys before
    invoking Fly. If you inspect older logs, a pending empty-check
    proposal may still exist as evidence, but it should not be
    considered executable.

## Next-session candidates (pick one, by priority)

### A — Design and prove safe execution for LLM-authored deploy proposals

`deploy-llm-agent` now creates health-checked `fly.deploy` proposals.
The next operator-value step is deciding how those proposals should be
executed safely:

- External runner path: vote/approve/execute `proposal_7e096a4d63fe`
  from outside Fly so the same-app guard does not apply, then verify
  terminal execution + health-check events survive the staging deploy.
- Peer-controller path: have one Quorum app deploy the other, then
  teach the deploy-agent evidence flow to propose staging first, wait
  for staging health evidence, and only then propose prod.

Do not execute a same-app staging proposal from inside the
`quorum-staging` Fly process.

### B — Minor operator hardening worth batching into one PR

- `demo_seed` optionally spawns the LLM adapter process
  (feature-flagged).
- Richer context in
  `_log.warning("projector_status_update_for_missing_proposal", ...)`.

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
