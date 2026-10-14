"""Declared capabilities for MySQL."""

from __future__ import annotations

from app.models.capabilities import DatabaseCapabilities

MYSQL_CAPABILITIES = DatabaseCapabilities(
    schemas=True,
    indexes=True,
    sequences=False,
    identity_columns=False,  # MySQL uses AUTO_INCREMENT.
    views=True,
    materialized_views=False,
    procedures=True,
    functions=True,
    triggers=True,
    partitions=True,
    foreign_keys=True,
    check_constraints=True,
    unique_constraints=True,
    generated_columns=True,
)
