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
    # Since adapter is a stub raising 501, it should result in 501 instead of 401!
    
    response = client.get(
        "/erp/invoices",
        headers={
            "X-ERP-Token": "Bearer my_valid_token_xyz",
            "X-ERP-Tenant-Id": "tenant-123"
        }
    )
    # Stubs return 501, meaning auth check succeeded and got delegated!
    assert response.status_code == 501
    data = response.json()
    assert data["error"] == "ADAPTER_NOT_IMPLEMENTED"
