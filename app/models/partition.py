"""Partition canonical model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PartitionModel(BaseModel):
    """A table partition in canonical form."""

    model_config = ConfigDict(extra="forbid")

    name: str
    table: str
    strategy: str | None = None  # RANGE / LIST / HASH
    partition_key: list[str] = Field(default_factory=list)
    bound: str | None = None
    quoted: bool = False
