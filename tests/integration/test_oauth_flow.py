"""
Integration tests for routes/auth.py — the OAuth setup/login/callback flow.
Mocks the actual Xero/QBO HTTP calls so these run fast and offline, while
still exercising the real route logic (state validation, credential storage,
token saving).
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from main import app
import token_manager

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_credential_and_token_files(tmp_path, monkeypatch):
    """Never let these tests touch the real .erp_tokens.json / .erp_credentials.json."""
    monkeypatch.setattr(token_manager, "TOKEN_FILE", str(tmp_path / ".erp_tokens.json"))
    monkeypatch.setattr(token_manager, "XERO_LEGACY_FILE", str(tmp_path / ".xero_tokens.json"))
    monkeypatch.setattr(token_manager, "CREDENTIALS_FILE", str(tmp_path / ".erp_credentials.json"))
    yield


def test_setup_form_loads():
    response = client.get("/auth/setup")
    assert response.status_code == 200
    assert "Xero" in response.text
    assert "QuickBooks Online" in response.text


def test_save_xero_credentials_then_reflected_in_setup_form():
    response = client.post(
        "/auth/setup/xero",
        data={"client_id": "test-xero-id", "client_secret": "test-xero-secret",
              "redirect_uri": "http://localhost:8080/auth/xero/callback"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    creds = token_manager.get_app_credentials("xero")
    assert creds["client_id"] == "test-xero-id"
    assert creds["client_secret"] == "test-xero-secret"


def test_save_qbo_credentials():
    response = client.post(
        "/auth/setup/qbo",
        data={"client_id": "test-qbo-id", "client_secret": "test-qbo-secret"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    creds = token_manager.get_app_credentials("quickbooks")
    assert creds["client_id"] == "test-qbo-id"


def test_xero_login_redirects_to_xero_when_credentials_present():
    token_manager.save_credentials("xero", "test-xero-id", "test-xero-secret")
    response = client.get("/auth/xero/login", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "login.xero.com" in response.headers["location"]
    assert "state=" in response.headers["location"]


def test_xero_login_redirects_to_setup_when_credentials_missing():
    response = client.get("/auth/xero/login", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "/auth/setup" in response.headers["location"]


def test_qbo_login_redirects_to_qbo_when_credentials_present():
    token_manager.save_credentials("quickbooks", "test-qbo-id", "test-qbo-secret")
    response = client.get("/auth/qbo/login", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "appcenter.intuit.com" in response.headers["location"]
    assert "state=" in response.headers["location"]


def test_xero_callback_rejects_unknown_state():
    response = client.get("/auth/xero/callback", params={"code": "abc", "state": "not-a-real-state"})
    assert response.status_code == 400


def test_qbo_callback_rejects_missing_realm_id():
    # Prime a valid state by hitting login first
    token_manager.save_credentials("quickbooks", "test-qbo-id", "test-qbo-secret")
    login_resp = client.get("/auth/qbo/login", follow_redirects=False)
    state = login_resp.headers["location"].split("state=")[1]
    response = client.get("/auth/qbo/callback", params={"code": "abc", "state": state})
    assert response.status_code == 400
    assert "realmId" in response.json()["detail"]


@pytest.mark.asyncio
async def test_xero_callback_end_to_end_saves_tokens():
    token_manager.save_credentials("xero", "test-xero-id", "test-xero-secret")
    login_resp = client.get("/auth/xero/login", follow_redirects=False)
    state = login_resp.headers["location"].split("state=")[1].split("&")[0]

    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {"access_token": "new-access-tok", "refresh_token": "new-refresh-tok"}

    conn_response = MagicMock()
    conn_response.status_code = 200
    conn_response.json.return_value = [{"tenantId": "tenant-abc", "tenantName": "Demo Company"}]

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = token_response
        mock_client.get.return_value = conn_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        response = client.get("/auth/xero/callback", params={"code": "auth-code-123", "state": state})

    assert response.status_code == 200
    assert "connected" in response.text.lower()
    saved = token_manager.load_all_tokens()
    assert saved["xero"]["access_token"] == "new-access-tok"
    assert saved["xero"]["tenant_id"] == "tenant-abc"


@pytest.mark.asyncio
async def test_qbo_callback_end_to_end_saves_tokens():
    token_manager.save_credentials("quickbooks", "test-qbo-id", "test-qbo-secret")
    login_resp = client.get("/auth/qbo/login", follow_redirects=False)
    state = login_resp.headers["location"].split("state=")[1].split("&")[0]

    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {"access_token": "qbo-access-tok", "refresh_token": "qbo-refresh-tok"}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = token_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        response = client.get(
            "/auth/qbo/callback",
            params={"code": "auth-code-456", "state": state, "realmId": "realm-123"},
        )

    assert response.status_code == 200
    assert "connected" in response.text.lower()
    saved = token_manager.load_all_tokens()
    assert saved["quickbooks"]["access_token"] == "qbo-access-tok"
    assert saved["quickbooks"]["tenant_id"] == "realm-123"
