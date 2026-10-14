"""Constraint canonical model (primary key, foreign key, unique, check)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ConstraintType(str, Enum):
    """Kinds of table constraint."""

    PRIMARY_KEY = "PRIMARY_KEY"
    FOREIGN_KEY = "FOREIGN_KEY"
    UNIQUE = "UNIQUE"
    CHECK = "CHECK"


class ForeignKeyReference(BaseModel):
    """The referenced side of a foreign key."""

    model_config = ConfigDict(extra="forbid")

    ref_schema: str | None = None
    ref_table: str
    ref_columns: list[str] = Field(default_factory=list)
    on_delete: str | None = None
    on_update: str | None = None


class ConstraintModel(BaseModel):
    """A table constraint in canonical form."""

    model_config = ConfigDict(extra="forbid")

    name: str
    constraint_type: ConstraintType
    columns: list[str] = Field(default_factory=list)
    # Present for CHECK constraints.
    check_expression: str | None = None
    # Present for FOREIGN_KEY constraints.
    references: ForeignKeyReference | None = None
    deferrable: bool = False
    quoted: bool = False
