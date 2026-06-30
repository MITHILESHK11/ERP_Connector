import pytest
import httpx
from fastapi.testclient import TestClient
from main import app
from routes.erp import get_adapter

client = TestClient(app)

class DummyTimeoutAdapter:
    async def get_invoices(self, *args, **kwargs):
        raise httpx.TimeoutException("Timeout contacting upstream ERP")


class DummyStatusErrorAdapter:
    def __init__(self, status_code: int):
        self.status_code = status_code

    async def get_invoices(self, *args, **kwargs):
        req = httpx.Request("GET", "http://test/invoices")
        res = httpx.Response(self.status_code, request=req)
        raise httpx.HTTPStatusError("HTTP Status Error", request=req, response=res)


def test_adapter_timeout_translation():
    app.dependency_overrides[get_adapter] = lambda: DummyTimeoutAdapter()
    try:
        response = client.get(
            "/erp/invoices",
            headers={
                "X-ERP-Token": "Bearer token",
                "X-ERP-Tenant-Id": "tenant-123"
            }
        )
        assert response.status_code == 504
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "ERP_TIMEOUT"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "http_status, expected_error, expected_code",
    [
        (401, "TOKEN_EXPIRED", 401),
        (404, "NOT_FOUND", 404),
        (400, "INVALID_REQUEST", 400),
        (500, "ERP_UNAVAILABLE", 502),
        (503, "ERP_UNAVAILABLE", 502),
    ]
)
def test_adapter_status_error_translation(http_status, expected_error, expected_code):
    adapter = DummyStatusErrorAdapter(http_status)
    app.dependency_overrides[get_adapter] = lambda: adapter
    try:
        response = client.get(
            "/erp/invoices",
            headers={
                "X-ERP-Token": "Bearer token",
                "X-ERP-Tenant-Id": "tenant-123"
            }
        )
        assert response.status_code == expected_code
        data = response.json()
        assert data["success"] is False
        assert data["error"] == expected_error
    finally:
        app.dependency_overrides.clear()
