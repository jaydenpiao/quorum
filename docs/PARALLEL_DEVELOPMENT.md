# Parallel development model

This document describes how Quorum should evolve from one main thread of development to safe parallel development.

## Phase 1: single-threaded core development

Use one main working branch until the core is stable.

Reason:
- the event model is shared by everything
- the proposal model is shared by everything
- careless parallel work will create schema churn

## Phase 2: worktree-based parallel development

Once the core is stable, use **git worktrees**.

### Why worktrees

Worktrees are better than many local clones because they preserve:

- one source of truth for refs
- cheap branch creation
- easy cleanup
- clearer merge discipline

### Branch naming

Use:

- `agent/backend/<task>`
- `agent/ui/<task>`
- `agent/docs/<task>`
- `agent/integration/<task>`
- `agent/research/<task>`

Examples:

- `agent/backend/event-snapshot-cache`
- `agent/ui/proposal-timeline`
- `agent/integration/github-actuator`

### Worktree creation

```bash
./scripts/new_worktree.sh agent/backend/event-snapshot-cache
```

That creates:

- a branch if it does not exist
- a sibling worktree directory under `../quorum-worktrees/`

### Merge model

Use small PRs into `main`.

Required before merge:

- tests pass
- lint passes
- docs updated when behavior changes
- schema changes reviewed carefully
- no breaking change to event log without explicit migration note

### Shared-core rule

Changes to any of these files are **high coordination** changes:

- `apps/api/app/domain/models.py`
- `apps/api/app/services/state_store.py`
- `apps/api/app/services/event_log.py`
- `config/policies.yaml`

If a task touches one of those, do not run many parallel branches against them without a coordinating owner.

### Recommended parallel lanes later

Good first parallel lanes after stabilization:

1. GitHub actuator lane
2. Kubernetes actuator lane
3. Console lane
4. Policy-engine lane
5. Auth / operator approval lane

### Review checklist before merge

- is the proposal schema still coherent?
- is the event sequence still understandable?
- did any new event type get reducer support?
- did docs and examples change with the code?
- could another agent understand the patch quickly?

## GitHub settings to use later

Set these on the repo when created:

- public repository
- protected `main`
- squash merge enabled
- required CI on PRs
- no direct pushes to `main` after initial bootstrap
- optional CODEOWNERS for shared-core files
