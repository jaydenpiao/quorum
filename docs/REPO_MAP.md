# Repo map

Where everything lives. This file exists so an AI agent can navigate
the repo without scanning every file. It is updated as a blocker for
any PR that moves / renames / adds top-level files or folders
(see `AGENTS.md` §9).

Last refreshed for the v0.6.8 release-prep pass.

## Top level

- `README.md` — product overview + quickstart
- `INIT.md` — shortest startup context for AI agents
- `AGENTS.md` — canonical repo-wide agent rules (binding)
- `CLAUDE.md` — pointer to `AGENTS.md` for Claude Code compatibility
- `CHANGELOG.md` — versioned feature list (Keep a Changelog format)
- `docs/GITHUB_APP_ACTUATOR_FLY.md` — operator runbook for enabling
  the GitHub App actuator on Fly
- `docs/DEMO_VIDEO.md` — recording runbook plus live operator proof
  helpers for GitHub fixture execution, LLM-authored prod deploy
  proof, review-voter acceptance proof, console proof smoke, and
  release-proof archive verification
- `llms.txt` — shortest file list for LLM navigation
- `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`
- `pyproject.toml`, `uv.lock` — Python packaging / locked deps;
  package version is sourced dynamically from
  `apps/api/app/version.py`
- `Makefile` — dev commands (`install`, `preflight`, `dev`, `test`,
  `validate`, `typecheck`, `demo`, `reset`, `sbom`,
  `clean-worktrees`) pinned to the managed `uv` Python path
- `Dockerfile`, `docker-compose.yml` — container build + local stack
- `fly.toml` — Fly.io app config (Phase 5)
- `.env.example` — environment variable template

## Config

- `config/system.yaml` — app and runtime settings (log path, CORS,
  rate limits, server port)
- `config/agents.yaml` — agent registry: roles, scopes, argon2id
  key hashes, per-agent `allowed_action_types` /
  `allowed_vote_action_types`, capability gates, optional `llm:` block
- `config/policies.yaml` — quorum policy: risk rules, environment
  overrides, per-`action_type` rule overrides, LLM vote caps, rollback
  settings
- `config/github.yaml` — GitHub App install IDs + limits (Phase 4)

## Backend — `apps/api/`

- `apps/api/AGENTS.md` — backend-area rules
- `apps/api/app/main.py` — FastAPI bootstrap, middleware, DI wiring,
  `/`, `/health`, `/readiness`, `/metrics`, `/console`
- `apps/api/app/version.py` — canonical runtime/package/release
  version strings used by FastAPI metadata, tracing, and the console
- `apps/api/app/middleware.py` — `SecurityHeadersMiddleware`
- `apps/api/app/request_context.py` — per-request UUID binding
- `apps/api/app/logging_config.py` — structlog JSON setup
- `apps/api/app/tracing.py` — optional OTLP/HTTP OpenTelemetry wiring

### Routes

- `apps/api/app/api/routes.py` — mutating `POST /api/v1/*` endpoints
  (intents, findings, proposals, votes, approvals, demo seed,
  execute), including server-owned LLM vote metadata/cap handling
- `apps/api/app/api/history.py` — read-only `/api/v1/history/*`
  endpoints backed by the Postgres projection, including proposal,
  policy, approval, execution, vote audit metadata, health-check,
  rollback, and image-push history

### Domain

- `apps/api/app/domain/models.py` — typed entities: `Intent`,
  `Finding`, `Proposal`, `Vote`, `PolicyDecision`,
  `ExecutionRecord`, `HealthCheckSpec`, `HealthCheckResult`,
  `RollbackRecord`, `RollbackImpossibleRecord`,
  `HumanApprovalRequest`, `HumanApprovalOutcome`, `EventEnvelope`,
  enums and `*Create` DTOs

### Services

- `apps/api/app/services/auth.py` — bearer auth, argon2id key
  registry, per-agent `allowed_action_types` /
  `allowed_vote_action_types` loaders, LLM-agent detection, and
  `can_propose` / `can_vote` capability gates
- `apps/api/app/services/event_log.py` — append-only JSONL writer
  with sha256 hash chain, `verify()`, pub/sub `subscribe()` for SSE
- `apps/api/app/services/state_store.py` — event reducer + current
  state snapshot
- `apps/api/app/services/policy_engine.py` — YAML policy evaluator
  plus LLM vote-cap decisions
- `apps/api/app/services/quorum_engine.py` — counted-vote quorum
  calculation
- `apps/api/app/services/health_checks.py` — runner for
  `always_pass`, `always_fail`, `http`, `github_check_run`
- `apps/api/app/services/executor.py` — dispatch (prefix-based
  `github.*` vs `fly.*` vs passthrough), action invocation,
  health-check loop, rollback path, rollback-impossible emission
- `apps/api/app/services/projector.py` — `Projector` protocol +
  `NoOpProjector`
- `apps/api/app/services/postgres_projector.py` — SQLAlchemy-based
  projection into Postgres
- `apps/api/app/services/reconcile.py` — JSONL → Postgres
  reconciliation
- `apps/api/app/demo_seed.py` — end-to-end demo incident seeder

### Actuators

- `apps/api/app/services/actuators/github/` — GitHub App actuator
  (`specs.py`, `auth.py` for JWT + installation tokens, `client.py`
  httpx wrapper, `actions.py` with `open_pr` / `comment_issue` /
  `close_pr` / `add_labels` + their rollback functions)
- `apps/api/app/services/actuators/fly/` — Fly.io actuator (Phase 5):
  `specs.py` (sha256-only `FlyDeploySpec`), `client.py` (flyctl
  subprocess wrapper), `actions.py` (`deploy` + `rollback_deploy`)

### Database (Postgres projection)

- `apps/api/app/db/engine.py` — `DATABASE_URL` + sync psycopg engine
- `apps/api/app/db/models.py` — SQLAlchemy ORM models

### CLI tools

- `apps/api/app/tools/bootstrap_keys.py` — generate / rotate
  argon2id-hashed API keys
- `apps/api/app/tools/bootstrap_github_app.py` — run the GitHub App
  manifest flow, store the generated PEM in Keychain, and report
  non-secret App / installation IDs
- `apps/api/app/tools/reconcile.py` — run the JSONL → Postgres
  reconciliation out-of-band

## LLM adapter — `apps/llm_agent/`

- `apps/llm_agent/AGENTS.md` — LLM-adapter-area rules
- `apps/llm_agent/run.py` — CLI entry point
  (`python -m apps.llm_agent.run --agent-id <id>`)
- `apps/llm_agent/loop.py` — tick loop + event cursor
- `apps/llm_agent/metrics.py` — Prometheus counters for token usage,
  tick outcomes, and successful LLM-created proposals; also starts the
  adapter sidecar `/metrics` HTTP server when requested
- `apps/llm_agent/claude_client.py` — Anthropic Messages API client
  with prompt caching + adaptive thinking
- `apps/llm_agent/config.py` — agents.yaml `llm:` block loader
- `apps/llm_agent/budget.py` — per-tick + daily input-token caps
  with atomic JSON checkpoints under `data/llm_usage/`
- `apps/llm_agent/tools.py` — `cast_vote`, `create_finding`, and
  `create_proposal` tool schemas + dispatcher, including runtime LLM
  vote metadata injection and the deploy-agent same-control-plane
  `fly.deploy` proposal guard
- `apps/llm_agent/quorum_api.py` — httpx client authenticated as the
  configured agent; infers the control-plane Fly app from `*.fly.dev`
  URLs or `QUORUM_LLM_CONTROL_PLANE_FLY_APP`
- `apps/llm_agent/prompts/telemetry-agent.md` — telemetry role prompt
- `apps/llm_agent/prompts/deploy-agent.md` — Phase 5 deploy-agent role
- `apps/llm_agent/prompts/review-agent.md` — review-voter role prompt

## Console — `apps/console/`

- `apps/console/AGENTS.md`
- `apps/console/index.html` — static operator console shell with
  overview cards, release badge, intent/finding lists, proposal table,
  inspector, timeline, and action forms
- `apps/console/app.js` — browser-only rendering + SSE live-tail +
  bearer-token storage + create-intent / cast-vote /
  grant-deny-approval / execute-proposal / event-chain-verify handlers,
  including counted/capped LLM vote audit rendering
- `apps/console/styles.css` — light SaaS dashboard styling for the
  static console

## Examples

- `examples/demo_incident.json` — canonical demo scenario
- `examples/sample_proposal.json` — sample proposal payload
- `examples/rollback_impossible_event.json` — example of the terminal
  rollback-impossible event shape
- `examples/image_push_completed.json` — example image-push evidence
  event consumed by the deploy-agent flow

## Docs

- `docs/ARCHITECTURE.md` — system design + mermaid diagrams
- `docs/CURRENT_MODE.md` — development mode (single-thread for now)
- `docs/PARALLEL_DEVELOPMENT.md` — worktree model for Phase 6+
- `docs/REPO_MAP.md` — this file
- `docs/ROADMAP.md` — phase ✅/⏳/⬜ tracker
- `docs/PRODUCT.md` — product framing
- `docs/DEMO_VIDEO.md` — active end-to-end recording commands, fallback
  dog-food seed commands, and 3-minute narration
- `docs/SESSION_HANDOFF.md` — live state, gotchas, next candidates
- `docs/GITHUB_AUTOMATION.md` — repo / CI setup reference
- `docs/releases/v0.6.1-proof.md` — durable release/deploy proof
  archive for the `v0.6.1` tag and live prod execution
- `docs/releases/v0.6.2-proof.md` — durable release/deploy proof
  archive for the `v0.6.2` tag and live prod execution
- `docs/releases/v0.6.3-proof.md` — durable release/deploy and
  review-voter proof archive for the `v0.6.3` tag
- `docs/releases/v0.6.4-proof.md` — durable release/deploy and
  review-voter helper proof archive for the `v0.6.4` tag
- `docs/releases/v0.6.5-proof.md` — durable release/deploy proof
  archive for the `v0.6.5` tag and live prod execution
- `docs/releases/v0.6.6-proof.md` — durable release/deploy proof
  archive for the `v0.6.6` tag, dependency hygiene release, Phase 6
  gate result, and live prod execution
- `docs/releases/v0.6.7-proof.md` — durable release/deploy proof
  archive for the `v0.6.7` tag, proof reliability release, Phase 6
  gate result, console proof smoke, and live prod execution
- `docs/design/postgres-projection.md` — projection architecture
- `docs/design/phase-4-github-actuator.md` — GitHub actuator design
- `docs/design/llm-adapter.md` — LLM adapter design
- `docs/design/llm-voter-role.md` — safety contract and implementation
  status for the LLM voter role series
- `docs/design/fly-deployment.md` — Phase 5 Fly.io design
- `docs/design/phase-6-gate-checklist.md` — criteria, no-go/reset
  triggers, and worktree switch procedure for opening Phase 6
- `docs/design/phase-6-readiness-checkpoint.md` — 2026-05-08
  pre-Phase-6 checkpoint with current live proof status, latest
  workflow evidence, schema-stability preflight, and no-go triggers
- `docs/design/phase-6-entry-plan.md` — planning-only entry plan for
  safe first Phase 6 worktree lanes after `phase6-gate-ready`

## Tests — `tests/`

Pytest tests, colocated by feature. Key
files:

- `tests/conftest.py`, `tests/_helpers.py` — shared fixtures
- `tests/test_auth.py`, `tests/test_auth_argon2.py`,
  `tests/test_allowed_action_types.py`,
  `tests/test_agent_capability_gates.py` — auth surface
- `tests/test_event_log_chain.py`, `tests/test_event_log_subscribe.py`
- `tests/test_policy_action_type_rules.py`
- `tests/test_executor_github_dispatch.py`,
  `tests/test_executor_fly_dispatch.py`
- `tests/test_github_*.py` — one per GitHub action
- `tests/test_github_live_integration.py` — opt-in fixture
  comment/rollback test, gated by `QUORUM_GITHUB_LIVE_TESTS=1`
- `tests/test_fly_actuator.py` — spec / client / actions
- `tests/test_fly_deploy_proposal_gate.py` — API and executor gates
  that prevent `fly.deploy` proposals from skipping health checks
- `tests/test_fly_live_integration.py` — opt-in live staging
  deploy/rollback test, gated by `QUORUM_FLY_LIVE_TESTS=1`
- `tests/test_deploy_llm_agent.py` — deploy-agent role wiring
- `tests/test_review_llm_agent.py` — review-voter role wiring
- `tests/test_review_voter_proof_helper.py` — static contract checks
  for the review-voter proof helper script
- `tests/test_dockerfile_runtime.py` — container runtime pinning
  checks for Python base image, `uv`, and `flyctl`
- `tests/test_image_push_workflow.py` — image-push workflow checks
  for staging/prod registry tags, digest summaries, and optional
  Quorum evidence notification
- `tests/test_live_release_monitor.py` — static checks for the live
  release monitor script and scheduled/manual workflow
- `tests/test_release_proof_docs.py` — static checks that archived
  release proof docs retain required evidence IDs
- `tests/test_phase6_gate_checklist.py` — static checks that the Phase
  6 gate doc records the stability, CI, live-monitor, no-go, and
  fallback rules
- `tests/test_llm_voter_design.py` — static checks for the LLM voter
  role safety contract
- `tests/test_llm_vote_policy.py` — LLM vote metadata, policy caps,
  self-vote/disallowed-action gates, counted-quorum behavior, and
  vote projection/history serialization
- `tests/test_image_push_evidence.py` — authenticated
  `image_push_completed` route + reducer coverage
- `tests/test_readiness.py` — Phase 5 readiness probe
- `tests/test_human_approval.py` — human-approval flow
- `tests/test_sse_stream.py` — SSE route wiring
- `tests/test_postgres_projector.py`, `tests/test_reconcile.py` —
  projection (integration-gated)
- `tests/test_llm_adapter_*.py` — LLM adapter components, including
  token/tick/proposal metrics and CLI metrics-port wiring
- `tests/test_bootstrap_contract.py` — static checks for the managed
  `uv` bootstrap path, runtime preflight, and validation commands
- `tests/test_version_contract.py` — runtime/package/tracing version
  consistency checks
- `tests/test_demo_recording_assets.py` — static coverage for the
  recording runbook, active GitHub fixture demo helper, and
  post-release proof acceptance commands
- `tests/test_phase6_gate_preflight.py` — static and fail-closed
  coverage for the read-only Phase 6 gate preflight script
- `tests/test_event_schema_stability_preflight.py` — static and
  dynamic checks for the schema-stability anchor script required by
  the Phase 6 gate
- `tests/test_phase6_readiness_checkpoint.py` — static checks that the
  readiness checkpoint, handoff, repo map, and gate checklist agree on
  latest release, gate date, proof commands, and no-go triggers
- `tests/test_phase6_entry_plan.py` — static checks that the Phase 6
  entry plan requires the gate, points to the worktree model, defines
  safe first lanes, and blocks shared-core work without an owner
- `tests/test_console_proof_smoke.py` — static contract checks for
  the read-only console proof deep-link smoke helper
- `tests/test_release_proof_archive_check.py` — static contract
  checks for the read-only release proof archive verifier

Integration tests are marked `@pytest.mark.integration` and excluded
from default CI; opt in with `pytest -m integration`.

## Scripts

- `scripts/bootstrap_local_repo.sh` — init local git + first commit
- `scripts/create_public_github_repo.sh` — create public repo via `gh`
- `scripts/new_worktree.sh` — create a worktree per task (Phase 6+)
- `scripts/check_python_runtime.py` — managed-Python preflight that
  fails fast on broken `readline` imports before local validation runs
- `scripts/validate_merge.sh` — run merge-gate checks locally
- `scripts/demo_run.sh` — fast local demo
- `scripts/demo_github_fixture_flow.sh` — paused active recording flow
  that drives a real fixture `github.comment_issue` proposal through
  intent, evidence, quorum, execution, health check, and audit proof
- `scripts/prove_llm_prod_deploy.sh` — live operator proof helper for
  `deploy-llm-agent --once`: fresh image-push evidence, staging
  success evidence (`execution_succeeded` or explicit
  `external_staging_verification` finding), verified `quorum-prod`
  proposal, optional vote/approval/execute path gated by
  `QUORUM_PROOF_EXECUTE=1`
- `scripts/prove_review_llm_vote.sh` — review-voter acceptance proof
  helper for `review-llm-agent`: validates an existing eligible
  low-risk GitHub proposal or creates an explicit fixture proposal,
  runs the adapter only when a counted proof vote is missing, and
  writes `proof.json` / `proof.md`
- `scripts/capture_operator_proof.sh` — read-only audit capture helper
  that writes `proof.json` and `proof.md` from staging/prod root
  metadata, event-chain verification, prod health, and the terminal
  `deploy-llm-agent` prod deploy proposal
- `scripts/check_console_proof.sh` — read-only console proof smoke:
  verifies release metadata, console shell/static JS, event-chain
  verification, selected `deploy-llm-agent` prod deploy proposal,
  policy/quorum/human approval, execution, and prod health checks; it
  prints `console-proof-ok: <console_url>` on success
- `scripts/check_release_proof_archive.sh` — read-only release proof
  archive verifier: checks the signed tag object, tagged commit,
  GitHub release/SBOM asset name, URL, digest, durable proof doc,
  handoff/repo-map pointers, and live monitor result; it prints
  `release-proof-archive-ok: <tag>` on success
- `scripts/check_live_release.sh` — read-only monitor for the current
  tagged release: staging/prod version metadata, prod health, staging
  event-chain verification, release SBOM asset, and latest main
  CI/security/image-push status
- `scripts/check_event_schema_stability.sh` — read-only Phase 6
  schema-stability preflight that fails if schema-sensitive
  event/model/projection, Alembic, or example payload files changed
  after the configured anchor tag, default `v0.6.3`
- `scripts/check_phase6_gate.sh` — read-only Phase 6 gate preflight:
  fail before 2026-05-14, require schema-stability preflight, live
  release monitor and latest main workflow success, require durable
  proof/handoff pointers, and print `phase6-gate-ready` only when the
  switch to
  `docs/PARALLEL_DEVELOPMENT.md` is allowed

## CI / GitHub — `.github/`

- `.github/workflows/ci.yml` — 5 required checks: `lint + format +
  test`, `pip-audit`, `mypy`, `docker build` (`gitleaks` lives in
  `security.yml`)
- `.github/workflows/security.yml` — gitleaks secret scan
- `.github/workflows/release.yml` — on `v*` tag push: generate SPDX
  SBOM, create GitHub release, attach asset as
  `quorum-<tag>.spdx.json`
- `.github/workflows/image-push.yml` — on merge to `main`: build +
  push image to `registry.fly.io/quorum-staging:<sha>` and
  `registry.fly.io/quorum-prod:<sha>` (gated on `FLY_API_TOKEN`);
  optional Quorum evidence posting retries with bounded backoff and
  records notifier status / returned IDs in the step summary
- `.github/workflows/live-release-monitor.yml` — manual + scheduled
  read-only live release check that runs
  `scripts/check_live_release.sh` without repo secrets
- `.github/dependabot.yml` — weekly pip, monthly github-actions
- `.github/CODEOWNERS` — protects shared-core files
- `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/`

## Claude Code harness — `.claude/` (tool-specific)

Claude-only batteries. Safe to ignore if you aren't using Claude Code.
Configuration for: permissions allowlist, PostToolUse hooks (ruff
autofix, destructive-command guard), pre-tool-use push-force block,
subagents, skills, slash commands.

- `.claude/settings.json` — permissions + hooks
- `.claude/agents/` — role-scoped subagents
- `.claude/skills/` — custom skills (`create-event-type`,
  `add-actuator`)
- `.claude/commands/` — slash commands (`/demo`, `/validate`,
  `/run-dev`, `/new-worktree`)
- `.mcp.json` — MCP server definitions

## Runtime data — `data/` (gitignored)

- `data/events.jsonl` — the append-only event log (single-writer,
  hash-chained; authoritative)
- `data/llm_usage/` — per-agent token budget checkpoints

Mount at `/app/data` in the container. Must survive restarts.
