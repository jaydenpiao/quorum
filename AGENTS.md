# AGENTS.md — repo-wide instructions for AI coding agents

This file defines how to work safely in the Quorum repository.

## Product intent

Quorum is **not** a generic chat agent.
It is a control plane for safe, auditable, policy-gated, quorum-based execution by AI agents operating on code and infrastructure.

All work should strengthen one or more of these properties:

- auditability
- policy enforcement
- consensus before mutation
- rollback readiness
- post-change verification
- operator visibility
- extensibility across actuator types

## What matters most

1. Keep the core state machine simple.
2. Keep domain objects explicit.
3. Preserve event sourcing and replayability.
4. Treat safety primitives as product primitives, not wrappers.
5. Prefer small files with clear names.
6. Favor markdown docs when making architectural changes.
7. When changing behavior, update docs and examples in the same patch.

## Current development mode

For now, default to **single-threaded development on the main working branch** until the POC is stable.

That means:

- avoid creating parallel branches unless a task explicitly calls for it
- do not introduce speculative abstractions for future concurrency
- prioritize a coherent vertical slice over surface area

When the demo is stable, switch to the worktree model in `docs/PARALLEL_DEVELOPMENT.md`.

## Required reading by area

### Whole repo
- `INIT.md`
- `docs/REPO_MAP.md`
- `docs/ARCHITECTURE.md`

### Backend / control plane
- `apps/api/AGENTS.md`
- `config/policies.yaml`
- `examples/demo_incident.json`

### Console
- `apps/console/AGENTS.md`

### Contracts
- `packages are represented by config + examples in this POC`
- prefer JSON examples and schema-like constraints in markdown until a dedicated schema package is added

## Coding rules

- Use Python 3.12+ features conservatively.
- Keep functions short and obvious.
- Add docstrings only where they clarify behavior.
- Avoid metaprogramming.
- Avoid hidden global state except for explicit app bootstrap.
- Keep the event log format stable.
- When adding a new event type, update:
  - reducer logic
  - examples
  - docs
  - tests

## Domain model rules

The minimum core entities are:

- Intent
- Finding
- Proposal
- Vote
- PolicyDecision
- ExecutionRecord
- HealthCheckResult
- RollbackRecord
- EventEnvelope

Do not bypass them with ad hoc dicts in business logic.

## Logging rules

Every state transition must produce an event.

Prefer new event types over ambiguous overloaded ones.

Bad:
- `status_changed`

Good:
- `proposal_created`
- `proposal_voted`
- `proposal_approved`
- `execution_started`
- `health_check_completed`
- `rollback_started`
- `rollback_completed`

## Safety rules

Do not add any path that allows:

- direct execution without a proposal
- silent policy bypass
- mutation without logging
- declaring success before health verification

## Docs rules

When changing architecture or workflow:

- update `docs/ARCHITECTURE.md`
- update `docs/REPO_MAP.md` if file layout changes
- update `docs/PARALLEL_DEVELOPMENT.md` if git workflow changes

## Git workflow rules

### Right now
Prefer:
- one main working branch
- small commits
- fast feedback
- local validation before commit

### Later
Use:
- one worktree per task
- branch naming: `agent/<role>/<task>`
- squash merges into `main`
- required CI + merge validation

See `docs/PARALLEL_DEVELOPMENT.md`.

## Definition of done for changes

A change is complete only when:

- code works
- docs match the code
- example payloads remain valid
- tests cover the changed path
- the change is understandable without external context

## If unsure

Choose the more explicit design.
