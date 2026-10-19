"""Azure SQL Database adapter.

Azure SQL is SQL Server on the Azure platform, so this reuses the SQL Server
adapter's metadata/data access and only differs in database type, default
platform, capabilities, and TLS/Entra defaults.
"""

from __future__ import annotations

from app.adapters.azure_sql.capabilities import AZURE_SQL_CAPABILITIES
from app.adapters.sqlserver.adapter import SQLServerAdapter
from app.core.enums import DatabaseType, DeploymentPlatform
from app.models.capabilities import DatabaseCapabilities


class AzureSQLAdapter(SQLServerAdapter):
    """Adapter for Azure SQL Database (SQL Server engine on Azure)."""

    DB_TYPE = DatabaseType.AZURE_SQL
    DEFAULT_PLATFORM = DeploymentPlatform.AZURE

    def capabilities(self) -> DatabaseCapabilities:
        return AZURE_SQL_CAPABILITIES
