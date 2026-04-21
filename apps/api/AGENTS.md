# AGENTS.md — backend / control-plane area

## Scope

This directory owns the core runtime behavior:

- event schemas
- replay and state reduction
- policy evaluation
- quorum evaluation
- execution and rollback

## Rules for changes here

- keep business logic explicit
- avoid framework magic
- preserve event ordering semantics
- tests are required for behavior changes
- if you add a new event type, update the reducer
- if you change proposal fields, update examples and docs

## Load-bearing files

- `app/domain/models.py`
- `app/services/event_log.py`
- `app/services/state_store.py`
- `app/services/policy_engine.py`
- `app/services/quorum_engine.py`
- `app/services/executor.py`

## Safe extension points

Good places to add behavior:
- new health check types
- new policy rules
- new actuator types
- new read-model endpoints

## Avoid

- hidden side effects
- unlogged state changes
- direct mutation outside the event path
