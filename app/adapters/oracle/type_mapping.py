"""Oracle type-mapping helpers.

Type normalization rules live in ``config/type_mappings/oracle.yaml`` and are
applied by the shared :class:`~app.normalization.datatypes.TypeNormalizer`; this
module only exposes a convenient accessor and identifier-quoting for Oracle.
"""

from __future__ import annotations

from app.core.enums import DatabaseType
from app.normalization.datatypes import TypeNormalizer


def get_normalizer(mapping_dir: str | None = None) -> TypeNormalizer:
    """Return the cached Oracle type normalizer."""
    return TypeNormalizer.for_database(DatabaseType.ORACLE, mapping_dir)


def quote_identifier(name: str) -> str:
    """Quote an Oracle identifier, escaping embedded double quotes."""
    escaped = name.replace('"', '""')
    return f'"{escaped}"'
