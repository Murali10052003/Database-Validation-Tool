"""MySQL type-mapping helpers.

Type rules live in ``config/type_mappings/mysql.yaml`` and are applied by the shared
:class:`~app.normalization.datatypes.TypeNormalizer`.
"""

from __future__ import annotations

from app.core.enums import DatabaseType
from app.normalization.datatypes import TypeNormalizer


def get_normalizer(mapping_dir: str | None = None) -> TypeNormalizer:
    """Return the cached MySQL type normalizer."""
    return TypeNormalizer.for_database(DatabaseType.MYSQL, mapping_dir)


def quote_identifier(name: str) -> str:
    """Quote a MySQL identifier with backticks, escaping embedded backticks."""
    escaped = name.replace("`", "``")
    return f"`{escaped}`"
