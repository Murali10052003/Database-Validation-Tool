"""Abstract adapter interface.

An adapter is the *only* place database-specific SQL and driver code may live. The
interface is capability-aware: callers check :meth:`DatabaseAdapter.capabilities`
before requesting objects a database may not support.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from types import TracebackType

from app.adapters._profile import KeyRange, ProfileRequest, TableProfile
from app.core.config import DatabaseConnectionConfig
from app.core.exceptions import NotSupportedError, QueryError, QueryTimeoutError
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


class DatabaseAdapter(ABC):
    """Canonical interface every database adapter implements."""

    def __init__(self, config: DatabaseConnectionConfig) -> None:
        self.config = config

    # -- lifecycle ---------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Open a connection (or pool) to the database."""

    @abstractmethod
    async def close(self) -> None:
        """Close the connection and release resources."""

    async def __aenter__(self) -> DatabaseAdapter:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    # -- connectivity / identity ------------------------------------------

    @abstractmethod
    async def test_connection(self) -> ConnectionResult:
        """Attempt to connect and run a trivial query; never raise on failure."""

    @abstractmethod
    async def get_database_info(self) -> DatabaseInfo:
        """Return engine type, platform and version."""

    # -- structural discovery ---------------------------------------------

    @abstractmethod
    async def get_schemas(self, names: list[str] | None = None) -> list[SchemaModel]:
        """Return the schemas visible to the connection (without child objects).

        ``names`` restricts the catalog query itself to those schemas (matched
        case-insensitively); ``None`` returns every visible schema.
        """

    @abstractmethod
    async def get_tables(self, schema: str) -> list[TableModel]:
        """Return tables in ``schema`` (without columns)."""

    @abstractmethod
    async def get_columns(self, schema: str, table: str) -> list[ColumnModel]:
        """Return columns of ``schema.table`` in ordinal order."""

    async def get_indexes(self, schema: str, table: str) -> list[IndexModel]:
        """Return indexes of ``schema.table``. Default: none (Phase 2)."""
        return []

    async def get_constraints(self, schema: str, table: str) -> list[ConstraintModel]:
        """Return constraints of ``schema.table``. Default: none (Phase 2)."""
        return []

    async def get_sequences(self, schema: str) -> list[SequenceModel]:
        """Return sequences in ``schema``. Default: none (Phase 2)."""
        return []

    async def get_views(self, schema: str) -> list[ViewModel]:
        """Return views in ``schema``. Default: none (Phase 4)."""
        return []

    async def get_routines(self, schema: str) -> list[RoutineModel]:
        """Return routines in ``schema``. Default: none (Phase 4)."""
        return []

    async def get_triggers(self, schema: str) -> list[TriggerModel]:
        """Return triggers in ``schema``. Default: none (Phase 4)."""
        return []

    async def get_partitions(self, schema: str) -> list[PartitionModel]:
        """Return partitions in ``schema``. Default: none (Phase 4)."""
        return []

    # -- data access -------------------------------------------------------

    @abstractmethod
    async def get_row_count(self, schema: str, table: str) -> int:
        """Return the exact row count of ``schema.table``."""

    async def get_row_count_with_timeout(
        self, schema: str, table: str, timeout_seconds: float | None
    ) -> int:
        """Exact row count that gives up after ``timeout_seconds`` (see :meth:`run_bounded`)."""
        return await self.run_bounded(
            timeout_seconds,
            lambda: self.get_row_count(schema, table),
            f"Row count of {schema}.{table}",
        )

    async def run_bounded[T](
        self,
        timeout_seconds: float | None,
        call: Callable[[], Awaitable[T]],
        description: str,
    ) -> T:
        """Run ``call`` with a per-query time limit.

        Adapters enable the driver's own query timeout through the hooks below so the
        database stops the query; the default is a client-side timeout. Raises
        :class:`QueryTimeoutError` when the limit is hit. ``call`` may issue several
        statements; the limit applies to each of them.
        """
        if not timeout_seconds or timeout_seconds <= 0:
            return await call()
        native = False
        try:
            native = await self._apply_statement_timeout(timeout_seconds)
            if native:
                return await call()
            async with asyncio.timeout(timeout_seconds):
                return await call()
        except TimeoutError as exc:
            await self._recover_from_timeout()
            raise QueryTimeoutError(f"{description} exceeded {timeout_seconds:g}s") from exc
        except QueryError as exc:
            if isinstance(exc, QueryTimeoutError) or not self._is_timeout_error(exc):
                raise
            await self._recover_from_timeout()
            raise QueryTimeoutError(f"{description} exceeded {timeout_seconds:g}s") from exc
        finally:
            if native:
                await self._clear_statement_timeout()

    async def get_table_profile(
        self,
        schema: str,
        table: str,
        request: ProfileRequest,
        key_range: KeyRange | None = None,
    ) -> TableProfile:
        """Row count, NULL counts and numeric aggregates of one table.

        Real adapters answer this with a single scan; the default composes it from the
        individual data-access methods (one query each) and cannot restrict to a key range.
        """
        if key_range is not None:
            raise NotSupportedError("This adapter cannot profile a key range")
        profile = TableProfile()
        if request.count:
            profile.row_count = await self.get_row_count(schema, table)
        if request.null_columns:
            profile.null_counts = await self.get_null_counts(
                schema, table, list(request.null_columns)
            )
        for column in request.aggregate_columns:
            profile.aggregates[column] = await self.get_numeric_aggregates(schema, table, column)
        return profile

    async def get_key_range(
        self, schema: str, table: str, column: str
    ) -> tuple[object, object] | None:
        """``(min, max)`` of a key column, ``None`` if the table is empty."""
        raise NotSupportedError("This adapter cannot read a key range")

    async def get_null_count_estimates(
        self, schema: str, table: str, columns: list[str]
    ) -> dict[str, int]:
        """Approximate NULL counts from database statistics (columns without any are omitted).

        Estimates can be stale or inexact and must never be presented as verified counts.
        """
        return {}

    async def get_row_count_estimate(self, schema: str, table: str) -> int | None:
        """Approximate row count from database statistics, without scanning the table.

        Returns ``None`` when no statistics exist. The value can be stale or inexact and
        must never be presented as a verified count. Default: unsupported.
        """
        return None

    # Hooks used by get_row_count_with_timeout; override per driver.

    async def _apply_statement_timeout(self, seconds: float) -> bool:
        """Enable a native per-query timeout. Return False if the driver has none."""
        return False

    async def _clear_statement_timeout(self) -> None:
        """Undo :meth:`_apply_statement_timeout`."""
        return None

    def _is_timeout_error(self, exc: Exception) -> bool:
        """Whether a driver error means the query hit the native timeout."""
        return False

    async def _recover_from_timeout(self) -> None:
        """Restore the connection to a usable state after a timeout."""
        return None

    async def get_null_counts(
        self, schema: str, table: str, columns: list[str]
    ) -> dict[str, int]:
        """Return the NULL count of each named column. Default: empty (Phase 2)."""
        return {}

    async def get_numeric_aggregates(
        self, schema: str, table: str, column: str
    ) -> dict[str, object]:
        """Return ``min``/``max``/``sum``/``count`` for a numeric column. Default: empty."""
        return {}

    async def fetch_rows(
        self,
        schema: str,
        table: str,
        columns: list[str],
        order_by: list[str],
        limit: int | None = None,
    ) -> list[tuple]:
        """Return ordered rows of the given columns. Default: empty (Phase 3)."""
        return []

    async def count_orphans(
        self,
        child_schema: str,
        child_table: str,
        fk_columns: list[str],
        ref_schema: str | None,
        ref_table: str,
        ref_columns: list[str],
    ) -> int:
        """Return child rows whose non-null FK has no matching parent. Default: 0."""
        return 0

    @abstractmethod
    async def execute_query(
        self, sql: str, parameters: dict | None = None
    ) -> QueryResult:
        """Execute an arbitrary read query and return the rows."""

    # -- capabilities ------------------------------------------------------

    @abstractmethod
    def capabilities(self) -> DatabaseCapabilities:
        """Return the feature-support matrix for this database."""
