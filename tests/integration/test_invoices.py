"""
Integration tests for /erp/invoices — exercises GET (list), GET (single),
POST (create), PUT (update) against BOTH XeroAdapter and QBOAdapter, using
FastAPI dependency_overrides so the active ERP_TYPE in .env doesn't limit
which adapter gets tested.
"""
import pytest
from fastapi.testclient import TestClient
from main import app
from routes import erp as erp_routes
from adapters.xero import XeroAdapter
from adapters.qbo import QBOAdapter

client = TestClient(app)

AUTH_HEADERS = {"X-ERP-Token": "Bearer test-token", "X-ERP-Tenant-Id": "tenant-123"}

SAMPLE_INVOICE = {
    "id": "inv-1",
    "reference_number": "INV-0001",
    "date": "2026-07-01",
    "due_date": "2026-07-15",
    "amount": 10000,
    "currency": "USD",
    "status": "draft",
    "contact_id": "c-1",
    "line_items": [
        {"description": "Consulting", "quantity": 1, "unit_amount": 10000, "account_code": "200"}
    ],
}

CREATE_INVOICE_PAYLOAD = {
    "contact_id": "55",
    "date": "2026-07-01",
    "due_date": "2026-07-15",
    "currency": "USD",
    "line_items": [
        {"description": "Consulting services", "quantity": 1, "unit_amount": 10000, "account_code": "200"}
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


def test_list_invoices(monkeypatch, adapter_class):
    async def mock_get_invoices(self, token, tenant_id, from_date=None, to_date=None, status=None):
        return [SAMPLE_INVOICE]

    monkeypatch.setattr(adapter_class, "get_invoices", mock_get_invoices)

    response = client.get("/erp/invoices", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["count"] == 1
    assert body["data"][0]["id"] == "inv-1"


def test_get_single_invoice(monkeypatch, adapter_class):
    async def mock_get_invoice(self, token, tenant_id, invoice_id):
        assert invoice_id == "inv-1"
        return SAMPLE_INVOICE

    monkeypatch.setattr(adapter_class, "get_invoice", mock_get_invoice)

    response = client.get("/erp/invoices/inv-1", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["id"] == "inv-1"


def test_create_invoice(monkeypatch, adapter_class):
    async def mock_create_invoice(self, token, tenant_id, data):
        assert data["contact_id"] == "55"
        return SAMPLE_INVOICE

    monkeypatch.setattr(adapter_class, "create_invoice", mock_create_invoice)

    response = client.post("/erp/invoices", headers=AUTH_HEADERS, json=CREATE_INVOICE_PAYLOAD)
    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["id"] == "inv-1"


def test_update_invoice(monkeypatch, adapter_class):
    async def mock_update_invoice(self, token, tenant_id, invoice_id, data):
        assert invoice_id == "inv-1"
        assert data["status"] == "paid"
        return {**SAMPLE_INVOICE, "status": "paid"}

    monkeypatch.setattr(adapter_class, "update_invoice", mock_update_invoice)

    response = client.put("/erp/invoices/inv-1", headers=AUTH_HEADERS, json={"status": "paid"})
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "paid"


def test_create_invoice_rejects_invalid_payload(adapter_class):
    bad_payload = {**CREATE_INVOICE_PAYLOAD, "currency": "usd"}  # must be uppercase 3-letter code
    response = client.post("/erp/invoices", headers=AUTH_HEADERS, json=bad_payload)
    assert response.status_code == 400
    assert response.json()["success"] is False
