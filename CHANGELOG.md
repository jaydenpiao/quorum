# Changelog

All notable changes to Quorum will live here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once
`v1.0.0` is tagged. Pre-1.0, every merge to `main` is unreleased until a
`vX.Y.Z` tag is cut — at which point the SBOM workflow publishes an SPDX
artifact against that tag (see `.github/workflows/release.yml`).

## [Unreleased]

### Added

- **OpenTelemetry traces** — `apps/api/app/tracing.py`, env-gated OTLP/HTTP
  exporter (`OTEL_EXPORTER_OTLP_ENDPOINT`). `/metrics` and `/health` excluded
  from tracing.
- **Prometheus `/metrics`** — public endpoint via
  `prometheus-fastapi-instrumentator`. Rate-limit-exempt, self-scrape excluded.
- **Structured JSON logs** — `structlog` with `RequestContextMiddleware`
  binding a per-request UUID4 into contextvars and echoing `X-Request-ID`.
- **Argon2id-hashed API keys** — `api_key_hash` field in `config/agents.yaml`
  with an env-var registry fallback; `python -m apps.api.app.tools.bootstrap_keys`
  CLI for generate / rotate.
- **Tamper-evident event log** — sha256 hash chain on `EventEnvelope`,
  `EventLog.verify()` on startup, `GET /api/v1/events/verify` endpoint.
- **Bearer-token auth** — required on every mutating `POST /api/v1/*` route;
  server-side actor binding (spoofed `agent_id` → 403).
- **Typed health checks** — `HealthCheckKind.http` with URL/scheme validation.
- **HTTP hardening** — `CORSMiddleware` pinned to allowlisted origins,
  `SecurityHeadersMiddleware` (HSTS, CSP, X-Frame-Options, X-Content-Type-Options,
  Referrer-Policy, Permissions-Policy), `slowapi` rate limit.
- **Strict pydantic DTOs** — `extra='forbid'`, per-field length bounds, enum
  narrowing on all `*Create` models.
- **Production foundation** — multi-stage non-root `Dockerfile`,
  `docker-compose.yml`, `pytest-cov` gate (60% floor), `mypy --strict` clean
  (0 errors, required CI), SPDX SBOM on tag push via `anchore/sbom-action`,
  Dependabot (weekly pip + monthly actions).
- **Claude Code harness** — `.claude/settings.json` with permissions + hooks
  (ruff autofix, destructive-command block, shared-core warn), five subagents
  on Opus 4.7, custom skills, slash commands, `.mcp.json` for GitHub +
  Filesystem + Sequential-thinking MCP servers.
- **OSS governance** — Apache-2.0 LICENSE, SECURITY.md, CONTRIBUTING.md (DCO),
  CODE_OF_CONDUCT.md (Contributor Covenant 2.1), CODEOWNERS protecting
  shared-core.

### Changed

- `EventLog.append` now returns the enriched `EventEnvelope` (with `prev_hash`
  and `hash` populated) so callers can inspect the chain.
- `seed_demo` accepts an optional `event_log` parameter so `/api/v1/demo/incident`
  preserves hash-chain continuity across reset + seed.
- `ExecutionRequest.actor_id` is retained for back-compat but ignored — the
  executor always runs under the authenticated agent.

### Removed

- `HealthCheckKind.shell` and the `subprocess.run(..., shell=True)` code path.
- `HealthCheckSpec.command` string field.

### Security

- Closed: shell-dispatch injection in health checks, unauthenticated API,
  publicly reachable destructive demo endpoint, non-tamper-evident event log,
  unbounded input payloads, missing CORS / security headers / rate limiting,
  advisory-only actor identity.

### CI

- Required checks on `main`: `lint + format + test`, `gitleaks`, `pip-audit`,
  `docker build`, `mypy`. Linear history enforced. Force-push disabled.

## v0 — initial POC scaffold

- FastAPI control-plane service, nine typed domain entities, YAML policy
  configuration, JSONL event log, quorum voting, automatic rollback,
  read-only operator console, demo incident seeder.
