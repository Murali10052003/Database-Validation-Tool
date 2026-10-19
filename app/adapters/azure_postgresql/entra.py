"""Microsoft Entra ID (Azure AD) authentication for Azure Database for PostgreSQL.

Non-browser clients can authenticate with a short-lived Entra access token instead
of a password. Browser requests supply their own token to the adapter and never
call this credential chain. For CLI use, the token is acquired via
``azure-identity``'s :class:`DefaultAzureCredential`, which transparently supports
managed identity, Azure CLI, environment credentials, and VS Code sign-in.
"""

from __future__ import annotations

from app.core.exceptions import DriverNotInstalledError

# Resource scope for Entra authentication against Azure Database for PostgreSQL.
POSTGRES_ENTRA_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def fetch_entra_token( client_id: str | None = None) -> str:
    """Return an Entra access token to use as the PostgreSQL password.

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
        token = credential.get_token(POSTGRES_ENTRA_SCOPE)
    finally:
        # DefaultAzureCredential holds sockets open; release them promptly.
        close = getattr(credential, "close", None)
        if callable(close):
            close()
    return token.token
