"""In-memory progress for long synchronous requests such as Discover & match.

A request that carries a client-chosen ``progress_id`` reports how far it has got; the
UI polls the snapshot while the request is still running. State lives in this process
only and is dropped after an hour, so it is advisory and never a source of truth.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

ProgressCallback = Callable[[float, str], None]


class ProgressReporter:
    """Reports weighted stages for one request; does nothing without a progress id."""

    def __init__(self, tracker: ProgressTracker | None, progress_id: str | None,
                 stages: Sequence[tuple[str, float]]) -> None:
        self._tracker = tracker
        self._id = progress_id
        self._stages = [name for name, _ in stages]
        total = sum(weight for _, weight in stages) or 1.0
        self._weights = [weight * 100.0 / total for _, weight in stages]

    @property
    def enabled(self) -> bool:
        return self._tracker is not None and self._id is not None

    def update(self, stage: int, fraction: float, message: str = "") -> None:
        if not self.enabled:
            return
        fraction = min(max(fraction, 0.0), 1.0)
        percent = sum(self._weights[:stage]) + self._weights[stage] * fraction
        self._tracker._set(self._id, {
            "state": "running",
            "percent": round(min(percent, 100.0), 1),
            "stage": self._stages[stage],
            "message": message,
            "stage_index": stage,
            "stage_count": len(self._stages),
        })

    def callback(self, stage: int) -> ProgressCallback:
        """A ``(fraction, message)`` callback that reports within ``stage``."""
        return lambda fraction, message="": self.update(stage, fraction, message)

    def complete(self, message: str = "Complete") -> None:
        if self.enabled:
            self._tracker._set(self._id, {
                "state": "completed", "percent": 100.0, "stage": self._stages[-1],
                "message": message, "stage_index": len(self._stages) - 1,
                "stage_count": len(self._stages),
            })

    def fail(self, message: str) -> None:
        if self.enabled:
            self._tracker._set(self._id, {"state": "failed", "error": message}, keep=True)


class ProgressTracker:
    """Thread-safe snapshots keyed by progress id."""

    def __init__(self, keep: int = 200, ttl_seconds: float = 3600.0) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._keep = keep
        self._ttl = ttl_seconds

    def begin(self, progress_id: str | None,
              stages: Sequence[tuple[str, float]]) -> ProgressReporter:
        reporter = ProgressReporter(self, progress_id, stages)
        if reporter.enabled:
            reporter.update(0, 0.0, "Starting")
        return reporter

    def get(self, progress_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(progress_id)
            return None if item is None else {k: v for k, v in item.items() if k != "_at"}

    def _set(self, progress_id: str, values: dict[str, Any], keep: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            previous = self._items.get(progress_id, {}) if keep else {}
            self._items[progress_id] = {**previous, **values, "_at": now}
            if len(self._items) > self._keep:
                stale = [key for key, item in self._items.items() if now - item["_at"] > self._ttl]
                for key in stale or sorted(self._items, key=lambda k: self._items[k]["_at"])[:1]:
                    self._items.pop(key, None)
