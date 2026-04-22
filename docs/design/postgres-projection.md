# Design: Postgres as a Derived Read-Model of the Event Log

**Status:** proposed
**Branch:** `agent/docs/postgres-design`
**Relevant roadmap entry:** `docs/ROADMAP.md` — Phase 3 tail: "Postgres projection (Phase 3 capstone)"

---

## 1. Context and Goal

The JSONL event log at `apps/api/app/services/event_log.py` is the canonical source of truth for all state in Quorum.
The in-process state store (`apps/api/app/services/state_store.py`) replays that log on startup and answers current-state queries efficiently for a small log.
As the log grows, two classes of queries become impractical to serve from replay alone:

- History filtering: "show me all proposals for agent X over the last 30 days"
- Cross-entity joins: "find every rollback triggered by a high-risk proposal in environment prod"
- Aggregate counts and time-range scans over `created_at`

This design adds Postgres as a **derived read-model** — a projection populated by processing the same events the JSONL already contains.
Postgres never originates state.
Postgres content is always fully reconstructible by replaying the JSONL from position zero.

**JSONL stays authoritative.**
If Postgres and the JSONL ever disagree, the JSONL wins.
Reconciliation always flows JSONL → Postgres, never the reverse.

---

## 2. Non-Goals

- Replace the JSONL event log. The log remains the write path and the backup.
- Become the OLTP store. No mutations originate in Postgres.
- Hold secrets. API keys, argon2id hashes, and agent credentials stay in `config/agents.yaml` and env vars.
- Serve multi-tenant data. This design is single-tenant.
- Provide read-after-write consistency through Postgres. A write that succeeds via `EventLog.append` may not be visible in Postgres until the projector processes it asynchronously. Callers that need immediate read-after-write must use the in-process `StateStore`, not the Postgres query layer.
- Provide retention or compliance guarantees. Neon's managed backups cover the projection; the JSONL is the authoritative backup.

---

## 3. Schema

### Design decisions

**Primary keys** use the existing domain IDs from `apps/api/app/domain/models.py`.
All IDs are generated via `new_id(prefix)` which produces strings like `intent_<12-hex>`, `proposal_<12-hex>`, `exec_<12-hex>`, etc.
No auto-increment columns.
This means rows are idempotent on re-projection: `INSERT ... ON CONFLICT (id) DO UPDATE` replaces a row with its current projected state.

**JSONB columns** hold fields that are rarely filtered — `evidence_refs`, `rollback_steps`, `health_checks`, `payload` payloads for executions.
Frequently-filtered fields (`agent_id`, `intent_id`, `status`, `created_at`, `environment`) are native columns.

**Foreign keys** are soft.
The projector may apply events out of strict creation order during reconciliation (e.g., a `finding_created` event before the corresponding `intent_id` row is committed).
Hard FK constraints would cause reconciliation failures.
Referential integrity is asserted by the reconciliation job, not enforced by the DB.

**Indexes** cover the three most common filter axes: `agent_id`, `intent_id`, and `created_at`.
Additional indexes can be added in later migrations without schema-breaking changes.

### Tables (column outlines — not full DDL)

#### `intents`

| column | type | notes |
|---|---|---|
| `id` | `text` PK | `intent_<12-hex>` |
| `title` | `text` | |
| `description` | `text` | |
| `environment` | `text` | indexed |
| `requested_by` | `text` | indexed (`agent_id` axis) |
| `created_at` | `timestamptz` | indexed |

#### `findings`

| column | type | notes |
|---|---|---|
| `id` | `text` PK | `finding_<12-hex>` |
| `intent_id` | `text` | soft FK → `intents.id`; indexed |
| `agent_id` | `text` | indexed |
| `summary` | `text` | |
| `confidence` | `float` | |
| `evidence_refs` | `jsonb` | list of strings |
| `created_at` | `timestamptz` | indexed |

#### `proposals`

| column | type | notes |
|---|---|---|
| `id` | `text` PK | `proposal_<12-hex>` |
| `intent_id` | `text` | soft FK; indexed |
| `agent_id` | `text` | indexed |
| `title` | `text` | |
| `action_type` | `text` | |
| `target` | `text` | |
| `environment` | `text` | indexed |
| `risk` | `text` | enum: `low/medium/high/critical` |
| `status` | `text` | enum: `pending/approved/blocked/executed/failed/rolled_back` |
| `rationale` | `text` | |
| `payload` | `jsonb` | holds `evidence_refs`, `rollback_steps`, `health_checks` |
| `created_at` | `timestamptz` | indexed |

#### `votes`

| column | type | notes |
|---|---|---|
| `id` | `text` PK | `vote_<12-hex>` |
| `proposal_id` | `text` | soft FK; indexed |
| `agent_id` | `text` | indexed |
| `decision` | `text` | enum: `approve/reject` |
| `reason` | `text` | |
| `created_at` | `timestamptz` | indexed |

#### `policy_decisions`

| column | type | notes |
|---|---|---|
| `proposal_id` | `text` PK | 1:1 with proposal |
| `allowed` | `boolean` | |
| `requires_human` | `boolean` | |
| `votes_required` | `integer` | |
| `reasons` | `jsonb` | list of strings |
| `created_at` | `timestamptz` | indexed |

#### `executions`

| column | type | notes |
|---|---|---|
| `id` | `text` PK | `exec_<12-hex>` |
| `proposal_id` | `text` | soft FK; indexed |
| `actor_id` | `text` | indexed |
| `status` | `text` | enum: `started/succeeded/failed/rolled_back` |
| `detail` | `text` | |
| `health_checks` | `jsonb` | list of `HealthCheckResult` objects |
| `created_at` | `timestamptz` | indexed |

#### `health_check_results`

Stored inline in `executions.health_checks` JSONB.
A separate table is not needed until query patterns require filtering individual check outcomes.
If that becomes necessary, extract to a child table in a later migration.

#### `rollbacks`

| column | type | notes |
|---|---|---|
| `id` | `text` PK | `rollback_<12-hex>` |
| `proposal_id` | `text` | soft FK; indexed |
| `actor_id` | `text` | indexed |
| `steps` | `jsonb` | list of strings |
| `status` | `text` | `started` or `completed` |
| `created_at` | `timestamptz` | indexed |

#### `events_projected`

Tracks projector progress through the JSONL.
One row per log file (keyed by path).

| column | type | notes |
|---|---|---|
| `log_path` | `text` PK | absolute or relative path to the JSONL file |
| `last_event_id` | `text` | `evt_<12-hex>` of the last successfully applied event |
| `last_event_hash` | `text` | sha256 hex of that event (from `EventEnvelope.hash`) |
| `applied_count` | `bigint` | running total for observability |
| `updated_at` | `timestamptz` | |

The projector reads `last_event_id` on startup to resume from the correct position.
After each batch of events is applied, it updates this row atomically within the same transaction.

---

## 4. Projector Service

### Location

New file: `apps/api/app/services/projector.py`

### Protocol

```python
class Projector(Protocol):
    async def apply(self, event: EventEnvelope) -> None: ...
    async def reconcile_from(
        self, log_path: str, start_id: str | None = None
    ) -> int: ...
```

`apply` processes a single `EventEnvelope` and writes the resulting row(s) to Postgres.
`reconcile_from` reads the JSONL from `log_path`, optionally starting after `start_id`, applies each event in order, and returns the number of events processed.

### Implementations

**`NoOpProjector`** — the default.
`apply` and `reconcile_from` are no-ops that return immediately.
Used in all tests that do not opt in to Postgres, and in dev when `DATABASE_URL` is unset.
Zero dependencies beyond the protocol.

**`PostgresProjector`** — the production implementation.
Uses SQLAlchemy 2.0 async engine with `asyncpg` as the driver.
Each `apply` call runs in a transaction:
1. Upsert the entity row (using `INSERT ... ON CONFLICT (id) DO UPDATE`).
2. Update `events_projected` to record `last_event_id` and `last_event_hash`.

### Call site

`EventLog.append` in `apps/api/app/services/event_log.py` calls the projector after the JSONL `fsync` succeeds.

```python
stored_event = event_log.append(event)
# projector.apply is fire-and-forget relative to the HTTP response;
# failure logs a warning and increments a counter — it does NOT revert the JSONL write.
await projector.apply(stored_event)
```

A projector failure:
- Logs a structured warning at `WARNING` level via `structlog`.
- Increments a Prometheus counter: `quorum_projector_failures_total` with label `event_type`.
- Does **not** raise to the caller.
- Does **not** revert or invalidate the JSONL write.

The projection is eventually consistent.
HTTP responses to the caller reflect the JSONL write, not the Postgres write.

### Dependency injection

`projector` is wired into `app.state` at startup in `apps/api/app/main.py`, the same pattern used for `event_log`, `state_store`, and `executor`.
If `DATABASE_URL` is absent or empty, `main.py` assigns a `NoOpProjector`.
If `DATABASE_URL` is present, it creates a `PostgresProjector` with an async engine.

---

## 5. Reconciliation

### Purpose

Reconciliation re-reads the JSONL from a given position and re-applies every event to Postgres.
It corrects drift caused by projector failures, restarts, or schema migrations.

### How it works

```
read JSONL[start_id:] → for each event: upsert entity rows → update events_projected
```

Reconciliation is idempotent.
Running it twice produces the same result.
It never reads from Postgres to decide what to write — it only reads from the JSONL.

### Trigger points

Three triggers:

1. **Startup catch-up.** When `PostgresProjector` initializes, it reads `events_projected.last_event_id`, then replays all JSONL events that follow that ID. This closes the gap from any crash or restart.

2. **Scheduled background job.** A periodic task (interval configurable via env var, default 5 minutes) runs `reconcile_from(log_path, start_id=last_event_id)`. This closes gaps from apply failures during normal operation. The scheduler is a `asyncio` background task registered on FastAPI's `lifespan` event.

3. **Admin endpoint.** `POST /api/v1/admin/reconcile` (auth-required, not public) triggers a full reconciliation from position zero. Used after migrations, disaster recovery, or manual diagnosis.

### What reconciliation reports

After each run, reconciliation emits a structured log event with:
- `events_processed`: count of events replayed
- `duration_ms`: wall-clock time
- `start_id`: where replay began (`null` means from genesis)
- `log_path`: which JSONL file was read

A Prometheus counter `quorum_reconcile_events_total` is incremented by `events_processed` on each run.

### What reconciliation does NOT do

- It does not edit the JSONL.
- It does not delete Postgres rows that have no corresponding JSONL event (orphan rows, if any, are a sign of a projector bug and are logged but left in place for manual inspection).
- It does not update `EventEnvelope.hash` or `EventEnvelope.prev_hash`.
- It does not expose a write API.

---

## 6. Migrations

### Tooling

Alembic manages schema versions.
New files introduced by this feature:

- `alembic/env.py` — async-aware environment that reads `DATABASE_URL` from the environment
- `alembic.ini` — points to the `alembic/versions/` directory
- `alembic/versions/0001_initial.py` — creates all tables listed in Section 3

### Policy

Migrations are **forward-only**.
Alembic `downgrade` scripts are written for safety but not run automatically.

Destructive changes (dropping a column, renaming a column, changing a column type) follow a staged path across at least three releases:

1. Add the new column (nullable or with a default). Deploy.
2. Backfill the new column from the old column. Deploy.
3. Switch all reads and writes to the new column. Deploy.
4. Drop the old column. Deploy.

No single migration may both add and drop a column in the same release.

Migrations run automatically on process startup in production (Alembic `upgrade head` called from `main.py` lifespan if `DATABASE_URL` is set).
In dev without `DATABASE_URL`, migrations are skipped.

---

## 7. Dev and Prod Topology

### Dev

`docker-compose.yml` currently defines a single `api` service.
Extend it by adding a `postgres` service:

```yaml
postgres:
  image: postgres:16-alpine
  environment:
    POSTGRES_DB: quorum
    POSTGRES_USER: quorum
    POSTGRES_PASSWORD: quorum_dev
  ports:
    - "5432:5432"
  volumes:
    - postgres_data:/var/lib/postgresql/data
```

Add `postgres_data` to the top-level `volumes:` block.
Add `DATABASE_URL` to `.env.example`:

```
DATABASE_URL=postgresql+asyncpg://quorum:quorum_dev@localhost:5432/quorum
```

If `DATABASE_URL` is absent or empty, the API starts with `NoOpProjector` and behaves identically to today.

### Prod

Use **Neon** (managed serverless Postgres, Apache-2.0 core, branchable for staging/prod isolation).
Neon fits this workload because:
- Serverless autoscaling matches the low-volume POC traffic pattern.
- Database branching lets the staging Fly.io deployment use a branch of the prod schema without a separate instance.
- Point-in-time recovery covers the projection (the JSONL is the real backup; Postgres can always be rebuilt).

Connection pooling: use SQLAlchemy's built-in `QueuePool` with `pool_size=5` and `max_overflow=10`.
This is sufficient for the current single-process deployment.
Revisit with PgBouncer in transaction mode if connection count becomes a bottleneck at scale.

`DATABASE_URL` in prod is set via Fly.io secrets (`fly secrets set DATABASE_URL=...`).
The value uses the `postgresql+asyncpg://` scheme and includes Neon's SSL requirement (`?ssl=require`).

### Backups

Neon's point-in-time recovery is sufficient for the derived projection.
The JSONL file on the Fly Volume is the authoritative backup.
If Postgres is lost entirely, run `POST /api/v1/admin/reconcile` after restoring or creating a fresh Neon database — the projector will replay the full JSONL.

---

## 8. Query Layer

### New endpoints

A new read-only query router is added, backed by Postgres, following the same auth policy as existing read endpoints (public, no bearer token required).

Proposed endpoints:

| endpoint | description |
|---|---|
| `GET /api/v1/query/intents` | filter by `requested_by`, `environment`, `created_after`, `created_before` |
| `GET /api/v1/query/proposals` | filter by `agent_id`, `intent_id`, `status`, `risk`, `environment`, `created_after` |
| `GET /api/v1/query/votes` | filter by `proposal_id`, `agent_id`, `decision` |
| `GET /api/v1/query/executions` | filter by `proposal_id`, `actor_id`, `status`, `created_after` |

All filters are optional query parameters.
Pagination via `limit` (default 50, max 200) and `offset`.

### Constraints

- These endpoints are **read-only**. They do not accept POST, PATCH, or DELETE.
- They fall back gracefully: if `DATABASE_URL` is unset and projector is `NoOpProjector`, these endpoints return `503 Service Unavailable` with a body `{"detail": "postgres projection not configured"}`.
- They do not replace `GET /api/v1/state` or `GET /api/v1/events`, which remain backed by the in-process `StateStore` and `EventLog`.
- The auth-free contract matches existing read endpoints. See `docs/ARCHITECTURE.md` — "Public (no auth)".

### No direct Postgres writes

No route writes directly to Postgres.
All mutations flow through `EventLog.append`, which triggers the projector.
This invariant must be preserved by any future agent adding routes.

---

## 9. Test Strategy

### Tier 1: Unit tests

Target: `apps/api/app/services/projector.py`

Use a stub `AsyncSession` backed by an in-memory dict.
Test that:
- `apply(event)` for each event type produces the correct upsert arguments.
- A projector failure does not raise — it logs and increments the counter.
- `NoOpProjector.apply` and `NoOpProjector.reconcile_from` complete without error.

No real database connection required.
These tests run in CI unconditionally.

### Tier 2: Integration tests

Target: full `PostgresProjector` against a real Postgres container.

Use `pytest-docker` (or a manually started `docker-compose up postgres` in CI) to provide a live Postgres instance.
Mark these tests with `@pytest.mark.integration`.

CI runs them behind an opt-in flag (`make test-integration` or a separate CI job) until the projector is stable.
Once stable, promote to the default CI gate.

Test coverage:
- Full round-trip: append event → projector applies → query row in Postgres equals event payload.
- Startup catch-up: simulate a gap by writing 10 events directly to JSONL (bypassing the projector), then initialize `PostgresProjector` and confirm it reconciles all 10.
- Concurrent appends: append 50 events in a loop; confirm `events_projected.applied_count` equals 50.

### Tier 3: Reconciliation tests

Use synthetic JSONL fixtures.

1. Build a fixture file: genesis `intent_created` event + N random envelopes covering all event types.
2. Project the fixture using `PostgresProjector` (or a dict-backed stub).
3. Wipe the Postgres projection tables (or the dict).
4. Run `reconcile_from(log_path, start_id=None)` from scratch.
5. Assert that the resulting rows equal the rows from step 2.

These tests validate idempotency and completeness.
They run in CI as integration tests (same `pytest.mark.integration` marker).

---

## 10. Rollout Plan

### PR A — Scaffold (zero new behavior)

- Add `Projector` Protocol and `NoOpProjector` to `apps/api/app/services/projector.py`.
- Wire `projector` into `app.state` in `apps/api/app/main.py`.
- Add `DATABASE_URL` env var to `.env.example` and `docker-compose.yml` Postgres service stub.
- Call `await projector.apply(stored_event)` in `EventLog.append` — at this point `NoOpProjector` is always used; behavior is unchanged.
- Add unit tests for `NoOpProjector`.
- No Alembic, no real DB, no new endpoints.

**Review focus:** call-site placement in `EventLog.append`, error isolation (failure must not propagate), Protocol definition.

### PR B — PostgresProjector + Alembic + Intent projection end-to-end

- Add `alembic/`, `alembic.ini`, `alembic/env.py`.
- Add `alembic/versions/0001_initial.py` with schema for all tables (Section 3).
- Implement `PostgresProjector` handling `intent_created` only.
- Add `pytest.mark.integration` marker and first integration test: Intent round-trip.
- `DATABASE_URL` detection in `main.py`: if set, create `PostgresProjector`; else `NoOpProjector`.
- Run `alembic upgrade head` in `lifespan` startup when `DATABASE_URL` is set.

**Review focus:** SQLAlchemy async session lifecycle, upsert correctness, `events_projected` update atomicity.

### PR C — Full entity projection + Reconciliation job

- Extend `PostgresProjector.apply` to handle all event types: `finding_created`, `proposal_created`, `policy_evaluated`, `proposal_voted`, `proposal_approved`, `proposal_blocked`, `execution_started`, `execution_succeeded`, `execution_failed`, `rollback_started`, `rollback_completed`.
- Implement `reconcile_from`.
- Add startup catch-up in `PostgresProjector.__init__`.
- Add background reconciliation task registered on FastAPI lifespan.
- Add `POST /api/v1/admin/reconcile` endpoint (auth-required).
- Add reconciliation integration tests (Tier 3, Section 9).

**Review focus:** completeness of entity coverage, idempotency of upserts, reconciliation does not touch the JSONL.

### PR D — Query-layer endpoints

- Add `apps/api/app/api/query_routes.py` with the endpoints listed in Section 8.
- Register query router in `main.py`.
- Add `503` fallback when `NoOpProjector` is active.
- Add unit tests for query parameter parsing and `503` fallback.
- Add integration tests: filter by `agent_id`, filter by `created_after`, pagination.

**Review focus:** no writes through query layer, public auth contract preserved, `NoOpProjector` fallback behavior.

---

## 11. Open Questions

- **Read replicas.** Neon supports read replicas. Should the query layer (Section 8) route to a replica while the projector writes to the primary? Deferred: add only if write latency on Neon primary becomes a bottleneck. Track in a follow-up issue.

- **JSONB vs full normalization for `payload`.** `proposals.payload` holds `evidence_refs`, `rollback_steps`, and `health_checks` as JSONB. If query patterns emerge that filter on individual health check outcomes or rollback step contents, this should be normalized into child tables. The migration path is safe (add child table, backfill, switch reads). Decide after observing real query patterns in Phase 5.

- **ed25519 signing interaction.** The ROADMAP cuts ed25519 signing of the hash chain for now (multi-writer scenario). When it is added, `EventEnvelope` will gain a `signature` field. The `events_projected` table should store that field for auditability. The schema in `0001_initial.py` should reserve a nullable `last_event_signature` column in `events_projected` to avoid a disruptive migration later. Decide before PR B merges.

- **Health check results as a first-class table.** Currently stored as JSONB in `executions.health_checks`. If operators need to query "how many http health checks failed in environment prod in the last 7 days", a separate `health_check_results` table is needed. Include in a PR C follow-on if use-case is confirmed.

- **Neon branching for staging.** The Fly.io staging deployment (Phase 5) should use a Neon branch rather than a separate database. This requires the `DATABASE_URL` for staging to point at a branch connection string. No schema changes needed — note here so the Phase 5 devops agent is aware.
