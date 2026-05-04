# Phase 6 Gate Checklist

Phase 6 stays blocked until the event schema and core payload shapes
have been stable for at least two weeks. The earliest gate-open date is
**2026-05-14**, assuming no event-schema or event-payload changes after
the v0.6.3 LLM vote metadata work.

Run the read-only preflight before switching from single-threaded
`main` work to the worktree model in
`docs/PARALLEL_DEVELOPMENT.md`:

```bash
QUORUM_RELEASE_TAG=v0.6.6 scripts/check_phase6_gate.sh
```

Before the calendar gate opens it must fail closed with
`phase6-gate-closed`. On or after the not-before date it must print
`phase6-gate-ready` before any Phase 6 worktree is created.

## Open Criteria

- Event schema has been stable for at least 14 days: no new event
  types, no event payload field changes, and no reducer/projector
  dispatch changes that alter replay semantics.
- Core proposal, vote, execution, rollback, health-check, approval,
  policy-decision, and image-push read shapes are stable.
- Latest `main` has all 5 required checks green: `lint + format +
  test`, `gitleaks`, `pip-audit`, `docker build`, and `mypy`.
- `QUORUM_RELEASE_TAG=<latest> scripts/check_live_release.sh` passes
  against staging/prod, including release metadata, SBOM, prod health,
  event-chain verification, and latest `main` CI/security/image-push
  status.
- `QUORUM_RELEASE_TAG=<latest> scripts/check_phase6_gate.sh` prints
  `phase6-gate-ready`.
- Durable release proof exists under `docs/releases/` for the latest
  deployed release, and `docs/SESSION_HANDOFF.md` points to it.
- No unmerged PR is modifying shared-core files listed in
  `docs/PARALLEL_DEVELOPMENT.md`.

## No-Go Or Reset Triggers

- Any new event type, event payload shape change, proposal/vote schema
  change, projection migration that changes replay/read semantics, or
  reducer/projector dispatch change resets the 14-day clock.
- Any live event-chain verification failure blocks Phase 6 until root
  cause is fixed and documented.
- Any failing required `main` check blocks Phase 6 until the failure is
  fixed and a clean `main` run is recorded.
- Any stale release proof, stale handoff, or missing repo-map entry
  blocks Phase 6 until docs match deployed reality.

## If The Gate Opens

- Keep the durable merge-autonomy rules from `AGENTS.md`: green PRs may
  merge autonomously, but only after local validation and all 5
  required checks pass.
- Switch branch creation to `scripts/new_worktree.sh` and follow
  `docs/PARALLEL_DEVELOPMENT.md`.
- Start with narrow lanes that avoid shared-core churn: console
  read-only polish, GitHub actuator depth, policy documentation, or
  operator proof tooling.
- Assign one coordinating owner before any lane touches domain models,
  event log/reducer/projector code, or policy semantics.

## If The Gate Is Still Closed

- Stay single-threaded on `main`.
- Ship only small v0.6.x hardening PRs that improve operator trust
  without changing event types, mutation routes, proposal fields,
  projection tables, actuators, or `fly.deploy` LLM voting.
- Re-run this checklist after the next meaningful release or after any
  schema-reset trigger has aged for 14 days.
