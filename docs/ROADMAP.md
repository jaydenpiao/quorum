# Roadmap

Status legend: ✅ done · ⏳ in flight · ⬜ planned · ✂️ cut for now.

## Phase 0 — Claude Code harness ✅

- `.claude/settings.json` with permissions allow/deny, PostToolUse ruff autofix, PreToolUse destructive-command guard, shared-core warning
- `.claude/settings.local.json` (gitignored)
- `.mcp.json`: GitHub + Filesystem + Sequential-thinking MCP servers
- Five subagents (backend, console, devops, docs, security-auditor), all on Opus 4.7
- Custom skills: `create-event-type`, `add-actuator`
- Slash commands: `/demo`, `/validate`, `/new-worktree`, `/run-dev`
- Git init + public GitHub repo push
- `CLAUDE.md` → `AGENTS.md` pointer (no more duplication)

## Phase 1 — OSS hygiene ✅

- Apache-2.0 `LICENSE` with patent grant
- `SECURITY.md`, `CONTRIBUTING.md` (DCO), `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1 by URL), `.github/CODEOWNERS` protecting shared-core
- `uv` dep management with committed `uv.lock`
- CI via `uv sync --frozen --extra dev`; `gitleaks` + `pip-audit` + Dependabot wired
- Branch protection on `main` (required PR, required CI)

## Phase 2 — Core security ✅

- Typed health checks (`always_pass`, `always_fail`, `http`); `subprocess shell=True` path removed
- Tamper-evident event-log hash chain (sha256, verify on startup, `GET /api/v1/events/verify`)
- Bearer-token auth on all mutating routes; `/api/v1/demo/incident` gated behind `QUORUM_ALLOW_DEMO=1` env var
- `CORSMiddleware`, `SecurityHeadersMiddleware` (CSP/HSTS/XCTO/XFO/Referrer-Policy/Permissions-Policy), `slowapi` rate limit
- Strict pydantic DTOs (`extra='forbid'`, length bounds, enum narrowing)

## Phase 2.5 — Identity + secrets ✅

- Server-side actor binding: spoofed `agent_id` returns 403; server-fill when omitted
- Argon2id-hashed API keys in `config/agents.yaml` with env-var registry fallback
- Bootstrap CLI: `python -m apps.api.app.tools.bootstrap_keys generate|rotate`

## Phase 3 — Production foundation ✅

- Multi-stage `Dockerfile` (non-root, distroless-adjacent); `docker-compose.yml`; `docker build` as a required CI check
- `pytest-cov` gate at 60% floor (87% baseline); `coverage.xml` as CI artifact
- `structlog` JSON logs + `RequestContextMiddleware` with per-request `X-Request-ID` UUID
- Prometheus `/metrics` via `prometheus-fastapi-instrumentator` (public, rate-limit-exempt, self-scrape excluded)
- `mypy --strict`: baseline zero errors; required CI gate
- SPDX SBOM on tag-push via `anchore/sbom-action` (attached as release asset)

Branch protection on `main` currently requires **5 checks**: `lint + format + test`, `gitleaks`, `pip-audit`, `docker build`, `mypy`.

## Phase 3 tail ✅

- ✅ OpenTelemetry trace instrumentation (OTLP/HTTP, env-gated)
- ✅ Log↔trace correlation: `request_id` + `trace_id` + `span_id` bound into structlog contextvars
- ✅ Postgres projection (Phase 3 capstone): JSONL stays canonical, Neon/Postgres as derived read-model with `alembic` migrations
- ✅ `CHANGELOG.md` + release tagging process; SBOM attached per tag

## Phase 4 — Real actuators and model orchestration ✅

- ✅ GitHub App actuator (PRs #35 / #36 / #37 / #38 / #40):
  `github.open_pr`, `github.comment_issue`, `github.close_pr`,
  `github.add_labels` all end-to-end — typed specs, Git Data REST
  methods, orchestration, executor dispatch via table, policy
  `action_type_rules` merge, actuator-aware rollback per action, the
  terminal `rollback_impossible` event. Feature-branch-only;
  `main` / `master` / `trunk` / `develop` / `release*` rejected at the
  pydantic boundary.
- ✅ `HealthCheckKind.github_check_run` (PR #41): poll a commit's
  check-runs via the App until every run is terminal; actuator-
  result threading (`context["head_sha"]`) so operators don't need
  to know the SHA at proposal time.
- ✅ LLM adapter (PRs #42 / #43 / #44 / #45) via the Anthropic SDK:
  Claude-backed telemetry agent that reads the event stream and
  emits findings + low-risk GitHub proposals (`comment_issue` /
  `add_labels`) through the same authenticated routes as any other
  caller. Prompt caching on the system prompt, adaptive thinking,
  per-tick + daily input-token caps. Server-side `allowed_action_types`
  gate prevents the LLM from escalating into operator-only actions
  (`open_pr` / `close_pr`).
- ✅ Interactive console (PR #48): forms for intent / finding /
  proposal / vote + SSE stream at `/api/v1/events/stream` with
  EventSource live-tail.
- ✅ Human approval entity + three event types (`human_approval_*`)
  (PR #47): execute-time gate on `requires_human=true` proposals;
  new terminal `ProposalStatus.approval_denied`.

## Phase 5 — Deployment ✅ (v0.5.0-alpha.1)

- ✅ `fly.toml` at repo root (region `iad`, volume mount at `/app/data`,
  http_checks on `/api/v1/health` + `/readiness`).
- ✅ `GET /readiness` endpoint — chain-verification + DB-ping gate.
- ✅ `fly.deploy` actuator (`apps/api/app/services/actuators/fly/`):
  sha256-only `FlyDeploySpec`, flyctl subprocess client, deploy +
  rollback with rollback-impossible fallback.
- ✅ Executor refactored to prefix-based dispatch (`github.*` vs
  `fly.*` vs passthrough).
- ✅ Policy rule: `fly.deploy` requires 2 votes + `requires_human=true`
  (strictest in the project).
- ✅ `deploy-llm-agent` LLM role with `allowed_action_types:
  [fly.deploy]`.
- ✅ Image-push CI (`.github/workflows/image-push.yml`) —
  content-addressed push to both
  `registry.fly.io/quorum-staging:<sha>` and
  `registry.fly.io/quorum-prod:<sha>` on merge to `main`, gated on
  `FLY_API_TOKEN`.
- ✅ Dockerfile runtime hardening — pinned `python:3.12-slim`
  linux/amd64 digest, pinned `uv`, and checksummed `flyctl` binary
  copied into the runtime image as `/usr/local/bin/fly`.
- ✅ Live Fly integration tests (`QUORUM_FLY_LIVE_TESTS=1`) — opt-in,
  skipped in default CI, and proven manually against `quorum-staging`.
- ✅ Same-app Fly deploy guard — `fly.deploy` refuses to deploy the
  current `FLY_APP_NAME`, preserving terminal event writes on
  single-machine Fly apps.
- ✅ Peer-controller dog-food deploy smoke — `quorum-staging` executed
  a real Quorum API-gated `fly.deploy` into `quorum-prod`, with policy,
  two votes, human approval, health checks, and terminal events verified.

## Phase 6 — Parallel operator agents ⬜

Gated on Phase 2 + Phase 3 stability (met) and ≥2 weeks of event-schema stability.

- Extend `scripts/new_worktree.sh` to seed per-worktree `.claude/settings.local.json` and link `.mcp.json`
- Use `superpowers:dispatching-parallel-agents` and `superpowers:subagent-driven-development` for multi-lane work
- First parallel lanes: GitHub actuator depth, K8s actuator, policy DSL v2, console redesign

## Cut for now ✂️

- ed25519 signing of the event hash chain (defer until multi-writer)
- cosign / SLSA provenance attestations (after first tagged release)
- HSM-backed chain signing, SOC2 / ISO27001 prep (months-scale, not this phase)
- Full local-model LLM adapter (keep the Anthropic SDK one, design for pluggability)
