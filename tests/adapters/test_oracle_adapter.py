"""Adapter tests with mocked drivers (no real database)."""

from __future__ import annotations

from typing import Any

import pytest

from app.adapters.oracle.adapter import OracleAdapter
from app.core.enums import DatabaseType
from app.models.capabilities import DatabaseCapabilities


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
