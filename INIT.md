# Quorum initialization

Read this file first if an AI agent has just entered the repo.

## Mission

Build Quorum as a production-safe control plane for agentic engineering.

The core loop is:

1. observe system state
2. create structured findings
3. create structured proposals
4. evaluate policy
5. require quorum
6. execute safely
7. verify health
8. roll back on failure
9. write everything to the append-only log

## Immediate priorities

- keep the architecture explicit and boring
- prefer transparent state machines over clever abstractions
- prefer structured data over free-form text
- preserve append-only event logging
- keep rollback and health verification first-class
- optimize the repo for AI maintainability

## Read next

1. `AGENTS.md`
2. **`docs/SESSION_HANDOFF.md`** — where the last session left off, phase status, known gotchas, next candidates.
3. `docs/ROADMAP.md`
4. `CHANGELOG.md`
5. `docs/REPO_MAP.md`
6. `docs/ARCHITECTURE.md`
7. `docs/CURRENT_MODE.md`

## Non-negotiables

- no hidden mutation paths
- no action executes without a proposal object
- no proposal executes without policy evaluation
- no success is declared until health checks pass
- every action must be logged
- code changes should preserve LLM readability
