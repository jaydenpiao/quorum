# Phase 6 Readiness Checkpoint - 2026-05-08

This checkpoint records the current pre-Phase-6 state after the
`v0.6.7` proof-reliability release and the first post-release hardening
PRs. It is a readiness record, not approval to start Phase 6.

Phase 6 remains closed until `scripts/check_phase6_gate.sh` prints
`phase6-gate-ready` on or after **2026-05-14**.

## Current Verdict

- Latest archived release: `v0.6.7`.
- Latest verified `main` before this checkpoint: commit
  `1e1758b77856d67a9bfe4f3753be4506eb09954f`.
- Current required gate result on 2026-05-08:
  `phase6-gate-closed: not before 2026-05-14 (today=2026-05-08)`.
- Future-date dry run with `QUORUM_PHASE6_TODAY=2026-05-14` reached
  `phase6-gate-ready` after the schema-stability, live release,
  workflow, open-PR, proof-archive, and handoff checks passed.

## Live Proof Status

Run these before any future Phase 6 switch:

```bash
QUORUM_RELEASE_TAG=v0.6.7 scripts/check_live_release.sh
QUORUM_RELEASE_TAG=v0.6.7 scripts/check_console_proof.sh
QUORUM_RELEASE_TAG=v0.6.7 scripts/check_release_proof_archive.sh
QUORUM_RELEASE_TAG=v0.6.7 scripts/check_phase6_gate.sh
```

Latest observed results:

- `live-release-ok: v0.6.7 staging=https://quorum-staging.fly.dev prod=https://quorum-prod.fly.dev repo=jaydenpiao/quorum main=main`
- `console-proof-ok: https://quorum-staging.fly.dev/console?proposal_id=proposal_bab1a4a4913d#proposals proposal=proposal_bab1a4a4913d`
- `release-proof-archive-ok: v0.6.7 proof=docs/releases/v0.6.7-proof.md`
- `phase6-gate-closed: not before 2026-05-14 (today=2026-05-08)`

## Latest Workflow Evidence

- `ci.yml`: run
  [`25562191387`](https://github.com/jaydenpiao/quorum/actions/runs/25562191387),
  success on `1e1758b77856d67a9bfe4f3753be4506eb09954f`.
- `security.yml`: run
  [`25562191332`](https://github.com/jaydenpiao/quorum/actions/runs/25562191332),
  success on `1e1758b77856d67a9bfe4f3753be4506eb09954f`.
- `image-push.yml`: run
  [`25562191390`](https://github.com/jaydenpiao/quorum/actions/runs/25562191390),
  success on `1e1758b77856d67a9bfe4f3753be4506eb09954f`.
- `live-release-monitor.yml`: latest scheduled run
  [`25560652276`](https://github.com/jaydenpiao/quorum/actions/runs/25560652276),
  success on `f932cf499137581a88bb2f4f213ed7f17e9eac12`.

The May 6 scheduled live monitor run is non-current evidence:
[`25425183614`](https://github.com/jaydenpiao/quorum/actions/runs/25425183614)
completed with failure on `f932cf499137581a88bb2f4f213ed7f17e9eac12`.
Later scheduled monitor runs and local live checks passed. PR #150
made future monitor failures more diagnosable with bounded job runtime,
labeled GitHub metadata checks, and a non-secret `$GITHUB_STEP_SUMMARY`.

## Schema-Stability Preflight

The mechanical schema-stability check is:

```bash
scripts/check_event_schema_stability.sh
```

Default anchor:

```bash
QUORUM_SCHEMA_STABILITY_ANCHOR_TAG=v0.6.3
QUORUM_SCHEMA_STABILITY_BASE_REF=HEAD
```

Current expected output:

```text
schema-stability-ok: anchor=v0.6.3 base=HEAD
```

The checker fails closed if any schema-sensitive file changed after the
anchor:

- `apps/api/app/domain/models.py`
- `apps/api/app/services/event_log.py`
- `apps/api/app/services/state_store.py`
- `apps/api/app/services/postgres_projector.py`
- `apps/api/app/db/models.py`
- `alembic/versions`
- `examples`

`scripts/check_phase6_gate.sh` runs this preflight after the calendar
gate passes and before live release, workflow, PR, and proof-archive
checks can mark Phase 6 ready.

## No-Go Triggers

- Any new event type or event payload shape change resets the 14-day
  stability clock.
- Any proposal, vote, execution, rollback, health-check, approval,
  policy-decision, or image-push read-shape change blocks Phase 6 until
  it has aged through a new stability window.
- Any reducer/projector dispatch change that alters replay semantics
  blocks Phase 6.
- Any Alembic migration or projection-shape change blocks Phase 6.
- Any example event payload change blocks Phase 6 until reviewed as a
  schema-impacting change or explicitly documented as non-impacting.
- Any live event-chain verification failure, prod health failure,
  release version drift, missing SBOM, stale proof archive, stale
  handoff/repo-map pointer, open shared-core PR, or failing latest
  `main` `ci`/`security`/`image-push` run blocks Phase 6.

## If The Gate Opens

- Re-run `QUORUM_RELEASE_TAG=v0.6.7 scripts/check_phase6_gate.sh` and
  require `phase6-gate-ready`.
- Switch to the worktree model in `docs/PARALLEL_DEVELOPMENT.md`.
- Keep Phase 6 lanes narrow until shared-core ownership is assigned.
- Continue the durable merge-autonomy rules from `AGENTS.md`: local
  validation, all 5 required checks, one concern per PR, squash-merge,
  no skipped hooks, no direct `main` push, and no force-push.
