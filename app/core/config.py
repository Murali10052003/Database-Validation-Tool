"""Configuration models and loading.

Configuration is expressed as YAML and parsed into Pydantic v2 models. String
values of the form ``${VAR}`` (or ``${VAR:-default}``) are interpolated from the
process environment before validation, so secrets are never committed to disk.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import (
    AuthMethod,
    ComparisonOperator,
    DatabaseType,
    DeploymentPlatform,
    ValidationProfile,
)
from app.core.exceptions import ConfigurationError

_ENV_PATTERN = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}")


def _interpolate_env(value: Any) -> Any:
    """Recursively replace ``${VAR}`` / ``${VAR:-default}`` in strings."""
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    if isinstance(value, str):

        def _sub(match: re.Match[str]) -> str:
            name = match.group("name")
            default = match.group("default")
            env_val = os.environ.get(name)
            if env_val is not None:
                return env_val
            if default is not None:
                return default
            raise ConfigurationError(
                f"Environment variable '{name}' referenced in config is not set "
                f"and has no default."
            )

        return _ENV_PATTERN.sub(_sub, value)
    return value


class DatabaseConnectionConfig(BaseModel):
    """Connection parameters for a source or target database."""

    model_config = ConfigDict(extra="forbid")

    type: DatabaseType
    platform: DeploymentPlatform = DeploymentPlatform.UNKNOWN
    host: str
    port: int | None = None
    # Oracle uses ``service``; most others use ``database``. Both are optional so
    # each adapter can validate what it actually needs.
    service: str | None = None
    database: str | None = None
    username: str
    password: SecretStr = SecretStr("")
    entra_token: SecretStr | None = Field(default=None, exclude=True, repr=False)
    entra_token_expires_at: int | None = Field(default=None, exclude=True, repr=False)
    entra_browser_auth: bool = Field(default=False, exclude=True)
    # Password auth by default; ENTRA uses a Microsoft Entra ID token (Azure targets).
    auth_method: AuthMethod = AuthMethod.PASSWORD
    # Extra driver-specific options (e.g. TLS settings), passed through to the adapter.
    options: dict[str, Any] = Field(default_factory=dict)
    connect_timeout_seconds: int = 30
    ssl: bool = False

    @field_validator("type", "platform", mode="before")
    @classmethod
    def _lower(cls, v: Any) -> Any:
        return v.lower() if isinstance(v, str) else v


class DataValidationConfig(BaseModel):
    """Tuning for data-level validation (used from Phase 3 onward)."""

    model_config = ConfigDict(extra="forbid")

    # Maximum ordered rows hashed per side; larger tables get partial checksum coverage.
    chunk_size: int = Field(default=100, ge=1)
    batch_size: int = 10_000
    parallel_workers: int = 4
    checksum: bool = False
    # Time limit for each exact row-count query (0 disables the limit).
    timeout_seconds: int = Field(default=300, ge=0)
    # "exact_then_estimate": when an exact COUNT(*) times out, compare the database's
    # statistics estimate instead and report the table as WARNING (never PASS).
    # "exact": a timeout is reported as an ERROR. Also governs NULL-count estimates.
    row_count_strategy: Literal["exact", "exact_then_estimate"] = "exact_then_estimate"
    # Tables whose statistics estimate exceeds this many rows get no NULL-count/aggregate
    # scan (reported SKIPPED). 0 = no limit.
    max_table_rows_for_column_checks: int = Field(default=0, ge=0)
    # A timed-out profile scan is retried over this many primary-key ranges (exact, each
    # range with its own time limit). 0 disables the retry.
    fallback_chunks: int = Field(default=32, ge=0, le=1000)


class SchemaValidationConfig(BaseModel):
    """Toggles for schema-level comparison."""

    model_config = ConfigDict(extra="forbid")

    compare_columns: bool = True
    compare_indexes: bool = True
    compare_constraints: bool = True
    compare_sequences: bool = True
    compare_views: bool = True
    compare_routines: bool = True
    compare_triggers: bool = True
    compare_partitions: bool = True


class CustomValidationConfig(BaseModel):
    """A user-defined business validation comparing two queries."""

    model_config = ConfigDict(extra="forbid")

    name: str
    source_query: str
    target_query: str
    comparison: ComparisonOperator = ComparisonOperator.EQUAL
    tolerance: float = 0.0
    severity: str | None = None


ValidationCheck = Literal[
    "schema", "constraints", "indexes", "sequences", "views", "routines",
    "triggers", "partitions", "rules", "row_count", "null_count", "aggregate",
    "referential_integrity", "checksum", "custom_query",
]
SelectedChecks = Annotated[list[ValidationCheck], Field(min_length=1)]


class ValidationConfig(BaseModel):
    """What to validate and how."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    profile: ValidationProfile = ValidationProfile.STANDARD
    selected_checks: SelectedChecks | None = None
    data: DataValidationConfig = Field(default_factory=DataValidationConfig)
    schema_options: SchemaValidationConfig = Field(
        default_factory=SchemaValidationConfig, alias="schema"
    )
    custom_validations: list[CustomValidationConfig] = Field(default_factory=list)


class MappingConfig(BaseModel):
    """Raw source-to-target name mappings and exclusions.

    Resolution logic lives in :mod:`app.mapping`; this model only holds the data.
    Keys are source object names; values are target object names.
    """

    model_config = ConfigDict(extra="forbid")

    schemas: dict[str, str] = Field(default_factory=dict)
    tables: dict[str, str] = Field(default_factory=dict)
    columns: dict[str, str] = Field(default_factory=dict)
    included_objects: list[str] = Field(default_factory=list)
    excluded_objects: list[str] = Field(default_factory=list)
    type_overrides: dict[str, str] = Field(default_factory=dict)
    validation_overrides: dict[str, str] = Field(default_factory=dict)


class MigrationMeta(BaseModel):
    """Descriptive metadata for a migration."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None


def clean_schema_scope(value: list[str] | None) -> list[str] | None:
    """Trim and de-duplicate a per-side schema scope; reject an empty selection."""
    if value is None:
        return None
    cleaned = list(dict.fromkeys(name.strip() for name in value if name.strip()))
    if not cleaned:
        raise ValueError("Select at least one schema, or omit the schema scope")
    return cleaned


class MigrationConfig(BaseModel):
    """Top-level configuration for a migration validation run."""

    model_config = ConfigDict(extra="forbid")

    migration: MigrationMeta
    source: DatabaseConnectionConfig
    target: DatabaseConnectionConfig
    mapping: MappingConfig = Field(default_factory=MappingConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    discovery_mode: Literal["full", "refresh", "reuse"] = "full"
    source_inventory_id: str | None = None
    target_inventory_id: str | None = None
    mapping_version_id: str | None = None
    # Independent per-side discovery scope. None = unscoped (legacy); an empty list
    # is rejected rather than treated as "all schemas".
    source_schemas: list[str] | None = None
    target_schemas: list[str] | None = None

    @field_validator("source_schemas", "target_schemas")
    @classmethod
    def _clean_scope(cls, value: list[str] | None) -> list[str] | None:
        return clean_schema_scope(value)

    @classmethod
    def from_yaml(cls, path: str | Path) -> MigrationConfig:
        """Load, interpolate environment variables, and validate a YAML config."""
        p = Path(path)
        if not p.is_file():
            raise ConfigurationError(f"Config file not found: {p}")
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"Invalid YAML in {p}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigurationError(f"Config root must be a mapping: {p}")
        interpolated = _interpolate_env(raw)
        try:
            return cls.model_validate(interpolated)
        except Exception as exc:  # pydantic ValidationError -> friendly message
            raise ConfigurationError(f"Invalid configuration in {p}: {exc}") from exc


class Settings(BaseSettings):
    """Process-level settings sourced from the environment (``MV_`` prefix)."""

    model_config = SettingsConfigDict(env_prefix="MV_", env_file=".env", extra="ignore")

    report_dir: Path = Path("reports")
    catalog_path: Path = Field(default_factory=lambda: Path(
        os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share"))
    ) / "MigrationValidator" / "catalog.sqlite3")
    log_level: str = "INFO"
    run_log_dir: Path = Path("reports/logs")
    run_log_retention_days: int = Field(default=0, ge=0)
    type_mappings_dir: Path = Path("config/type_mappings")


def get_settings() -> Settings:
    """Return process-level settings."""
    return Settings()
