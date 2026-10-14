"""Resolve real (discovered) target object names for a source object.

Without explicit table/column mappings the mapping resolver echoes the *source*
name, whose casing (e.g. Oracle upper-case) may not match the real target
identifier (e.g. PostgreSQL lower-case). Data validators must query the target
using its actual discovered names, so this locates them from the target model.
"""

from __future__ import annotations

from app.mapping.mapping_resolver import MappingResolver
from app.models.database import DatabaseModel
from app.models.schema import SchemaModel
from app.models.table import TableModel


class TargetLookup:
    """Finds real target schema/table/column names from a discovered target model."""

    def __init__(self, mapping: MappingResolver, target_model: DatabaseModel | None) -> None:
        self._mapping = mapping
        self._schemas: dict[str, SchemaModel] = (
            {s.name.casefold(): s for s in target_model.schemas} if target_model else {}
        )

    def table(self, src_schema: str, src_table: str) -> tuple[str, str, TableModel] | None:
        """Return ``(schema_name, table_name, table)`` of the matching target table."""
        target_schema_name = self._mapping.resolve_schema(src_schema)
        tgt_schema = self._schemas.get(target_schema_name.casefold())
        if tgt_schema is None:
            return None
        _, mapped = self._mapping.resolve_table(src_schema, src_table)
        key = mapped.casefold()
        for t in tgt_schema.tables:
            if t.name.casefold() == key:
                return tgt_schema.name, t.name, t
        return None

    def column(
        self, src_schema: str, src_table: str, src_col: str, tgt_table: TableModel
    ) -> str | None:
        """Return the real target column name for a source column, or ``None``."""
        mapped = self._mapping.resolve_column(src_schema, src_table, src_col)
        key = mapped.casefold()
        for c in tgt_table.columns:
            if c.name.casefold() == key:
                return c.name
        return None
