"""API request/response schemas for the web POC."""

from app.schemas.api import (
    ConnectionCheck,
    ConnectionInput,
    DiscoverResponse,
    ErrorResponse,
    MappingInput,
    MigrationRequest,
    SchemaSummary,
    TestConnectionResponse,
)

__all__ = [
    "ConnectionCheck",
    "ConnectionInput",
    "DiscoverResponse",
    "ErrorResponse",
    "MappingInput",
    "MigrationRequest",
    "SchemaSummary",
    "TestConnectionResponse",
]
