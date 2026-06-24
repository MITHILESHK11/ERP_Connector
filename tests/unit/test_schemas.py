import pytest
from pydantic import ValidationError
from models.schemas import (
    LineItem,
    CreateInvoiceRequest,
    CreateBillRequest,
    CreateContactRequest,
    RecordPaymentRequest
)

def test_line_item_validation():
    # Valid line item
    item = LineItem(
        description="Consulting Services",
        quantity=2.5,
        unit_amount=15000,
        account_code="400"
    )
    assert item.description == "Consulting Services"

    # Invalid description (empty)
    with pytest.raises(ValidationError):
        LineItem(description="", quantity=1.0, unit_amount=100, account_code="400")

    # Invalid quantity (zero or negative)
    with pytest.raises(ValidationError):
        LineItem(description="Test", quantity=0.0, unit_amount=100, account_code="400")


def test_create_invoice_request_validation():
    # Valid payload
    payload = {
        "contact_id": "contact-123",
        "date": "2026-06-24",
        "due_date": "2026-06-30",
        "currency": "USD",
        "line_items": [
            {
                "description": "Item 1",
                "quantity": 1.0,
                "unit_amount": 5000,
                "account_code": "200"
            }
        ]
    }
    req = CreateInvoiceRequest(**payload)
    assert req.contact_id == "contact-123"

    # Invalid currency (lowercase)
    bad_payload = payload.copy()
    bad_payload["currency"] = "usd"
    with pytest.raises(ValidationError):
        CreateInvoiceRequest(**bad_payload)

    # Invalid date comparison (due_date < date)
    bad_payload2 = payload.copy()
    bad_payload2["date"] = "2026-06-30"
    bad_payload2["due_date"] = "2026-06-20"
    with pytest.raises(ValidationError) as exc_info:
        CreateInvoiceRequest(**bad_payload2)
    assert "due_date must be greater than or equal to date" in str(exc_info.value)


def test_create_contact_request_validation():
    # Valid
    req = CreateContactRequest(name="John Doe", type="customer", email="john@example.com")
    assert req.name == "John Doe"

    # Invalid email format
    with pytest.raises(ValidationError):
        CreateContactRequest(name="John Doe", type="customer", email="invalid-email")

    # Invalid contact type
    with pytest.raises(ValidationError):
        CreateContactRequest(name="John Doe", type="invalid-type")
