"""Adapter factory.

Resolves a :class:`~app.core.enums.DatabaseType` to a concrete adapter. Adapter
classes are imported lazily so a missing optional driver only fails when that
specific database is actually used.
"""

from __future__ import annotations

from collections.abc import Callable

from app.adapters.base import DatabaseAdapter
from app.core.config import DatabaseConnectionConfig
from app.core.enums import DatabaseType
from app.core.exceptions import UnsupportedDatabaseError

# A registry entry lazily imports and returns an adapter class. Lazy importing
# keeps optional database drivers out of the import path until they are needed.
AdapterLoader = Callable[[], type[DatabaseAdapter]]


def _load_oracle() -> type[DatabaseAdapter]:
    from app.adapters.oracle.adapter import OracleAdapter

    return OracleAdapter


def _load_azure_postgresql() -> type[DatabaseAdapter]:
    from app.adapters.azure_postgresql.adapter import AzurePostgreSQLAdapter

    return AzurePostgreSQLAdapter


def _load_mysql() -> type[DatabaseAdapter]:
    from app.adapters.mysql.adapter import MySQLAdapter

    return MySQLAdapter


def _load_sqlserver() -> type[DatabaseAdapter]:
    from app.adapters.sqlserver.adapter import SQLServerAdapter

    return SQLServerAdapter


def _load_azure_sql() -> type[DatabaseAdapter]:
    from app.adapters.azure_sql.adapter import AzureSQLAdapter

    return AzureSQLAdapter


class AdapterFactory:
    """Creates adapters from configuration via a database-type registry."""

    def __init__(self) -> None:
        self._registry: dict[DatabaseType, AdapterLoader] = {
            DatabaseType.ORACLE: _load_oracle,
            DatabaseType.AZURE_POSTGRESQL: _load_azure_postgresql,
            DatabaseType.MYSQL: _load_mysql,
            DatabaseType.SQLSERVER: _load_sqlserver,
            DatabaseType.AZURE_SQL: _load_azure_sql,
        }

    def register(self, db_type: DatabaseType, loader: AdapterLoader) -> None:
        """Register (or override) an adapter loader for a database type.

        New databases are added here without touching the core engine.
        """
        self._registry[db_type] = loader

    def supported_types(self) -> list[DatabaseType]:
        """Database types with a registered adapter."""
        return list(self._registry)

    def create(self, config: DatabaseConnectionConfig) -> DatabaseAdapter:
        """Instantiate the adapter for ``config.type``."""
        loader = self._registry.get(config.type)
        if loader is None:
            raise UnsupportedDatabaseError(
                f"No adapter registered for database type '{config.type.value}'."
            )
        adapter_cls = loader()
        return adapter_cls(config)


# Module-level singleton used throughout the app.
adapter_factory = AdapterFactory()
