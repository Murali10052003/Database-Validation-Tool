"""Azure Database for PostgreSQL adapter implementation (target, Phase 1)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.adapters._helpers import maybe_await
from app.adapters._profile import KeyRange, ProfileRequest, TableProfile
from app.adapters.azure_postgresql.capabilities import AZURE_POSTGRESQL_CAPABILITIES
from app.adapters.azure_postgresql.data import PostgreSQLDataAccessor
from app.adapters.azure_postgresql.entra import fetch_entra_token
from app.adapters.azure_postgresql.metadata import PostgreSQLMetadataCollector
from app.adapters.azure_postgresql.type_mapping import get_normalizer
from app.adapters.base import DatabaseAdapter
from app.core.config import DatabaseConnectionConfig
from app.core.enums import AuthMethod, DatabaseType, DeploymentPlatform
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


class AzurePostgreSQLAdapter(DatabaseAdapter):
    """Adapter for Azure Database for PostgreSQL using async ``psycopg`` (v3)."""

    def __init__(self, config: DatabaseConnectionConfig) -> None:
        super().__init__(config)
        self._connection: Any | None = None
        self._normalizer = get_normalizer()
        self._metadata = PostgreSQLMetadataCollector(self._fetch, self._normalizer)
        self._data = PostgreSQLDataAccessor(self._fetch)
        self._saved_statement_timeout: str | None = None

    # -- lifecycle ---------------------------------------------------------

    async def _create_connection(self) -> Any:
        """Open a raw async PostgreSQL connection. Overridable in tests."""
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - import guard
            raise DriverNotInstalledError("azure_postgresql", "psycopg[binary]") from exc

        # Azure Database for PostgreSQL requires TLS.
        require_tls = self.config.ssl or self.config.platform == DeploymentPlatform.AZURE
        sslmode = "require" if require_tls else "prefer"
        return await psycopg.AsyncConnection.connect(
            host=self.config.host,
            port=self.config.port or 5432,
            dbname=self.config.database,
            user=self.config.username,
            password=await self._resolve_password(),
            connect_timeout=self.config.connect_timeout_seconds,
            sslmode=self.config.options.get("sslmode", sslmode),
            autocommit=True,
        )

    async def _resolve_password(self) -> str:
        """Return the connection secret: an Entra token or the configured password."""
        if self.config.auth_method == AuthMethod.ENTRA:
            if self.config.entra_browser_auth:
                if not self.config.entra_token or not self.config.entra_token_expires_at:
                    raise ConnectionError(
                        "Microsoft sign-in is required. Test this connection again."
                    )
                if self.config.entra_token_expires_at <= time.time() + 30:
                    raise ConnectionError(
                        "Microsoft sign-in has expired. Test this connection again."
                    )
                return self.config.entra_token.get_secret_value()
            client_id = self.config.options.get("managed_identity_client_id")
            # Token acquisition is blocking; keep the event loop responsive.
            return await asyncio.to_thread(fetch_entra_token, client_id)
        return self.config.password.get_secret_value()

    async def connect(self) -> None:
        if self._connection is not None:
            return
        try:
            self._connection = await self._create_connection()
        except DriverNotInstalledError:
            raise
        except Exception as exc:
            if self.config.entra_browser_auth:
                raise ConnectionError(
                    "PostgreSQL connection failed. Check Microsoft sign-in, token expiry, "
                    "database role, host, and TLS/network access."
                ) from None
            raise ConnectionError(f"Failed to connect to Azure PostgreSQL: {exc}") from exc

    async def close(self) -> None:
        if self._connection is not None:
            await maybe_await(self._connection.close())
            self._connection = None

    # -- query plumbing ----------------------------------------------------

    async def _fetch(self, sql: str, parameters: dict | None = None) -> QueryResult:
        if self._connection is None:
            raise ConnectionError("Azure PostgreSQL adapter is not connected.")
        cursor = self._connection.cursor()
        try:
            await maybe_await(cursor.execute(sql, parameters or {}))
            description = cursor.description
            rows = await maybe_await(cursor.fetchall())
        except Exception as exc:
            raise QueryError(f"PostgreSQL query failed: {exc}") from exc
        finally:
            await maybe_await(cursor.close())
        columns = [_column_name(d) for d in (description or [])]
        tuple_rows = [tuple(r) for r in (rows or [])]
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
                database_type=DatabaseType.AZURE_POSTGRESQL,
                version=info.version,
                message="Connection successful.",
                latency_ms=round(latency, 2),
            )
        except Exception as exc:
            return ConnectionResult(
                success=False,
                database_type=DatabaseType.AZURE_POSTGRESQL,
                error=str(exc),
                message="Connection failed.",
            )

    async def get_database_info(self) -> DatabaseInfo:
        await self.connect()
        result = await self._fetch("SELECT version()", None)
        version = result.scalar()
        return DatabaseInfo(
            database_type=DatabaseType.AZURE_POSTGRESQL,
            platform=DeploymentPlatform.AZURE,
            version=str(version) if version else None,
            default_schema="public",
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
        current = await self._fetch("SELECT current_setting('statement_timeout')", None)
        self._saved_statement_timeout = str(current.scalar() or "0")
        await self._fetch(
            "SELECT set_config('statement_timeout', %(ms)s, false)",
            {"ms": str(max(1, int(seconds * 1000)))},
        )
        return True

    async def _clear_statement_timeout(self) -> None:
        saved, self._saved_statement_timeout = self._saved_statement_timeout, None
        if saved is None or self._connection is None:
            return
        try:
            await self._fetch(
                "SELECT set_config('statement_timeout', %(value)s, false)", {"value": saved}
            )
        except Exception as exc:  # the connection is not reusable anyway
            logger.warning("statement_timeout_restore_failed", extra={"error": str(exc)})

    def _is_timeout_error(self, exc: Exception) -> bool:
        # SQLSTATE 57014 is also a user cancel; "statement timeout" identifies the limit.
        return "statement timeout" in str(exc).lower()

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
        return AZURE_POSTGRESQL_CAPABILITIES


def _column_name(descriptor: Any) -> str:
    """Extract a column name from a DBAPI/psycopg description entry."""
    name = getattr(descriptor, "name", None)
    if name is not None:
        return name
    return descriptor[0]
