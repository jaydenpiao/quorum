from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Iterable

from apps.api.app.domain.models import EventEnvelope


class EventLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        if not self.path.exists():
            self.path.touch()

    def append(self, event: EventEnvelope) -> None:
        line = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
        with self.lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def read_all(self) -> list[EventEnvelope]:
        events: list[EventEnvelope] = []
        if not self.path.exists():
            return events
        with self.path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                events.append(EventEnvelope.model_validate(json.loads(raw)))
        return events

    def reset(self) -> None:
        with self.lock:
            self.path.write_text("", encoding="utf-8")
