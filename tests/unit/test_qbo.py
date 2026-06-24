import pytest
from adapters.qbo import (
    normalize_qbo_invoice,
    normalize_qbo_bill,
    normalize_qbo_customer,
    normalize_qbo_vendor,
    normalize_qbo_account,
    format_qbo_address,
)

def test_format_qbo_address():
    addr = {
        "Line1": "123 Main St",
        "City": "Springfield",
        "CountrySubDivisionCode": "IL",
        "PostalCode": "62701",
    }
    assert format_qbo_address(addr) == "123 Main St, Springfield, IL, 62701"
    assert format_qbo_address(None) is None
    assert format_qbo_address({}) is None


def test_normalize_qbo_invoice():
    raw_invoice = {
        "Id": "100",
        "DocNumber": "INV-0001",
        "TxnDate": "2026-06-24",
        "DueDate": "2026-07-24",
        "TotalAmt": 150.50,
        "Balance": 0.0,
        "CurrencyRef": {"value": "USD"},
        "CustomerRef": {"value": "cust-99"},
        "Line": [
            {
                "DetailType": "SalesItemLineDetail",
                "Amount": 150.50,
                "SalesItemLineDetail": {
                    "Qty": 2.0,
                    "ItemRef": {"name": "Widget"},
                    "ItemAccountRef": {"value": "4000"},
                },
            },
            {
                "DetailType": "SubTotalLineDetail",
                "Amount": 150.50,
            },
        ],
    }
    
    normalized = normalize_qbo_invoice(raw_invoice)
    assert normalized["id"] == "100"
    assert normalized["reference_number"] == "INV-0001"
    assert normalized["date"] == "2026-06-24"
    assert normalized["due_date"] == "2026-07-24"
    assert normalized["amount"] == 15050
    assert normalized["currency"] == "USD"
    assert normalized["status"] == "paid"
    assert normalized["contact_id"] == "cust-99"
    assert len(normalized["line_items"]) == 1
    assert normalized["line_items"][0] == {
        "description": "Widget",
        "quantity": 2.0,
        "unit_amount": 15050,
        "account_code": "4000",
    }


def test_normalize_qbo_bill():
    raw_bill = {
        "Id": "200",
        "DocNumber": "BILL-999",
        "TxnDate": "2026-06-25",
        "DueDate": "2026-07-25",
        "TotalAmt": 80.0,
        "Balance": 80.0,
        "CurrencyRef": {"value": "GBP"},
        "VendorRef": {"value": "vend-11"},
        "Line": [
            {
                "DetailType": "AccountBasedExpenseLineDetail",
                "Amount": 80.0,
                "AccountBasedExpenseLineDetail": {
                    "Qty": 1.0,
                    "AccountRef": {"name": "Office Expense", "value": "6000"},
                },
            }
        ],
    }
    
    normalized = normalize_qbo_bill(raw_bill)
    assert normalized["id"] == "200"
    assert normalized["bill_number"] == "BILL-999"
    assert normalized["date"] == "2026-06-25"
    assert normalized["due_date"] == "2026-07-25"
    assert normalized["amount"] == 8000
    assert normalized["currency"] == "GBP"
    assert normalized["status"] == "authorised"
    assert normalized["supplier_id"] == "vend-11"
    assert len(normalized["line_items"]) == 1
    assert normalized["line_items"][0] == {
        "description": "Office Expense",
        "quantity": 1.0,
        "unit_amount": 8000,
        "account_code": "6000",
    }


def test_normalize_qbo_customer():
    raw_cust = {
        "Id": "c-123",
        "DisplayName": "Jane Doe",
        "PrimaryEmailAddr": {"Address": "jane@example.com"},
        "PrimaryPhone": {"FreeFormNumber": "555-0199"},
        "BillAddr": {"Line1": "456 Oak Rd", "City": "Denver"},
    }
    normalized = normalize_qbo_customer(raw_cust)
    assert normalized == {
        "id": "c-123",
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "555-0199",
        "type": "customer",
        "address": "456 Oak Rd, Denver",
    }


def test_normalize_qbo_vendor():
    raw_vend = {
        "Id": "v-456",
        "DisplayName": "Supplier Inc",
        "PrintOnCheckName": "Supplier Incorporated",
        "PrimaryEmailAddr": {"Address": "sales@supplier.com"},
        "PrimaryPhone": {"FreeFormNumber": "123-4567"},
        "BillAddr": {"Line1": "789 Pine Way", "City": "Boston"},
    }
    normalized = normalize_qbo_vendor(raw_vend)
    assert normalized == {
        "id": "v-456",
        "name": "Supplier Incorporated",
        "email": "sales@supplier.com",
        "phone": "123-4567",
        "type": "supplier",
        "address": "789 Pine Way, Boston",
    }


def test_normalize_qbo_account():
    raw_acct = {
        "Id": "a-789",
        "Name": "Sales Revenue",
        "AccountType": "Revenue",
        "AcctNum": "4000",
        "TaxCodeRef": {"value": "TAX-US"},
        "CurrencyRef": {"value": "USD"},
    }
    normalized = normalize_qbo_account(raw_acct)
    assert normalized == {
        "id": "a-789",
        "code": "4000",
        "name": "Sales Revenue",
        "type": "Revenue",
        "tax_type": "TAX-US",
        "currency_code": "USD",
    }


def test_build_qbo_lines_from_items():
    from adapters.qbo import build_qbo_lines_from_items
    items = [
        {
            "description": "Custom Widget",
            "quantity": 3.0,
            "unit_amount": 1050,  # 10.50
        }
    ]
    lines = build_qbo_lines_from_items(items)
    assert len(lines) == 1
    assert lines[0] == {
        "Amount": 31.50,
        "DetailType": "SalesItemLineDetail",
        "SalesItemLineDetail": {
            "ItemRef": {"value": "1", "name": "Custom Widget"},
            "Qty": 3.0,
            "UnitPrice": 10.50,
        }
    }


@pytest.mark.asyncio
async def test_record_payment():
    from unittest.mock import AsyncMock, patch
    
    with patch("adapters.qbo.QBOHttpClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        
        mock_client.get_entity.return_value = {
            "Invoice": {
                "Id": "100",
                "CustomerRef": {"value": "cust-99"},
            }
        }
        
        mock_client.post_entity.return_value = {
            "Payment": {
                "Id": "pay-777",
            }
        }
        
        from adapters.qbo import QBOAdapter
        adapter = QBOAdapter()
        
        data = {
            "invoice_id": "100",
            "amount": 5000,
            "date": "2026-06-15",
            "account_code": "bank-1",
        }
        
        result = await adapter.record_payment("test_token", "test_realm", data)
        
        mock_client.get_entity.assert_called_once_with("invoice", "100")
        mock_client.post_entity.assert_called_once_with(
            "payment",
            {
                "TotalAmt": 50.0,
                "CustomerRef": {"value": "cust-99"},
                "DepositToAccountRef": {"value": "bank-1"},
                "TxnDate": "2026-06-15",
                "Line": [
                    {
                        "Amount": 50.0,
                        "LinkedTxn": [
                            {"TxnId": "100", "TxnType": "Invoice"}
                        ]
                    }
                ]
            }
        )
        
        assert result == {
            "success": True,
            "payment_id": "pay-777",
            "invoice_id": "100",
            "amount": 5000,
            "date": "2026-06-15",
        }


@pytest.mark.asyncio
async def test_update_invoice():
    from unittest.mock import AsyncMock, patch
    
    with patch("adapters.qbo.QBOHttpClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        
        mock_client.get_entity.return_value = {
            "Invoice": {
                "Id": "100",
                "SyncToken": "2",
                "DocNumber": "INV-0001",
                "TxnDate": "2026-06-01",
                "DueDate": "2026-06-30",
                "TotalAmt": 150.0,
                "Line": [],
                "CustomerRef": {"value": "cust-99"},
            }
        }
        
        mock_client.post_entity.return_value = {
            "Invoice": {
                "Id": "100",
                "SyncToken": "3",
                "DocNumber": "INV-0001",
                "TxnDate": "2026-06-01",
                "DueDate": "2026-09-30",
                "TotalAmt": 150.0,
                "Line": [],
                "CustomerRef": {"value": "cust-99"},
            }
        }
        
        from adapters.qbo import QBOAdapter
        adapter = QBOAdapter()
        
        data = {
            "due_date": "2026-09-30",
        }
        
        result = await adapter.update_invoice("test_token", "test_realm", "100", data)
        
        mock_client.get_entity.assert_called_once_with("invoice", "100")
        mock_client.post_entity.assert_called_once_with(
            "invoice",
            {
                "Id": "100",
                "SyncToken": "2",
                "DocNumber": "INV-0001",
                "TxnDate": "2026-06-01",
                "DueDate": "2026-09-30",
                "TotalAmt": 150.0,
                "Line": [],
                "CustomerRef": {"value": "cust-99"},
                "sparse": True,
            }
        )
        
        assert result["id"] == "100"
        assert result["due_date"] == "2026-09-30"


def test_check_response_sync_token_conflict():
    import httpx
    from adapters.qbo import QBOHttpClient
    from utils.errors import ERPConnectorError
    
    client = QBOHttpClient("token", "123")
    
    response = httpx.Response(
        status_code=400,
        json={
            "Fault": {
                "Error": [
                    {
                        "Message": "Object Version Conflict",
                        "Detail": "An updated version of this object is available.",
                        "code": "5010"
                    }
                ],
                "type": "ValidationFault"
            }
        }
    )
    
    with pytest.raises(ERPConnectorError) as exc_info:
        client._check_response(response)
        
    assert exc_info.value.error_code == "INVALID_REQUEST"
    assert "Version conflict" in exc_info.value.message



