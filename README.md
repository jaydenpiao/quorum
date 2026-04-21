# Quorum

Quorum is a production-safe control plane for AI agents that act on real code and infrastructure.

This repository is a **POC scaffold** designed to be easy for AI coding agents to read, modify, and extend.
It treats agent actions as distributed-systems operations:

- specialized agents observe different slices of system state
- agents produce structured findings and proposals
- policy gates proposals before mutation
- a quorum must agree before execution
- every step is written to an append-only event log
- post-change health checks determine success
- rollback is automatic when verification fails

## Why this repo exists

The goal is to make agentic engineering safe enough for:

- incident investigation
- rollback coordination
- deploy safety checks
- controlled infra changes
- later, autonomous low-risk execution

This POC does **not** attempt to solve all of that at once.
It gives a clean base that an AI coding agent can immediately extend.

## Current POC capabilities

- FastAPI control-plane service
- append-only JSONL execution log
- materialized in-memory state via event replay
- structured models for intents, findings, proposals, votes, executions, and rollbacks
- YAML-based policy configuration
- quorum evaluation
- pluggable health checks
- automatic rollback when health checks fail
- static operator console
- demo incident seeding endpoint
- branch / worktree / GitHub automation scripts
- agent initialization markdown in multiple places

## Repo map

Read these files first:

1. `INIT.md` — shortest startup context for any agent
2. `AGENTS.md` — full repo-wide operating rules
3. `docs/REPO_MAP.md` — where everything lives
4. `docs/ARCHITECTURE.md` — system design and diagrams
5. `docs/PARALLEL_DEVELOPMENT.md` — migration path from single-thread to multi-worktree development

## Quick start

### Local run

```bash
cd Quorum
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn apps.api.app.main:app --reload --port 8080
```

Open:

- API docs: `http://localhost:8080/docs`
- Operator console: `http://localhost:8080/console`

### Seed the demo incident

```bash
curl -X POST http://localhost:8080/api/v1/demo/incident
```

Then inspect:

```bash
curl http://localhost:8080/api/v1/state | jq
curl http://localhost:8080/api/v1/events | jq
```

## POC walkthrough

### Step 1
Create an intent such as:

- investigate elevated p99 latency
- propose rollback after a bad deploy
- review a low-risk config change

### Step 2
Specialized agents add findings.

Examples:

- telemetry agent reports error-rate regression
- deploy agent points to a new release
- code agent references a suspect diff

### Step 3
One or more agents create a structured proposal.

A proposal includes:

- action type
- target
- risk
- rationale
- rollback steps
- health checks
- evidence references

### Step 4
Agents vote on the proposal.

The policy engine computes whether:

- the action is allowed
- human approval is required
- the number of votes needed changes by risk and environment

### Step 5
The executor runs the proposal.

The executor:

- writes an execution-started event
- simulates the action
- runs health checks
- records success or failure
- triggers rollback on failed verification

## Design constraints

This repo is deliberately optimized for AI modification:

- plain Python, minimal indirection
- explicit file layout
- simple JSON/YAML formats
- human-readable mermaid diagrams
- no hidden build system magic
- all important decisions documented in markdown

## GitHub automation

This environment can manage files, branches, commits, and PRs **inside an existing repository**,
but it cannot directly create a new GitHub repository from here.

To keep the workflow near-fully automated, this repo includes:

- `scripts/bootstrap_local_repo.sh`
- `scripts/create_public_github_repo.sh`
- `scripts/new_worktree.sh`
- `scripts/validate_merge.sh`

The intended path is:

```bash
./scripts/bootstrap_local_repo.sh
./scripts/create_public_github_repo.sh Quorum
```

That second script uses either:

- `gh repo create`
- or the GitHub REST API with `GITHUB_TOKEN`

## Development mode

**Right now:** develop on one main thread until the core POC stabilizes.

**Later:** move to parallel worktrees with one task branch per agent or task family.

See `docs/PARALLEL_DEVELOPMENT.md`.

## Suggested next milestones

1. replace demo agents with real model adapters
2. add actuator plugins for GitHub, Kubernetes, Terraform, and feature flags
3. persist state in SQLite/Postgres instead of pure replay-only memory
4. add approval workflows and authenticated operators
5. add real policy DSL and richer risk scoring
6. add PR-based merge orchestration and deployment verification
