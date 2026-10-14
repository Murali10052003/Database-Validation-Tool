"""Inventory-backed scoped discovery; data queries always remain live."""

from __future__ import annotations

from app.core.catalog import Catalog
from app.models.database import DatabaseModel
from app.models.schema import SchemaModel
from app.models.table import TableModel

# Checks that read only names, columns or live data; every other check consumes
# constraints, indexes, sequences, views, routines, triggers or partitions. Aggregates
# read constraints too: they skip key columns.
_NO_STRUCTURE_CHECKS = frozenset({"schema", "row_count", "null_count", "custom_query"})


def needs_structural(checks: list[str]) -> bool:
    """Whether any selected check needs structural (non-column) metadata."""
    return any(check not in _NO_STRUCTURE_CHECKS for check in checks)


def load_scope(ctx):
    config = ctx.config
    if config.validation.custom_validations:
        raise ValueError(
            "Scoped reruns cannot execute arbitrary custom SQL; use a reviewed full run")
    if not config.source_inventory_id or not config.target_inventory_id:
        raise ValueError("Saved source and target inventories are required for a rerun")
    catalog = Catalog()
    includes = [name.strip() for name in config.mapping.included_objects if name.strip()]
    excludes = [name.strip() for name in config.mapping.excluded_objects if name.strip()]
    excludes.extend(
        schema for schema, target in config.mapping.schemas.items() if not target.strip()
    )
    source = catalog.load_inventory(
        config.source_inventory_id, config.source, included=includes, excluded=excludes,
        require_complete=True,
    )
    available = {schema.name.casefold() for schema in source.schemas}
    targets = []
    for schema in source.schemas:
        for collection in (schema.tables, schema.views, schema.sequences, schema.routines):
            for item in collection:
                available.add(f"{schema.name}.{item.name}".casefold())
                if isinstance(item, TableModel):
                    target_schema, target_name = ctx.mapping.resolve_table(schema.name, item.name)
                else:
                    target_schema = ctx.mapping.resolve_schema(schema.name)
                    target_name = item.name
                targets.append(f"{target_schema}.{target_name}")
    for name in includes:
        if name.casefold() not in available and not ctx.mapping.is_excluded_table(
            name.split(".")[0], name.split(".", 1)[-1]
        ):
            raise ValueError(f"Included object not found in saved inventory: {name}")
    if not targets:
        raise ValueError("Scope contains no inventory objects; full discovery was not started")
    target = catalog.load_inventory(
        config.target_inventory_id, config.target, included=targets,
        require_complete=True,
    )
    if config.discovery_mode == "refresh":
        for schema in source.schemas:
            for table in schema.tables:
                target_schema, target_name = ctx.mapping.resolve_table(schema.name, table.name)
                found_schema = next((item for item in target.schemas
                                     if item.name.casefold() == target_schema.casefold()), None)
                if found_schema is None:
                    found_schema = SchemaModel(name=target_schema)
                    target.schemas.append(found_schema)
                if not any(item.name.casefold() == target_name.casefold()
                           for item in found_schema.tables):
                    found_schema.tables.append(TableModel(
                        schema_name=found_schema.name, name=target_name,
                    ))
    return source, target


async def refresh_scope(adapter, model: DatabaseModel, checks: list[str]) -> DatabaseModel:
    """Re-read the saved scope from the live database.

    Columns are always re-read (they double as the existence check). Constraints,
    indexes and the schema-level object lists are re-read only when a selected check
    consumes them.
    """
    structural = needs_structural(checks)
    refreshed = model.model_copy(deep=True)
    for schema in refreshed.schemas:
        for table in schema.tables:
            columns = await adapter.get_columns(schema.name, table.name)
            if not columns:
                raise ValueError(
                    f"Selected table missing or inaccessible: {schema.name}.{table.name}")
            table.columns = columns
            if structural:
                table.constraints = await adapter.get_constraints(schema.name, table.name)
                table.indexes = await adapter.get_indexes(schema.name, table.name)
        if not structural:
            continue
        for check, attribute, method in (
            ("views", "views", adapter.get_views),
            ("sequences", "sequences", adapter.get_sequences),
            ("routines", "routines", adapter.get_routines),
        ):
            if getattr(schema, attribute):
                selected = {item.name for item in getattr(schema, attribute)}
                objects = await method(schema.name)
                if selected - {item.name for item in objects}:
                    raise ValueError(f"Selected {check} missing or inaccessible in {schema.name}")
                setattr(schema, attribute, [item for item in objects if item.name in selected])
        for attribute, method in (
            ("triggers", adapter.get_triggers),
            ("partitions", adapter.get_partitions),
        ):
            if schema.tables:
                objects = await method(schema.name)
                for table in schema.tables:
                    setattr(table, attribute, [item for item in objects
                                               if item.table.casefold() == table.name.casefold()])
    return refreshed