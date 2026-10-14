"""Declared feature support for a database engine + platform."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DatabaseCapabilities(BaseModel):
    """What a given adapter's database supports.

    The validation engine consults these flags so it never reports a feature as
    ``FAIL`` when the database legitimately does not support it; it reports
    ``NOT_SUPPORTED`` or ``SKIPPED`` instead.
    """

    model_config = ConfigDict(frozen=True)

    schemas: bool = True
    indexes: bool = True
    sequences: bool = False
    identity_columns: bool = False
    views: bool = True
    materialized_views: bool = False
    procedures: bool = False
    functions: bool = False
    triggers: bool = False
    partitions: bool = False
    foreign_keys: bool = True
    check_constraints: bool = True
    unique_constraints: bool = True
    generated_columns: bool = False
