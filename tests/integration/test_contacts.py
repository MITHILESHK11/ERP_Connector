import pytest
from fastapi.testclient import TestClient
from main import app
from routes import erp as erp_routes
from adapters.xero import XeroAdapter
from adapters.qbo import QBOAdapter

client = TestClient(app)
AUTH_HEADERS = {"X-ERP-Token": "Bearer test-token", "X-ERP-Tenant-Id": "tenant-123"}

SAMPLE_CONTACT = {
    "id": "c-1",
    "name": "Acme Corp",
    "email": "billing@acme.com",
    "phone": "555-1234",
    "type": "customer",
    "address": "123 Main St",
}

CREATE_CONTACT_PAYLOAD = {
    "name": "Acme Corp",
    "email": "billing@acme.com",
    "phone": "555-1234",
    "type": "customer",
}


@pytest.fixture(params=[XeroAdapter, QBOAdapter], ids=["xero", "qbo"])
def adapter_class(request):
    return request.param


@pytest.fixture(autouse=True)
def override_adapter(adapter_class):
    app.dependency_overrides[erp_routes.get_adapter] = lambda: adapter_class()
    yield
    app.dependency_overrides.pop(erp_routes.get_adapter, None)


def test_list_contacts(monkeypatch, adapter_class):
    async def mock_get_contacts(self, token, tenant_id, contact_type=None):
        return [SAMPLE_CONTACT]

    monkeypatch.setattr(adapter_class, "get_contacts", mock_get_contacts)
    response = client.get("/erp/contacts", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["count"] == 1
    assert body["data"][0]["id"] == "c-1"


def test_get_single_contact(monkeypatch, adapter_class):
    async def mock_get_contact(self, token, tenant_id, contact_id, contact_type=None):
        assert contact_id == "c-1"
        return SAMPLE_CONTACT

    monkeypatch.setattr(adapter_class, "get_contact", mock_get_contact)
    response = client.get("/erp/contacts/c-1", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["data"]["id"] == "c-1"


def test_create_contact(monkeypatch, adapter_class):
    async def mock_create_contact(self, token, tenant_id, data):
        assert data["name"] == "Acme Corp"
        return SAMPLE_CONTACT

    monkeypatch.setattr(adapter_class, "create_contact", mock_create_contact)
    response = client.post("/erp/contacts", headers=AUTH_HEADERS, json=CREATE_CONTACT_PAYLOAD)
    assert response.status_code == 201
    assert response.json()["data"]["id"] == "c-1"
