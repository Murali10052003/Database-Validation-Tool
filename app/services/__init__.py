"""Application services.

Thin orchestration over adapters, discovery, the validation engine and reporting.
These are the entry points used by the CLI (and, in Phase 5, the API).
"""

from app.services.discovery_service import DiscoveryService
from app.services.migration_service import MigrationRun, MigrationService
from app.services.report_service import ReportService
from app.services.validation_service import ValidationService

__all__ = [
    "DiscoveryService",
    "MigrationRun",
    "MigrationService",
    "ReportService",
    "ValidationService",
]
