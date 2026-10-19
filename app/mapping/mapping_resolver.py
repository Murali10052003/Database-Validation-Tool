"""Resolve source object names to their target counterparts.

Lookups are case-insensitive on the source side so a mapping key of
``HR.EMPLOYEES`` matches an Oracle-discovered ``HR.EMPLOYEES`` regardless of the
casing a user typed. When no explicit mapping exists, the source name is returned
unchanged and identifier normalization handles cross-database case differences.
"""

from __future__ import annotations

from app.core.config import MappingConfig


def _key(*parts: str) -> str:
    """Build a case-insensitive lookup key from name parts."""
    return ".".join(p.casefold() for p in parts)


class MappingResolver:
    """Applies a :class:`MappingConfig` to resolve names and exclusions."""

    def __init__(self, mapping: MappingConfig) -> None:
        self._mapping = mapping
        self._schemas = {k.casefold(): v.strip() for k, v in mapping.schemas.items()}
        self._tables = {_key(k): v for k, v in mapping.tables.items()}
        self._columns = {_key(k): v for k, v in mapping.columns.items()}
        self._included = {
            name.strip().casefold() for name in mapping.included_objects if name.strip()
        }
        self._excluded = {e.strip().casefold() for e in mapping.excluded_objects if e.strip()}
        self._type_overrides = {_key(k): v for k, v in mapping.type_overrides.items()}

    # -- exclusions --------------------------------------------------------

    def is_excluded_schema(self, schema: str) -> bool:
        schema_key = schema.casefold()
        return self._schemas.get(schema_key) == "" or schema_key in self._excluded or (
            bool(self._included)
            and schema_key not in self._included
            and not any(name.startswith(f"{schema_key}.") for name in self._included)
        )

    def is_excluded_table(self, schema: str, table: str) -> bool:
        return (
            self.is_excluded_schema(schema)
            or _key(schema, table) in self._excluded
            or (
                bool(self._included)
                and schema.casefold() not in self._included
                and _key(schema, table) not in self._included
            )
        )

    def is_excluded_column(self, schema: str, table: str, column: str) -> bool:
        return (
            self.is_excluded_table(schema, table)
            or _key(schema, table, column) in self._excluded
        )

    # -- resolution --------------------------------------------------------

    def resolve_schema(self, schema: str) -> str:
        """Target schema name for ``schema`` (explicit mapping or unchanged)."""
        return self._schemas.get(schema.casefold(), schema)

    def resolve_table(self, schema: str, table: str) -> tuple[str, str]:
        """Return ``(target_schema, target_table)`` for a source table."""
        mapped = self._tables.get(_key(schema, table))
        if mapped:
            if "." in mapped:
                target_schema, target_table = mapped.split(".", 1)
                return target_schema, target_table
            return self.resolve_schema(schema), mapped
        return self.resolve_schema(schema), table

    def resolve_column(self, schema: str, table: str, column: str) -> str:
        """Target column name for a source column (explicit mapping or unchanged)."""
        return self._columns.get(_key(schema, table, column), column)

    def type_override(self, schema: str, table: str, column: str) -> str | None:
        """An explicit target type override for a column, if configured."""
        return self._type_overrides.get(_key(schema, table, column))
