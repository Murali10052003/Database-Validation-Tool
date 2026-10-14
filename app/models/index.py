"""Index canonical model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class IndexColumn(BaseModel):
    """A single column participating in an index."""

    model_config = ConfigDict(extra="forbid")

    name: str
    descending: bool = False
    # For expression / functional indexes the ordinal expression, if any.
    expression: str | None = None


class IndexModel(BaseModel):
    """A table index in canonical form."""

    model_config = ConfigDict(extra="forbid")

    name: str
    columns: list[IndexColumn] = Field(default_factory=list)
    unique: bool = False
    primary: bool = False
    index_type: str | None = None
    partial_predicate: str | None = None
    quoted: bool = False
