"""Database discovery.

Walks an adapter to assemble a complete, canonical :class:`DatabaseModel`. This is
adapter-agnostic: it only calls interface methods and never contains
database-specific logic.
"""

from __future__ import annotations

from app.adapters.base import DatabaseAdapter
from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.core.progress import ProgressCallback
from app.models.database import DatabaseModel
from app.models.schema import SchemaModel
from app.models.table import TableModel

logger = get_logger(__name__)


class DatabaseDiscovery:
    """Builds a :class:`DatabaseModel` from a connected adapter."""

    def __init__(self, adapter: DatabaseAdapter) -> None:
        self._adapter = adapter

    async def discover(
        self,
        schemas: list[str] | None = None,
        *,
        include_columns: bool = True,
        include_row_counts: bool = False,
        include_structural: bool = False,
        require_all_schemas: bool = False,
        on_progress: ProgressCallback | None = None,
    ) -> DatabaseModel:
        """Discover schemas, tables and (optionally) columns / row counts.

        ``schemas`` optionally restricts discovery to specific schema names
        (matched case-insensitively); the restriction is applied by the catalog
        query itself, so unselected schemas are never walked. With
        ``require_all_schemas`` a requested schema that is not visible raises
        :class:`ConfigurationError`. One failed table does not abort discovery.
        When ``include_structural`` is set, per-table indexes and constraints and
        per-schema sequences are also collected (Phase 2 validators need these).
        ``on_progress`` receives ``(fraction, message)`` as each schema and table is read.
        """
        report = on_progress or (lambda fraction, message="": None)
        report(0.0, "Connecting and listing schemas")
        info = await self._adapter.get_database_info()
        discovered = await self._adapter.get_schemas(schemas)
        selected = _filter_schemas(discovered, schemas)
        if require_all_schemas and schemas:
            found = {s.name.casefold() for s in selected}
            missing = [s for s in schemas if s.casefold() not in found]
            if missing:
                raise ConfigurationError(
                    "Schema not found or not visible to this connection: "
                    + ", ".join(missing)
                )

        result_schemas: list[SchemaModel] = []
        total = len(selected) or 1
        per_table_work = include_columns or include_structural or include_row_counts
        for position, schema in enumerate(selected):
            label = f"schema {schema.name} ({position + 1} of {len(selected)})"
            report(position / total, f"Reading {label}")
            tables = await self._adapter.get_tables(schema.name)
            for done, table in enumerate(tables, start=1):
                if include_columns:
                    table.columns = await self._adapter.get_columns(schema.name, table.name)
                if include_structural:
                    table.constraints = await self._adapter.get_constraints(
                        schema.name, table.name
                    )
                    table.indexes = await self._adapter.get_indexes(schema.name, table.name)
                if include_row_counts:
                    table.row_count = await self._adapter.get_row_count(schema.name, table.name)
                if per_table_work:
                    report(
                        (position + done / len(tables)) / total,
                        f"Reading {label}: {done} of {len(tables)} tables",
                    )
            schema.tables = tables
            if include_structural:
                schema.sequences = await self._adapter.get_sequences(schema.name)
                schema.views = await self._adapter.get_views(schema.name)
                schema.routines = await self._adapter.get_routines(schema.name)
                await self._assign_table_objects(schema, tables)
            result_schemas.append(schema)
            logger.info(
                "schema_discovered",
                extra={"schema": schema.name, "table_count": len(tables)},
            )

        report(1.0, f"Read {len(result_schemas)} schemas")
        return DatabaseModel(
            database_type=info.database_type,
            platform=info.platform,
            version=info.version,
            schemas=result_schemas,
        )

    async def _assign_table_objects(
        self, schema: SchemaModel, tables: list[TableModel]
    ) -> None:
        """Distribute schema-wide triggers and partitions onto their owning tables."""
        by_name = {t.name.casefold(): t for t in tables}
        for trigger in await self._adapter.get_triggers(schema.name):
            table = by_name.get(trigger.table.casefold())
            if table is not None:
                table.triggers.append(trigger)
        for partition in await self._adapter.get_partitions(schema.name):
            table = by_name.get(partition.table.casefold())
            if table is not None:
                table.partitions.append(partition)


def _filter_schemas(
    discovered: list[SchemaModel], wanted: list[str] | None
) -> list[SchemaModel]:
    """Keep only the requested schemas (case-insensitive), preserving order."""
    if not wanted:
        return discovered
    wanted_keys = {w.casefold() for w in wanted}
    return [s for s in discovered if s.name.casefold() in wanted_keys]
