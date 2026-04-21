---
description: Create a worktree for parallel agent work (Phase 6+ only — gate first)
argument-hint: <branch-name e.g. agent/backend/event-hash-chain>
---

Wraps `scripts/new_worktree.sh` with a readiness check.

**Gate:** This command is for Phase 6. Do not run unless the stability criteria from `docs/PARALLEL_DEVELOPMENT.md` are met (event schema stable ≥2 weeks, CI green on main, shared-core not in flux). If the project is still in Phase 0–3, work on the main branch instead.

Branch: `$1` (must follow `agent/<role>/<task>` convention — `role` ∈ {backend, ui, docs, integration, research}).

```bash
set -e
if [ -z "$1" ]; then
  echo "Usage: /new-worktree agent/<role>/<task>"
  exit 1
fi
if ! echo "$1" | grep -qE '^agent/(backend|ui|docs|integration|research)/.+'; then
  echo "Branch name must match 'agent/<role>/<task>'. See docs/PARALLEL_DEVELOPMENT.md."
  exit 1
fi
bash scripts/new_worktree.sh "$1"
echo
echo "Worktree ready. Next steps:"
echo "  1. cd ../quorum-worktrees/${1//\//-}"
echo "  2. uv sync --extra dev  (once uv is in place — Phase 1)"
echo "  3. claude  (launches a fresh session in the worktree)"
```
