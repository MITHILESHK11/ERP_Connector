import pytest
from fastapi.testclient import TestClient
from main import app
from routes.erp import get_adapter

client = TestClient(app)

class MockPaymentsAdapter:
    async def get_payments(self, token: str, tenant_id: str):
        return [
            {
                "id": "pay-100",
                "invoice_id": "inv-200",
                "amount": 15000,
                "date": "2026-06-29",
                "account_code": "120",
            }
        ]

    async def record_payment(self, token: str, tenant_id: str, data: dict):
        return {
            "success": True,
            "payment_id": "pay-101",
            "invoice_id": data["invoice_id"],
            "amount": data["amount"],
            "date": data["date"],
        }


def test_get_payments():
    app.dependency_overrides[get_adapter] = lambda: MockPaymentsAdapter()
    try:
        response = client.get(
            "/erp/payments",
            headers={
                "X-ERP-Token": "Bearer token",
                "X-ERP-Tenant-Id": "tenant-123"
            }
        )
        assert response.status_code == 200
        res = response.json()
        assert res["success"] is True
        assert res["count"] == 1
        assert res["data"][0]["id"] == "pay-100"
    finally:
        app.dependency_overrides.clear()


def test_post_payments():
    app.dependency_overrides[get_adapter] = lambda: MockPaymentsAdapter()
    try:
        payload = {
            "invoice_id": "inv-200",
            "amount": 15000,
            "date": "2026-06-29",
            "account_code": "120",
        }
        response = client.post(
            "/erp/payments",
            headers={
                "X-ERP-Token": "Bearer token",
                "X-ERP-Tenant-Id": "tenant-123"
            },
            json=payload
        )
        assert response.status_code == 201
        res = response.json()
        assert res["success"] is True
        assert res["data"]["payment_id"] == "pay-101"
    finally:
        app.dependency_overrides.clear()
