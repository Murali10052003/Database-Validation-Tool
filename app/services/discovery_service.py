"""Discovery service.

Wraps :class:`DatabaseDiscovery` with adapter lifecycle management so callers can
discover a database's structure from a single connection config.
"""

from __future__ import annotations

from app.adapters.factory import adapter_factory
from app.core.config import DatabaseConnectionConfig
from app.core.progress import ProgressCallback
from app.discovery.database_discovery import DatabaseDiscovery
from app.models.database import DatabaseModel


class DiscoveryService:
    """Discover a database's canonical structure from a connection config."""

    async def discover(
        self,
        config: DatabaseConnectionConfig,
        schemas: list[str] | None = None,
        *,
        include_columns: bool = True,
        include_row_counts: bool = False,
        include_structural: bool = False,
        require_all_schemas: bool = False,
        on_progress: ProgressCallback | None = None,
    ) -> DatabaseModel:
        adapter = adapter_factory.create(config)
        try:
            return await DatabaseDiscovery(adapter).discover(
                schemas,
                include_columns=include_columns,
                include_row_counts=include_row_counts,
                include_structural=include_structural,
                require_all_schemas=require_all_schemas,
                on_progress=on_progress,
            )
        finally:
            await adapter.close()

    async def list_schemas(self, config: DatabaseConnectionConfig) -> DatabaseModel:
        """Lightweight listing: database identity and visible schema names only."""
        adapter = adapter_factory.create(config)
        try:
            info = await adapter.get_database_info()
            schemas = await adapter.get_schemas()
            return DatabaseModel(
                database_type=info.database_type,
                platform=info.platform,
                version=info.version,
                schemas=schemas,
            )
        finally:
            await adapter.close()
