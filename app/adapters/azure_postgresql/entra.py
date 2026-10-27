"""Microsoft Entra ID (Azure AD) authentication for Azure Database for PostgreSQL.

The implementation is shared with the other Azure open-source adapters; see
:mod:`app.adapters._entra`.
"""

from __future__ import annotations

from app.adapters._entra import OSSRDBMS_ENTRA_SCOPE, fetch_entra_token

# Resource scope for Entra authentication against Azure Database for PostgreSQL.
POSTGRES_ENTRA_SCOPE = OSSRDBMS_ENTRA_SCOPE

__all__ = ["POSTGRES_ENTRA_SCOPE", "fetch_entra_token"]
