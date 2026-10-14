"""Schema canonical model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.routine import RoutineModel
from app.models.sequence import SequenceModel
from app.models.table import TableModel
from app.models.view import ViewModel


class SchemaModel(BaseModel):
    """A schema (namespace) and the objects it owns."""

    model_config = ConfigDict(extra="forbid")

    name: str
    tables: list[TableModel] = Field(default_factory=list)
    views: list[ViewModel] = Field(default_factory=list)
    sequences: list[SequenceModel] = Field(default_factory=list)
    routines: list[RoutineModel] = Field(default_factory=list)
    quoted: bool = False

    def table_map(self) -> dict[str, TableModel]:
        """Tables keyed by name."""
        return {t.name: t for t in self.tables}
