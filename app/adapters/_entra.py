"""Microsoft Entra ID (Azure AD) authentication shared by the Azure open-source
database adapters (Azure Database for PostgreSQL and for MySQL).

Non-browser clients can authenticate with a short-lived Entra access token instead
of a password. Browser requests supply their own token to the adapter and never
call this credential chain. For CLI use, the token is acquired via
``azure-identity``'s :class:`DefaultAzureCredential`, which transparently supports
managed identity, Azure CLI, environment credentials, and VS Code sign-in.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from app.core.config import DatabaseConnectionConfig
from app.core.enums import AuthMethod
from app.core.exceptions import ConnectionError, DriverNotInstalledError

# Resource scope for Entra authentication against Azure Database for
# PostgreSQL and Azure Database for MySQL (both use the OSS RDBMS resource).
OSSRDBMS_ENTRA_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def fetch_entra_token(client_id: str | None = None) -> str:
    """Return an Entra access token to use as the database password.

    ``client_id`` selects a specific user-assigned managed identity when set;
    otherwise the default credential chain is used.
    """
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:  # pragma: no cover - import guard
        raise DriverNotInstalledError("entra", "azure-identity") from exc

    credential = (
        DefaultAzureCredential(managed_identity_client_id=client_id)
        if client_id
        else DefaultAzureCredential()
    )
    try:
        token = credential.get_token(OSSRDBMS_ENTRA_SCOPE)
    finally:
        # DefaultAzureCredential holds sockets open; release them promptly.
        close = getattr(credential, "close", None)
        if callable(close):
            close()
    return token.token


async def resolve_connection_secret(
    config: DatabaseConnectionConfig,
    token_fetcher: Callable[[str | None], str],
) -> str:
    """Return the connection secret: an Entra token or the configured password."""
    if config.auth_method == AuthMethod.ENTRA:
        if config.entra_browser_auth:
            if not config.entra_token or not config.entra_token_expires_at:
                raise ConnectionError("Microsoft sign-in is required. Test this connection again.")
            if config.entra_token_expires_at <= time.time() + 30:
                raise ConnectionError("Microsoft sign-in has expired. Test this connection again.")
            return config.entra_token.get_secret_value()
        client_id = config.options.get("managed_identity_client_id")
        # Token acquisition is blocking; keep the event loop responsive.
        return await asyncio.to_thread(token_fetcher, client_id)
    return config.password.get_secret_value()
