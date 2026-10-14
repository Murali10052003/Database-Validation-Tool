"""SQL Server type-mapping helpers.

Type rules live in ``config/type_mappings/sqlserver.yaml`` and are applied by the
shared :class:`~app.normalization.datatypes.TypeNormalizer`.
"""

from __future__ import annotations

from app.core.enums import DatabaseType
from app.normalization.datatypes import TypeNormalizer


def get_normalizer(
    database_type: DatabaseType = DatabaseType.SQLSERVER, mapping_dir: str | None = None
) -> TypeNormalizer:
    """Return the cached SQL Server / Azure SQL type normalizer."""
    return TypeNormalizer.for_database(database_type, mapping_dir)


def quote_identifier(name: str) -> str:
    """Quote a SQL Server identifier with brackets, escaping embedded brackets."""
    escaped = name.replace("]", "]]")
    return f"[{escaped}]"
