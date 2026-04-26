# Repo map

Where everything lives. This file exists so an AI agent can navigate
the repo without scanning every file. It is updated as a blocker for
any PR that moves / renames / adds top-level files or folders
(see `AGENTS.md` §9).

Last refreshed at v0.5.0-alpha.1.

## Top level

- `README.md` — product overview + quickstart
- `INIT.md` — shortest startup context for AI agents
- `AGENTS.md` — canonical repo-wide agent rules (binding)
- `CLAUDE.md` — pointer to `AGENTS.md` for Claude Code compatibility
- `CHANGELOG.md` — versioned feature list (Keep a Changelog format)
- `docs/GITHUB_APP_ACTUATOR_FLY.md` — operator runbook for enabling
  the GitHub App actuator on Fly
- `docs/DEMO_VIDEO.md` — recording runbook + script for the polished
  local dog-food deploy demo
- `llms.txt` — shortest file list for LLM navigation
- `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`
- `pyproject.toml`, `uv.lock` — Python packaging / locked deps
- `Makefile` — dev commands (`dev`, `test`, `validate`, `demo`,
  `reset`, `sbom`, `clean-worktrees`)
- `Dockerfile`, `docker-compose.yml` — container build + local stack
- `fly.toml` — Fly.io app config (Phase 5)
- `.env.example` — environment variable template

## Config

- `config/system.yaml` — app and runtime settings (log path, CORS,
  rate limits, server port)
- `config/agents.yaml` — agent registry: roles, scopes, argon2id
  key hashes, per-agent `allowed_action_types`, optional `llm:` block
- `config/policies.yaml` — quorum policy: risk rules, environment
  overrides, per-`action_type` rule overrides, rollback settings
- `config/github.yaml` — GitHub App install IDs + limits (Phase 4)

## Backend — `apps/api/`

- `apps/api/AGENTS.md` — backend-area rules
- `apps/api/app/main.py` — FastAPI bootstrap, middleware, DI wiring,
  `/`, `/health`, `/readiness`, `/metrics`, `/console`
- `apps/api/app/middleware.py` — `SecurityHeadersMiddleware`
- `apps/api/app/request_context.py` — per-request UUID binding
- `apps/api/app/logging_config.py` — structlog JSON setup
- `apps/api/app/tracing.py` — optional OTLP/HTTP OpenTelemetry wiring

### Routes

- `apps/api/app/api/routes.py` — mutating `POST /api/v1/*` endpoints
  (intents, findings, proposals, votes, approvals, demo seed,
  execute)
- `apps/api/app/api/history.py` — read-only `/api/v1/history/*`
  endpoints backed by the Postgres projection

### Domain

- `apps/api/app/domain/models.py` — typed entities: `Intent`,
  `Finding`, `Proposal`, `Vote`, `PolicyDecision`,
  `ExecutionRecord`, `HealthCheckSpec`, `HealthCheckResult`,
  `RollbackRecord`, `RollbackImpossibleRecord`,
  `HumanApprovalRequest`, `HumanApprovalOutcome`, `EventEnvelope`,
  enums and `*Create` DTOs

### Services

- `apps/api/app/services/auth.py` — bearer auth, argon2id key
  registry, per-agent `allowed_action_types` loader
- `apps/api/app/services/event_log.py` — append-only JSONL writer
  with sha256 hash chain, `verify()`, pub/sub `subscribe()` for SSE
- `apps/api/app/services/state_store.py` — event reducer + current
  state snapshot
- `apps/api/app/services/policy_engine.py` — YAML policy evaluator
- `apps/api/app/services/quorum_engine.py` — vote counting
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
- `apps/llm_agent/tools.py` — `create_finding` + `create_proposal`
  tool schemas + dispatcher, including the deploy-agent same-control-
  plane `fly.deploy` proposal guard
- `apps/llm_agent/quorum_api.py` — httpx client authenticated as the
  configured agent; infers the control-plane Fly app from `*.fly.dev`
  URLs or `QUORUM_LLM_CONTROL_PLANE_FLY_APP`
- `apps/llm_agent/prompts/telemetry-agent.md` — telemetry role prompt
- `apps/llm_agent/prompts/deploy-agent.md` — Phase 5 deploy-agent role

## Console — `apps/console/`

- `apps/console/AGENTS.md`
- `apps/console/index.html` — static operator console shell with
  overview cards, proposal table, inspector, timeline, and action forms
- `apps/console/app.js` — browser-only rendering + SSE live-tail +
  bearer-token storage + create-intent / cast-vote /
  grant-deny-approval handlers
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
- `docs/DEMO_VIDEO.md` — local recording commands, live read-only
  proof commands, and 3-minute narration
- `docs/SESSION_HANDOFF.md` — live state, gotchas, next candidates
- `docs/GITHUB_AUTOMATION.md` — repo / CI setup reference
- `docs/design/postgres-projection.md` — projection architecture
- `docs/design/phase-4-github-actuator.md` — GitHub actuator design
- `docs/design/llm-adapter.md` — LLM adapter design
- `docs/design/fly-deployment.md` — Phase 5 Fly.io design

## Tests — `tests/`

Pytest tests, colocated by feature. 392 default tests + 13 integration-
gated tests, ~81% coverage. Key
files:

- `tests/conftest.py`, `tests/_helpers.py` — shared fixtures
- `tests/test_auth.py`, `tests/test_auth_argon2.py`,
  `tests/test_allowed_action_types.py` — auth surface
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
- `tests/test_dockerfile_runtime.py` — container runtime pinning
  checks for Python base image, `uv`, and `flyctl`
- `tests/test_image_push_workflow.py` — image-push workflow checks
  for staging/prod registry tags, digest summaries, and optional
  Quorum evidence notification
- `tests/test_image_push_evidence.py` — authenticated
  `image_push_completed` route + reducer coverage
- `tests/test_readiness.py` — Phase 5 readiness probe
- `tests/test_human_approval.py` — human-approval flow
- `tests/test_sse_stream.py` — SSE route wiring
- `tests/test_postgres_projector.py`, `tests/test_reconcile.py` —
  projection (integration-gated)
- `tests/test_llm_adapter_*.py` — LLM adapter components, including
  token/tick/proposal metrics and CLI metrics-port wiring

Integration tests are marked `@pytest.mark.integration` and excluded
from default CI; opt in with `pytest -m integration`.

## Scripts

- `scripts/bootstrap_local_repo.sh` — init local git + first commit
- `scripts/create_public_github_repo.sh` — create public repo via `gh`
- `scripts/new_worktree.sh` — create a worktree per task (Phase 6+)
- `scripts/validate_merge.sh` — run merge-gate checks locally
- `scripts/demo_run.sh` — fast local demo

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
  `registry.fly.io/quorum-prod:<sha>` (gated on `FLY_API_TOKEN`)
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
