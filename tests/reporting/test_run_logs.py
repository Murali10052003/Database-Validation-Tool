import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.config import Settings
from app.services.run_log_service import RunAlreadyExistsError, RunLogService, emit, error_code


def test_persistence_isolation_redaction_and_paging(tmp_path):
    settings = Settings(run_log_dir=tmp_path / "logs")
    store = RunLogService(settings)

    def run(number):
        run_id = f"{number:012x}"
        store.start(run_id, "Test", "full")
        with store.bind(run_id):
            emit("error", "checksum", "check_finished", status="ERROR", password="secret",
                 source_value="private", error="password=secret", error_code=error_code("ORA-01017 secret"))
        store.finish(run_id, "completed", "FAIL")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, [1, 2]))
    reopened = RunLogService(settings)
    assert len(reopened.runs()) == 2
    events = reopened.events("000000000001", level="error", stage="checksum")
    assert events["total"] == 1
    assert events["items"][0]["details"] == {"status": "ERROR", "error_code": "ORA-01017"}
    assert reopened.events("000000000001", limit=1, offset=1)["items"][0]["stage"] == "checksum"
    assert reopened.get("000000000001")["outcome"] == "FAIL"
    assert (settings.run_log_dir / "run-000000000001.jsonl").is_file()
    assert not list(tmp_path.rglob("*.sqlite3"))
    with pytest.raises(RunAlreadyExistsError):
        reopened.start("000000000001", "duplicate", "full")
    with pytest.raises(ValueError):
        store.start("../escape", "Test", "full")


def test_retention_removes_only_finished_old_runs(tmp_path):
    store = RunLogService(Settings(run_log_dir=tmp_path / "logs", run_log_retention_days=30))
    store.start("000000000001", "old", "full")
    store.finish("000000000001", "failed")
    store.start("000000000002", "active", "full")
    path = store._path("000000000001", "meta.json")
    run = json.loads(path.read_text())
    run["finished_at"] = "2000-01-01T00:00:00+00:00"
    path.write_text(json.dumps(run), encoding="utf-8")
    store.start("000000000003", "new", "full")
    assert store.get("000000000001") is None
    assert store.events("000000000001")["total"] == 0
    assert store.get("000000000002")["state"] == "running"


def test_retention_disabled_by_default_and_partial_tail_recovery(tmp_path):
    store = RunLogService(Settings(run_log_dir=tmp_path))
    store.start("000000000001", "old", "full")
    store.finish("000000000001", "completed", "PASS")
    path = store._path("000000000001", "meta.json")
    run = json.loads(path.read_text())
    run["finished_at"] = "2000-01-01T00:00:00+00:00"
    path.write_text(json.dumps(run), encoding="utf-8")
    store.start("000000000002", "new", "full")
    assert store.get("000000000001") is not None
    with store._path("000000000002", "jsonl").open("ab") as stream:
        stream.write(b'{"id":2')
    assert store.events("000000000002")["total"] == 1
    store.append("000000000002", "info", "test", "recovered")
    assert [entry["id"] for entry in store.events("000000000002")["items"]] == [1, 2]


def test_multiple_instances_serialize_same_run(tmp_path):
    settings = Settings(run_log_dir=tmp_path)
    store = RunLogService(settings)
    store.start("000000000001", "parallel", "full")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda number: RunLogService(settings).append(
            "000000000001", "info", "test", "event", check_id=str(number)), range(20)))
    entries = store.events("000000000001")["items"]
    assert [entry["id"] for entry in entries] == list(range(1, 22))


def test_large_event_tail_and_malformed_complete_line(tmp_path):
    store = RunLogService(Settings(run_log_dir=tmp_path))
    store.start("000000000001", "large", "full")
    store.append("000000000001", "info", "test", "large", check_id="a" * 9000)
    store.append("000000000001", "info", "test", "last")
    assert [entry["id"] for entry in store.events("000000000001")["items"]] == [1, 2, 3]
    with store._path("000000000001", "jsonl").open("ab") as stream:
        stream.write(b'{broken}\n')
    with pytest.raises(json.JSONDecodeError):
        store.events("000000000001")