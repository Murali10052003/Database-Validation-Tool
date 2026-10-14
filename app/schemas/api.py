"""Request/response schemas for the web API.

These accept plain-text passwords from the UI and are converted into a validated
:class:`~app.core.config.MigrationConfig`. Responses never echo credentials back.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.core.config import (
    DatabaseConnectionConfig,
    MappingConfig,
    MigrationConfig,
    MigrationMeta,
    SelectedChecks,
    ValidationConfig,
    clean_schema_scope,
)
from app.core.enums import (
    AuthMethod,
    DatabaseType,
    DeploymentPlatform,
    ValidationProfile,
    ValidationStatus,
)


class ConnectionInput(BaseModel):
    """A single database connection as entered in the UI."""

    model_config = ConfigDict(extra="forbid")

    type: DatabaseType
    platform: DeploymentPlatform = DeploymentPlatform.UNKNOWN
    host: str
    port: int | None = None
    service: str | None = None
    database: str | None = None
    username: str
    password: str = ""
    entra_token: SecretStr | None = Field(default=None, exclude=True, repr=False)
    entra_token_expires_at: int | None = Field(default=None, exclude=True, repr=False)
    auth_method: AuthMethod = AuthMethod.PASSWORD
    entra_mode: Literal["browser", "local"] = "browser"
    entra_client_id: str = Field(default="", max_length=36, exclude=True)
    entra_tenant_id: str = Field(default="", max_length=36, exclude=True)
    ssl: bool = False

    @model_validator(mode="after")
    def validate_entra_mode(self):
        if self.entra_mode == "local":
            if self.auth_method != AuthMethod.ENTRA or self.type != DatabaseType.AZURE_POSTGRESQL:
                raise ValueError(
                    "Local credentials require Azure PostgreSQL with Entra authentication."
                )
            if os.environ.get("MV_ALLOW_LOCAL_ENTRA", "").lower() != "true":
                raise ValueError(
                    "Local Entra credentials are disabled. "
                    "Set MV_ALLOW_LOCAL_ENTRA=true on the local backend."
                )
            if self.entra_token is not None:
                raise ValueError("Local credential mode cannot accept a browser token.")
        return self

    def to_config(self) -> DatabaseConnectionConfig:
        return DatabaseConnectionConfig(
            type=self.type,
            platform=self.platform,
            host=self.host,
            port=self.port,
            service=self.service,
            database=self.database,
            username=self.username,
            password=self.password,
            entra_token=self.entra_token,
            entra_token_expires_at=self.entra_token_expires_at,
            entra_browser_auth=(
                self.auth_method == AuthMethod.ENTRA and self.entra_mode == "browser"
            ),
            auth_method=self.auth_method,
            ssl=self.ssl,
        )


class MappingInput(BaseModel):
    """Source-to-target name mappings and exclusions."""

    model_config = ConfigDict(extra="forbid")

    schemas: dict[str, str] = Field(default_factory=dict)
    tables: dict[str, str] = Field(default_factory=dict)
    columns: dict[str, str] = Field(default_factory=dict)
    type_overrides: dict[str, str] = Field(default_factory=dict)
    validation_overrides: dict[str, str] = Field(default_factory=dict)
    included_objects: list[str] = Field(default_factory=list)
    excluded_objects: list[str] = Field(default_factory=list)

    def to_config(self) -> MappingConfig:
        return MappingConfig(
            schemas=self.schemas,
            tables=self.tables,
            columns=self.columns,
            type_overrides=self.type_overrides,
            validation_overrides=self.validation_overrides,
            included_objects=self.included_objects,
            excluded_objects=self.excluded_objects,
        )


class MigrationRequest(BaseModel):
    """A full migration definition posted from the UI."""

    model_config = ConfigDict(extra="forbid")

    name: str = "Ad-hoc migration"
    source: ConnectionInput
    target: ConnectionInput
    mapping: MappingInput = Field(default_factory=MappingInput)
    profile: ValidationProfile = ValidationProfile.STANDARD
    selected_checks: SelectedChecks | None = None
    discovery_mode: Literal["full", "refresh", "reuse"] = "full"
    source_inventory_id: str | None = None
    target_inventory_id: str | None = None
    mapping_version_id: str | None = None
    source_schemas: list[str] | None = None
    target_schemas: list[str] | None = None

    @field_validator("source_schemas", "target_schemas")
    @classmethod
    def _clean_scope(cls, value: list[str] | None) -> list[str] | None:
        return clean_schema_scope(value)

    def to_migration_config(self) -> MigrationConfig:
        return MigrationConfig(
            migration=MigrationMeta(name=self.name),
            source=self.source.to_config(),
            target=self.target.to_config(),
            mapping=self.mapping.to_config(),
            validation=ValidationConfig(profile=self.profile, selected_checks=self.selected_checks),
            discovery_mode=self.discovery_mode,
            source_inventory_id=self.source_inventory_id,
            target_inventory_id=self.target_inventory_id,
            mapping_version_id=self.mapping_version_id,
            source_schemas=self.source_schemas,
            target_schemas=self.target_schemas,
        )


class ConnectionCheck(BaseModel):
    """Connectivity outcome for one side (no credentials)."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    database_type: DatabaseType
    version: str | None = None
    latency_ms: float | None = None
    message: str | None = None
    error: str | None = None


class TestConnectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: ConnectionCheck
    target: ConnectionCheck


class SchemaSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    tables: int
    columns: int


class DiscoverResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: str
    database_type: DatabaseType
    version: str | None = None
    schemas: list[SchemaSummary] = Field(default_factory=list)
    table_count: int = 0


class SchemaListResponse(BaseModel):
    """Visible schema names for one connection (no tables or columns)."""

    model_config = ConfigDict(extra="forbid")

    database_type: DatabaseType
    version: str | None = None
    schemas: list[str] = Field(default_factory=list)


class ObjectCounts(BaseModel):
    """Discovered object counts for one side of a migration."""

    model_config = ConfigDict(extra="forbid")

    database_type: DatabaseType
    version: str | None = None
    schemas: int = 0
    tables: int = 0
    columns: int = 0
    indexes: int = 0
    constraints: int = 0
    sequences: int = 0
    views: int = 0


class TableMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    match_type: str  # exact | case_insensitive


class SchemaMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    match_type: str
    matched_tables: list[TableMatch] = Field(default_factory=list)
    unmatched_source_tables: list[str] = Field(default_factory=list)
    unmatched_target_tables: list[str] = Field(default_factory=list)


class AmbiguousMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    candidates: list[str] = Field(default_factory=list)


class PlanResponse(BaseModel):
    """Auto-discovery + auto-matching plan the UI renders before validation."""

    model_config = ConfigDict(extra="forbid")

    source: ObjectCounts
    target: ObjectCounts
    schema_matches: list[SchemaMatch] = Field(default_factory=list)
    unmatched_source_schemas: list[str] = Field(default_factory=list)
    unmatched_target_schemas: list[str] = Field(default_factory=list)
    ambiguous_schemas: list[AmbiguousMatch] = Field(default_factory=list)
    # Suggested source-schema -> target-schema mapping (the default, editable in the UI).
    suggested_mapping: dict[str, str] = Field(default_factory=dict)
    source_inventory_id: str | None = None
    target_inventory_id: str | None = None
    mapping_version_id: str | None = None
    saved_mapping: MappingInput | None = None
    # False when the inventories hold schema/table names only (scoped Discover & match):
    # columns, constraints, indexes and other objects are collected at validation time.
    metadata_complete: bool = True
    source_scope: list[str] | None = None
    target_scope: list[str] | None = None


class SavedConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    label: str = Field(min_length=1, max_length=100)
    type: DatabaseType
    platform: DeploymentPlatform = DeploymentPlatform.UNKNOWN
    host: str = Field(min_length=1)
    port: int | None = Field(default=None, ge=1, le=65535)
    service: str | None = None
    database: str | None = None
    username: str = Field(min_length=1)
    auth_method: AuthMethod = AuthMethod.PASSWORD
    ssl: bool = False


class ReportListItem(BaseModel):
    """Lightweight summary of a saved report for list views."""

    model_config = ConfigDict(extra="forbid")

    migration_id: str
    migration_name: str
    generated_at: datetime
    profile: ValidationProfile
    overall_status: ValidationStatus
    total: int = 0
    passed: int = 0
    failed: int = 0
    warning: int = 0
    duration_ms: int | None = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: str
    error_type: str | None = None


def query_dict(pairs: list[dict[str, Any]] | None) -> dict[str, str]:
    """Convert a list of ``{key, value}`` UI rows into a dict, ignoring blanks."""
    result: dict[str, str] = {}
    for pair in pairs or []:
        key = str(pair.get("key", "")).strip()
        value = str(pair.get("value", "")).strip()
        if key:
            result[key] = value
    return result
