"""Identifier normalization.

Databases fold unquoted identifiers differently (Oracle upper-cases, PostgreSQL
lower-cases). Rather than blindly lower-casing everything, this preserves whether an
identifier was quoted/case-sensitive and produces a cross-database comparison key
that is case-insensitive only for unquoted identifiers.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.core.enums import DatabaseType

# How each engine folds unquoted identifiers when storing them.
_FOLDING: dict[DatabaseType, str] = {
    DatabaseType.ORACLE: "upper",
    DatabaseType.AZURE_POSTGRESQL: "lower",
    DatabaseType.AZURE_SQL: "preserve",
    DatabaseType.SQLSERVER: "preserve",
    DatabaseType.MYSQL: "preserve",
    DatabaseType.AZURE_MYSQL: "preserve",
}


class NormalizedIdentifier(BaseModel):
    """A normalized identifier retaining case-sensitivity information."""

    model_config = ConfigDict(frozen=True)

    original: str
    folded: str
    quoted: bool
    comparison_key: str

    def __eq__(self, other: object) -> bool:
        if isinstance(other, NormalizedIdentifier):
            return self.comparison_key == other.comparison_key
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.comparison_key)


def normalize_identifier(
    name: str, database_type: DatabaseType, quoted: bool = False
) -> NormalizedIdentifier:
    """Normalize ``name`` for ``database_type``.

    Unquoted identifiers get a case-insensitive comparison key; quoted
    (case-sensitive) identifiers keep their exact case.
    """
    fold = _FOLDING.get(database_type, "preserve")
    if quoted:
        folded = name
    elif fold == "upper":
        folded = name.upper()
    elif fold == "lower":
        folded = name.lower()
    else:
        folded = name
    comparison_key = folded if quoted else folded.casefold()
    return NormalizedIdentifier(
        original=name, folded=folded, quoted=quoted, comparison_key=comparison_key
    )
