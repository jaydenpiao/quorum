# Phase 6 Gate Checklist

Phase 6 stays blocked until the event schema and core payload shapes
have been stable for at least two weeks. The earliest gate-open date is
**2026-05-14 UTC**, assuming no event-schema or event-payload changes
after the v0.6.3 LLM vote metadata work.

Run the read-only preflight before switching from single-threaded
`main` work to the worktree model in
`docs/PARALLEL_DEVELOPMENT.md`:

```bash
QUORUM_RELEASE_TAG=v0.6.8 scripts/check_phase6_gate.sh
```

Before the calendar gate opens it must fail closed with
`phase6-gate-closed`. On or after the not-before date it must print
`phase6-gate-ready` before any Phase 6 worktree is created. The script
uses UTC dates; use `QUORUM_PHASE6_TODAY=YYYY-MM-DD` only for explicit
dry runs.

When it opens, start from `docs/design/phase-6-entry-plan.md` before
creating worktrees.

The latest checkpoint is
`docs/design/phase-6-readiness-checkpoint.md`. It records the current
`v0.6.7` live proof status, latest main workflow runs, the non-current
May 6 monitor failure, and the schema-stability preflight evidence.

## Open Criteria

- Event schema has been stable for at least 14 days: no new event
  types, no event payload field changes, and no reducer/projector
  dispatch changes that alter replay semantics.
- The mechanical schema-stability preflight passes after the calendar
  gate opens:

```bash
QUORUM_SCHEMA_STABILITY_ANCHOR_TAG=v0.6.3 scripts/check_event_schema_stability.sh
```

- Core proposal, vote, execution, rollback, health-check, approval,
  policy-decision, and image-push read shapes are stable.
- Latest `main` has all 5 required checks green: `lint + format +
  test`, `gitleaks`, `pip-audit`, `docker build`, and `mypy`.
- Latest `live-release-monitor.yml`, `ci.yml`, `security.yml`, and
  `image-push.yml` runs are completed successfully for the current
  `main` head. If the live monitor is stale, refresh it with
  `gh workflow run live-release-monitor.yml --repo jaydenpiao/quorum --ref main -f release_tag=<latest>`.
- `QUORUM_RELEASE_TAG=<latest> scripts/check_live_release.sh` passes
  against staging/prod, including release metadata, SBOM, prod health,
  event-chain verification, and latest `main` CI/security/image-push
  status.
- `QUORUM_RELEASE_TAG=<latest> scripts/check_phase6_gate.sh` prints
  `phase6-gate-ready`. This script runs
  `scripts/check_event_schema_stability.sh` after the calendar gate and
  before live release / workflow checks.
- Durable release proof exists under `docs/releases/` for the latest
  deployed release, and `docs/SESSION_HANDOFF.md` points to it.
- No unmerged PR is modifying shared-core files listed in
  `docs/PARALLEL_DEVELOPMENT.md`.

## No-Go Or Reset Triggers

- Any new event type, event payload shape change, proposal/vote schema
  change, projection migration that changes replay/read semantics, or
  reducer/projector dispatch change resets the 14-day clock.
- Any schema-sensitive change detected by
  `scripts/check_event_schema_stability.sh` blocks Phase 6 until the
  change is reviewed as non-impacting or the stability anchor/date is
  intentionally reset.
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
- Read `docs/design/phase-6-entry-plan.md` and choose one of its safe
  first lanes.
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
