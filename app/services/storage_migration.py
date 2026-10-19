from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from filelock import FileLock
from pydantic import ValidationError

from app.core.catalog import Catalog
from app.core.config import Settings
from app.reporting.report_builder import ValidationReport
from app.services.run_log_service import RunLogService, write_json_atomic


def _copy_atomic(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != content:
            raise FileExistsError(f"Conflicting history, not overwritten: {destination}")
        return
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".import-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def migrate_storage(
    *, legacy_db: Path | None, source_reports: Path, destination: Path,
    source_logs: Path | None = None,
) -> dict:
    if not source_reports.is_dir():
        raise FileNotFoundError(f"Report directory does not exist: {source_reports}")
    if legacy_db is not None and not legacy_db.is_file():
        raise FileNotFoundError(f"Legacy database does not exist: {legacy_db}")
    if source_logs is not None and not source_logs.is_dir():
        raise FileNotFoundError(f"Log directory does not exist: {source_logs}")
    settings = Settings(report_dir=destination / "reports", run_log_dir=destination / "logs")
    store = RunLogService(settings)
    destination.mkdir(parents=True, exist_ok=True)
    catalog = Catalog(destination / "catalog.sqlite3")
    counts = {"runs_imported": 0, "runs_existing": 0, "events_imported": 0,
              "reports_copied": 0, "reports_existing": 0}
    with FileLock(destination / ".migration.lock", timeout=30):
        if legacy_db is not None:
            connection = sqlite3.connect(legacy_db.resolve().as_uri() + "?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("BEGIN")
                for row in connection.execute("SELECT * FROM runs ORDER BY started_at"):
                    run = dict(row)
                    run_id = run["id"]
                    events = [dict(event) | {"details": json.loads(event["details"])}
                              for event in connection.execute(
                                  "SELECT * FROM events WHERE run_id=? ORDER BY id", (run_id,))]
                    content = "".join(json.dumps(event, ensure_ascii=True) + "\n"
                                      for event in events).encode("utf-8")
                    with store._lock(run_id):
                        existing = store._metadata(run_id)
                        if existing is not None:
                            if existing != run or list(store._iter_events(run_id)) != events:
                                raise FileExistsError(f"Conflicting run, not overwritten: {run_id}")
                            counts["runs_existing"] += 1
                            continue
                        _copy_atomic(store._path(run_id, "jsonl"), content)
                        write_json_atomic(store._path(run_id, "meta.json"), run)
                        counts["runs_imported"] += 1
                        counts["events_imported"] += len(events)
            finally:
                connection.close()
        for source in sorted(source_reports.glob("migration-*.json")):
            target = settings.report_dir / source.name
            exists = target.exists()
            _copy_atomic(target, source.read_bytes())
            counts["reports_existing" if exists else "reports_copied"] += 1
            try:
                report = ValidationReport.model_validate_json(source.read_bytes())
            except ValidationError:
                continue
            catalog.import_report(report)
        if source_logs is not None:
            for pattern in ("*.meta.json", "*.jsonl"):
                for source in source_logs.glob(pattern):
                    _copy_atomic(settings.run_log_dir / source.name, source.read_bytes())
    return counts