"""MySQL / SQL Server / Azure SQL adapter wiring and metadata mapping."""

from __future__ import annotations

from app.adapters.azure_sql.adapter import AzureSQLAdapter
from app.adapters.factory import adapter_factory
from app.adapters.mysql.adapter import MySQLAdapter
from app.adapters.mysql.metadata import MySQLMetadataCollector
from app.adapters.mysql.type_mapping import get_normalizer as mysql_normalizer
from app.adapters.sqlserver.adapter import SQLServerAdapter
from app.adapters.sqlserver.metadata import SQLServerMetadataCollector
from app.adapters.sqlserver.type_mapping import get_normalizer as mssql_normalizer
from app.core.config import DatabaseConnectionConfig
from app.core.enums import DatabaseType
from app.models.constraint import ConstraintType
from app.models.database import QueryResult


def _cfg(db_type: DatabaseType) -> DatabaseConnectionConfig:
    return DatabaseConnectionConfig(
        type=db_type, host="h", database="d", username="u", password="p"
    )


def test_factory_returns_real_adapters() -> None:
    assert isinstance(adapter_factory.create(_cfg(DatabaseType.MYSQL)), MySQLAdapter)
    assert isinstance(adapter_factory.create(_cfg(DatabaseType.SQLSERVER)), SQLServerAdapter)
    azure = adapter_factory.create(_cfg(DatabaseType.AZURE_SQL))
    assert isinstance(azure, AzureSQLAdapter)
    assert isinstance(azure, SQLServerAdapter)  # Azure SQL reuses the SQL Server engine


def test_mysql_maps_auto_increment_identity() -> None:
    collector = MySQLMetadataCollector(fetch=None, normalizer=mysql_normalizer())  # type: ignore[arg-type]
    col = collector._map_column(
        ("id", "int", None, 10, 0, "NO", 1, None, "auto_increment", "int(11)")
    )
    assert col.is_identity is True


async def test_mysql_groups_foreign_key() -> None:
    async def fetch(sql: str, params: dict | None) -> QueryResult:
        return QueryResult(
            columns=["n", "t", "c", "rs", "rt", "rc", "p"],
            rows=[("fk_dept", "FOREIGN KEY", "dept_id", "hr", "dept", "id", 1)],
        )

    collector = MySQLMetadataCollector(fetch=fetch, normalizer=mysql_normalizer())
    cons = await collector.get_constraints("hr", "emp")
    assert cons[0].constraint_type is ConstraintType.FOREIGN_KEY
    assert cons[0].references.ref_table == "dept"
    assert cons[0].references.ref_columns == ["id"]


async def test_sqlserver_constraints_merge_pk_and_fk() -> None:
    async def fetch(sql: str, params: tuple | None) -> QueryResult:
        if "TABLE_CONSTRAINTS" in sql:
            return QueryResult(columns=["n", "t", "c", "o"], rows=[("PK_emp", "PRIMARY KEY", "id", 1)])
        if "foreign_keys" in sql:
            return QueryResult(
                columns=["n", "rs", "rt", "c", "rc"],
                rows=[("FK_dept", "dbo", "dept", "dept_id", "id")],
            )
        return QueryResult()

    collector = SQLServerMetadataCollector(
        fetch=fetch, normalizer=mssql_normalizer(DatabaseType.SQLSERVER), db_type=DatabaseType.SQLSERVER
    )
    cons = await collector.get_constraints("dbo", "emp")
    kinds = {c.constraint_type for c in cons}
    assert ConstraintType.PRIMARY_KEY in kinds
    assert ConstraintType.FOREIGN_KEY in kinds


def test_sqlserver_maps_identity_column() -> None:
    collector = SQLServerMetadataCollector(
        fetch=None,  # type: ignore[arg-type]
        normalizer=mssql_normalizer(DatabaseType.SQLSERVER),
        db_type=DatabaseType.SQLSERVER,
    )
    col = collector._map_column(("id", "int", None, 10, 0, "NO", 1, None, 1))
    assert col.is_identity is True
