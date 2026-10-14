"""Base class for not-yet-implemented adapters.

Provides capability declarations while raising a clear, actionable error for any
operation. Concrete stubs set ``DB_TYPE`` and ``CAPABILITIES``.
"""

from __future__ import annotations

from app.adapters.base import DatabaseAdapter
from app.core.enums import DatabaseType
from app.core.exceptions import NotSupportedError
from app.models.capabilities import DatabaseCapabilities
from app.models.column import ColumnModel
from app.models.database import ConnectionResult, DatabaseInfo, QueryResult
from app.models.schema import SchemaModel
from app.models.table import TableModel


class StubAdapter(DatabaseAdapter):
    """An adapter placeholder whose implementation arrives in a later phase."""

    DB_TYPE: DatabaseType
    CAPABILITIES: DatabaseCapabilities

    def _not_implemented(self) -> NotSupportedError:
        return NotSupportedError(
            f"The '{self.DB_TYPE.value}' adapter is not implemented yet "
            f"(planned for a later phase)."
        )

    async def connect(self) -> None:
        raise self._not_implemented()

    async def close(self) -> None:
        return None

    async def test_connection(self) -> ConnectionResult:
        return ConnectionResult(
            success=False,
            database_type=self.DB_TYPE,
            message="Adapter not implemented.",
            error=str(self._not_implemented()),
        )

    async def get_database_info(self) -> DatabaseInfo:
        raise self._not_implemented()

    async def get_schemas(self, names: list[str] | None = None) -> list[SchemaModel]:
        raise self._not_implemented()

    async def get_tables(self, schema: str) -> list[TableModel]:
        raise self._not_implemented()

    async def get_columns(self, schema: str, table: str) -> list[ColumnModel]:
        raise self._not_implemented()

    async def get_row_count(self, schema: str, table: str) -> int:
        raise self._not_implemented()

    async def execute_query(self, sql: str, parameters: dict | None = None) -> QueryResult:
        raise self._not_implemented()

    def capabilities(self) -> DatabaseCapabilities:
        return self.CAPABILITIES
