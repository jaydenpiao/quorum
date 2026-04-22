# Changelog

All notable changes to Quorum will live here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once
`v1.0.0` is tagged. Pre-1.0, every merge to `main` is unreleased until a
`vX.Y.Z` tag is cut — at which point the SBOM workflow publishes an SPDX
artifact against that tag (see `.github/workflows/release.yml`).

## [Unreleased]

### Added

- **LLM adapter scaffold (Phase 4 LLM PR 1)** — new `apps/llm_agent/`
  package that will drive Claude-backed agents (starting with
  `telemetry-llm-agent`) as proposers inside Quorum. Runs as its own OS
  process per agent; talks to the Quorum API over HTTP under the
  agent's argon2id-hashed credentials — no in-process coupling with the
  control plane. PR 1 ships scaffolding only: `LlmAgentConfig` parses
  the new `llm:` sub-block from `config/agents.yaml`; `LlmBudget`
  enforces per-tick + daily input-token caps with atomic JSON
  checkpoints under `data/llm_usage/`; `ClaudeClient` builds Messages
  API request bodies with prompt caching (`cache_control: ephemeral`),
  adaptive thinking, and `output_config.effort=high` (omitted on models
  that reject it); `QuorumApiClient` wraps bearer-authenticated calls
  to `/api/v1/events`, `/api/v1/findings`, `/api/v1/proposals`; and a
  `run_tick()` + `python -m apps.llm_agent.run` CLI wire everything
  together. **No live Claude calls yet** — the tick builds the request
  body and advances its event cursor; PR 2 flips on `create_finding`
  and PR 3 adds `create_proposal` + cost-cap hard-enforcement. New
  runtime dep: `anthropic>=0.45.0`.
- **`HealthCheckKind.github_check_run` (Phase 4 PR E)** — a new health
  check that polls `GET /repos/{owner}/{repo}/commits/{sha}/check-runs`
  via the configured GitHub App until every check run reaches a
  terminal state, or a wall-clock timeout expires (default 300 s, max
  30 min). Pass criteria: `status="completed"` AND `conclusion` in
  {success, neutral, skipped} for every run. Any non-passing terminal
  conclusion fails fast. Optional `github_check_name` filter scopes the
  poll to a single workflow. `HealthCheckSpec` gains `github_owner`,
  `github_repo`, `github_commit_sha`, `github_check_name`, and
  `poll_interval_seconds`; the executor threads its actuator result
  (e.g. `OpenPrResult.head_sha`) as `context["head_sha"]` so the spec's
  `github_commit_sha` is optional — the operator can attach a check-run
  probe to an `open_pr` proposal without knowing the SHA in advance.
  `GitHubAppClient.list_commit_check_runs` is the underlying REST
  method. `HealthCheckRunner` now accepts an optional `github_client`
  and a `sleep_fn` injection point for testability.
- **Remaining GitHub actions (Phase 4 PR D)** — `github.comment_issue`,
  `github.close_pr`, `github.add_labels`, each with typed spec, result,
  orchestration function, and idempotent rollback (delete comment,
  reopen PR, remove-only-what-we-added labels). `GitHubAppClient` gains
  `create_issue_comment`, `delete_issue_comment`, `reopen_pull_request`,
  `list_issue_labels`, `add_issue_labels`, `remove_issue_label` plus a
  `_list_request` helper for JSON-array endpoints. Executor switches
  from hardcoded action_type branches to per-action dispatch tables
  (`_ACTION_DISPATCH` / `_ROLLBACK_DISPATCH`) — adding a new action is
  now a three-line change here plus a spec + action function in the
  actuator subpackage. `rollback_close_pr` surfaces
  `RollbackImpossibleError` when the PR was merged between close and
  rollback. `add_labels` pre-lists existing labels and captures only
  the diff as `labels_added`, so rollback never removes labels that
  were already present. `config/policies.yaml` ships default
  `action_type_rules` for all three new actions
  (`comment_issue`/`add_labels` require 1 vote; `close_pr` requires 2).
- **Actuator-aware rollback + `rollback_impossible` event (Phase 4 PR C)** —
  the executor now dispatches rollback for `github.*` proposals to a
  matching actuator function (currently `rollback_open_pr`: closes the
  PR via `PATCH state=closed` and deletes the branch via `DELETE
  /git/refs/heads/...`, both idempotent on 404/422). When the actuator
  cannot undo the mutation (e.g. the PR was merged out-of-band), the
  executor emits a new terminal **`rollback_impossible`** event with a
  human-readable `reason` plus an `actuator_state` blob, and the
  proposal lands in the new `ProposalStatus.rollback_impossible`.
  Reducer, `PostgresProjector` handler, dispatch-completeness regression
  guard, state-store replay test, and a full integration test ("open PR
  succeeds → health check fails → PR already merged → rollback_impossible")
  all ship together. Non-github proposals keep their pre-PR-C text-only
  rollback behaviour unchanged.
- **GitHub actuator wired into the executor (Phase 4 PR B2)** —
  `Executor` now dispatches on `proposal.action_type`. `github.*`
  proposals route to the PR B1 actuator; non-github action types keep
  the existing simulated-execution path. `Proposal` gains a typed
  `payload: dict[str, Any]` (JSON-size capped at 256 KiB) and
  `ExecutionRecord` gains `result` (the actuator's return blob,
  replayable from events). Policy engine merges a new
  `action_type_rules` section from `config/policies.yaml` — MAX of
  `votes_required`, OR of `requires_human`, can only tighten the
  risk-level default. `config/policies.yaml` ships a
  `github.open_pr: {votes_required: 2, requires_human: false}` default.
  `main.py` conditionally constructs a `GitHubAppClient` on startup iff
  `config/github.yaml` has a non-placeholder `app_id` and the private
  key is available; otherwise the actuator stays disabled and
  `github.*` proposals fail fast with a clear dispatch error.
- **GitHub `open_pr` action (Phase 4 PR B1)** — new `actions.open_pr`
  orchestrates the Git Data API flow (base branch lookup → blobs →
  tree → commit → ref → PR) into a single atomic action. Typed
  `GitHubOpenPrSpec` / `GitHubFileSpec` payloads with UTF-8 byte-size
  validation, repo-path safety checks, and `extra='forbid'`. Head
  branch name is derived as `quorum/<proposal_id>` so rollback (PR C)
  can find it deterministically. `GitHubAppClient` gains `get_branch`,
  `create_blob`, `create_tree`, `create_commit`, `create_ref`,
  `create_pull_request`, all routed through the PR A
  single-retry-on-401 wrapper. Not yet wired into the executor — that
  dispatch + policy merge + `HealthCheckKind.github_check_run` land
  in PR B2.
- **GitHub App actuator scaffold (Phase 4 PR A)** — new
  `apps/api/app/services/actuators/github/` package with `AppJWTSigner`
  (RS256 App JWT minting), `InstallationTokenCache` (per-install token
  cache with 60s refresh margin + single-retry 401 renewal),
  `GitHubAppClient`, and typed config loader for a new `config/github.yaml`.
  Private key loaded from `QUORUM_GITHUB_APP_PRIVATE_KEY` or
  `QUORUM_GITHUB_APP_PRIVATE_KEY_PATH` env. No action dispatch yet — the
  executor wiring and first action (`github.open_pr`) land in PR B. New
  runtime deps: `pyjwt`, `cryptography`. New dev dep: `respx`.
- **`health_check_completed` event emission** — the executor now emits one
  `health_check_completed` event per check between `execution_started` and
  the terminal `execution_succeeded`/`execution_failed`. Closes the
  long-standing `docs/ARCHITECTURE.md` drift. `HealthCheckResult` gains
  `id` and `created_at`. New `health_check_results` table (Alembic 0003)
  and projector handler; reducer added to `state_store`.
- **Read-only history endpoints** — `/api/v1/history/{intents,findings,
  proposals,votes,executions}` backed by the Postgres projection; return
  503 when `DATABASE_URL` is unset.
- **Postgres projection capstone** — `PostgresProjector` (SQLAlchemy 2.0
  sync + psycopg3), Alembic migrations 0001–0003, `Projector` Protocol
  with `NoOpProjector` default wired into `EventLog.append` post-fsync,
  reconcile service + `python -m apps.api.app.tools.reconcile` CLI.
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
