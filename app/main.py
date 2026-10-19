"""FastAPI application for the migration-validation web POC.

Run with:  uvicorn app.main:app --reload
or:        migration-validator-web
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock

from app.api.routes import router
from app.core.catalog import Catalog
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.background_validation import BackgroundValidation
from app.services.migration_service import MigrationService

_STATIC_DIR = Path(__file__).parent / "web" / "static"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(application):
        catalog = Catalog(settings.catalog_path)
        ownership = FileLock(str(settings.catalog_path) + ".worker.lock", thread_local=False)
        ownership.acquire(timeout=0)
        worker = BackgroundValidation(MigrationService(settings), ownership=ownership)
        application.state.validation_worker = worker
        try:
            catalog.recover_runs()
            yield
        finally:
            await asyncio.to_thread(worker.shutdown)

    app = FastAPI(
        title="Database Migration Validation",
        description="POC UI for validating Oracle → Azure PostgreSQL migrations.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        errors = [
            {"loc": error["loc"], "type": error["type"], "msg": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    return app


app = create_app()

