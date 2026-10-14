"""Exception hierarchy for the platform.

All raised exceptions derive from :class:`MigrationValidatorError` so callers can
catch a single base type. Validators are expected to convert unexpected
exceptions into ``ERROR`` results rather than letting them abort a whole run.
"""

from __future__ import annotations


class MigrationValidatorError(Exception):
    """Base class for all platform errors."""


class ConfigurationError(MigrationValidatorError):
    """Raised when configuration is missing, malformed or references an unknown value."""


class UnsupportedDatabaseError(MigrationValidatorError):
    """Raised when a database type has no registered adapter."""


class AdapterError(MigrationValidatorError):
    """Base class for adapter-level failures."""


class ConnectionError(AdapterError):
    """Raised when a database connection cannot be established."""


class DriverNotInstalledError(AdapterError):
    """Raised when the driver required by an adapter is not installed."""

    def __init__(self, database_type: str, package: str) -> None:
        super().__init__(
            f"The driver for '{database_type}' is not installed. "
            f"Install it with: pip install {package}"
        )
        self.database_type = database_type
        self.package = package


class QueryError(AdapterError):
    """Raised when a query fails to execute."""


class QueryTimeoutError(QueryError):
    """Raised when a query exceeds its configured time limit."""


class NotSupportedError(AdapterError):
    """Raised when an adapter is asked for a capability it does not support."""


class MappingError(MigrationValidatorError):
    """Raised when a mapping definition is invalid or cannot be resolved."""


class ValidationEngineError(MigrationValidatorError):
    """Raised for engine-level orchestration failures."""


class MigrationNotFoundError(MigrationValidatorError):
    """Raised when a migration id is not found in the run store."""
