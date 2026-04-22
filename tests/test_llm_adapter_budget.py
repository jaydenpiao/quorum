"""Per-tick + daily budget accounting for the LLM adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.llm_agent.budget import (
    BudgetStatus,
    DailyBudgetExceeded,
    LlmBudget,
    TickBudgetExceeded,
)


def _fresh(tmp_path: Path, **kwargs: object) -> LlmBudget:
    defaults: dict[str, object] = {
        "agent_id": "telemetry-llm-agent",
        "daily_cap": 100_000,
        "per_tick_cap": 20_000,
        "storage_dir": tmp_path,
    }
    defaults.update(kwargs)
    return LlmBudget(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_checks_and_records(tmp_path: Path) -> None:
    budget = _fresh(tmp_path)
    budget.check_tick(5_000)
    status = budget.record_tick(4_823)
    assert status.daily_used == 4_823
    assert status.daily_cap == 100_000


def test_status_reflects_recorded_spend(tmp_path: Path) -> None:
    budget = _fresh(tmp_path)
    budget.record_tick(1_000)
    budget.record_tick(2_500)
    status = budget.status()
    assert status.daily_used == 3_500


# ---------------------------------------------------------------------------
# Tick cap
# ---------------------------------------------------------------------------


def test_rejects_tick_above_per_tick_cap(tmp_path: Path) -> None:
    budget = _fresh(tmp_path, per_tick_cap=1_000)
    with pytest.raises(TickBudgetExceeded):
        budget.check_tick(1_001)


def test_rejects_negative_estimate(tmp_path: Path) -> None:
    budget = _fresh(tmp_path)
    with pytest.raises(ValueError):
        budget.check_tick(-1)


# ---------------------------------------------------------------------------
# Daily cap
# ---------------------------------------------------------------------------


def test_rejects_when_cumulative_would_exceed_daily_cap(tmp_path: Path) -> None:
    budget = _fresh(tmp_path, daily_cap=10_000)
    budget.record_tick(6_000)
    # 6000 + 5000 > 10_000 → reject BEFORE the call runs
    with pytest.raises(DailyBudgetExceeded):
        budget.check_tick(5_000)


def test_accepts_at_exact_daily_cap(tmp_path: Path) -> None:
    budget = _fresh(tmp_path, daily_cap=10_000)
    budget.record_tick(9_999)
    # 9999 + 1 = 10_000 exactly → accept (not exceed)
    budget.check_tick(1)


# ---------------------------------------------------------------------------
# Persistence + day roll
# ---------------------------------------------------------------------------


def test_spend_persists_across_instances(tmp_path: Path) -> None:
    first = _fresh(tmp_path)
    first.record_tick(1_234)
    second = _fresh(tmp_path)
    assert second.status().daily_used == 1_234


def test_daily_counter_resets_on_new_day(tmp_path: Path) -> None:
    budget = _fresh(tmp_path)
    budget.record_tick(500)
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    status = budget.status(now=tomorrow)
    assert status.daily_used == 0


def test_checkpoint_file_shape(tmp_path: Path) -> None:
    budget = _fresh(tmp_path)
    budget.record_tick(777)
    today = datetime.now(UTC).date().isoformat()
    path = tmp_path / f"telemetry-llm-agent-{today}.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["daily_used"] == 777
    assert data["daily_cap"] == 100_000


def test_rejects_unreadable_checkpoint_gracefully(tmp_path: Path) -> None:
    """A corrupt checkpoint does not crash the adapter — it logs and
    resets the in-memory counter to 0 so the next write overwrites
    the bad file."""
    today = datetime.now(UTC).date().isoformat()
    bad = tmp_path / f"telemetry-llm-agent-{today}.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not valid json", encoding="utf-8")

    budget = _fresh(tmp_path)
    assert budget.status().daily_used == 0
    budget.record_tick(100)
    assert budget.status().daily_used == 100


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_rejects_non_positive_caps(tmp_path: Path) -> None:
    for bad_daily in (0, -1):
        with pytest.raises(ValueError):
            LlmBudget(
                agent_id="x",
                daily_cap=bad_daily,
                per_tick_cap=1,
                storage_dir=tmp_path,
            )
    for bad_tick in (0, -1):
        with pytest.raises(ValueError):
            LlmBudget(
                agent_id="x",
                daily_cap=1,
                per_tick_cap=bad_tick,
                storage_dir=tmp_path,
            )


def test_status_shape_is_immutable(tmp_path: Path) -> None:
    budget = _fresh(tmp_path)
    status = budget.status()
    assert isinstance(status, BudgetStatus)
    with pytest.raises((AttributeError, TypeError)):
        status.daily_used = 42  # type: ignore[misc]
