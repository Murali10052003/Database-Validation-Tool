"""Column-level canonical model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import GeneratedValueStrategy, LogicalType


class ColumnModel(BaseModel):
    """A single table column.

    Both ``native_type`` (the original database representation) and ``logical_type``
    (the normalized, database-independent type) are preserved so reports can explain
    differences in the source's own terms.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    ordinal_position: int
    logical_type: LogicalType = LogicalType.UNKNOWN
    native_type: str
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    nullable: bool = True
    default_expression: str | None = None
    is_identity: bool = False
    is_generated: bool = False
    generated_strategy: GeneratedValueStrategy = GeneratedValueStrategy.NONE
    collation: str | None = None
    comment: str | None = None
    # Set when the raw identifier was quoted / case-sensitive in the source.
    quoted: bool = False
    extra: dict[str, str] = Field(default_factory=dict)
