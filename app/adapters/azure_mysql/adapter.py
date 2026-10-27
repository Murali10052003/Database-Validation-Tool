"""Azure Database for MySQL adapter.

Azure Database for MySQL is MySQL on the Azure platform, so this reuses the MySQL
adapter's metadata/data access and only differs in database type, default
platform, capabilities, mandatory TLS, and Microsoft Entra ID authentication.
"""

from __future__ import annotations

from typing import Any

from app.adapters._entra import fetch_entra_token, resolve_connection_secret
from app.adapters.azure_mysql.capabilities import AZURE_MYSQL_CAPABILITIES
from app.adapters.mysql.adapter import MySQLAdapter
from app.core.enums import AuthMethod, DatabaseType, DeploymentPlatform
from app.core.exceptions import ConnectionError, DriverNotInstalledError
from app.models.capabilities import DatabaseCapabilities


class AzureMySQLAdapter(MySQLAdapter):
    """Adapter for Azure Database for MySQL (Flexible Server)."""

    DB_TYPE = DatabaseType.AZURE_MYSQL
    DEFAULT_PLATFORM = DeploymentPlatform.AZURE
    DISPLAY_NAME = "Azure MySQL"

    async def _resolve_password(self) -> str:
        """Return the connection secret: an Entra token or the configured password."""
        return await resolve_connection_secret(self.config, fetch_entra_token)

    async def _create_connection(self) -> Any:
        """Open a raw MySQL connection over TLS. Overridable in tests."""
        try:
            import mysql.connector
        except ImportError as exc:  # pragma: no cover - import guard
            raise DriverNotInstalledError("azure_mysql", "mysql-connector-python") from exc

        kwargs: dict[str, Any] = {
            "host": self.config.host,
            "port": self.config.port or 3306,
            "user": self.config.username,
            "password": await self._resolve_password(),
            "database": self.config.database,
            "connection_timeout": self.config.connect_timeout_seconds,
            # Azure Database for MySQL enforces TLS by default.
            "ssl_disabled": False,
        }
        if self.config.options.get("ssl_ca"):
            kwargs["ssl_ca"] = self.config.options["ssl_ca"]
        if self.config.auth_method == AuthMethod.ENTRA:
            # The Entra access token is sent as the password, in clear text over TLS.
            kwargs["auth_plugin"] = "mysql_clear_password"
        return mysql.connector.connect(**kwargs)

    async def connect(self) -> None:
        if self._connection is not None:
            return
        try:
            self._connection = await self._create_connection()
        except (DriverNotInstalledError, ConnectionError):
            raise
        except Exception as exc:
            if self.config.entra_browser_auth:
                # Never echo driver text: it may contain the access token.
                raise ConnectionError(
                    "Azure MySQL connection failed. Check Microsoft sign-in, token expiry, "
                    "database user, host, and TLS/network access."
                ) from None
            raise ConnectionError(f"Failed to connect to {self.DISPLAY_NAME}: {exc}") from exc

    def capabilities(self) -> DatabaseCapabilities:
        return AZURE_MYSQL_CAPABILITIES
