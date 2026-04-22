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

## Phase 3 tail — in flight / next ⏳

- ⏳ OpenTelemetry trace instrumentation (OTLP/HTTP, env-gated)
- ⬜ Log↔trace correlation: bind `request_id` into the current span
- ⬜ Postgres projection (Phase 3 capstone): JSONL stays canonical, Neon/Postgres as derived read-model with `alembic` migrations
- ⬜ CHANGELOG + release tagging process

## Phase 4 — Real actuators and model orchestration

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
- ⬜ Interactive console: forms for intent / finding / proposal / vote;
  SSE stream at `/api/v1/events/stream`.
- ⬜ Human approval entity + notifier for high / critical risk.

## Phase 5 — Deployment ⬜

- Fly.io (`fly.toml`, Fly Volume for canonical JSONL, Neon Postgres for projection)
- Staging + prod apps
- Dog-food deploys: production deploys flow through the Quorum API itself (deploy-agent → code-agent votes → operator approves → executor calls `fly deploy ...@sha256:...`)

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
