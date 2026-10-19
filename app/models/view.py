"""View / materialized view canonical model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ViewModel(BaseModel):
    """A view or materialized view in canonical form."""

    model_config = ConfigDict(extra="forbid")

    name: str
    materialized: bool = False
    definition: str | None = None
    quoted: bool = False
