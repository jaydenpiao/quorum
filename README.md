# Quorum

[![CI](https://github.com/jaydenpiao/quorum/actions/workflows/ci.yml/badge.svg)](https://github.com/jaydenpiao/quorum/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)](#project-status)
[![coverage: target >= 60%](https://img.shields.io/badge/coverage-%E2%89%A5%2060%25-blue.svg)](#)
[![mypy](https://img.shields.io/badge/mypy-strict%20(phased)-orange)](https://github.com/jaydenpiao/quorum/actions/workflows/ci.yml)

Quorum is a control plane for **safe, auditable, policy-gated, quorum-based execution** by AI agents operating on code and infrastructure.

It is **not** a chat agent. Every mutation flows through:

`Intent → Finding → Proposal → PolicyDecision → Quorum vote → Execution → HealthCheck → (Rollback on failure)`

Every step is appended to a tamper-evident event log. Rollback is first-class. Post-change health verification is mandatory. Safety is the product.

## Project status

**Alpha — not yet security-audited. Not for production use.**

Quorum is actively under development and open to public scrutiny precisely because a control plane with destructive verbs needs that scrutiny. Known limitations and the roadmap for closing them live in [SECURITY.md](SECURITY.md) and [docs/ROADMAP.md](docs/ROADMAP.md). Do not expose a pre-1.0 Quorum deployment to untrusted networks.

## Why this repo exists

Agentic engineering becomes viable when an AI agent's actions are:

- structured (typed proposals, not free-form text)
- reviewable (explicit policy + peer votes)
- observable (append-only event log)
- reversible (first-class rollback)
- verified (health checks after every change)

Quorum is the minimal control plane that makes those guarantees real.

## Core capabilities (today)

- FastAPI control-plane service with nine typed domain entities (Intent, Finding, Proposal, Vote, PolicyDecision, ExecutionRecord, HealthCheckResult, RollbackRecord, EventEnvelope).
- Append-only JSONL event log with sha256 hash chain; tamper-evidence verified on startup and on demand.
- Materialized in-memory state via event replay; Postgres projection as an optional derived read-model.
- YAML-based policy configuration with risk levels, environment overrides, denied action types, and per-action-type rule overrides.
- Quorum voting with configurable thresholds.
- Pluggable typed health checks (incl. `github_check_run` polling) with automatic rollback on failure.
- Operator console (`/console`) with read-only views.
- **GitHub App actuator** (Phase 4): `open_pr` / `comment_issue` / `close_pr` / `add_labels` with actuator-aware rollback and a terminal `rollback_impossible` event when a mutation cannot be undone.
- **LLM adapter** (Phase 4): Claude-backed telemetry agent runs as its own process, observes the event stream, emits structured findings + low-risk GitHub proposals through the same authenticated routes as any other caller. Per-agent `allowed_action_types` cap + prompt caching + budget-capped token usage.
- Demo incident seeder (`POST /api/v1/demo/incident`) runs the full flow end-to-end.

## What's next (phased)

See [docs/ROADMAP.md](docs/ROADMAP.md). Brief version:

1. **Phase 2** — tamper-evident event log (hash chain), typed health checks, authenticated API, locked CORS, rate limiting.
2. **Phase 3** — Dockerfile, Postgres projection, observability (structlog + OpenTelemetry + Prometheus), hardened CI with SBOM.
3. **Phase 4** — real actuators (GitHub App first), LLM agent adapter via Anthropic SDK, interactive console, human-approval workflows.
4. **Phase 5** — Fly.io deployment with canonical-log volume and managed Postgres.
5. **Phase 6** — parallel development via git worktrees per [docs/PARALLEL_DEVELOPMENT.md](docs/PARALLEL_DEVELOPMENT.md).

## Quick start

Requires Python 3.12+.

### With `uv` (recommended)

```bash
uv sync --extra dev
uv run uvicorn apps.api.app.main:app --reload --port 8080
```

### With `venv` + `pip`

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn apps.api.app.main:app --reload --port 8080
```

### Or just `make`

```bash
make install    # creates .venv and installs dev deps
make dev        # runs uvicorn
make validate   # ruff check + ruff format --check + pytest (enforces coverage floor)
```

### With Docker

```bash
# 1. Create a local .env from the template and fill in your values.
cp .env.example .env
# Edit .env: set QUORUM_API_KEYS=<agent_id>:<your_key> and optionally QUORUM_ALLOW_DEMO=true

# 2. Build and start the API container.
docker compose up --build
```

The container publishes port **8080** and mounts `./data` as a persistent volume
so the append-only event log (`data/events.jsonl`) survives container restarts.

Environment variables are loaded from `.env` (never committed — see `.env.example`
for the template). In production, inject secrets via `fly secrets set` or your
orchestrator's secret store.

Open:

- Operator console → http://127.0.0.1:8080/console
- API docs (OpenAPI) → http://127.0.0.1:8080/docs

### Seed the demo

```bash
curl -sX POST http://127.0.0.1:8080/api/v1/demo/incident | python3 -m json.tool
```

Then inspect:

```bash
curl -s http://127.0.0.1:8080/api/v1/state  | python3 -m json.tool
curl -s http://127.0.0.1:8080/api/v1/events | python3 -m json.tool
```

### Run the LLM adapter (optional)

A Claude-backed telemetry agent that watches the event stream and
emits structured findings + low-risk GitHub proposals. See
[`docs/design/llm-adapter.md`](docs/design/llm-adapter.md) for the
full design.

```bash
# 1. Seed adapter credentials
export ANTHROPIC_API_KEY=sk-ant-...
export QUORUM_API_KEYS="telemetry-llm-agent:<plaintext>"

# 2. Generate the matching argon2id hash and store it in config/agents.yaml
python -m apps.api.app.tools.bootstrap_keys generate --agent-id telemetry-llm-agent

# 3. Start Quorum in one terminal, the adapter in another
make dev                                                       # Quorum on :8080
python -m apps.llm_agent.run --agent-id telemetry-llm-agent    # adapter polls :8080
```

The adapter reads `config/agents.yaml`'s `llm:` block for model,
caps, and the system-prompt reference. Token usage is capped per-tick
and per-day with atomic JSON checkpoints under `data/llm_usage/`.
Adapter-emitted proposals are server-side capped by
`allowed_action_types` in the same config — LLM agents can only
propose `github.comment_issue` and `github.add_labels` in v1.

## Reading order for new contributors (human or AI)

1. [INIT.md](INIT.md) — shortest startup context.
2. [AGENTS.md](AGENTS.md) — repo-wide operating rules and Definition of Done.
3. [docs/REPO_MAP.md](docs/REPO_MAP.md) — where everything lives.
4. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design and mermaid diagrams.
5. [CONTRIBUTING.md](CONTRIBUTING.md) — how to propose changes.
6. [docs/PARALLEL_DEVELOPMENT.md](docs/PARALLEL_DEVELOPMENT.md) — single-thread today, worktrees later.

## Design constraints

Quorum is deliberately optimized for AI maintainability:

- Plain Python, minimal indirection.
- Explicit file layout — no clever re-exports.
- Small files with clear names.
- JSON/YAML over bespoke formats.
- Mermaid diagrams for every non-trivial flow.
- All important decisions live in markdown.

## Governance

- **License:** [Apache-2.0](LICENSE) — patent grant included.
- **Security reports:** see [SECURITY.md](SECURITY.md). Do not open public issues for vulnerabilities.
- **Contributions:** see [CONTRIBUTING.md](CONTRIBUTING.md). DCO sign-off required (`git commit -s`).
- **Code of Conduct:** [Contributor Covenant 2.1](CODE_OF_CONDUCT.md).
- **Code owners:** [.github/CODEOWNERS](.github/CODEOWNERS) protects shared-core files.

## Claude Code harness

This repo includes a batteries-included Claude Code setup for AI-driven development:

- `.claude/settings.json` — permissions allowlist, safety hooks (ruff autofix, destructive-command block, shared-core warnings), env, statusLine.
- `.mcp.json` — GitHub, Filesystem, and Sequential-thinking MCP servers.
- `.claude/agents/` — five role-scoped subagents (backend, console, security-auditor, docs, devops), all running on Opus 4.7.
- `.claude/skills/` — custom skills: `create-event-type`, `add-actuator`.
- `.claude/commands/` — slash commands: `/demo`, `/validate`, `/run-dev`, `/new-worktree`.

The intent is that a fresh Claude Code session opened in this repo can drive the product end-to-end with minimal operator friction while still honoring every safety rule in [AGENTS.md](AGENTS.md).
