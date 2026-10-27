"""MySQL adapter implementation (source database).

Uses the synchronous ``mysql-connector-python`` driver; its cursor calls are made
uniform with the async adapters via :func:`maybe_await`.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from app.adapters._helpers import maybe_await
from app.adapters._profile import KeyRange, ProfileRequest, TableProfile
from app.adapters.base import DatabaseAdapter
from app.adapters.mysql.capabilities import MYSQL_CAPABILITIES
from app.adapters.mysql.data import MySQLDataAccessor
from app.adapters.mysql.metadata import MySQLMetadataCollector
from app.adapters.mysql.type_mapping import get_normalizer
from app.core.config import DatabaseConnectionConfig
from app.core.enums import DatabaseType, DeploymentPlatform
from app.core.exceptions import ConnectionError, DriverNotInstalledError, QueryError
from app.core.logging import get_logger
from app.models.capabilities import DatabaseCapabilities
from app.models.column import ColumnModel
from app.models.constraint import ConstraintModel
from app.models.database import ConnectionResult, DatabaseInfo, QueryResult
from app.models.index import IndexModel
from app.models.schema import SchemaModel
from app.models.table import TableModel

logger = get_logger(__name__)


class MySQLAdapter(DatabaseAdapter):
    """Adapter for MySQL using ``mysql-connector-python``."""

    DB_TYPE: DatabaseType = DatabaseType.MYSQL
    DEFAULT_PLATFORM: DeploymentPlatform = DeploymentPlatform.SELF_MANAGED
    DISPLAY_NAME = "MySQL"

    def __init__(self, config: DatabaseConnectionConfig) -> None:
        super().__init__(config)
        self._connection: Any | None = None
        self._normalizer = get_normalizer()
        self._metadata = MySQLMetadataCollector(self._fetch, self._normalizer)
        self._data = MySQLDataAccessor(self._fetch)
        self._saved_max_execution_time: int | None = None

    async def _create_connection(self) -> Any:
        """Open a raw MySQL connection. Overridable in tests."""
        try:
            import mysql.connector
        except ImportError as exc:  # pragma: no cover - import guard
            raise DriverNotInstalledError("mysql", "mysql-connector-python") from exc
        return mysql.connector.connect(
            host=self.config.host,
            port=self.config.port or 3306,
            user=self.config.username,
            password=self.config.password.get_secret_value(),
            database=self.config.database,
            connection_timeout=self.config.connect_timeout_seconds,
        )

    async def connect(self) -> None:
        if self._connection is not None:
            return
        try:
            self._connection = await self._create_connection()
        except DriverNotInstalledError:
            raise
        except Exception as exc:
            raise ConnectionError(f"Failed to connect to {self.DISPLAY_NAME}: {exc}") from exc

    async def close(self) -> None:
        if self._connection is not None:
            await maybe_await(self._connection.close())
            self._connection = None

    async def _fetch(self, sql: str, parameters: dict | None = None) -> QueryResult:
        if self._connection is None:
            raise ConnectionError("MySQL adapter is not connected.")
        cursor = self._connection.cursor()
        try:
            await maybe_await(cursor.execute(sql, parameters or {}))
            description = cursor.description
            rows = await maybe_await(cursor.fetchall())
        except Exception as exc:
            raise QueryError(f"MySQL query failed: {exc}") from exc
        finally:
            await maybe_await(cursor.close())
        columns = [d[0] for d in (description or [])]
        tuple_rows = [tuple(r) for r in (rows or [])]
        return QueryResult(columns=columns, rows=tuple_rows, row_count=len(tuple_rows))

    async def test_connection(self) -> ConnectionResult:
        start = time.perf_counter()
        try:
            await self.connect()
            info = await self.get_database_info()
            latency = (time.perf_counter() - start) * 1000
            return ConnectionResult(
                success=True,
                database_type=self.DB_TYPE,
                version=info.version,
                message="Connection successful.",
                latency_ms=round(latency, 2),
            )
        except Exception as exc:
            return ConnectionResult(
                success=False,
                database_type=self.DB_TYPE,
                error=str(exc),
                message="Connection failed.",
            )

    async def get_database_info(self) -> DatabaseInfo:
        await self.connect()
        result = await self._fetch("SELECT VERSION()", None)
        version = result.scalar()
        return DatabaseInfo(
            database_type=self.DB_TYPE,
            platform=self.DEFAULT_PLATFORM,
            version=str(version) if version else None,
            default_schema=self.config.database,
        )

    async def get_schemas(self, names: list[str] | None = None) -> list[SchemaModel]:
        await self.connect()
        return await self._metadata.get_schemas(names)

    async def get_tables(self, schema: str) -> list[TableModel]:
        await self.connect()
        return await self._metadata.get_tables(schema)

    async def get_columns(self, schema: str, table: str) -> list[ColumnModel]:
        await self.connect()
        return await self._metadata.get_columns(schema, table)

    async def get_constraints(self, schema: str, table: str) -> list[ConstraintModel]:
        await self.connect()
        return await self._metadata.get_constraints(schema, table)

    async def get_indexes(self, schema: str, table: str) -> list[IndexModel]:
        await self.connect()
        return await self._metadata.get_indexes(schema, table)

    async def get_row_count_estimate(self, schema: str, table: str) -> int | None:
        await self.connect()
        return await self._data.get_row_count_estimate(schema, table)

    async def _apply_statement_timeout(self, seconds: float) -> bool:
        await self.connect()
        try:
            current = await self._fetch("SELECT @@SESSION.max_execution_time", None)
            self._saved_max_execution_time = int(current.scalar() or 0)
            await self._exec(f"SET SESSION max_execution_time = {max(1, int(seconds * 1000))}")
        except Exception:  # e.g. MariaDB, which uses max_statement_time instead
            self._saved_max_execution_time = None
            return False
        return True

    async def _clear_statement_timeout(self) -> None:
        saved, self._saved_max_execution_time = self._saved_max_execution_time, None
        if saved is not None and self._connection is not None:
            with contextlib.suppress(Exception):
                await self._exec(f"SET SESSION max_execution_time = {saved}")

    async def _exec(self, sql: str) -> None:
        assert self._connection is not None
        cursor = self._connection.cursor()
        try:
            await maybe_await(cursor.execute(sql))
        finally:
            await maybe_await(cursor.close())

    def _is_timeout_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return "3024" in text or "maximum statement execution time" in text

    async def get_row_count(self, schema: str, table: str) -> int:
        await self.connect()
        return await self._data.get_row_count(schema, table)

    async def get_table_profile(
        self,
        schema: str,
        table: str,
        request: ProfileRequest,
        key_range: KeyRange | None = None,
    ) -> TableProfile:
        await self.connect()
        return await self._data.get_table_profile(schema, table, request, key_range)

    async def get_key_range(
        self, schema: str, table: str, column: str
    ) -> tuple[object, object] | None:
        await self.connect()
        return await self._data.get_key_range(schema, table, column)
    async def get_null_counts(
        self, schema: str, table: str, columns: list[str]
    ) -> dict[str, int]:
        await self.connect()
        return await self._data.get_null_counts(schema, table, columns)

    async def get_numeric_aggregates(
        self, schema: str, table: str, column: str
    ) -> dict[str, object]:
        await self.connect()
        return await self._data.get_numeric_aggregates(schema, table, column)

    async def fetch_rows(
        self,
        schema: str,
        table: str,
        columns: list[str],
        order_by: list[str],
        limit: int | None = None,
    ) -> list[tuple]:
        await self.connect()
        return await self._data.fetch_rows(schema, table, columns, order_by, limit)

    async def count_orphans(
        self,
        child_schema: str,
        child_table: str,
        fk_columns: list[str],
        ref_schema: str | None,
        ref_table: str,
        ref_columns: list[str],
    ) -> int:
        await self.connect()
        return await self._data.count_orphans(
            child_schema, child_table, fk_columns, ref_schema, ref_table, ref_columns
        )

    async def execute_query(self, sql: str, parameters: dict | None = None) -> QueryResult:
        await self.connect()
        return await self._fetch(sql, parameters)

    def capabilities(self) -> DatabaseCapabilities:
        return MYSQL_CAPABILITIES
