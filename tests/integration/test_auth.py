import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health_endpoint_no_auth():
    # Hit health endpoint — should succeed without auth headers
    response = client.get("/erp/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "erp" in data
    assert "version" in data


def test_invoices_endpoint_no_headers():
    # Hit invoices without any headers — should fail with 401 TOKEN_EXPIRED
    response = client.get("/erp/invoices")
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "TOKEN_EXPIRED"


def test_invoices_endpoint_missing_token():
    # Hit invoices with only tenant ID — should fail with 401 TOKEN_EXPIRED
    response = client.get(
        "/erp/invoices",
        headers={"X-ERP-Tenant-Id": "tenant-123"}
    )
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "TOKEN_EXPIRED"


def test_invoices_endpoint_empty_token():
    # Hit invoices with empty token header — should fail with 401 TOKEN_EXPIRED
    response = client.get(
        "/erp/invoices",
        headers={
            "X-ERP-Token": "   ",
            "X-ERP-Tenant-Id": "tenant-123"
        }
    )
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "TOKEN_EXPIRED"


def test_invoices_endpoint_bearer_prefix_stripped(monkeypatch):
    # If valid headers are passed, should proceed past auth and hit adapter.
    # We patch the adapter method to avoid making actual external API calls.
    called = []
    async def mock_get_invoices(self, token, tenant_id, from_date=None, to_date=None, status=None):
        called.append((token, tenant_id))
        return []

    from adapters.qbo import QBOAdapter
    monkeypatch.setattr(QBOAdapter, "get_invoices", mock_get_invoices)

    response = client.get(
        "/erp/invoices",
        headers={
            "X-ERP-Token": "Bearer my_valid_token_xyz",
            "X-ERP-Tenant-Id": "tenant-123"
        }
    )
    assert response.status_code == 200
    res = response.json()
    assert res["success"] is True
    assert res["data"] == []
    assert res["erp"] == "quickbooks"
    assert res["count"] == 0
    assert "correlationId" in res
    assert called == [("my_valid_token_xyz", "tenant-123")]


