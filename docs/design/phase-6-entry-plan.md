# Phase 6 Entry Plan

Phase 6 may start only after:

```bash
QUORUM_RELEASE_TAG=v0.6.8 scripts/check_phase6_gate.sh
```

prints `phase6-gate-ready` on or after **2026-05-14 UTC**. Until then,
stay single-threaded on `main` and keep shipping only v0.6.x hardening.

When the gate opens, switch to the worktree model in
`docs/PARALLEL_DEVELOPMENT.md` and keep the first work small,
readable, and independently reviewable.

## First Safe Lanes

- **Read-only console polish:** improve filtering, empty states,
  visual proof summaries, and proposal inspector clarity without changing API payloads or mutation behavior.
- **GitHub actuator hardening:** add focused coverage and reliability
  fixes for existing `github.*` actions without new event types or
  proposal fields.
- **Policy and proof documentation:** tighten runbooks, threat-model
  notes, screenshots, and acceptance checklists without changing
  runtime behavior.
- **Operator proof tooling:** improve non-mutating proof capture,
  archive validation, browser smoke helpers, and diagnostics using
  existing read-only APIs.

## Blocked Until Coordinated

Do not start shared-core work in parallel until one coordinating owner
is assigned and writes the owner decision into the active PR:

- domain models or event payload shapes
- event-log append/verification semantics
- reducer or projector dispatch
- Alembic migrations or projection table shape
- proposal, vote, execution, health-check, rollback, approval, policy,
  or image-push read shapes
- new actuators, new event types, new mutation routes, or `fly.deploy` LLM voting

## Entry Procedure

1. Run `QUORUM_RELEASE_TAG=v0.6.8 scripts/check_phase6_gate.sh` and
   require `phase6-gate-ready`.
2. Confirm `git status --short --branch` is clean except ignored local
   artifacts and `gh pr list` has no unexpected open shared-core PR.
3. Create each lane with `scripts/new_worktree.sh agent/<lane>/<task>`.
4. Keep each PR one concern, with local validation and all five
   required GitHub checks green before squash-merge.
5. If any lane discovers it must touch shared core, stop that lane and
   assign a coordinating owner before continuing.
