"""Shared pytest fixtures and test doubles."""

from __future__ import annotations

import pytest

from app.adapters.base import DatabaseAdapter
from app.core.config import DatabaseConnectionConfig
from app.core.enums import DatabaseType, DeploymentPlatform
from app.models.capabilities import DatabaseCapabilities
from app.models.column import ColumnModel
from app.models.database import ConnectionResult, DatabaseInfo, QueryResult
from app.models.schema import SchemaModel
from app.models.table import TableModel


@pytest.fixture(autouse=True)
def isolated_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("MV_CATALOG_PATH", str(tmp_path / "catalog.sqlite3"))


class FakeCursor:
    """A synchronous cursor whose results are awaited via ``maybe_await``."""

    def __init__(self, script: dict[str, tuple[list[str], list[tuple]]]) -> None:
        self._script = script
        self.description: list[tuple] | None = None
        self._rows: list[tuple] = []

    def execute(self, sql: str, parameters: dict | None = None) -> None:
        columns, rows = self._script.get(sql, ([], []))
        self.description = [(c,) for c in columns]
        self._rows = rows

    def fetchall(self) -> list[tuple]:
        return self._rows

    def close(self) -> None:  # noqa: D401 - simple stub
        return None


class FakeConnection:
    """A fake DB connection returning scripted cursor results."""

    def __init__(self, script: dict[str, tuple[list[str], list[tuple]]], version: str = "1.0") -> None:
        self._script = script
        self.version = version

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._script)

    def close(self) -> None:
        return None


class MockAdapter(DatabaseAdapter):
    """An in-memory adapter used to drive discovery/validation tests."""

    def __init__(
        self,
        database_type: DatabaseType,
        schemas: list[SchemaModel],
        *,
        capabilities: DatabaseCapabilities | None = None,
        connect_ok: bool = True,
    ) -> None:
        self.config = None  # type: ignore[assignment]
        self._type = database_type
        self._schemas = schemas
        self._caps = capabilities or DatabaseCapabilities()
        self._connect_ok = connect_ok
        self._schema_map = {s.name: s for s in schemas}

    async def connect(self) -> None:
        if not self._connect_ok:
            raise RuntimeError("boom")

    async def close(self) -> None:
        return None

    async def test_connection(self) -> ConnectionResult:
        return ConnectionResult(
            success=self._connect_ok,
            database_type=self._type,
            version="test",
            error=None if self._connect_ok else "unreachable",
        )

    async def get_database_info(self) -> DatabaseInfo:
        return DatabaseInfo(database_type=self._type, version="test")

    async def get_schemas(self, names: list[str] | None = None) -> list[SchemaModel]:
        wanted = None if names is None else {n.casefold() for n in names}
        return [
            SchemaModel(name=s.name) for s in self._schemas
            if wanted is None or s.name.casefold() in wanted
        ]

    async def get_tables(self, schema: str) -> list[TableModel]:
        s = self._schema_map.get(schema)
        return [TableModel(schema_name=t.schema_name, name=t.name) for t in (s.tables if s else [])]

    async def get_columns(self, schema: str, table: str) -> list[ColumnModel]:
        found = self._find_table(schema, table)
        return list(found.columns) if found else []

    async def get_row_count(self, schema: str, table: str) -> int:
        found = self._find_table(schema, table)
        return (found.row_count or 0) if found else 0

    def _find_table(self, schema: str, table: str) -> TableModel | None:
        s = self._schema_map.get(schema) or next(
            (v for k, v in self._schema_map.items() if k.casefold() == schema.casefold()),
            None,
        )
        if not s:
            return None
        return next((t for t in s.tables if t.name.casefold() == table.casefold()), None)

    async def execute_query(self, sql: str, parameters: dict | None = None) -> QueryResult:
        return QueryResult()

    def capabilities(self) -> DatabaseCapabilities:
        return self._caps


@pytest.fixture
def oracle_conn_config() -> DatabaseConnectionConfig:
    return DatabaseConnectionConfig(
        type=DatabaseType.ORACLE,
        platform=DeploymentPlatform.SELF_MANAGED,
        host="db.example.com",
        port=1521,
        service="ORCL",
        username="hr",
        password="secret",
    )


@pytest.fixture
def pg_conn_config() -> DatabaseConnectionConfig:
    return DatabaseConnectionConfig(
        type=DatabaseType.AZURE_POSTGRESQL,
        platform=DeploymentPlatform.AZURE,
        host="pg.example.com",
        port=5432,
        database="appdb",
        username="app",
        password="secret",
    )
