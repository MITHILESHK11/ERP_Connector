import logging
from adapters.base_adapter import BaseERPAdapter, register_adapter
from utils.errors import raise_not_found

logger = logging.getLogger("erp_connector.mock")

MOCK_INVOICES = [
    {
        "id": "inv-101",
        "reference_number": "INV-1001",
        "date": "2026-07-01",
        "due_date": "2026-07-15",
        "amount": 150000,
        "currency": "USD",
        "status": "authorised",
        "contact_id": "c-101",
        "line_items": [
            {
                "description": "Software Development Services",
                "quantity": 10,
                "unit_amount": 15000,
                "account_code": "200",
                "item_id": "item-1"
            }
        ]
    },
    {
        "id": "inv-102",
        "reference_number": "INV-1002",
        "date": "2026-07-05",
        "due_date": "2026-07-20",
        "amount": 50000,
        "currency": "USD",
        "status": "paid",
        "contact_id": "c-102",
        "line_items": [
            {
                "description": "Consulting Fee",
                "quantity": 5,
                "unit_amount": 10000,
                "account_code": "200",
                "item_id": "item-2"
            }
        ]
    },
    {
        "id": "inv-103",
        "reference_number": "INV-1003",
        "date": "2026-07-10",
        "due_date": "2026-07-25",
        "amount": 25000,
        "currency": "USD",
        "status": "draft",
        "contact_id": "c-101",
        "line_items": [
            {
                "description": "Support Package",
                "quantity": 1,
                "unit_amount": 25000,
                "account_code": "200",
                "item_id": "item-1"
            }
        ]
    }
]

MOCK_BILLS = [
    {
        "id": "bill-201",
        "reference_number": "BILL-2001",
        "date": "2026-07-02",
        "due_date": "2026-07-16",
        "amount": 80000,
        "currency": "USD",
        "status": "authorised",
        "supplier_id": "v-201",
        "line_items": [
            {
                "description": "Cloud Infrastructure Hosting",
                "quantity": 1,
                "unit_amount": 80000,
                "account_code": "500"
            }
        ]
    },
    {
        "id": "bill-202",
        "reference_number": "BILL-2002",
        "date": "2026-07-08",
        "due_date": "2026-07-22",
        "amount": 35000,
        "currency": "USD",
        "status": "paid",
        "supplier_id": "v-202",
        "line_items": [
            {
                "description": "Office Supplies",
                "quantity": 1,
                "unit_amount": 35000,
                "account_code": "510"
            }
        ]
    }
]

MOCK_CONTACTS = [
    {
        "id": "c-101",
        "name": "Acme Corporation",
        "email": "billing@acme.com",
        "phone": "+1-555-0101",
        "type": "customer",
        "addresses": ["123 Tech Way, Suite 400, San Francisco, CA 94107"]
    },
    {
        "id": "c-102",
        "name": "Global Logistics Inc",
        "email": "accounts@globallogistics.com",
        "phone": "+1-555-0102",
        "type": "customer",
        "addresses": ["456 Commerce Blvd, Chicago, IL 60601"]
    },
    {
        "id": "v-201",
        "name": "Amazon Web Services",
        "email": "aws-invoices@amazon.com",
        "phone": "+1-800-555-0199",
        "type": "supplier",
        "addresses": ["410 Terry Ave N, Seattle, WA 98109"]
    },
    {
        "id": "v-202",
        "name": "Staples Supplies",
        "email": "orders@staples.com",
        "phone": "+1-800-555-0188",
        "type": "supplier",
        "addresses": ["500 Staples Drive, Framingham, MA 01702"]
    }
]

MOCK_ACCOUNTS = [
    {
        "account_id": "acc-101",
        "code": "200",
        "name": "Sales Revenue",
        "type": "revenue",
        "status": "active"
    },
    {
        "account_id": "acc-102",
        "code": "500",
        "name": "Hosting & Infrastructure Expense",
        "type": "expense",
        "status": "active"
    },
    {
        "account_id": "acc-103",
        "code": "090",
        "name": "Operating Bank Account",
        "type": "bank",
        "status": "active"
    }
]

MOCK_ITEMS = [
    {
        "id": "item-1",
        "name": "Software Development",
        "type": "Service",
        "unit_price": 150.0,
        "income_account_id": "200"
    },
    {
        "id": "item-2",
        "name": "Consulting Services",
        "type": "Service",
        "unit_price": 100.0,
        "income_account_id": "200"
    }
]


@register_adapter("mock")
class MockAdapter(BaseERPAdapter):
    """
    Mock ERP Adapter for local testing, demo, and offline sandbox operations.
    Fully implements BaseERPAdapter schema contracts.
    """

    async def get_invoices(self, token: str, tenant_id: str, from_date: str = None, to_date: str = None, status: str = None) -> list[dict]:
        invoices = MOCK_INVOICES
        if status:
            invoices = [inv for inv in invoices if inv["status"].lower() == status.lower()]
        return invoices

    async def get_invoice(self, token: str, tenant_id: str, invoice_id: str) -> dict:
        for inv in MOCK_INVOICES:
            if inv["id"] == invoice_id:
                return inv
        raise_not_found("mock", f"Invoice {invoice_id}")

    async def get_bills(self, token: str, tenant_id: str, from_date: str = None, to_date: str = None) -> list[dict]:
        return MOCK_BILLS

    async def get_bill(self, token: str, tenant_id: str, bill_id: str) -> dict:
        for bill in MOCK_BILLS:
            if bill["id"] == bill_id:
                return bill
        raise_not_found("mock", f"Bill {bill_id}")

    async def get_contacts(self, token: str, tenant_id: str, contact_type: str = None) -> list[dict]:
        contacts = MOCK_CONTACTS
        if contact_type:
            contacts = [c for c in contacts if c["type"].lower() == contact_type.lower()]
        return contacts

    async def get_contact(self, token: str, tenant_id: str, contact_id: str, contact_type: str = None) -> dict:
        for c in MOCK_CONTACTS:
            if c["id"] == contact_id:
                if contact_type and c["type"].lower() != contact_type.lower():
                    continue
                return c
        raise_not_found("mock", f"Contact {contact_id}")

    async def get_accounts(self, token: str, tenant_id: str) -> list[dict]:
        return MOCK_ACCOUNTS

    async def get_items(self, token: str, tenant_id: str) -> list[dict]:
        return MOCK_ITEMS

    async def create_invoice(self, token: str, tenant_id: str, data: dict) -> dict:
        new_inv = {
            "id": f"inv-{len(MOCK_INVOICES) + 101}",
            "reference_number": f"INV-{len(MOCK_INVOICES) + 1001}",
            "date": data.get("date"),
            "due_date": data.get("due_date"),
            "amount": sum(item.get("unit_amount", 0) * item.get("quantity", 1) for item in data.get("line_items", [])),
            "currency": data.get("currency", "USD"),
            "status": "draft",
            "contact_id": data.get("contact_id"),
            "line_items": data.get("line_items", [])
        }
        return new_inv

    async def create_bill(self, token: str, tenant_id: str, data: dict) -> dict:
        new_bill = {
            "id": f"bill-{len(MOCK_BILLS) + 201}",
            "reference_number": f"BILL-{len(MOCK_BILLS) + 2001}",
            "date": data.get("date"),
            "due_date": data.get("due_date"),
            "amount": sum(item.get("unit_amount", 0) * item.get("quantity", 1) for item in data.get("line_items", [])),
            "currency": data.get("currency", "USD"),
            "status": "authorised",
            "supplier_id": data.get("supplier_id"),
            "line_items": data.get("line_items", [])
        }
        return new_bill

    async def create_contact(self, token: str, tenant_id: str, data: dict) -> dict:
        new_contact = {
            "id": f"c-{len(MOCK_CONTACTS) + 101}",
            "name": data.get("name"),
            "email": data.get("email"),
            "phone": data.get("phone"),
            "type": data.get("type", "customer"),
            "addresses": []
        }
        return new_contact

    async def record_payment(self, token: str, tenant_id: str, data: dict) -> dict:
        return {
            "payment_id": "pay-999",
            "invoice_id": data.get("invoice_id"),
            "amount": data.get("amount"),
            "date": data.get("date"),
            "status": "success"
        }

    async def update_invoice(self, token: str, tenant_id: str, invoice_id: str, data: dict) -> dict:
        for inv in MOCK_INVOICES:
            if inv["id"] == invoice_id:
                return {**inv, **data}
        return {
            "id": invoice_id,
            "status": data.get("status", "draft"),
            "due_date": data.get("due_date", "2026-07-31"),
            "amount": 150000,
            "currency": "USD"
        }
