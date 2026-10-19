"""Data-type normalization.

A :class:`TypeNormalizer` maps a database's native type name to a canonical
:class:`~app.core.enums.LogicalType` using a YAML mapping file. Exact numeric
precision and scale are preserved; directional compatibility belongs to comparison.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from app.core.enums import DatabaseType, LogicalType
from app.core.exceptions import ConfigurationError

_TYPE_NAME = re.compile(r"^\s*([A-Za-z0-9_ ]+?)\s*(?:\(.*\))?\s*$")

_DEFAULT_MAPPING_DIR = Path("config/type_mappings")


class NormalizedType(BaseModel):
    """The canonical form of a column type."""

    model_config = ConfigDict(frozen=True)

    logical_type: LogicalType
    length: int | None = None
    precision: int | None = None
    scale: int | None = None

    def signature(self) -> tuple:
        """Hashable identity used for equality comparison."""
        return (self.logical_type, self.length, self.precision, self.scale)


def _base_type_name(native_type: str) -> str:
    """Extract the bare type name, dropping any ``(...)`` size qualifier."""
    match = _TYPE_NAME.match(native_type or "")
    name = match.group(1) if match else (native_type or "")
    return name.strip().upper()


class TypeNormalizer:
    """Normalizes native type names to logical types for one database."""

    def __init__(self, type_map: dict[str, LogicalType], database_type: str) -> None:
        self._type_map = type_map
        self.database_type = database_type

    @classmethod
    def from_yaml(cls, path: str | Path) -> TypeNormalizer:
        """Load a normalizer from a YAML mapping file."""
        p = Path(path)
        if not p.is_file():
            raise ConfigurationError(f"Type mapping file not found: {p}")
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        raw_map = data.get("type_map", {})
        db = str(data.get("database", p.stem))
        type_map: dict[str, LogicalType] = {}
        for native, logical in raw_map.items():
            try:
                type_map[str(native).strip().upper()] = LogicalType(str(logical).strip().upper())
            except ValueError as exc:
                raise ConfigurationError(
                    f"Unknown logical type '{logical}' for '{native}' in {p}"
                ) from exc
        return cls(type_map, db)

    @classmethod
    @functools.cache
    def for_database(
        cls, database_type: DatabaseType, mapping_dir: str | None = None
    ) -> TypeNormalizer:
        """Load and cache the normalizer for a database type.

        The mapping file is ``{mapping_dir}/{database}.yaml``. PostgreSQL/SQL variants
        fall back to a shared engine mapping when a platform-specific one is absent.
        """
        directory = Path(mapping_dir) if mapping_dir else _DEFAULT_MAPPING_DIR
        candidates = _mapping_candidates(database_type)
        for name in candidates:
            candidate = directory / f"{name}.yaml"
            if candidate.is_file():
                return cls.from_yaml(candidate)
        raise ConfigurationError(
            f"No type mapping file found for '{database_type.value}' in {directory} "
            f"(tried: {', '.join(candidates)})"
        )

    def normalize(
        self,
        native_type: str,
        length: int | None = None,
        precision: int | None = None,
        scale: int | None = None,
    ) -> NormalizedType:
        """Return the canonical type for a native type + size qualifiers."""
        base = _base_type_name(native_type)
        logical = self._type_map.get(base, LogicalType.UNKNOWN)
        # Character-length only matters for string types.
        norm_length = length if logical in {LogicalType.STRING, LogicalType.FIXED_STRING} else None
        norm_precision = precision if logical == LogicalType.DECIMAL else None
        norm_scale = scale if logical == LogicalType.DECIMAL else None
        return NormalizedType(
            logical_type=logical,
            length=norm_length,
            precision=norm_precision,
            scale=norm_scale,
        )

def _mapping_candidates(database_type: DatabaseType) -> list[str]:
    """Ordered list of mapping file stems to try for a database type."""
    engine_fallbacks = {
        DatabaseType.ORACLE: ["oracle"],
        DatabaseType.AZURE_POSTGRESQL: ["azure_postgresql", "postgresql"],
        DatabaseType.AZURE_SQL: ["azure_sql", "sqlserver"],
        DatabaseType.SQLSERVER: ["sqlserver"],
        DatabaseType.MYSQL: ["mysql"],
    }
    return engine_fallbacks.get(database_type, [database_type.value])
