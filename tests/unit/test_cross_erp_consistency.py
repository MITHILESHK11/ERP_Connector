"""
Cross-ERP consistency tests.

The entire point of this connector is that callers get ONE consistent
response shape regardless of which ERP is behind it. These tests mock the
raw HTTP layer for both Xero and QBO and assert their normalized outputs
have the SAME set of keys — this is what caught the record_payment bug
where QBO returned {"success": True, ...} while Xero returned
{"status": "success", ...}.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_record_payment_same_shape_across_erps():
    from adapters.xero import XeroAdapter
    from adapters.qbo import QBOAdapter

    # --- Xero side ---
    xero_response = MagicMock()
    xero_response.status_code = 200
    xero_response.json.return_value = {
        "Payments": [{"PaymentID": "xero-pay-1", "Amount": 50.0, "Date": "2026-06-15"}]
    }
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = xero_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        xero_adapter = XeroAdapter()
        xero_result = await xero_adapter.record_payment(
            "token", "tenant-1",
            {"invoice_id": "inv-1", "amount": 5000, "date": "2026-06-15", "account_code": "090"},
        )

    # --- QBO side ---
    with patch("adapters.qbo.QBOHttpClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_entity.return_value = {
            "Invoice": {"Id": "inv-1", "CustomerRef": {"value": "cust-1"}}
        }
        mock_client.post_entity.return_value = {"Payment": {"Id": "qbo-pay-1"}}

        qbo_adapter = QBOAdapter()
        qbo_result = await qbo_adapter.record_payment(
            "token", "realm-1",
            {"invoice_id": "inv-1", "amount": 5000, "date": "2026-06-15", "account_code": "1"},
        )

    # Both must expose the exact same set of fields to the caller.
    assert set(xero_result.keys()) == set(qbo_result.keys()) == {
        "payment_id", "invoice_id", "amount", "date", "status"
    }
    assert xero_result["status"] == qbo_result["status"] == "success"
