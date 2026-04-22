"""Tests for the `health_check_completed` event emission.

Closes the longstanding `docs/ARCHITECTURE.md` drift — that document has
listed `health_check_completed` as a first-class event since bootstrap,
but the executor never emitted one until this PR.
"""

from __future__ import annotations

from pathlib import Path

from apps.api.app.domain.models import (
    HealthCheckKind,
    HealthCheckSpec,
    Proposal,
    ProposalStatus,
)
from apps.api.app.services.event_log import EventLog
from apps.api.app.services.executor import Executor
from apps.api.app.services.policy_engine import PolicyEngine
from apps.api.app.services.state_store import StateStore


def _make_proposal(*specs: HealthCheckSpec) -> Proposal:
    return Proposal(
        intent_id="intent_abc",
        agent_id="test-operator",
        title="t",
        action_type="config-change",
        target="svc",
        rationale="because",
        health_checks=list(specs),
        status=ProposalStatus.approved,
    )


def test_executor_emits_one_event_per_check(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    executor = Executor(log, PolicyEngine("config/policies.yaml"))

    executor.execute(
        _make_proposal(
            HealthCheckSpec(name="check-one", kind=HealthCheckKind.always_pass),
            HealthCheckSpec(name="check-two", kind=HealthCheckKind.always_pass),
            HealthCheckSpec(name="check-three", kind=HealthCheckKind.always_pass),
        ),
        actor_id="test-operator",
    )

    all_events = log.read_all()
    hcc = [e for e in all_events if e.event_type == "health_check_completed"]
    assert len(hcc) == 3
    assert [e.payload["name"] for e in hcc] == ["check-one", "check-two", "check-three"]
    for event in hcc:
        # Payload shape contract — every downstream consumer depends on these keys.
        for field in (
            "id",
            "execution_id",
            "proposal_id",
            "name",
            "kind",
            "passed",
            "detail",
            "created_at",
        ):
            assert field in event.payload, f"missing {field!r} in payload: {event.payload}"


def test_health_check_event_precedes_execution_outcome(tmp_path: Path) -> None:
    """health_check_completed events are written between execution_started and
    the terminal execution_succeeded/failed — so a projector re-applying the
    log in order sees the per-check rows before the status transition."""
    log = EventLog(tmp_path / "events.jsonl")
    executor = Executor(log, PolicyEngine("config/policies.yaml"))

    executor.execute(
        _make_proposal(HealthCheckSpec(name="only", kind=HealthCheckKind.always_pass)),
        actor_id="test-operator",
    )

    types = [e.event_type for e in log.read_all()]
    started = types.index("execution_started")
    hcc = types.index("health_check_completed")
    terminal_ix = next(
        i for i, t in enumerate(types) if t in {"execution_succeeded", "execution_failed"}
    )
    assert started < hcc < terminal_ix


def test_failing_check_still_emits_event(tmp_path: Path) -> None:
    """An always_fail check must still produce a health_check_completed event
    with passed=False before the failure + rollback cascade."""
    log = EventLog(tmp_path / "events.jsonl")
    executor = Executor(log, PolicyEngine("config/policies.yaml"))

    result = executor.execute(
        _make_proposal(HealthCheckSpec(name="doomed", kind=HealthCheckKind.always_fail)),
        actor_id="test-operator",
    )
    assert result["status"] == "failed"

    hcc = [e for e in log.read_all() if e.event_type == "health_check_completed"]
    assert len(hcc) == 1
    assert hcc[0].payload["passed"] is False
    assert hcc[0].payload["kind"] == "always_fail"


def test_state_store_reduces_health_check_events(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    executor = Executor(log, PolicyEngine("config/policies.yaml"))
    executor.execute(
        _make_proposal(
            HealthCheckSpec(name="a", kind=HealthCheckKind.always_pass),
            HealthCheckSpec(name="b", kind=HealthCheckKind.always_pass),
        ),
        actor_id="test-operator",
    )

    store = StateStore()
    store.replay(log.read_all())
    # One bucket per execution_id; our single execution has 2 checks.
    assert len(store.health_check_results) == 1
    bucket = next(iter(store.health_check_results.values()))
    assert len(bucket) == 2
    assert {b["name"] for b in bucket} == {"a", "b"}
