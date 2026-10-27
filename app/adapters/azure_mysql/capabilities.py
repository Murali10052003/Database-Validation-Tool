"""Declared capabilities for Azure Database for MySQL."""

from __future__ import annotations

from app.models.capabilities import DatabaseCapabilities

AZURE_MYSQL_CAPABILITIES = DatabaseCapabilities(
    schemas=True,
    indexes=True,
    sequences=False,
    identity_columns=True,  # AUTO_INCREMENT columns are modelled as identity.
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
