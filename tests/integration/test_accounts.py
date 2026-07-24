import pytest
from fastapi.testclient import TestClient
from main import app
from routes import erp as erp_routes
from adapters.xero import XeroAdapter
from adapters.qbo import QBOAdapter

client = TestClient(app)
AUTH_HEADERS = {"X-ERP-Token": "Bearer test-token", "X-ERP-Tenant-Id": "tenant-123"}

SAMPLE_ACCOUNT = {
    "id": "a-1",
    "code": "200",
    "name": "Sales",
    "type": "revenue",
    "tax_type": "NONE",
    "currency_code": "USD",
}


@pytest.fixture(params=[XeroAdapter, QBOAdapter], ids=["xero", "qbo"])
def adapter_class(request):
    return request.param


@pytest.fixture(autouse=True)
def override_adapter(adapter_class):
    app.dependency_overrides[erp_routes.get_adapter] = lambda: adapter_class()
    yield
    app.dependency_overrides.pop(erp_routes.get_adapter, None)


def test_list_accounts(monkeypatch, adapter_class):
    async def mock_get_accounts(self, token, tenant_id):
        return [SAMPLE_ACCOUNT]

    monkeypatch.setattr(adapter_class, "get_accounts", mock_get_accounts)
    response = client.get("/erp/accounts", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["count"] == 1
    assert body["data"][0]["id"] == "a-1"


def test_list_items(monkeypatch, adapter_class):
    # Xero has no Item entity so its get_items() should return []; QBO's
    # get_items() calls the real API, so mock it either way — this proves
    # the /items route works uniformly for both adapters without either one
    # making a real network call in tests.
    get_items_fn = getattr(adapter_class, "get_items", None)
    if get_items_fn is not None:
        async def mock_get_items(self, token, tenant_id):
            return []
        monkeypatch.setattr(adapter_class, "get_items", mock_get_items)

    response = client.get("/erp/items", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == []
    assert body["count"] == 0
