import pytest
from fastapi.testclient import TestClient
from main import app
from routes import erp as erp_routes
from adapters.xero import XeroAdapter
from adapters.qbo import QBOAdapter

client = TestClient(app)
AUTH_HEADERS = {"X-ERP-Token": "Bearer test-token", "X-ERP-Tenant-Id": "tenant-123"}

SAMPLE_PAYMENT = {
    "payment_id": "p-1",
    "invoice_id": "inv-1",
    "amount": 5000,
    "date": "2026-07-01",
    "status": "success",
}

RECORD_PAYMENT_PAYLOAD = {
    "invoice_id": "inv-1",
    "amount": 5000,
    "date": "2026-07-01",
    "account_code": "35",
}


@pytest.fixture(params=[XeroAdapter, QBOAdapter], ids=["xero", "qbo"])
def adapter_class(request):
    return request.param


@pytest.fixture(autouse=True)
def override_adapter(adapter_class):
    app.dependency_overrides[erp_routes.get_adapter] = lambda: adapter_class()
    yield
    app.dependency_overrides.pop(erp_routes.get_adapter, None)


def test_record_payment(monkeypatch, adapter_class):
    async def mock_record_payment(self, token, tenant_id, data):
        assert data["invoice_id"] == "inv-1"
        assert data["amount"] == 5000
        return SAMPLE_PAYMENT

    monkeypatch.setattr(adapter_class, "record_payment", mock_record_payment)
    response = client.post("/erp/payments", headers=AUTH_HEADERS, json=RECORD_PAYMENT_PAYLOAD)
    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["payment_id"] == "p-1"
    assert body["data"]["status"] == "success"


def test_record_payment_rejects_non_positive_amount(adapter_class):
    bad_payload = {**RECORD_PAYMENT_PAYLOAD, "amount": 0}
    response = client.post("/erp/payments", headers=AUTH_HEADERS, json=bad_payload)
    assert response.status_code == 400
    assert response.json()["success"] is False
