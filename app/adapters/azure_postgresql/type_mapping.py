"""PostgreSQL type-mapping helpers.

Type rules live in ``config/type_mappings/postgresql.yaml`` and are applied by the
shared :class:`~app.normalization.datatypes.TypeNormalizer`.
"""

from __future__ import annotations

from app.core.enums import DatabaseType
from app.normalization.datatypes import TypeNormalizer


def get_normalizer(mapping_dir: str | None = None) -> TypeNormalizer:
    """Return the cached Azure PostgreSQL type normalizer."""
    return TypeNormalizer.for_database(DatabaseType.AZURE_POSTGRESQL, mapping_dir)


def quote_identifier(name: str) -> str:
    """Quote a PostgreSQL identifier, escaping embedded double quotes."""
    escaped = name.replace('"', '""')
    return f'"{escaped}"'
