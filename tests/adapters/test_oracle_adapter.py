"""Adapter tests with mocked drivers (no real database)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from app.adapters.oracle.adapter import OracleAdapter
from app.core.enums import DatabaseType
from app.core.exceptions import QueryError
from app.models.capabilities import DatabaseCapabilities
from app.validators.checksum import _digest


class _CountingCursor:
    """A cursor that returns a fixed COUNT(*) for any query."""

    def __init__(self, count: int) -> None:
        self._count = count
        self.description = [("COUNT(*)",)]

    def execute(self, sql: str, parameters: dict | None = None) -> None:
        return None

    def fetchall(self) -> list[tuple]:
        return [(self._count,)]

    def close(self) -> None:
        return None


class _Conn:
    def __init__(self, count: int, version: str) -> None:
        self._count = count
        self.version = version

    def cursor(self) -> _CountingCursor:
        return _CountingCursor(self._count)

    def close(self) -> None:
        return None


@pytest.fixture
def patched_oracle(oracle_conn_config, monkeypatch: pytest.MonkeyPatch) -> OracleAdapter:
    adapter = OracleAdapter(oracle_conn_config)

    async def fake_create() -> Any:
        return _Conn(count=42, version="19.0.0.0")

    monkeypatch.setattr(adapter, "_create_connection", fake_create)
    return adapter


async def test_oracle_test_connection_succeeds(patched_oracle: OracleAdapter) -> None:
    result = await patched_oracle.test_connection()
    assert result.success is True
    assert result.database_type == DatabaseType.ORACLE
    assert result.version == "19.0.0.0"


async def test_oracle_database_info(patched_oracle: OracleAdapter) -> None:
    info = await patched_oracle.get_database_info()
    assert info.database_type == DatabaseType.ORACLE
    assert info.version == "19.0.0.0"


async def test_oracle_row_count(patched_oracle: OracleAdapter) -> None:
    assert await patched_oracle.get_row_count("HR", "EMPLOYEES") == 42


def test_oracle_capabilities_are_full() -> None:
    caps = OracleAdapter.__mro__  # sanity: class resolvable
    assert caps is not None
    from app.adapters.oracle.capabilities import ORACLE_CAPABILITIES

    assert isinstance(ORACLE_CAPABILITIES, DatabaseCapabilities)
    assert ORACLE_CAPABILITIES.sequences is True


async def test_oracle_connection_failure_is_captured(oracle_conn_config, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = OracleAdapter(oracle_conn_config)

    async def boom() -> Any:
        raise RuntimeError("no listener")

    monkeypatch.setattr(adapter, "_create_connection", boom)
    result = await adapter.test_connection()
    assert result.success is False
    assert "no listener" in (result.error or "")


async def test_oracle_fetch_materializes_lobs_before_closing_cursor(oracle_conn_config):
    text = SimpleNamespace(read=AsyncMock(return_value="large text"))
    binary = SimpleNamespace(read=AsyncMock(return_value=b"\x00\xff"))
    national = SimpleNamespace(read=AsyncMock(return_value="national text"))
    cursor = Mock()
    cursor.description = [
        ("ID", SimpleNamespace(name="DB_TYPE_NUMBER")),
        ("TEXT", SimpleNamespace(name="DB_TYPE_CLOB")),
        ("BINARY", SimpleNamespace(name="DB_TYPE_BLOB")),
        ("NATIONAL", SimpleNamespace(name="DB_TYPE_NCLOB")),
    ]
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=[(1, text, binary, national), (2, None, None, None)])
    for lob in (text, binary, national):
        async def read_before_close(original=lob.read):
            cursor.close.assert_not_called()
            return await original()
        lob.read = read_before_close
    adapter = OracleAdapter(oracle_conn_config)
    adapter._connection = SimpleNamespace(cursor=lambda: cursor)

    result = await adapter._fetch('SELECT * FROM "HR"."T"')

    expected = [(1, "large text", b"\x00\xff", "national text"), (2, None, None, None)]
    assert result.rows == expected
    assert _digest(result.rows) == _digest(expected)
    cursor.close.assert_called_once()


async def test_oracle_lob_read_failure_is_query_error_and_closes_cursor(oracle_conn_config):
    cursor = Mock()
    cursor.description = [("PAYLOAD", SimpleNamespace(name="DB_TYPE_BLOB"))]
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=[
        (SimpleNamespace(read=AsyncMock(side_effect=RuntimeError("LOB read failed"))),),
    ])
    adapter = OracleAdapter(oracle_conn_config)
    adapter._connection = SimpleNamespace(cursor=lambda: cursor)

    with pytest.raises(QueryError, match="LOB read failed"):
        await adapter._fetch('SELECT "PAYLOAD" FROM "HR"."T"')
    cursor.close.assert_called_once()


@pytest.mark.parametrize("payload", ["", "text", b"", b"\x00\xff", None])
async def test_oracle_fetch_preserves_already_materialized_lobs(oracle_conn_config, payload):
    cursor = Mock()
    cursor.description = [("PAYLOAD", SimpleNamespace(name="DB_TYPE_BLOB"))]
    cursor.fetchall.return_value = [(payload,)]
    adapter = OracleAdapter(oracle_conn_config)
    adapter._connection = SimpleNamespace(cursor=lambda: cursor)
    result = await adapter._fetch('SELECT "PAYLOAD" FROM "HR"."T"')
    assert result.rows == [(payload,)]
    cursor.close.assert_called_once()
