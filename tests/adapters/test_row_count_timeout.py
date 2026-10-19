"""Native query timeouts and statistics estimates per adapter (fake driver connections)."""

from __future__ import annotations

import pytest

from app.adapters.azure_postgresql.adapter import AzurePostgreSQLAdapter
from app.adapters.mysql.adapter import MySQLAdapter
from app.adapters.oracle.adapter import OracleAdapter
from app.adapters.sqlserver.adapter import SQLServerAdapter
from app.core.config import DatabaseConnectionConfig
from app.core.enums import DatabaseType
from app.core.exceptions import QueryError, QueryTimeoutError


class FakeCursor:
    description = [("c",)]

    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn
        self.rows: list[tuple] = []

    def execute(self, sql: str, params=None) -> None:
        self.conn.executed.append((sql, params, self.conn.call_timeout, self.conn.timeout))
        if self.conn.fail_on and self.conn.fail_on in sql:
            raise RuntimeError(self.conn.message)
        if "COUNT" in sql:
            self.rows = [(7,)]
        elif any(key in sql for key in ("num_rows", "reltuples", "table_rows", "sys.partitions")):
            self.rows = [(self.conn.estimate,)]
        elif "current_setting" in sql or "max_execution_time" in sql:
            self.rows = [("0",)]
        else:
            self.rows = [("ok",)]

    def fetchall(self) -> list[tuple]:
        return self.rows

    def close(self) -> None:
        return None


class FakeConnection:
    version = "19.0"

    def __init__(self, *, fail_on=None, message="", estimate=None) -> None:
        self.fail_on, self.message, self.estimate = fail_on, message, estimate
        self.executed: list[tuple] = []
        self.call_timeout = 0  # Oracle
        self.timeout = 0  # pyodbc
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def _cfg(db_type: DatabaseType) -> DatabaseConnectionConfig:
    return DatabaseConnectionConfig(
        type=db_type, host="h", database="d", service="s", username="u", password="p",
    )


def _adapter(cls, db_type, monkeypatch, *connections):
    adapter = cls(_cfg(db_type))
    queue = list(connections)

    async def create():
        return queue.pop(0)

    monkeypatch.setattr(adapter, "_create_connection", create)
    return adapter


# -- Oracle ---------------------------------------------------------------------------


async def test_oracle_call_timeout_is_applied_and_a_timed_out_session_is_replaced(monkeypatch):
    first = FakeConnection(fail_on="COUNT(*)", message="DPY-4024: call timeout of 5000 ms exceeded")
    second = FakeConnection(estimate=123)
    adapter = _adapter(OracleAdapter, DatabaseType.ORACLE, monkeypatch, first, second)

    with pytest.raises(QueryTimeoutError, match="HR.EMP exceeded 5s"):
        await adapter.get_row_count_with_timeout("HR", "EMP", 5)
    assert first.executed[0][2] == 5000  # call_timeout was in force for the COUNT(*)
    assert first.closed and adapter._connection is None  # unusable session dropped
    assert await adapter.get_row_count_estimate("HR", "EMP") == 123  # transparently reconnected
    assert "num_rows" in second.executed[0][0]
    assert second.executed[0][1] == {"owner": "HR", "table_name": "EMP"}


async def test_oracle_resets_the_timeout_and_returns_the_exact_count_when_fast(monkeypatch):
    conn = FakeConnection()
    adapter = _adapter(OracleAdapter, DatabaseType.ORACLE, monkeypatch, conn)
    assert await adapter.get_row_count_with_timeout("HR", "EMP", 30) == 7
    assert conn.executed[0][2] == 30000 and conn.call_timeout == 0


async def test_oracle_other_errors_are_not_reported_as_timeouts(monkeypatch):
    conn = FakeConnection(fail_on="COUNT(*)", message="ORA-00942: table or view does not exist")
    adapter = _adapter(OracleAdapter, DatabaseType.ORACLE, monkeypatch, conn)
    with pytest.raises(QueryError) as caught:
        await adapter.get_row_count_with_timeout("HR", "EMP", 5)
    assert not isinstance(caught.value, QueryTimeoutError)
    assert not conn.closed


async def test_oracle_estimate_is_none_without_statistics(monkeypatch):
    adapter = _adapter(OracleAdapter, DatabaseType.ORACLE, monkeypatch, FakeConnection(estimate=None))
    assert await adapter.get_row_count_estimate("HR", "EMP") is None


# -- PostgreSQL -----------------------------------------------------------------------


async def test_postgres_statement_timeout_is_set_then_restored(monkeypatch):
    conn = FakeConnection(fail_on="COUNT(*)", message="canceling statement due to statement timeout")
    adapter = _adapter(AzurePostgreSQLAdapter, DatabaseType.AZURE_POSTGRESQL, monkeypatch, conn)
    with pytest.raises(QueryTimeoutError):
        await adapter.get_row_count_with_timeout("hr", "emp", 5)
    settings = [params for sql, params, *_ in conn.executed if "set_config" in sql]
    assert settings == [{"ms": "5000"}, {"value": "0"}]  # limit applied, original restored
    assert not conn.closed  # autocommit session stays usable


@pytest.mark.parametrize(("stored", "expected"), [(42, 42), (0, 0), (-1, None), (None, None)])
async def test_postgres_estimate_ignores_never_analyzed_tables(monkeypatch, stored, expected):
    adapter = _adapter(AzurePostgreSQLAdapter, DatabaseType.AZURE_POSTGRESQL, monkeypatch,
                       FakeConnection(estimate=stored))
    assert await adapter.get_row_count_estimate("hr", "emp") == expected


# -- SQL Server -----------------------------------------------------------------------


async def test_sqlserver_query_timeout_is_applied_and_cleared(monkeypatch):
    conn = FakeConnection(fail_on="COUNT", message="('HYT00', '[HYT00] Query timeout expired')")
    adapter = _adapter(SQLServerAdapter, DatabaseType.SQLSERVER, monkeypatch, conn)
    with pytest.raises(QueryTimeoutError):
        await adapter.get_row_count_with_timeout("dbo", "emp", 4.2)
    assert conn.executed[0][3] == 5  # whole seconds, rounded up
    assert conn.timeout == 0


async def test_sqlserver_estimate_uses_the_catalog_with_a_quoted_name(monkeypatch):
    conn = FakeConnection(estimate=99)
    adapter = _adapter(SQLServerAdapter, DatabaseType.SQLSERVER, monkeypatch, conn)
    assert await adapter.get_row_count_estimate("dbo", "emp") == 99
    assert conn.executed[0][1] == ("[dbo].[emp]",)


# -- MySQL ----------------------------------------------------------------------------


async def test_mysql_max_execution_time_is_set_then_restored(monkeypatch):
    conn = FakeConnection(
        fail_on="COUNT", message="3024 (HY000): Query execution was interrupted, "
        "maximum statement execution time exceeded")
    adapter = _adapter(MySQLAdapter, DatabaseType.MYSQL, monkeypatch, conn)
    with pytest.raises(QueryTimeoutError):
        await adapter.get_row_count_with_timeout("hr", "emp", 5)
    statements = [sql for sql, *_ in conn.executed if sql.startswith("SET SESSION")]
    assert statements == ["SET SESSION max_execution_time = 5000",
                          "SET SESSION max_execution_time = 0"]


async def test_mysql_without_max_execution_time_still_counts(monkeypatch):
    conn = FakeConnection(fail_on="@@SESSION.max_execution_time", message="Unknown system variable")
    adapter = _adapter(MySQLAdapter, DatabaseType.MYSQL, monkeypatch, conn)
    assert await adapter.get_row_count_with_timeout("hr", "emp", 5) == 7
