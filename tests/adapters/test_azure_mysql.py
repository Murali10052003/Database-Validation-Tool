"""Azure Database for MySQL adapter: wiring, TLS, password and Entra authentication."""

from __future__ import annotations

import sys
import time
import types

import pytest

import app.adapters.azure_mysql.adapter as az_mysql
from app.adapters.azure_mysql.adapter import AzureMySQLAdapter
from app.adapters.factory import adapter_factory
from app.adapters.mysql.adapter import MySQLAdapter
from app.core.config import DatabaseConnectionConfig
from app.core.enums import AuthMethod, DatabaseType, DeploymentPlatform
from app.core.exceptions import ConnectionError
from app.models.database import QueryResult
from app.schemas.api import ConnectionInput


def _config(auth: AuthMethod = AuthMethod.PASSWORD, **extra) -> DatabaseConnectionConfig:
    return DatabaseConnectionConfig(
        type=DatabaseType.AZURE_MYSQL,
        platform=DeploymentPlatform.AZURE,
        host="my.mysql.database.azure.com",
        port=3306,
        database="appdb",
        username="user@tenant",
        password="s3cret",
        auth_method=auth,
        **extra,
    )


@pytest.fixture
def captured(monkeypatch) -> dict:
    """Replace mysql.connector.connect and capture its keyword arguments."""
    seen: dict = {}
    fake_connector = types.SimpleNamespace(connect=lambda **kwargs: seen.update(kwargs) or object())
    monkeypatch.setitem(sys.modules, "mysql", types.SimpleNamespace(connector=fake_connector))
    monkeypatch.setitem(sys.modules, "mysql.connector", fake_connector)
    return seen


def test_factory_returns_azure_mysql_adapter() -> None:
    adapter = adapter_factory.create(_config())
    assert isinstance(adapter, AzureMySQLAdapter)
    assert isinstance(adapter, MySQLAdapter)  # Azure MySQL reuses the MySQL engine
    assert DatabaseType.AZURE_MYSQL in adapter_factory.supported_types()
    # AUTO_INCREMENT columns must not raise a "target lacks identity" warning.
    assert adapter.capabilities().identity_columns is True


async def test_identity_is_azure_mysql(monkeypatch) -> None:
    adapter = AzureMySQLAdapter(_config())
    adapter._connection = object()

    async def fetch(sql: str, parameters: dict | None = None) -> QueryResult:
        return QueryResult(columns=["v"], rows=[("8.0.36",)], row_count=1)

    monkeypatch.setattr(adapter, "_fetch", fetch)
    info = await adapter.get_database_info()
    assert info.database_type is DatabaseType.AZURE_MYSQL
    assert info.platform is DeploymentPlatform.AZURE
    result = await adapter.test_connection()
    assert result.success and result.database_type is DatabaseType.AZURE_MYSQL


async def test_plain_mysql_identity_is_unchanged(monkeypatch) -> None:
    adapter = MySQLAdapter(DatabaseConnectionConfig(type="mysql", host="h", username="u"))
    adapter._connection = object()

    async def fetch(sql: str, parameters: dict | None = None) -> QueryResult:
        return QueryResult(columns=["v"], rows=[("8.0.36",)], row_count=1)

    monkeypatch.setattr(adapter, "_fetch", fetch)
    info = await adapter.get_database_info()
    assert info.database_type is DatabaseType.MYSQL
    assert info.platform is DeploymentPlatform.SELF_MANAGED


async def test_password_connection_requires_tls(captured) -> None:
    await AzureMySQLAdapter(_config())._create_connection()
    assert captured["ssl_disabled"] is False
    assert captured["password"] == "s3cret"
    assert "auth_plugin" not in captured


async def test_entra_connection_sends_token_as_clear_text_password(captured, monkeypatch) -> None:
    monkeypatch.setattr(az_mysql, "fetch_entra_token", lambda client_id=None: "aad-token")
    await AzureMySQLAdapter(_config(AuthMethod.ENTRA))._create_connection()
    assert captured["password"] == "aad-token"
    assert captured["auth_plugin"] == "mysql_clear_password"
    assert captured["ssl_disabled"] is False


async def test_ssl_ca_option_is_passed_through(captured) -> None:
    await AzureMySQLAdapter(_config(options={"ssl_ca": "/certs/ca.pem"}))._create_connection()
    assert captured["ssl_ca"] == "/certs/ca.pem"


def test_local_entra_mode_allowed_for_azure_mysql(monkeypatch) -> None:
    values = dict(type="azure_mysql", host="db.example", username="reader",
                  auth_method="entra", entra_mode="local")
    monkeypatch.setenv("MV_ALLOW_LOCAL_ENTRA", "true")
    assert ConnectionInput(**values).to_config().entra_browser_auth is False
    with pytest.raises(ValueError, match="Azure PostgreSQL or Azure MySQL"):
        ConnectionInput(**{**values, "type": "azure_sql"})


async def test_browser_token_used_and_expiry_enforced(captured) -> None:
    request = ConnectionInput(
        type="azure_mysql", host="db.example", username="db-user", auth_method="entra",
        entra_token="browser-secret", entra_token_expires_at=int(time.time()) + 3600,
    )
    adapter = AzureMySQLAdapter(request.to_config())
    assert await adapter._resolve_password() == "browser-secret"
    await adapter._create_connection()
    assert captured["password"] == "browser-secret"

    expired = request.to_config()
    expired.entra_token_expires_at = 1
    with pytest.raises(ConnectionError, match="sign-in"):
        await AzureMySQLAdapter(expired).connect()


async def test_browser_driver_error_does_not_expose_token(monkeypatch) -> None:
    config = _config(AuthMethod.ENTRA)
    config.entra_browser_auth = True
    adapter = AzureMySQLAdapter(config)

    async def fail():
        raise RuntimeError("driver echoed browser-secret")

    monkeypatch.setattr(adapter, "_create_connection", fail)
    result = await adapter.test_connection()
    assert not result.success
    assert "browser-secret" not in result.error
