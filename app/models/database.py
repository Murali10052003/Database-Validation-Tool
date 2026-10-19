"""Database-level canonical model and adapter result types."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import DatabaseType, DeploymentPlatform
from app.models.schema import SchemaModel


class DatabaseInfo(BaseModel):
    """Identity of a live database, gathered on connect."""

    model_config = ConfigDict(extra="forbid")

    database_type: DatabaseType
    platform: DeploymentPlatform = DeploymentPlatform.UNKNOWN
    version: str | None = None
    server_name: str | None = None
    default_schema: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class ConnectionResult(BaseModel):
    """Outcome of a connectivity test. Never contains credentials."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    database_type: DatabaseType
    version: str | None = None
    message: str | None = None
    latency_ms: float | None = None
    error: str | None = None


class QueryResult(BaseModel):
    """Rows returned by :meth:`DatabaseAdapter.execute_query`."""

    model_config = ConfigDict(extra="forbid")

    columns: list[str] = Field(default_factory=list)
    rows: list[tuple[Any, ...]] = Field(default_factory=list)
    row_count: int = 0

    def scalar(self) -> Any | None:
        """First column of the first row, or ``None`` when empty."""
        if self.rows and self.rows[0]:
            return self.rows[0][0]
        return None


class DatabaseModel(BaseModel):
    """A complete, database-independent snapshot of a database's structure."""

    model_config = ConfigDict(extra="forbid")

    database_type: DatabaseType
    platform: DeploymentPlatform = DeploymentPlatform.UNKNOWN
    version: str | None = None
    schemas: list[SchemaModel] = Field(default_factory=list)

    def schema_map(self) -> dict[str, SchemaModel]:
        """Schemas keyed by name."""
        return {s.name: s for s in self.schemas}
