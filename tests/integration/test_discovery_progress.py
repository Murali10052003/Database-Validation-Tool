"""Discover & match progress: weighted stages, discovery callbacks and the polling endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import routes
from app.core.enums import DatabaseType
from app.core.exceptions import ConfigurationError
from app.core.progress import ProgressTracker
from app.discovery.database_discovery import DatabaseDiscovery
from app.models.column import ColumnModel
from app.models.database import DatabaseModel
from app.models.schema import SchemaModel
from app.models.table import TableModel
from tests.conftest import MockAdapter

SOURCE = {"type": "oracle", "host": "source", "username": "reader"}
TARGET = {"type": "azure_postgresql", "host": "target", "username": "reader"}


def _schema(name: str, tables=("T",)) -> SchemaModel:
    return SchemaModel(name=name, tables=[
        TableModel(schema_name=name, name=table, columns=[
            ColumnModel(name="ID", ordinal_position=1, native_type="INTEGER"),
        ]) for table in tables
    ])


# -- tracker -----------------------------------------------------------------------


def test_stage_weights_are_normalised_to_one_hundred_percent():
    tracker = ProgressTracker()
    reporter = tracker.begin("progress-1", [("a", 45), ("b", 45), ("c", 10)])
    assert tracker.get("progress-1")["percent"] == 0
    reporter.update(1, 0.5, "half way")
    snapshot = tracker.get("progress-1")
    assert snapshot["percent"] == 67.5
    assert (snapshot["stage"], snapshot["message"], snapshot["state"]) == ("b", "half way", "running")
    reporter.update(2, 5.0)  # fractions are clamped
    assert tracker.get("progress-1")["percent"] == 100
    reporter.complete()
    assert tracker.get("progress-1")["state"] == "completed"


def test_failure_keeps_last_known_progress_and_reports_the_error():
    tracker = ProgressTracker()
    reporter = tracker.begin("progress-2", [("a", 1), ("b", 1)])
    reporter.update(0, 0.5, "reading")
    reporter.fail("boom")
    snapshot = tracker.get("progress-2")
    assert snapshot["state"] == "failed" and snapshot["error"] == "boom"
    assert snapshot["percent"] == 25


def test_reporter_without_an_id_is_inert():
    tracker = ProgressTracker()
    reporter = tracker.begin(None, [("a", 1)])
    reporter.update(0, 0.5)
    reporter.complete()
    reporter.fail("ignored")
    assert not reporter.enabled and tracker.get("anything") is None


def test_tracker_evicts_the_oldest_entries_when_full():
    tracker = ProgressTracker(keep=2)
    for index in range(3):
        tracker.begin(f"progress-{index}", [("a", 1)])
    assert tracker.get("progress-0") is None
    assert tracker.get("progress-2") is not None


# -- discovery callback ------------------------------------------------------------


async def test_discovery_reports_each_schema_and_ends_at_one():
    adapter = MockAdapter(DatabaseType.ORACLE, [_schema("HR"), _schema("SALES")])
    seen: list[tuple[float, str]] = []
    await DatabaseDiscovery(adapter).discover(
        include_columns=False, on_progress=lambda fraction, message: seen.append((fraction, message)),
    )
    fractions = [fraction for fraction, _ in seen]
    assert fractions == sorted(fractions) and fractions[0] == 0 and fractions[-1] == 1
    assert any("HR (1 of 2)" in message for _, message in seen)
    assert any("SALES (2 of 2)" in message for _, message in seen)
    assert not any("tables" in message for _, message in seen)  # names-only: no per-table work


async def test_discovery_reports_tables_when_reading_columns():
    adapter = MockAdapter(DatabaseType.ORACLE, [_schema("HR", ("A", "B"))])
    seen: list[tuple[float, str]] = []
    await DatabaseDiscovery(adapter).discover(
        include_columns=True, on_progress=lambda fraction, message: seen.append((fraction, message)),
    )
    assert [m for _, m in seen if "tables" in m] == [
        "Reading schema HR (1 of 1): 1 of 2 tables",
        "Reading schema HR (1 of 1): 2 of 2 tables",
    ]


# -- endpoint ----------------------------------------------------------------------


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def test_plan_publishes_progress_for_the_request_id(client, monkeypatch):
    async def discover(config, schemas=None, *, on_progress=None, **kwargs):
        on_progress(0.5, "halfway")
        return DatabaseModel(database_type="oracle", schemas=[_schema("HR")])

    monkeypatch.setattr(routes._discovery_service, "discover", discover)
    response = await client.post("/api/plan?progress_id=plan-progress-ok", json={
        "source": SOURCE, "target": TARGET,
        "source_schemas": ["HR"], "target_schemas": ["HR"]})
    assert response.status_code == 200, response.text
    snapshot = (await client.get("/api/plan/progress/plan-progress-ok")).json()
    assert snapshot["state"] == "completed" and snapshot["percent"] == 100


async def test_plan_without_a_progress_id_does_not_pass_a_callback(client, monkeypatch):
    discover = AsyncMock(side_effect=[
        DatabaseModel(database_type="oracle", schemas=[_schema("HR")]),
        DatabaseModel(database_type="azure_postgresql", schemas=[_schema("hr")]),
    ])
    monkeypatch.setattr(routes._discovery_service, "discover", discover)
    response = await client.post("/api/plan", json={"source": SOURCE, "target": TARGET})
    assert response.status_code == 200, response.text
    assert all("on_progress" not in call.kwargs for call in discover.await_args_list)


async def test_failed_plan_reports_the_error_through_progress(client, monkeypatch):
    async def discover(config, schemas=None, **kwargs):
        raise ConfigurationError("Schema not found or not visible to this connection: NOPE")

    monkeypatch.setattr(routes._discovery_service, "discover", discover)
    response = await client.post("/api/plan?progress_id=plan-progress-bad", json={
        "source": SOURCE, "target": TARGET, "source_schemas": ["NOPE"], "target_schemas": ["x"]})
    assert response.status_code == 400
    snapshot = (await client.get("/api/plan/progress/plan-progress-bad")).json()
    assert snapshot["state"] == "failed" and "NOPE" in snapshot["error"]


async def test_progress_lookup_rejects_unknown_and_malformed_ids(client):
    assert (await client.get("/api/plan/progress/never-started-id")).status_code == 404
    assert (await client.get("/api/plan/progress/short")).status_code == 422
    bad = await client.post("/api/plan?progress_id=bad id!", json={"source": SOURCE, "target": TARGET})
    assert bad.status_code == 422
