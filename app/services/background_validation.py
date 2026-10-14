from __future__ import annotations

import asyncio
import sys
import threading
import uuid

from filelock import FileLock
from pydantic import SecretStr

from app.core.catalog import Catalog
from app.core.config import MigrationConfig
from app.services.migration_service import MigrationRun, MigrationService
from app.services.run_log_service import error_code


class ValidationBusyError(RuntimeError):
    pass


class BackgroundValidation:
    def __init__(self, service: MigrationService, ownership: FileLock | None = None):
        self.service = service
        self._ownership = ownership
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._closed = False

    def submit(self, config: MigrationConfig, run_id: str | None = None) -> str:
        with self._lock:
            if self._closed or self._thread is not None:
                raise ValidationBusyError(
                    "A validation is already active or the worker is stopping",
                )
            run = self.service.prepare_background_run(config, run_id or uuid.uuid4().hex[:12])
            self._thread = threading.Thread(
                target=self._execute, args=(run,), name=f"validation-{run.id}", daemon=True,
            )
            try:
                self._thread.start()
            except BaseException as exc:
                self._thread = None
                try:
                    self._fail(run, exc)
                finally:
                    self._clear_credentials(run)
                raise
            return run.id

    def _execute(self, run: MigrationRun):
        loop = asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            with self._lock:
                self._loop = loop
                self._task = loop.create_task(
                    self.service.run_validation(run.config, prepared_run=run),
                )
                if self._closed:
                    self._task.cancel()
                task = self._task
            loop.run_until_complete(task)
        except BaseException as exc:
            self._fail(run, exc)
        finally:
            self._clear_credentials(run)
            with self._lock:
                self._loop = None
                self._task = None
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()
                with self._lock:
                    self._thread = None
                    if self._closed and self._ownership is not None:
                        self._ownership.release()

    def _fail(self, run: MigrationRun, exc: BaseException):
        try:
            state = Catalog().run_state(run.id)
            if state and state["status"] in {"queued", "running"}:
                if isinstance(exc, asyncio.CancelledError):
                    Catalog().interrupt_run(run.id)
                    self.service._logs.finish(run.id, "interrupted")
                else:
                    Catalog().finish_run(run.id, error=error_code(exc))
                    self.service._logs.finish(run.id, "failed")
        finally:
            if run.report is None:
                run.status = "interrupted" if isinstance(exc, asyncio.CancelledError) else "failed"

    @staticmethod
    def _clear_credentials(run: MigrationRun):
        for connection in (run.config.source, run.config.target):
            connection.password = SecretStr("")
            connection.entra_token = None
            connection.entra_token_expires_at = None

    def shutdown(self):
        with self._lock:
            self._closed = True
            thread = self._thread
            if self._loop is not None and self._task is not None:
                self._loop.call_soon_threadsafe(self._task.cancel)
        if thread is not None:
            thread.join(timeout=5)
        with self._lock:
            if self._thread is None and self._ownership is not None:
                self._ownership.release()