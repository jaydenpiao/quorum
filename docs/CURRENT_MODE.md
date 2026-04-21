# Current development mode

## Default mode right now

Use **one main development thread** until the vertical slice is stable.

That means:

- keep the repo coherent
- prefer end-to-end functionality over parallel feature branches
- make the event model, proposal model, policy model, and execution model stable first
- do not prematurely optimize for many simultaneous contributors

## Why

Parallel agent development too early creates:

- drift in schemas
- merge conflicts in shared control-plane code
- inconsistent docs
- harder debugging of event formats

For a control plane, the shared core matters more than parallel throughput in the first phase.

## What counts as stable enough to switch

Switch to multi-worktree development after these are true:

- event schema is stable
- proposal schema is stable
- execution and rollback loop works
- CI is green
- docs reflect reality
- at least one end-to-end demo path is reliable

After that, follow `docs/PARALLEL_DEVELOPMENT.md`.
