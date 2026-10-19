import json
import sqlite3

import pytest
from typer.testing import CliRunner

from app.cli import app
from app.core.config import Settings
from app.services.run_log_service import RunLogService
from app.services.storage_migration import migrate_storage


def legacy_history(tmp_path):
    source = tmp_path / "old"
    source.mkdir()
    report = source / "migration-000000000001.json"
    report.write_text('{"existing":"report"}', encoding="utf-8")
    database = source / "run-logs.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE runs (id TEXT PRIMARY KEY, name TEXT, profile TEXT, started_at TEXT,
                finished_at TEXT, state TEXT, outcome TEXT, report_id TEXT);
            CREATE TABLE events (id INTEGER PRIMARY KEY, run_id TEXT, time TEXT, level TEXT,
                stage TEXT, event TEXT, details TEXT);
            INSERT INTO runs VALUES ('000000000001','old','full','2020-01-01T00:00:00+00:00',
                '2020-01-01T00:00:01+00:00','completed','FAIL','000000000001');
            INSERT INTO events VALUES (42,'000000000001','2020-01-01T00:00:01+00:00','error',
                'run','completed','{"status":"FAIL"}');
        """)
    return source, database


def test_migration_preserves_history_and_is_idempotent(tmp_path):
    source, database = legacy_history(tmp_path)
    original = database.read_bytes()
    destination = tmp_path / "Desktop" / "MigrationValidator"
    result = migrate_storage(legacy_db=database, source_reports=source, destination=destination)
    assert result["runs_imported"] == result["events_imported"] == result["reports_copied"] == 1
    store = RunLogService(Settings(run_log_dir=destination / "logs"))
    assert store.get("000000000001")["outcome"] == "FAIL"
    event = store.events("000000000001")["items"][0]
    assert event["id"] == 42
    assert event["details"] == {"status": "FAIL"}
    assert (destination / "reports" / "migration-000000000001.json").read_bytes() == (
        source / "migration-000000000001.json").read_bytes()
    again = migrate_storage(legacy_db=database, source_reports=source, destination=destination)
    assert again["runs_imported"] == again["reports_copied"] == 0
    assert again["runs_existing"] == again["reports_existing"] == 1
    assert database.read_bytes() == original
    store.append("000000000001", "info", "test", "after_import")
    assert store.events("000000000001")["items"][-1]["id"] == 43
    with pytest.raises(FileExistsError, match="Conflicting run"):
        migrate_storage(legacy_db=database, source_reports=source, destination=destination)
    assert store.events("000000000001")["total"] == 2


def test_migration_recovers_metadata_commit_and_rejects_report_overwrite(tmp_path):
    source, database = legacy_history(tmp_path)
    destination = tmp_path / "data"
    migrate_storage(legacy_db=database, source_reports=source, destination=destination)
    (destination / "logs" / "run-000000000001.meta.json").unlink()
    migrate_storage(legacy_db=database, source_reports=source, destination=destination)
    assert json.loads((destination / "logs" / "run-000000000001.meta.json").read_text())["state"] == "completed"
    report = destination / "reports" / "migration-000000000001.json"
    report.write_text("different", encoding="utf-8")
    with pytest.raises(FileExistsError, match="Conflicting history"):
        migrate_storage(legacy_db=database, source_reports=source, destination=destination)
    assert report.read_text() == "different"


def test_migration_command(tmp_path):
    source, database = legacy_history(tmp_path)
    result = CliRunner().invoke(app, ["migrate-storage", "--legacy-db", str(database),
                                     "--source-reports", str(source),
                                     "--destination", str(tmp_path / "data")])
    assert result.exit_code == 0, result.output
    assert "runs_imported" in result.output