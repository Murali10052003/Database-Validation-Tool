"""HTTP routes for the migration-validation web POC.

Thin adapters over the service layer; all real work lives in ``app.services``.

The DB-touching endpoints are declared synchronously so FastAPI runs them in a
worker thread, where each request drives the async services on a dedicated
``SelectorEventLoop``. This sidesteps uvicorn's Windows ProactorEventLoop, which
psycopg's async client cannot use.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Coroutine
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import PlainTextResponse, Response, StreamingResponse

from app.core.catalog import Catalog
from app.core.exceptions import MigrationValidatorError
from app.core.logging import get_logger
from app.core.progress import ProgressReporter, ProgressTracker
from app.mapping.auto_matcher import _match_one, _match_tables, build_plan
from app.reporting.report_builder import ValidationReport
from app.schemas.api import (
    ConnectionCheck,
    ConnectionInput,
    DiscoverResponse,
    MappingInput,
    MigrationRequest,
    PlanResponse,
    ReportListItem,
    SavedConnectionInput,
    SchemaListResponse,
    SchemaMatch,
    SchemaSummary,
    TestConnectionResponse,
)
from app.services.background_validation import ValidationBusyError
from app.services.discovery_service import DiscoveryService
from app.services.migration_service import MigrationService
from app.services.report_service import ReportService
from app.services.run_log_service import RunAlreadyExistsError, RunLogService

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["validation"])

_migration_service = MigrationService()
_discovery_service = DiscoveryService()
_report_service = ReportService()
_run_logs = RunLogService()
_progress = ProgressTracker()


@router.get("/health")
def health():
    with Catalog().connect() as connection:
        connection.execute("SELECT 1 FROM schema_migrations LIMIT 1")
    return {"status": "ok"}


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on a fresh selector loop (psycopg-safe on Windows)."""
    loop = asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@router.get("/supported")
async def supported() -> dict[str, list[str]]:
    """Database types the platform can currently target."""
    from app.adapters.factory import adapter_factory

    return {"database_types": [t.value for t in adapter_factory.supported_types()]}


@router.get("/auth/config")
def auth_config() -> dict[str, str]:
    return {
        "client_id": os.environ.get("MV_ENTRA_CLIENT_ID", ""),
        "tenant_id": os.environ.get("MV_ENTRA_TENANT_ID", ""),
    }


@router.post("/test-connection/single", response_model=ConnectionCheck)
def test_single_connection(request: ConnectionInput) -> ConnectionCheck:
    try:
        return _to_check(_run(_migration_service.test_connection(request.to_config())))
    except MigrationValidatorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/test-connection", response_model=TestConnectionResponse)
def test_connection(request: MigrationRequest) -> TestConnectionResponse:
    config = request.to_migration_config()
    try:
        source, target = _run(_migration_service.test_connections(config))
    except MigrationValidatorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TestConnectionResponse(
        source=_to_check(source),
        target=_to_check(target),
    )


@router.post("/discover", response_model=DiscoverResponse)
def discover(
    request: MigrationRequest,
    side: str = Query("source", pattern="^(source|target)$"),
) -> DiscoverResponse:
    config = request.to_migration_config()
    if side == "source":
        connection = config.source
        schema_filter = list(config.mapping.schemas.keys()) or None
    else:
        connection = config.target
        schema_filter = list(config.mapping.schemas.values()) or None

    try:
        model = _run(
            _discovery_service.discover(connection, schema_filter, include_columns=True)
        )
    except MigrationValidatorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # driver / connectivity failures
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    summaries = [
        SchemaSummary(
            name=s.name,
            tables=len(s.tables),
            columns=sum(len(t.columns) for t in s.tables),
        )
        for s in model.schemas
    ]
    return DiscoverResponse(
        side=side,
        database_type=model.database_type,
        version=model.version,
        schemas=summaries,
        table_count=sum(s.tables for s in summaries),
    )


@router.post("/schemas", response_model=SchemaListResponse)
def list_schemas(request: ConnectionInput) -> SchemaListResponse:
    """Lightweight listing of the schemas visible to one connection (no tables/columns)."""
    try:
        model = _run(_discovery_service.list_schemas(request.to_config()))
    except MigrationValidatorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # driver / connectivity failures
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SchemaListResponse(
        database_type=model.database_type,
        version=model.version,
        schemas=[schema.name for schema in model.schemas],
    )


PLAN_STAGES = (
    ("Reading source", 45.0),
    ("Reading target", 45.0),
    ("Matching and saving", 10.0),
)
PROGRESS_ID = r"^[A-Za-z0-9_-]{8,64}$"


@router.post("/plan", response_model=PlanResponse)
def plan(
    request: MigrationRequest,
    progress_id: str | None = Query(None, pattern=PROGRESS_ID),
) -> PlanResponse:
    """Discover both databases and auto-match schemas/tables.

    With an explicit ``source_schemas`` / ``target_schemas`` scope, only the selected
    schemas are discovered and only schema/table names are collected (matching needs
    nothing else); columns, constraints, indexes and other objects are collected at
    validation time. Without a scope, the legacy full discovery is retained.

    A client-chosen ``progress_id`` lets the caller poll ``/plan/progress/{id}`` while
    this request is running.
    """
    progress = _progress.begin(progress_id, PLAN_STAGES)
    try:
        response = _plan(request, progress)
    except HTTPException as exc:
        progress.fail(str(exc.detail))
        raise
    except Exception as exc:
        progress.fail(str(exc))
        raise
    progress.complete("Discovery complete")
    return response


@router.get("/plan/progress/{progress_id}")
def plan_progress(progress_id: str = Path(pattern=PROGRESS_ID)) -> dict[str, Any]:
    """Current progress of a running Discover & match request."""
    snapshot = _progress.get(progress_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No progress recorded for this id.")
    return snapshot


def _plan(request: MigrationRequest, progress: ProgressReporter) -> PlanResponse:
    config = request.to_migration_config()
    scoped = config.source_schemas is not None or config.target_schemas is not None
    detail = {"include_columns": not scoped, "include_structural": not scoped}
    # Passed only when a client asked for progress, so other callers are unaffected.
    reporting = (lambda stage: {"on_progress": progress.callback(stage)}) if progress.enabled \
        else (lambda stage: {})
    try:
        source = _run(
            _discovery_service.discover(
                config.source, config.source_schemas, **detail,
                require_all_schemas=scoped, **reporting(0),
            )
        )
        target = _run(
            _discovery_service.discover(
                config.target, config.target_schemas, **detail,
                require_all_schemas=scoped, **reporting(1),
            )
        )
    except MigrationValidatorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # driver / connectivity failures
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    progress.update(2, 0.1, "Matching schemas and tables")
    catalog = Catalog()
    response = build_plan(source, target)
    progress.update(2, 0.4, "Saving discovered inventories")
    collected = [] if scoped else None
    response.source_inventory_id = catalog.save_inventory(
        config.source, source, collected=collected)
    response.target_inventory_id = catalog.save_inventory(
        config.target, target, collected=collected)
    progress.update(2, 0.8, "Saving mapping")
    previous = catalog.mappings(config.source, config.target)
    mapping = previous[0]["payload"] if previous else {
        "schemas": response.suggested_mapping, "tables": {}, "columns": {},
        "included_objects": [], "excluded_objects": [],
    }
    if scoped:
        mapping = _scope_mapping(mapping, source, response.suggested_mapping)
    response.mapping_version_id = catalog.save_mapping(
        config.source, config.target, response.source_inventory_id,
        response.target_inventory_id, mapping,
    )
    response.saved_mapping = MappingInput.model_validate(mapping)
    apply_plan_mapping(response, source, target, mapping)
    response.metadata_complete = not scoped
    response.source_scope = [schema.name for schema in source.schemas]
    response.target_scope = [schema.name for schema in target.schemas]
    return response


def _scope_mapping(mapping: dict, source, suggested: dict[str, str]) -> dict:
    """Restrict a restored mapping to the discovered source schemas.

    A saved mapping from an earlier, wider scope must not re-introduce schemas the user
    did not select. Selected schemas the saved mapping never mentioned get the
    auto-matched suggestion; explicit blank (skip) entries are preserved.
    """
    keep = {schema.name.casefold() for schema in source.schemas}

    def in_scope(key: str) -> bool:
        return key.split(".", 1)[0].strip().casefold() in keep

    restricted = dict(mapping)
    for field in ("schemas", "tables", "columns", "type_overrides", "validation_overrides"):
        restricted[field] = {
            key: value for key, value in mapping.get(field, {}).items() if in_scope(key)
        }
    for field in ("included_objects", "excluded_objects"):
        restricted[field] = [name for name in mapping.get(field, []) if in_scope(name)]
    known = {key.casefold() for key in restricted["schemas"]}
    for schema in source.schemas:
        if schema.name.casefold() not in known:
            restricted["schemas"][schema.name] = suggested.get(schema.name, "")
    return restricted


def apply_plan_mapping(response, source, target, mapping):
    target_by_name = {}
    for schema in target.schemas:
        target_by_name.setdefault(schema.name.casefold(), []).append(schema)
    schema_map = {
        key.casefold(): value.strip() for key, value in mapping.get("schemas", {}).items()
    }
    matches = []
    matched_targets = set()
    for schema in source.schemas:
        target_name = schema_map.get(schema.name.casefold(), "")
        target_schema, _, _ = _match_one(target_name, target.schemas, target_by_name)
        if target_schema is not None:
            match_type = (
                "exact" if schema.name == target_schema.name else
                "case_insensitive" if schema.name.casefold() == target_schema.name.casefold()
                else "explicit"
            )
            matches.append(_match_tables(schema, target_schema, match_type))
            matched_targets.add(target_schema.name)
        else:
            matches.append(SchemaMatch(
                source=schema.name, target=target_name, match_type="unmatched",
                unmatched_source_tables=[table.name for table in schema.tables],
            ))
    response.schema_matches = matches
    response.unmatched_source_schemas = []
    response.ambiguous_schemas = []
    response.unmatched_target_schemas = [
        schema.name for schema in target.schemas if schema.name not in matched_targets
    ]


@router.get("/connections")
def saved_connections():
    return Catalog().connections()


@router.post("/connections")
def save_connection(request: SavedConnectionInput):
    return Catalog().save_connection(request.model_dump(mode="json"))


@router.delete("/connections/{identifier}")
def delete_connection(identifier: str):
    Catalog().delete_connection(identifier)
    return {"deleted": True}


@router.post("/inventories/search")
def inventory_search(request: MigrationRequest):
    catalog = Catalog()
    return {"source": catalog.inventories(request.source),
            "target": catalog.inventories(request.target),
            "mappings": catalog.mappings(request.source, request.target),
            "runs": catalog.runs_for(request.source, request.target)}


@router.post("/inventories/plan")
def inventory_plan(request: MigrationRequest):
    catalog = Catalog()
    try:
        source = catalog.load_inventory(request.source_inventory_id, request.source)
        target = catalog.load_inventory(request.target_inventory_id, request.target)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    response = build_plan(source, target)
    response.source_inventory_id = request.source_inventory_id
    response.target_inventory_id = request.target_inventory_id
    try:
        response.metadata_complete = all(
            {"columns", "structural"}.issubset(catalog.inventory_collected(identifier, side))
            for identifier, side in (
                (request.source_inventory_id, request.source),
                (request.target_inventory_id, request.target),
            )
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    response.source_scope = [schema.name for schema in source.schemas]
    response.target_scope = [schema.name for schema in target.schemas]
    mapping = request.mapping.model_dump(mode="json")
    response.saved_mapping = request.mapping
    apply_plan_mapping(response, source, target, mapping)
    return response


@router.post("/mappings")
def save_mapping(request: MigrationRequest):
    catalog = Catalog()
    try:
        catalog.load_inventory(request.source_inventory_id, request.source, [])
        catalog.load_inventory(request.target_inventory_id, request.target, [])
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    identifier = catalog.save_mapping(
        request.source, request.target, request.source_inventory_id,
        request.target_inventory_id, request.mapping.model_dump(mode="json"),
    )
    return {"id": identifier}


@router.get("/catalog/runs")
def catalog_runs():
    return Catalog().runs()


@router.post("/catalog/backup")
def catalog_backup():
    return {"filename": Catalog().backup().name}


@router.post("/validations", status_code=202)
def submit_validation(
    request: MigrationRequest,
    http_request: Request,
    run_id: str | None = Query(None, pattern=r"^[a-f0-9]{12,32}$"),
) -> dict:
    worker = getattr(http_request.app.state, "validation_worker", None)
    if worker is None:
        raise HTTPException(503, "Background validation worker is unavailable")
    try:
        identifier = worker.submit(request.to_migration_config(), run_id)
    except ValidationBusyError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RunAlreadyExistsError as exc:
        raise HTTPException(409, "Run ID already exists") from exc
    except Exception as exc:
        raise HTTPException(
            503, "Unable to submit validation; check run history before retrying",
        ) from exc
    return {"run_id": identifier, "status_url": f"/api/runs/{identifier}"}


@router.post("/validate", response_model=ValidationReport)
def validate(
    request: MigrationRequest,
    run_id: str | None = Query(None, pattern=r"^[a-f0-9]{12,32}$"),
) -> ValidationReport:
    config = request.to_migration_config()
    try:
        run = _run(_migration_service.run_validation(
            config, profile=request.profile, run_id=run_id,
        ))
    except RunAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="Run ID already exists") from exc
    except MigrationValidatorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("validation_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    assert run.report is not None
    return run.report


@router.get("/runs")
def list_runs(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> list[dict]:
    catalog = Catalog()
    return [_catalog_run_state(run, catalog) for run in _run_logs.runs(limit, offset)]


def _catalog_run_state(run: dict, catalog: Catalog) -> dict:
    state = catalog.run_state(run["id"])
    if state is not None:
        run = {**run, "state": state["status"]}
        if state["status"] in {"failed", "interrupted"}:
            run.update(outcome=None, report_id=None)
    return run


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = _run_logs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not recorded or logs expired")
    return _catalog_run_state(run, Catalog())


@router.get("/runs/{run_id}/results")
def run_results(run_id: str, limit: int = Query(100, ge=1, le=500),
                offset: int = Query(0, ge=0)) -> dict:
    result = Catalog().partial_report(run_id, limit=limit, offset=offset)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not recorded in catalog")
    return result


@router.get("/runs/{run_id}/events")
def run_events(run_id: str, level: str = "", stage: str = "", query: str = "",
               limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict:
    get_run(run_id)
    return _run_logs.events(
        run_id, level=level, stage=stage, query=query, limit=limit, offset=offset,
    )


@router.get("/runs/{run_id}/download")
def download_run_logs(run_id: str) -> StreamingResponse:
    run = get_run(run_id)

    def lines():
        yield json.dumps({"run": run}) + "\n"
        offset = 0
        while True:
            batch = _run_logs.events(run_id, offset=offset, limit=500)["items"]
            if not batch:
                break
            for event in batch:
                yield json.dumps(event) + "\n"
            offset += len(batch)

    return StreamingResponse(
        lines(), media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="run-{run["id"]}.jsonl"'},
    )


@router.get("/reports", response_model=list[ReportListItem])
async def list_reports() -> list[ReportListItem]:
    """Summaries of every saved report, newest first (powers the Reports list)."""
    return [
        ReportListItem(
            migration_id=r.migration_id,
            migration_name=r.migration_name,
            generated_at=r.generated_at,
            profile=r.profile,
            overall_status=r.overall_status,
            total=r.summary.total,
            passed=r.summary.passed,
            failed=r.summary.failed,
            warning=r.summary.warning,
            duration_ms=r.duration_ms,
        )
        for r in _report_service.list_reports()
    ]


@router.get("/reports/{migration_id}.html", response_class=Response)
async def get_report_html(migration_id: str) -> Response:
    report = _load_or_404(migration_id)
    return Response(content=_report_service.render_html(report), media_type="text/html")


@router.get("/reports/{migration_id}.csv", response_class=PlainTextResponse)
async def get_report_csv(migration_id: str) -> Response:
    report = _load_or_404(migration_id)
    return Response(
        content=_report_service.render_csv(report),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="migration-{migration_id}.csv"'},
    )


@router.get("/reports/{migration_id}", response_model=ValidationReport)
async def get_report(migration_id: str) -> ValidationReport:
    return _load_or_404(migration_id)


def _load_or_404(migration_id: str) -> ValidationReport:
    path = _report_service.report_path(migration_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"No report for id '{migration_id}'")
    return _report_service.load(migration_id)


def _to_check(result) -> ConnectionCheck:
    return ConnectionCheck(
        success=result.success,
        database_type=result.database_type,
        version=result.version,
        latency_ms=result.latency_ms,
        message=result.message,
        error=result.error,
    )
