import pytest
from fastapi.testclient import TestClient
from main import app
from routes import erp as erp_routes
from adapters.xero import XeroAdapter
from adapters.qbo import QBOAdapter

client = TestClient(app)
AUTH_HEADERS = {"X-ERP-Token": "Bearer test-token", "X-ERP-Tenant-Id": "tenant-123"}

SAMPLE_BILL = {
    "id": "bill-1",
    "bill_number": "BILL-0001",
    "date": "2026-07-01",
    "due_date": "2026-07-15",
    "amount": 5000,
    "currency": "USD",
    "status": "authorised",
    "supplier_id": "s-1",
    "line_items": [
        {"description": "Office supplies", "quantity": 1, "unit_amount": 5000, "account_code": "400"}
    ],
}

CREATE_BILL_PAYLOAD = {
    "supplier_id": "21",
    "date": "2026-07-01",
    "due_date": "2026-07-15",
    "currency": "USD",
    "line_items": [
        {"description": "Office supplies", "quantity": 1, "unit_amount": 5000, "account_code": "400"}
    ],
}


@pytest.fixture(params=[XeroAdapter, QBOAdapter], ids=["xero", "qbo"])
def adapter_class(request):
    return request.param


@pytest.fixture(autouse=True)
def override_adapter(adapter_class):
    app.dependency_overrides[erp_routes.get_adapter] = lambda: adapter_class()
    yield
    app.dependency_overrides.pop(erp_routes.get_adapter, None)


def test_list_bills(monkeypatch, adapter_class):
    async def mock_get_bills(self, token, tenant_id, from_date=None, to_date=None):
        return [SAMPLE_BILL]

    monkeypatch.setattr(adapter_class, "get_bills", mock_get_bills)
    response = client.get("/erp/bills", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["count"] == 1
    assert body["data"][0]["id"] == "bill-1"


def test_get_single_bill(monkeypatch, adapter_class):
    async def mock_get_bill(self, token, tenant_id, bill_id):
        assert bill_id == "bill-1"
        return SAMPLE_BILL

    monkeypatch.setattr(adapter_class, "get_bill", mock_get_bill)
    response = client.get("/erp/bills/bill-1", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["data"]["id"] == "bill-1"


def test_create_bill(monkeypatch, adapter_class):
    async def mock_create_bill(self, token, tenant_id, data):
        assert data["supplier_id"] == "21"
        return SAMPLE_BILL

    monkeypatch.setattr(adapter_class, "create_bill", mock_create_bill)
    response = client.post("/erp/bills", headers=AUTH_HEADERS, json=CREATE_BILL_PAYLOAD)
    assert response.status_code == 201
    assert response.json()["data"]["id"] == "bill-1"
