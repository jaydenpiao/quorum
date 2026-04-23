# Quorum initialization

Read this file first if an AI agent has just entered the repo. Applies
to any agent that honors `AGENTS.md` (Codex, Claude Code, Cursor,
Windsurf, etc.).

## Mission

Build Quorum as a production-safe control plane for agentic engineering.

The core loop is:

1. observe system state
2. create structured findings
3. create structured proposals
4. evaluate policy
5. require quorum
6. execute safely (through a typed actuator — today: `github.*`, `fly.*`)
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

## Read next, in order

1. `AGENTS.md` — repo-wide rules (binding)
2. **`docs/SESSION_HANDOFF.md`** — current phase status, live gotchas
   list, next-session candidates. Most current state of the project.
3. `docs/ROADMAP.md` — ✅/⏳/⬜ phase markers
4. `CHANGELOG.md` — versioned feature list
5. `docs/REPO_MAP.md` — where every file lives
6. `docs/ARCHITECTURE.md` — system design + diagrams
7. `docs/CURRENT_MODE.md` — development mode (single-thread vs
   worktrees)

Area-specific reading is listed in `AGENTS.md` §"Required reading by
area".

## Non-negotiables

- no hidden mutation paths
- no action executes without a proposal object
- no proposal executes without policy evaluation
- no success is declared until health checks pass
- every action must be logged (via the executor, not the actuator)
- code changes should preserve LLM readability
- DCO sign-off on every commit (`git commit -s`)
- all 5 required CI checks must pass before merging to `main`
