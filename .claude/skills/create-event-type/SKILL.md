---
name: create-event-type
description: Use when adding a new event type to the Quorum event log (e.g., health_check_completed, human_approval_requested, deploy_intent_created). Ensures the five required touch points from AGENTS.md land in the same patch — reducer, emission site, docs, examples, tests — so the event schema stays coherent and the audit trail stays replayable.
---

# Skill: create-event-type

Adding a new event type is a **shared-core change** per `docs/PARALLEL_DEVELOPMENT.md`. Treat it as such: one small PR, coordinated, no parallel work on the same event schema.

## When to invoke this skill

You need a new event type when you are:
- Adding a new state transition that the existing event types cannot express accurately (prefer a specific new event over overloading `status_changed` or similar — AGENTS.md "Logging rules").
- Introducing a new entity or sub-entity that emits its own lifecycle events.
- Refactoring an implicit state change (e.g., health-check result embedded in `ExecutionRecord`) into an explicit standalone event.

Do **not** invoke this skill for:
- Adding a field to an existing event's payload (backward-compatible — just update the payload dict).
- Renaming an existing event type (that's a migration, not a new event).

## Checklist — five touch points

Every new event type requires all five:

### 1. Event type identifier

Pick a `snake_case` event type string. It should read as `<entity>_<verb_past_tense>`. Examples:
- `proposal_created`
- `proposal_approved`
- `execution_started`
- `health_check_completed`
- `rollback_completed`

Register it however the codebase registers types (currently events are string-typed in `EventEnvelope.event_type`; consider adding an `EventType` enum if the list grows past ~20).

### 2. Emission site

Find the service method where the state transition happens. Emit the event via `event_log.append(EventEnvelope(...))`. Emission must be **inside the same code path** as the mutation — never in a separate goroutine/task/middleware that could skip on failure.

Critical files:
- `apps/api/app/services/executor.py` — execution, rollback, health-check events
- `apps/api/app/services/quorum_engine.py` — approval/blocking events
- `apps/api/app/api/routes.py` — creation events (intent, finding, proposal, vote)
- `apps/api/app/services/policy_engine.py` — `policy_evaluated`

### 3. Reducer in the state store

`apps/api/app/services/state_store.py` has a reducer that materializes events into the in-memory state snapshot. Every event type needs a case, even a no-op:

```python
def apply(self, event: EventEnvelope) -> None:
    match event.event_type:
        case "proposal_created":
            ...
        case "your_new_event":
            ...  # update self.state appropriately
        case _:
            pass  # unknown event types are ignored, not an error
```

If the reducer has a missing case, replay will silently drop state — a subtle bug that surfaces only after restart.

### 4. Documentation

Update `docs/ARCHITECTURE.md`:
- Add the event to the event-flow section.
- If there's a mermaid sequence diagram, add your event to it.
- If the event is triggered by an API call, document the API behavior.

Update `docs/REPO_MAP.md` if the emission site is in a new file.

### 5. Example + test

Add an example payload to `examples/` (new JSON file, or extend `examples/demo_incident.json` if it fits the demo flow).

Add a test in `tests/`:
- Positive: the event is emitted under the expected conditions.
- Reducer: feeding the event produces the expected state change.
- Replay: re-reading the log reconstructs the same state.

## Verification

Before claiming done:
```bash
ruff check . && ruff format --check . && pytest -q
```

Then, in a fresh interpreter, load the log and verify:
```bash
python -c "from apps.api.app.services.event_log import EventLog; from apps.api.app.services.state_store import StateStore; s = StateStore(); [s.apply(e) for e in EventLog('data/events.jsonl').read_all()]; print('replayed', len(s.events), 'events ok')"
```

If the event chain ever lands (Phase 2), also verify the chain is intact after your addition.

## Anti-patterns

- **Overloaded event types.** `status_changed` with a `to` field in the payload. Bad because observability and reducers have to branch on payload to know what happened. Prefer `proposal_approved`, `proposal_blocked`, etc.
- **Synchronous emit + async mutation.** Emit the event *after* the mutation completes, never before. A pre-commit event followed by a failed mutation = a lie in the log.
- **Events without reducers.** Every event has a reducer case, even if the reducer is a pass — the explicitness is the point.
- **Forgetting docs.** AGENTS.md "Docs rules" make this a product bug, not a nit.
