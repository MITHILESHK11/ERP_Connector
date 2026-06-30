import pytest
from adapters.xero import XeroAdapter

@pytest.fixture
def adapter():
    return XeroAdapter()

def test_normalize_xero_invoice(adapter):
    raw_inv = {
        "InvoiceID": "xero-inv-100",
        "InvoiceNumber": "INV-001",
        "DateString": "2026-06-29T00:00:00",
        "DueDateString": "2026-07-29T00:00:00",
        "Total": 150.50,
        "CurrencyCode": "USD",
        "Status": "AUTHORISED",
        "Contact": {"ContactID": "cont-999"},
        "LineItems": [
            {
                "Description": "Consulting",
                "Quantity": 2.0,
                "UnitAmount": 75.25,
                "AccountCode": "200"
            }
        ]
    }
    norm = adapter._normalize_invoice(raw_inv)
    assert norm["id"] == "xero-inv-100"
    assert norm["reference_number"] == "INV-001"
    assert norm["amount"] == 15050
    assert norm["status"] == "authorised"
    assert norm["contact_id"] == "cont-999"
    assert len(norm["line_items"]) == 1
    assert norm["line_items"][0]["unit_amount"] == 7525

def test_normalize_xero_bill(adapter):
    raw_bill = {
        "InvoiceID": "xero-bill-200",
        "InvoiceNumber": "BILL-001",
        "DateString": "2026-06-29T00:00:00",
        "DueDateString": "2026-07-29T00:00:00",
        "Total": 500.00,
        "CurrencyCode": "USD",
        "Status": "PAID",
        "Contact": {"ContactID": "supp-777"},
        "LineItems": []
    }
    norm = adapter._normalize_bill(raw_bill)
    assert norm["id"] == "xero-bill-200"
    assert norm["bill_number"] == "BILL-001"
    assert norm["amount"] == 50000
    assert norm["status"] == "paid"
    assert norm["supplier_id"] == "supp-777"

def test_normalize_xero_contact(adapter):
    raw_contact = {
        "ContactID": "c-123",
        "Name": "Acme Corp",
        "EmailAddress": "acme@example.com",
        "IsCustomer": True,
        "IsSupplier": False
    }
    norm = adapter._normalize_contact(raw_contact)
    assert norm["id"] == "c-123"
    assert norm["name"] == "Acme Corp"
    assert norm["type"] == "customer"
