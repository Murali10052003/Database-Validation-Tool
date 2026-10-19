"""Routine (procedure / function) canonical model."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RoutineType(str, Enum):
    """Kind of routine."""

    PROCEDURE = "PROCEDURE"
    FUNCTION = "FUNCTION"


class RoutineParameter(BaseModel):
    """A routine parameter."""

    model_config = ConfigDict(extra="forbid")

    name: str
    native_type: str
    mode: str = "IN"


class RoutineModel(BaseModel):
    """A stored procedure or function in canonical form."""

    model_config = ConfigDict(extra="forbid")

    name: str
    routine_type: RoutineType
    parameters: list[RoutineParameter] = Field(default_factory=list)
    return_type: str | None = None
    language: str | None = None
    definition: str | None = None
    quoted: bool = False
