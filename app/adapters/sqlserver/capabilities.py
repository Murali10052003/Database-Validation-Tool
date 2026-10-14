"""Declared capabilities for SQL Server."""

from __future__ import annotations

from app.models.capabilities import DatabaseCapabilities

SQLSERVER_CAPABILITIES = DatabaseCapabilities(
    schemas=True,
    indexes=True,
    sequences=True,
    identity_columns=True,
    views=True,
    materialized_views=False,  # Indexed views are modelled separately later.
    procedures=True,
    functions=True,
    triggers=True,
    partitions=True,
    foreign_keys=True,
    check_constraints=True,
    unique_constraints=True,
    generated_columns=True,  # Computed columns.
)
