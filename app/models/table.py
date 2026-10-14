"""Table canonical model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.column import ColumnModel
from app.models.constraint import ConstraintModel
from app.models.index import IndexModel
from app.models.partition import PartitionModel
from app.models.trigger import TriggerModel


class TableModel(BaseModel):
    """A table and its owned objects in canonical form.

    In Phase 1 only ``columns`` is populated by discovery; the remaining
    collections are defined so later phases can fill them without changing the
    model's consumers.
    """

    model_config = ConfigDict(extra="forbid")

    schema_name: str
    name: str
    columns: list[ColumnModel] = Field(default_factory=list)
    constraints: list[ConstraintModel] = Field(default_factory=list)
    indexes: list[IndexModel] = Field(default_factory=list)
    partitions: list[PartitionModel] = Field(default_factory=list)
    triggers: list[TriggerModel] = Field(default_factory=list)
    row_count: int | None = None
    comment: str | None = None
    quoted: bool = False

    def column_map(self) -> dict[str, ColumnModel]:
        """Columns keyed by name for O(1) lookup."""
        return {c.name: c for c in self.columns}
