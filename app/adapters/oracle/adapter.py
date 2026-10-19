"""Oracle adapter implementation (source database, Phase 1)."""

from __future__ import annotations

import contextlib
import time
from typing import Any

from app.adapters._helpers import maybe_await
from app.adapters._profile import KeyRange, ProfileRequest, TableProfile
from app.adapters.base import DatabaseAdapter
from app.adapters.oracle.capabilities import ORACLE_CAPABILITIES
from app.adapters.oracle.data import OracleDataAccessor
from app.adapters.oracle.metadata import OracleMetadataCollector
from app.adapters.oracle.type_mapping import get_normalizer
from app.core.config import DatabaseConnectionConfig
from app.core.enums import DatabaseType, DeploymentPlatform
from app.core.exceptions import ConnectionError, DriverNotInstalledError, QueryError
from app.core.logging import get_logger
from app.models.capabilities import DatabaseCapabilities
from app.models.column import ColumnModel
from app.models.constraint import ConstraintModel
from app.models.database import ConnectionResult, DatabaseInfo, QueryResult
from app.models.index import IndexModel
from app.models.partition import PartitionModel
from app.models.routine import RoutineModel
from app.models.schema import SchemaModel
from app.models.sequence import SequenceModel
from app.models.table import TableModel
from app.models.trigger import TriggerModel
from app.models.view import ViewModel

logger = get_logger(__name__)


class OracleAdapter(DatabaseAdapter):
    """Adapter for Oracle Database using the async ``python-oracledb`` driver."""

    def __init__(self, config: DatabaseConnectionConfig) -> None:
        super().__init__(config)
        self._connection: Any | None = None
        self._normalizer = get_normalizer()
        self._metadata = OracleMetadataCollector(self._fetch, self._normalizer)
        self._data = OracleDataAccessor(self._fetch)

    # -- lifecycle ---------------------------------------------------------

    async def _create_connection(self) -> Any:
        """Open a raw async Oracle connection. Overridable in tests."""
        try:
            import oracledb
        except ImportError as exc:  # pragma: no cover - import guard
            raise DriverNotInstalledError("oracle", "oracledb") from exc

        dsn = oracledb.makedsn(
            self.config.host,
            self.config.port or 1521,
            service_name=self.config.service,
        )
        return await oracledb.connect_async(
            user=self.config.username,
            password=self.config.password.get_secret_value(),
            dsn=dsn,
            tcp_connect_timeout=self.config.connect_timeout_seconds,
        )

    async def connect(self) -> None:
        if self._connection is not None:
            return
        try:
            self._connection = await self._create_connection()
        except DriverNotInstalledError:
            raise
        except Exception as exc:
            raise ConnectionError(f"Failed to connect to Oracle: {exc}") from exc

    async def close(self) -> None:
        if self._connection is not None:
            await maybe_await(self._connection.close())
            self._connection = None

    # -- query plumbing ----------------------------------------------------

    async def _fetch(self, sql: str, parameters: dict | None = None) -> QueryResult:
        if self._connection is None:
            raise ConnectionError("Oracle adapter is not connected.")
        cursor = self._connection.cursor()
        try:
            await maybe_await(cursor.execute(sql, parameters or {}))
            description = cursor.description
            rows = await maybe_await(cursor.fetchall())
            lob_columns = {
                index for index, column in enumerate(description or [])
                if len(column) > 1 and getattr(column[1], "name", None)
                in {"DB_TYPE_CLOB", "DB_TYPE_NCLOB", "DB_TYPE_BLOB", "DB_TYPE_BFILE"}
            }
            # Materialize locators while the cursor/session is available.
            tuple_rows = []
            for row in rows or []:
                values = list(row)
                for index in lob_columns:
                    value = values[index]
                    if value is not None and not isinstance(value, (str, bytes)):
                        values[index] = await maybe_await(value.read())
                tuple_rows.append(tuple(values))
        except Exception as exc:
            raise QueryError(f"Oracle query failed: {exc}") from exc
        finally:
            await maybe_await(cursor.close())
        columns = [d[0] for d in (description or [])]
        return QueryResult(columns=columns, rows=tuple_rows, row_count=len(tuple_rows))

    # -- connectivity / identity ------------------------------------------

    async def test_connection(self) -> ConnectionResult:
        start = time.perf_counter()
        try:
            await self.connect()
            info = await self.get_database_info()
            latency = (time.perf_counter() - start) * 1000
            return ConnectionResult(
                success=True,
                database_type=DatabaseType.ORACLE,
                version=info.version,
                message="Connection successful.",
                latency_ms=round(latency, 2),
            )
        except Exception as exc:
            return ConnectionResult(
                success=False,
                database_type=DatabaseType.ORACLE,
                error=str(exc),
                message="Connection failed.",
            )

    async def get_database_info(self) -> DatabaseInfo:
        await self.connect()
        assert self._connection is not None
        version = getattr(self._connection, "version", None)
        platform = (
            self.config.platform
            if self.config.platform != DeploymentPlatform.UNKNOWN
            else DeploymentPlatform.SELF_MANAGED
        )
        return DatabaseInfo(
            database_type=DatabaseType.ORACLE,
            platform=platform,
            version=str(version) if version else None,
            default_schema=self.config.username.upper(),
        )

    # -- structural discovery ---------------------------------------------

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

    async def get_sequences(self, schema: str) -> list[SequenceModel]:
        await self.connect()
        return await self._metadata.get_sequences(schema)

    async def get_views(self, schema: str) -> list[ViewModel]:
        await self.connect()
        return await self._metadata.get_views(schema)

    async def get_routines(self, schema: str) -> list[RoutineModel]:
        await self.connect()
        return await self._metadata.get_routines(schema)

    async def get_triggers(self, schema: str) -> list[TriggerModel]:
        await self.connect()
        return await self._metadata.get_triggers(schema)

    async def get_partitions(self, schema: str) -> list[PartitionModel]:
        await self.connect()
        return await self._metadata.get_partitions(schema)

    # -- data access -------------------------------------------------------

    async def get_row_count_estimate(self, schema: str, table: str) -> int | None:
        await self.connect()
        return await self._data.get_row_count_estimate(schema, table)

    async def _apply_statement_timeout(self, seconds: float) -> bool:
        await self.connect()
        assert self._connection is not None
        self._connection.call_timeout = max(1, int(seconds * 1000))
        return True

    async def _clear_statement_timeout(self) -> None:
        if self._connection is not None:
            with contextlib.suppress(Exception):  # connection already torn down by the timeout
                self._connection.call_timeout = 0

    def _is_timeout_error(self, exc: Exception) -> bool:
        text = str(exc)
        return "DPY-4024" in text or "ORA-03156" in text or "call timeout" in text.lower()

    async def _recover_from_timeout(self) -> None:
        # A call timeout can leave the session unusable; drop it so the next call reconnects.
        connection, self._connection = self._connection, None
        if connection is not None:
            with contextlib.suppress(Exception):
                await maybe_await(connection.close())

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
    async def get_null_count_estimates(
        self, schema: str, table: str, columns: list[str]
    ) -> dict[str, int]:
        await self.connect()
        return await self._data.get_null_count_estimates(schema, table, columns)
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

    # -- capabilities ------------------------------------------------------

    def capabilities(self) -> DatabaseCapabilities:
        return ORACLE_CAPABILITIES
