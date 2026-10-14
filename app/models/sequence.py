"""Sequence / auto-increment canonical model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.core.enums import GeneratedValueStrategy


class SequenceModel(BaseModel):
    """A sequence or identity generator in canonical form."""

    model_config = ConfigDict(extra="forbid")

    name: str
    strategy: GeneratedValueStrategy = GeneratedValueStrategy.SEQUENCE
    start_value: int | None = None
    increment: int | None = None
    min_value: int | None = None
    max_value: int | None = None
    current_value: int | None = None
    cycle: bool = False
    # For identity/auto-increment, the owning table/column when known.
    owner_table: str | None = None
    owner_column: str | None = None
    quoted: bool = False
