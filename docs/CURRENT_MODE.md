# Current development mode

## Right now: single-threaded main-branch development

Through v0.5.0-alpha.1 the project has stayed single-threaded on the
main working branch. The POC vertical slice is stable; Phases 2–5 are
complete.

Stay single-thread until Phase 6's explicit gate is met (≥2 weeks of
event-schema stability per `docs/ROADMAP.md`).

That means:

- keep the repo coherent
- prefer end-to-end functionality over parallel feature branches
- make the event model, proposal model, policy model, and execution
  model stable — don't drift them speculatively
- no long-lived parallel branches
- one PR at a time; wait for all 5 required CI checks green before
  merging; pause for operator confirmation before each merge unless a
  durable instruction overrides

## Why

Parallel agent development too early creates:

- drift in schemas
- merge conflicts in shared control-plane code
- inconsistent docs
- harder debugging of event formats

For a control plane, the shared core matters more than parallel
throughput.

## When to switch

Switch to the worktree model in `docs/PARALLEL_DEVELOPMENT.md` when
all of the following are true:

- event schema has been stable for ≥2 weeks (no new event types in
  that window)
- proposal schema is stable
- execution and rollback loop is stable (both actuator families)
- CI is consistently green
- docs reflect reality
- at least one end-to-end demo path is reliable (met: the
  `/api/v1/demo/incident` seeder runs the full flow)

The Phase 4 + Phase 5 work added several event types (`rollback_impossible`,
the `human_approval_*` family) — let the schema settle before Phase 6.

## Where to work

- Feature branch off `main`: `feat/<topic>` / `docs/<topic>` /
  `chore/<topic>` / `ci/<topic>` / `fix/<topic>`.
- Squash-merge into `main`. Linear history enforced by branch
  protection.
- Force-push is blocked by a pre-tool-use hook — if a stacked PR's
  parent merges, merge `main` *into* the stacked branch (regular
  fast-forward push) rather than rebasing.
