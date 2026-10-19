"""Trigger canonical model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TriggerModel(BaseModel):
    """A table trigger in canonical form."""

    model_config = ConfigDict(extra="forbid")

    name: str
    table: str
    timing: str | None = None  # BEFORE / AFTER / INSTEAD OF
    events: list[str] = Field(default_factory=list)  # INSERT / UPDATE / DELETE
    definition: str | None = None
    enabled: bool = True
    quoted: bool = False
