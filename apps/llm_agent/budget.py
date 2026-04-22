"""Per-tick + daily token-cap accounting for the LLM adapter.

Stores cumulative-per-day input tokens on disk as JSON checkpoints under
``data/llm_usage/<agent_id>-<YYYY-MM-DD>.json`` so a crash recovers the
day's spend. In-memory cache avoids re-reading the file on every tick;
writes are fsync'd on every update so a kill -9 doesn't lose state.

Enforcement is client-side hard-stop: a tick that would exceed either
cap raises ``TickBudgetExceeded`` (per-tick) or ``DailyBudgetExceeded``
(daily). Both are subclasses of ``BudgetExceededError`` so the loop can
catch either with one branch.

Scope decision: this tracks **input** tokens only. Output tokens are
bounded by ``max_tokens`` on the request itself (SDK-enforced). Tracking
output too would double the config surface without reducing risk — the
only thing that drives the cost curve is input, and the per-tick cap
guards the worst-case output indirectly (a model doesn't emit 60K
output tokens from a 500-token input).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import structlog

_log = structlog.get_logger(__name__)


class BudgetExceededError(RuntimeError):
    """Base for both per-tick and daily cap violations."""


class TickBudgetExceeded(BudgetExceededError):
    """A single tick would exceed ``per_tick_token_cap``."""


class DailyBudgetExceeded(BudgetExceededError):
    """Cumulative spend for the day would exceed ``daily_token_cap``."""


@dataclass(frozen=True)
class BudgetStatus:
    """Snapshot returned to callers for logging / observability."""

    agent_id: str
    day: date
    daily_cap: int
    daily_used: int
    per_tick_cap: int


class LlmBudget:
    """Enforce + persist per-agent, per-day input-token spend.

    Instances are agent-scoped. Call ``check_tick(estimated)`` before a
    Claude call to pre-flight both caps; call ``record_tick(actual)``
    after the call completes with the true ``usage.input_tokens`` to
    advance the counter. A failure between check and record leaks
    nothing — the worst case is the next tick double-refuses because
    the in-memory figure is stale relative to the persisted one.
    """

    def __init__(
        self,
        *,
        agent_id: str,
        daily_cap: int,
        per_tick_cap: int,
        storage_dir: str | Path = "data/llm_usage",
    ) -> None:
        if daily_cap < 1:
            raise ValueError("daily_cap must be positive")
        if per_tick_cap < 1:
            raise ValueError("per_tick_cap must be positive")

        self._agent_id = agent_id
        self._daily_cap = daily_cap
        self._per_tick_cap = per_tick_cap
        self._dir = Path(storage_dir)
        self._lock = threading.Lock()
        self._current_day: date | None = None
        self._daily_used: int = 0
        self._load()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def check_tick(self, estimated_input_tokens: int, *, now: datetime | None = None) -> None:
        """Raise if ``estimated_input_tokens`` would break either cap.

        Called **before** the Claude call so the adapter can skip or
        truncate the request rather than pay for a call the operator
        has already budgeted out of.
        """
        if estimated_input_tokens < 0:
            raise ValueError("estimated_input_tokens must be >= 0")
        with self._lock:
            self._roll_if_new_day(now)
            if estimated_input_tokens > self._per_tick_cap:
                raise TickBudgetExceeded(
                    f"tick estimate {estimated_input_tokens} exceeds per_tick_token_cap "
                    f"({self._per_tick_cap})"
                )
            if self._daily_used + estimated_input_tokens > self._daily_cap:
                _log.warning(
                    "llm_cap_exceeded",
                    agent_id=self._agent_id,
                    cap="daily_token_cap",
                    daily_used=self._daily_used,
                    daily_cap=self._daily_cap,
                    estimated=estimated_input_tokens,
                )
                raise DailyBudgetExceeded(
                    f"daily used {self._daily_used} + estimated {estimated_input_tokens} "
                    f"exceeds daily_token_cap ({self._daily_cap})"
                )

    def record_tick(
        self,
        actual_input_tokens: int,
        *,
        now: datetime | None = None,
    ) -> BudgetStatus:
        """Advance the daily counter by ``actual_input_tokens`` and persist.

        Returns a snapshot of the post-update state for logging.
        """
        if actual_input_tokens < 0:
            raise ValueError("actual_input_tokens must be >= 0")
        with self._lock:
            self._roll_if_new_day(now)
            self._daily_used += actual_input_tokens
            self._persist()
            return BudgetStatus(
                agent_id=self._agent_id,
                day=self._current_day or _today(),
                daily_cap=self._daily_cap,
                daily_used=self._daily_used,
                per_tick_cap=self._per_tick_cap,
            )

    def status(self, *, now: datetime | None = None) -> BudgetStatus:
        """Read-only snapshot of the current day's state."""
        with self._lock:
            self._roll_if_new_day(now)
            return BudgetStatus(
                agent_id=self._agent_id,
                day=self._current_day or _today(),
                daily_cap=self._daily_cap,
                daily_used=self._daily_used,
                per_tick_cap=self._per_tick_cap,
            )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _checkpoint_path(self, day: date) -> Path:
        return self._dir / f"{self._agent_id}-{day.isoformat()}.json"

    def _roll_if_new_day(self, now: datetime | None) -> None:
        today = _today(now)
        if self._current_day == today:
            return
        # New day (or first load): reset counter + reload from disk if
        # a prior run already wrote something for today.
        self._current_day = today
        self._daily_used = 0
        path = self._checkpoint_path(today)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                used = int(data.get("daily_used", 0))
                if used >= 0:
                    self._daily_used = used
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                _log.warning(
                    "llm_budget_checkpoint_unreadable",
                    agent_id=self._agent_id,
                    path=str(path),
                    reason=type(exc).__name__,
                )

    def _persist(self) -> None:
        assert self._current_day is not None, "called outside _roll_if_new_day"
        path = self._checkpoint_path(self._current_day)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "agent_id": self._agent_id,
            "day": self._current_day.isoformat(),
            "daily_used": self._daily_used,
            "daily_cap": self._daily_cap,
            "per_tick_cap": self._per_tick_cap,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        # Atomic replace so a crash mid-write never leaves a partial
        # checkpoint that fails to parse on the next startup.
        fd, tmp_path = tempfile.mkstemp(
            prefix=f"{self._agent_id}-",
            suffix=".json.tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
        except Exception:
            # Best-effort cleanup on failure — os.replace raises before
            # the temp file is gone; os.fdopen failures leave it too.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load(self) -> None:
        # Prime the in-memory cache from today's checkpoint on construction.
        self._roll_if_new_day(None)


def _today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(UTC).date()
