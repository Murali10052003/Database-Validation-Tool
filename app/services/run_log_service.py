from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path

from filelock import FileLock

from app.core.config import Settings, get_settings

_current: ContextVar[tuple[RunLogService, str] | None] = ContextVar("run_log", default=None)
_FIELDS = {"check_id", "source_object", "target_object", "status", "duration_ms", "error_code"}


class RunAlreadyExistsError(ValueError):
    pass


def write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class RunLogService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _path(self, run_id: str, suffix: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{12,32}", run_id):
            raise ValueError("Invalid run ID")
        return self.settings.run_log_dir / f"run-{run_id}.{suffix}"

    @contextmanager
    def _lock(self, run_id: str):
        self._path(run_id, "meta.json")
        directory = self.settings.run_log_dir / ".locks"
        directory.mkdir(parents=True, exist_ok=True)
        with FileLock(directory / f"{run_id}.lock", timeout=30):
            yield

    def _metadata(self, run_id: str) -> dict | None:
        path = self._path(run_id, "meta.json")
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _iter_events(self, run_id: str):
        path = self._path(run_id, "jsonl")
        if not path.is_file():
            return
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.endswith("\n"):
                    break
                yield json.loads(line)

    def _append(self, run_id: str, level: str, stage: str, event: str, details: dict) -> None:
        if self._metadata(run_id) is None:
            raise FileNotFoundError(f"Run not recorded: {run_id}")
        path = self._path(run_id, "jsonl")
        with path.open("a+b") as stream:
            position = stream.seek(0, os.SEEK_END)
            tail = b""
            while position and tail.count(b"\n") < 2:
                size = min(position, 4096)
                position -= size
                stream.seek(position)
                tail = stream.read(size) + tail
            newline = tail.rfind(b"\n")
            valid_end = position + newline + 1 if newline >= 0 else 0
            last_id = json.loads(tail[:newline].rsplit(b"\n", 1)[-1])["id"] if newline >= 0 else 0
            stream.truncate(valid_end)
            stream.seek(valid_end)
            entry = {
                "id": last_id + 1, "run_id": run_id, "time": datetime.now(UTC).isoformat(),
                "level": level, "stage": stage, "event": event,
                "details": {key: value for key, value in details.items() if key in _FIELDS},
            }
            stream.write((json.dumps(entry, ensure_ascii=True) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())

    def start(self, run_id: str, name: str, profile: str, state: str = "running") -> None:
        self._path(run_id, "meta.json")
        self._purge_expired()
        with self._lock(run_id):
            if self._path(run_id, "meta.json").exists() or self._path(run_id, "jsonl").exists():
                raise RunAlreadyExistsError("Run ID already exists")
            write_json_atomic(self._path(run_id, "meta.json"), {
                "id": run_id, "name": name, "profile": profile,
                "started_at": datetime.now(UTC).isoformat(), "finished_at": None,
                "state": state, "outcome": None, "report_id": None,
            })
            self._append(run_id, "info", "run", "queued" if state == "queued" else "started", {})

    def finish(self, run_id: str, state: str, outcome: str | None = None) -> None:
        with self._lock(run_id):
            run = self._metadata(run_id)
            if run is None:
                raise FileNotFoundError(f"Run not recorded: {run_id}")
            level = "error" if state == "failed" or outcome == "FAIL" else (
                "warning" if outcome == "WARNING" else "info"
            )
            self._append(run_id, level, "run", state, {"status": outcome or state})
            run.update(finished_at=datetime.now(UTC).isoformat(), state=state, outcome=outcome,
                       report_id=run_id if state == "completed" else None)
            write_json_atomic(self._path(run_id, "meta.json"), run)

    def append(self, run_id: str, level: str, stage: str, event: str, **details) -> None:
        with self._lock(run_id):
            self._append(run_id, level, stage, event, details)

    def runs(self, limit: int = 100, offset: int = 0) -> list[dict]:
        runs = []
        for path in self.settings.run_log_dir.glob("run-*.meta.json"):
            run_id = path.name.removeprefix("run-").removesuffix(".meta.json")
            run = self.get(run_id)
            if run is not None:
                runs.append(run)
        runs.sort(key=lambda run: (run["started_at"], run["id"]), reverse=True)
        return runs[offset:offset + limit]

    def get(self, run_id: str) -> dict | None:
        if not re.fullmatch(r"[a-f0-9]{12,32}", run_id):
            return None
        with self._lock(run_id):
            return self._metadata(run_id)

    def events(
        self,
        run_id: str,
        *,
        level: str = "",
        stage: str = "",
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        items = []
        total = 0
        with self._lock(run_id):
            for entry in self._iter_events(run_id):
                if level and entry["level"] != level or stage and entry["stage"] != stage:
                    continue
                text = entry["event"] + json.dumps(entry["details"], ensure_ascii=True)
                if query and query.lower() not in text.lower():
                    continue
                if offset <= total < offset + limit:
                    items.append(entry)
                total += 1
        return {"total": total, "items": items}

    def _purge_expired(self) -> None:
        days = self.settings.run_log_retention_days
        if not days:
            return
        cutoff = datetime.now(UTC) - timedelta(days=days)
        for path in self.settings.run_log_dir.glob("run-*.meta.json"):
            run_id = path.name.removeprefix("run-").removesuffix(".meta.json")
            with self._lock(run_id):
                run = self._metadata(run_id)
                if (run and run.get("finished_at")
                    and datetime.fromisoformat(run["finished_at"]) < cutoff):
                    self._path(run_id, "jsonl").unlink(missing_ok=True)
                    path.unlink(missing_ok=True)

    @contextmanager
    def bind(self, run_id: str):
        token = _current.set((self, run_id))
        try:
            yield
        finally:
            _current.reset(token)


def emit(level: str, stage: str, event: str, **details) -> None:
    current = _current.get()
    if current:
        store, run_id = current
        store.append(run_id, level, stage, event, **details)


def error_code(error: object) -> str:
    match = re.search(r"\b(?:ORA-\d{5}|SQLSTATE[ :\[]+[A-Z0-9]{5})\b", str(error))
    return match.group(0) if match else "DETAILS_WITHHELD"
