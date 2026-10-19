"""Microsoft Entra ID authentication for the Azure PostgreSQL adapter."""

from __future__ import annotations

import time

import pytest
from pydantic import SecretStr

import app.adapters.azure_postgresql.adapter as pg_adapter
from app.adapters.azure_postgresql.adapter import AzurePostgreSQLAdapter
from app.core.config import DatabaseConnectionConfig
from app.core.enums import AuthMethod, DatabaseType, DeploymentPlatform
from app.core.exceptions import ConnectionError
from app.schemas.api import ConnectionInput


def _config(auth: AuthMethod, password: str = "") -> DatabaseConnectionConfig:
    return DatabaseConnectionConfig(
        type=DatabaseType.AZURE_POSTGRESQL,
        platform=DeploymentPlatform.AZURE,
        host="pg.example.com",
        port=5432,
        database="appdb",
        username="user@tenant",
        password=password,
        auth_method=auth,
    )


def test_auth_method_parses_case_insensitively() -> None:
    cfg = DatabaseConnectionConfig(
        type="azure_postgresql", host="h", database="d", username="u",
        auth_method="Entra",
    )
    assert cfg.auth_method is AuthMethod.ENTRA


async def test_password_auth_uses_configured_password() -> None:
    adapter = AzurePostgreSQLAdapter(_config(AuthMethod.PASSWORD, password="s3cret"))
    assert await adapter._resolve_password() == "s3cret"


async def test_entra_auth_uses_token(monkeypatch) -> None:
    monkeypatch.setattr(pg_adapter, "fetch_entra_token", lambda client_id=None: "aad-token")
    adapter = AzurePostgreSQLAdapter(_config(AuthMethod.ENTRA))
    assert await adapter._resolve_password() == "aad-token"


async def test_local_web_mode_uses_default_credentials_only_when_enabled(monkeypatch):
    values = dict(type="azure_postgresql", host="db.example", username="reader",
                  auth_method="entra", entra_mode="local")
    monkeypatch.delenv("MV_ALLOW_LOCAL_ENTRA", raising=False)
    with pytest.raises(ValueError, match="disabled"):
        ConnectionInput(**values)
    monkeypatch.setenv("MV_ALLOW_LOCAL_ENTRA", "true")
    monkeypatch.setattr(pg_adapter, "fetch_entra_token", lambda client_id=None: "local-token")
    config = ConnectionInput(**values).to_config()
    assert config.entra_browser_auth is False
    assert await AzurePostgreSQLAdapter(config)._resolve_password() == "local-token"
    with pytest.raises(ValueError, match="cannot accept"):
        ConnectionInput(**values, entra_token="browser-token")
    browser = ConnectionInput(**{**values, "entra_mode": "browser"}).to_config()
    with pytest.raises(ConnectionError, match="sign-in"):
        await AzurePostgreSQLAdapter(browser)._resolve_password()


async def test_browser_token_used_without_default_credentials(monkeypatch):
    def unexpected_default(*args):
        pytest.fail("Browser requests must not use DefaultAzureCredential")
    monkeypatch.setattr(pg_adapter, "fetch_entra_token", unexpected_default)
    request = ConnectionInput(
        type="azure_postgresql", host="db.example", username="database-role",
        auth_method="entra", entra_token="browser-secret",
        entra_token_expires_at=int(time.time()) + 3600,
        entra_client_id="11111111-1111-1111-1111-111111111111",
        entra_tenant_id="22222222-2222-2222-2222-222222222222",
    )
    config = request.to_config()
    assert await AzurePostgreSQLAdapter(config)._resolve_password() == "browser-secret"
    for model in (request, config):
        assert "browser-secret" not in repr(model)
        assert "entra_token" not in model.model_dump()
        assert "entra_client_id" not in model.model_dump()
        assert "entra_tenant_id" not in model.model_dump()
        assert "browser-secret" not in model.model_dump_json()


@pytest.mark.parametrize("expires_at", [None, 0, 1])
async def test_browser_missing_or_expired_token_requires_sign_in(expires_at):
    config = _config(AuthMethod.ENTRA)
    config.entra_browser_auth = True
    config.entra_token = SecretStr("expired-secret")
    config.entra_token_expires_at = expires_at
    with pytest.raises(ConnectionError, match="sign-in"):
        await AzurePostgreSQLAdapter(config)._resolve_password()


async def test_browser_driver_error_does_not_expose_token(monkeypatch):
    config = _config(AuthMethod.ENTRA)
    config.entra_browser_auth = True
    adapter = AzurePostgreSQLAdapter(config)
    async def fail():
        raise RuntimeError("driver echoed browser-secret")
    monkeypatch.setattr(adapter, "_create_connection", fail)
    result = await adapter.test_connection()
    assert not result.success
    assert "browser-secret" not in result.error
