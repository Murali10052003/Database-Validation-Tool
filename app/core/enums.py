"""Enumerations shared across the platform.

These enums are deliberately database-agnostic. No adapter-specific values belong
here; adapters translate their native concepts into these canonical enums.
"""

from __future__ import annotations

from enum import Enum


class DatabaseType(str, Enum):
    """Supported source and target database engines.

    ``MYSQL``, ``SQLSERVER`` and ``AZURE_SQL`` are declared for Phase 1 so the
    factory and configuration can reference them, but their adapters are stubs.
    """

    ORACLE = "oracle"
    MYSQL = "mysql"
    SQLSERVER = "sqlserver"
    AZURE_POSTGRESQL = "azure_postgresql"
    AZURE_SQL = "azure_sql"


class DeploymentPlatform(str, Enum):
    """Where a database engine is deployed.

    Kept separate from the engine so capabilities can differ between, e.g., a
    self-managed PostgreSQL and Azure Database for PostgreSQL.
    """

    SELF_MANAGED = "self_managed"
    AZURE = "azure"
    UNKNOWN = "unknown"


class AuthMethod(str, Enum):
    """How an adapter authenticates to a database.

    ``ENTRA`` uses a Microsoft Entra ID (Azure AD) access token in place of a
    password; only Azure-platform adapters honour it.
    """

    PASSWORD = "password"
    ENTRA = "entra"

    @classmethod
    def _missing_(cls, value: object) -> AuthMethod | None:
        if isinstance(value, str):
            lower = value.lower()
            return next((m for m in cls if m.value == lower), None)
        return None


class ValidationStatus(str, Enum):
    """Outcome of a single validation check."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    ERROR = "ERROR"


class Severity(str, Enum):
    """Business severity attached to a validation result."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ValidationCategory(str, Enum):
    """High-level grouping of a validation check for reporting."""

    CONNECTIVITY = "CONNECTIVITY"
    SCHEMA = "SCHEMA"
    TABLE = "TABLE"
    COLUMN = "COLUMN"
    CONSTRAINT = "CONSTRAINT"
    INDEX = "INDEX"
    SEQUENCE = "SEQUENCE"
    VIEW = "VIEW"
    ROUTINE = "ROUTINE"
    TRIGGER = "TRIGGER"
    PARTITION = "PARTITION"
    ROW_COUNT = "ROW_COUNT"
    NULL_COUNT = "NULL_COUNT"
    AGGREGATE = "AGGREGATE"
    CHECKSUM = "CHECKSUM"
    SAMPLE_DATA = "SAMPLE_DATA"
    REFERENTIAL_INTEGRITY = "REFERENTIAL_INTEGRITY"
    CUSTOM_QUERY = "CUSTOM_QUERY"
    COMPATIBILITY = "COMPATIBILITY"


class ValidationProfile(str, Enum):
    """Named bundles of validators to run."""

    QUICK = "QUICK"
    STANDARD = "STANDARD"
    FULL = "FULL"
    CUSTOM = "CUSTOM"

    @classmethod
    def _missing_(cls, value: object) -> ValidationProfile | None:
        # Accept case-insensitive input from YAML configs, the API and the CLI.
        if isinstance(value, str):
            upper = value.upper()
            return next((m for m in cls if m.value == upper), None)
        return None


class GeneratedValueStrategy(str, Enum):
    """How a column's values are auto-generated, normalized across engines."""

    SEQUENCE = "SEQUENCE"
    IDENTITY = "IDENTITY"
    AUTO_INCREMENT = "AUTO_INCREMENT"
    NONE = "NONE"


class ComparisonOperator(str, Enum):
    """Comparison operators for custom validation queries."""

    EQUAL = "EQUAL"
    NOT_EQUAL = "NOT_EQUAL"
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    APPROXIMATE = "APPROXIMATE"
    CUSTOM = "CUSTOM"


class LogicalType(str, Enum):
    """Database-independent logical data types.

    Native database types are normalized to one of these so that, for example,
    Oracle ``NUMBER(10)`` and PostgreSQL ``INTEGER`` compare as equal.
    """

    STRING = "STRING"
    FIXED_STRING = "FIXED_STRING"
    TEXT = "TEXT"
    BOOLEAN = "BOOLEAN"
    SMALLINT = "SMALLINT"
    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    DECIMAL = "DECIMAL"
    FLOAT = "FLOAT"
    DOUBLE = "DOUBLE"
    DATE = "DATE"
    TIME = "TIME"
    TIMESTAMP = "TIMESTAMP"
    TIMESTAMP_TZ = "TIMESTAMP_TZ"
    INTERVAL = "INTERVAL"
    BINARY = "BINARY"
    BLOB = "BLOB"
    UUID = "UUID"
    JSON = "JSON"
    XML = "XML"
    ENUM = "ENUM"
    UNKNOWN = "UNKNOWN"
