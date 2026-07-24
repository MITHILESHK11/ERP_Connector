"""
transforms.py
=============
Small, named functions referenced by name from config/mappings/*.yaml.

These exist only for the handful of cases that are genuinely business logic,
not a plain field rename — e.g. QBO has no single "status" field on an
invoice, so it must be derived from Balance/TotalAmt/EmailStatus. That kind
of decision can't live in a YAML file; everything else in this project's
normalization now can.

Each transform takes either:
  - a single raw value (when the mapping entry has a `source`), or
  - the entire raw record (when the mapping entry is transform-only, i.e.
    has no `source` key) — used when a field must be derived from several
    other fields at once.
"""

from __future__ import annotations


def money_to_cents(value) -> int:
    """Convert a decimal currency amount (e.g. 19.99) to integer cents (1999)."""
    return int(round(float(value or 0) * 100))


def date10(value) -> str:
    """Truncate any ISO-ish date/datetime string down to YYYY-MM-DD."""
    if not value:
        return ""
    return str(value)[:10]


def lowercase(value) -> str:
    return str(value or "").lower()


def stringify(value) -> str:
    return str(value) if value is not None else ""


# ---------------------------------------------------------------------------
# Xero-specific derived fields
# ---------------------------------------------------------------------------

_XERO_STATUS_MAP = {
    "DRAFT": "draft",
    "SUBMITTED": "draft",
    "AUTHORISED": "authorised",
    "PAID": "paid",
    "VOIDED": "voided",
    "DELETED": "voided",
}


def xero_status(raw: dict) -> str:
    status = (raw.get("Status") or "").upper()
    return _XERO_STATUS_MAP.get(status, "draft")


def xero_invoice_date(raw: dict) -> str:
    """Xero sends either DateString or Date for the invoice date — prefer DateString."""
    return date10(raw.get("DateString") or raw.get("Date"))


def xero_invoice_due_date(raw: dict) -> str:
    return date10(raw.get("DueDateString") or raw.get("DueDate"))


def xero_reference_number(raw: dict) -> str:
    return str(raw.get("InvoiceNumber") or raw.get("InvoiceID") or "")


def xero_line_items(raw: dict) -> list[dict]:
    items = raw.get("LineItems") or []
    normalized = []
    for item in items:
        normalized.append({
            "description": item.get("Description", "") or "Item",
            "quantity": float(item.get("Quantity", 1.0) or 1.0),
            "unit_amount": money_to_cents(item.get("UnitAmount", 0)),
            "account_code": stringify(item.get("AccountCode", "") or ""),
        })
    return normalized


def xero_contact_type(raw: dict) -> str:
    return "customer" if raw.get("IsCustomer", False) else "supplier"


def xero_phone(raw: dict) -> str | None:
    phones = raw.get("Phones", [])
    for p in phones:
        if p.get("PhoneType") == "DEFAULT" and p.get("PhoneNumber"):
            return p.get("PhoneNumber")
    return phones[0].get("PhoneNumber") if phones else None


def xero_address(raw: dict) -> str | None:
    addresses = raw.get("Addresses", [])
    for a in addresses:
        if a.get("AddressType") == "POSTAL" and a.get("AddressLine1"):
            return a.get("AddressLine1")
    return addresses[0].get("AddressLine1") if addresses else None


# ---------------------------------------------------------------------------
# QBO-specific derived fields
# QBO genuinely has no single "status" field for invoices/bills — it must be
# derived from Balance vs TotalAmt vs EmailStatus/PrivateNote. This is real
# business logic, not a rename, so it stays as code rather than config.
# ---------------------------------------------------------------------------

def qbo_derive_status(raw: dict) -> str:
    private_note = str(raw.get("PrivateNote", "") or "")
    if "void" in private_note.lower():
        return "voided"
    balance = float(raw.get("Balance", 0) or 0)
    total = float(raw.get("TotalAmt", 0) or 0)
    if total > 0 and balance == 0:
        return "paid"
    if raw.get("EmailStatus") == "NotSet" and balance == total:
        return "draft"
    return "authorised"


def qbo_line_items(raw: dict) -> list[dict]:
    line_items = []
    for line in raw.get("Line", []):
        if line.get("DetailType") == "SalesItemLineDetail":
            detail = line.get("SalesItemLineDetail", {})
            line_items.append({
                "description": detail.get("ItemRef", {}).get("name", ""),
                "quantity": detail.get("Qty", 1),
                "unit_amount": money_to_cents(line.get("Amount", 0)),
                "account_code": detail.get("ItemAccountRef", {}).get("value", ""),
            })
    return line_items


def qbo_ref_value(raw_value) -> str | None:
    """Pull `.value` out of a QBO *Ref object, e.g. CurrencyRef: {value: 'USD'}."""
    if isinstance(raw_value, dict):
        return raw_value.get("value")
    return raw_value


def qbo_bill_status(raw: dict) -> str:
    balance = float(raw.get("Balance") or 0.0)
    return "paid" if balance == 0.0 else "authorised"


def qbo_bill_number(raw: dict) -> str:
    return str(raw.get("DocNumber") or raw.get("Id") or "")


def qbo_bill_line_items(raw: dict) -> list[dict]:
    line_items = []
    for line in raw.get("Line", []):
        if line.get("DetailType") == "AccountBasedExpenseLineDetail":
            detail = line.get("AccountBasedExpenseLineDetail", {})
            line_items.append({
                "description": detail.get("AccountRef", {}).get("name", ""),
                "quantity": float(detail.get("Qty") or 1.0),
                "unit_amount": money_to_cents(line.get("Amount", 0)),
                "account_code": detail.get("AccountRef", {}).get("value", ""),
            })
    return line_items


def qbo_address(raw: dict) -> str | None:
    addr = raw.get("BillAddr")
    if not addr:
        return None
    parts = []
    for key in ["Line1", "Line2", "Line3", "City", "CountrySubDivisionCode", "PostalCode"]:
        val = addr.get(key)
        if val:
            parts.append(str(val).strip())
    return ", ".join(parts) if parts else None


def qbo_email(raw: dict) -> str | None:
    return raw.get("PrimaryEmailAddr", {}).get("Address") if raw.get("PrimaryEmailAddr") else None


def qbo_phone(raw: dict) -> str | None:
    return raw.get("PrimaryPhone", {}).get("FreeFormNumber") if raw.get("PrimaryPhone") else None


def qbo_vendor_name(raw: dict) -> str:
    return raw.get("PrintOnCheckName") or raw.get("DisplayName", "")


def qbo_account_code(raw: dict) -> str:
    return str(raw.get("AcctNum") or raw.get("Id") or "")


TRANSFORMS = {
    "money_to_cents": money_to_cents,
    "date10": date10,
    "lowercase": lowercase,
    "stringify": stringify,
    "xero_status": xero_status,
    "xero_invoice_date": xero_invoice_date,
    "xero_invoice_due_date": xero_invoice_due_date,
    "xero_reference_number": xero_reference_number,
    "xero_line_items": xero_line_items,
    "xero_contact_type": xero_contact_type,
    "xero_phone": xero_phone,
    "xero_address": xero_address,
    "qbo_derive_status": qbo_derive_status,
    "qbo_line_items": qbo_line_items,
    "qbo_ref_value": qbo_ref_value,
    "qbo_bill_status": qbo_bill_status,
    "qbo_bill_number": qbo_bill_number,
    "qbo_bill_line_items": qbo_bill_line_items,
    "qbo_address": qbo_address,
    "qbo_email": qbo_email,
    "qbo_phone": qbo_phone,
    "qbo_vendor_name": qbo_vendor_name,
    "qbo_account_code": qbo_account_code,
}
