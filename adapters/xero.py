import logging
import httpx
from adapters.base_adapter import BaseERPAdapter, register_adapter
from utils.errors import (
    raise_token_expired,
    raise_not_found,
    raise_invalid_request,
    raise_erp_unavailable,
    raise_erp_timeout
)
from utils.field_mapper import load_mapping, map_record
from utils.transforms import TRANSFORMS

_INVOICE_MAPPING = load_mapping("xero", "invoice")
_BILL_MAPPING = load_mapping("xero", "bill")
_CONTACT_MAPPING = load_mapping("xero", "contact")
_ACCOUNT_MAPPING = load_mapping("xero", "account")

XERO_BASE_URL = "https://api.xero.com/api.xro/2.0"
logger = logging.getLogger("erp_connector.xero")


def _is_dummy_token(token: str) -> bool:
    if not token:
        return True
    clean = token.replace("Bearer ", "").strip()
    return any(clean.startswith(prefix) for prefix in ("your_", "mock", "test-token", "demo", "dummy"))


@register_adapter("xero")
class XeroAdapter(BaseERPAdapter):
    """
    Concrete adapter implementation for Xero.
    Handles authentication headers, endpoint queries, error translation,
    and output normalization to match the common ERP Connector schema contract.
    Delegates to MockAdapter for testing/demo tokens.
    """

    def __init__(self):
        from adapters.mock import MockAdapter
        self._mock = MockAdapter()


    def _get_headers(self, token: str, tenant_id: str) -> dict:
        clean_token = token.replace("Bearer ", "").strip() if token else ""
        return {
            "Authorization": f"Bearer {clean_token}",
            "Xero-tenant-id": tenant_id,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def _check_response(self, response: httpx.Response, endpoint: str = "") -> None:
        """
        Check HTTP status and translate raw Xero errors into clean ERPConnectorError.
        """
        if response.status_code in (200, 201):
            return
        logger.error(
            f"Xero API error: status={response.status_code} "
            f"endpoint={endpoint} body={response.text[:200]}"
        )
        if response.status_code == 401:
            raise_token_expired("xero")
        elif response.status_code == 404:
            raise_not_found("xero", endpoint)
        elif response.status_code == 400:
            err_msg = response.text
            try:
                err_data = response.json()
                elements = err_data.get("Elements", [])
                val_errs = []
                for el in elements:
                    for ve in el.get("ValidationErrors", []):
                        val_errs.append(ve.get("Message"))
                if val_errs:
                    err_msg = "; ".join(val_errs)
                elif "Message" in err_data:
                    err_msg = err_data.get("Message", err_msg)
            except Exception:
                pass
            raise_invalid_request("xero", err_msg)

        elif response.status_code in (429, 500, 502, 503):
            raise_erp_unavailable("xero")
        else:
            raise_erp_unavailable("xero")

    # ------------------------------------------------------------------
    # Normalization now comes from config/mappings/xero.yaml + named
    # transforms in utils/transforms.py, instead of hand-written dict
    # literals per field. See utils/field_mapper.py for how this works,
    # and why a couple of fields (status, line_items) still call small
    # code functions rather than being pure renames.
    # ------------------------------------------------------------------

    def _normalize_invoice(self, inv: dict) -> dict:
        return map_record(inv, _INVOICE_MAPPING, TRANSFORMS)

    def _normalize_bill(self, bill: dict) -> dict:
        return map_record(bill, _BILL_MAPPING, TRANSFORMS)

    def _normalize_contact(self, contact: dict) -> dict:
        return map_record(contact, _CONTACT_MAPPING, TRANSFORMS)

    def _normalize_account(self, account: dict) -> dict:
        return map_record(account, _ACCOUNT_MAPPING, TRANSFORMS)

    # ----------------------------------------------------------------
    # GET INVOICES
    # ----------------------------------------------------------------
    async def get_invoices(self, token: str, tenant_id: str, from_date: str = None,
                           to_date: str = None, status: str = None) -> list[dict]:
        if _is_dummy_token(token):
            return await self._mock.get_invoices(token, tenant_id, from_date, to_date, status)
        headers = self._get_headers(token, tenant_id)
        all_invoices = []
        page = 1

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                while True:
                    params = {"Type": "ACCREC", "page": page}
                    if from_date:
                        params["DateFrom"] = from_date
                    if to_date:
                        params["DateTo"] = to_date

                    response = await client.get(
                        f"{XERO_BASE_URL}/Invoices",
                        headers=headers,
                        params=params
                    )
                    self._check_response(response, "/Invoices")
                    data = response.json()
                    invoices = data.get("Invoices", [])
                    all_invoices.extend([self._normalize_invoice(inv) for inv in invoices])

                    if len(invoices) < 100:
                        break
                    page += 1
        except httpx.TimeoutException:
            raise_erp_timeout("xero")
        except httpx.RequestError:
            raise_erp_unavailable("xero")

        if status:
            all_invoices = [inv for inv in all_invoices if inv["status"] == status.lower()]

        return all_invoices

    # ----------------------------------------------------------------
    # GET SINGLE INVOICE
    # ----------------------------------------------------------------
    async def get_invoice(self, token: str, tenant_id: str, invoice_id: str) -> dict:
        if _is_dummy_token(token):
            return await self._mock.get_invoice(token, tenant_id, invoice_id)
        headers = self._get_headers(token, tenant_id)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{XERO_BASE_URL}/Invoices/{invoice_id}",
                    headers=headers
                )
                self._check_response(response, f"/Invoices/{invoice_id}")
                data = response.json()
                invoices = data.get("Invoices", [])
                if not invoices:
                    raise_not_found("xero", f"/Invoices/{invoice_id}")
                return self._normalize_invoice(invoices[0])
        except httpx.TimeoutException:
            raise_erp_timeout("xero")
        except httpx.RequestError:
            raise_erp_unavailable("xero")

    # ----------------------------------------------------------------
    # GET BILLS
    # ----------------------------------------------------------------
    async def get_bills(self, token: str, tenant_id: str, from_date: str = None,
                        to_date: str = None) -> list[dict]:
        if _is_dummy_token(token):
            return await self._mock.get_bills(token, tenant_id, from_date, to_date)
        headers = self._get_headers(token, tenant_id)
        all_bills = []
        page = 1

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                while True:
                    params = {"Type": "ACCPAY", "page": page}
                    if from_date:
                        params["DateFrom"] = from_date
                    if to_date:
                        params["DateTo"] = to_date

                    response = await client.get(
                        f"{XERO_BASE_URL}/Invoices",
                        headers=headers,
                        params=params
                    )
                    self._check_response(response, "/Invoices (Bills)")
                    data = response.json()
                    bills = data.get("Invoices", [])
                    all_bills.extend([self._normalize_bill(bill) for bill in bills])

                    if len(bills) < 100:
                        break
                    page += 1
        except httpx.TimeoutException:
            raise_erp_timeout("xero")
        except httpx.RequestError:
            raise_erp_unavailable("xero")

        return all_bills

    # ----------------------------------------------------------------
    # GET SINGLE BILL
    # ----------------------------------------------------------------
    async def get_bill(self, token: str, tenant_id: str, bill_id: str) -> dict:
        if _is_dummy_token(token):
            return await self._mock.get_bill(token, tenant_id, bill_id)
        headers = self._get_headers(token, tenant_id)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{XERO_BASE_URL}/Invoices/{bill_id}",
                    headers=headers
                )
                self._check_response(response, f"/Invoices/{bill_id}")
                data = response.json()
                bills = data.get("Invoices", [])
                if not bills:
                    raise_not_found("xero", f"/Invoices/{bill_id}")
                return self._normalize_bill(bills[0])
        except httpx.TimeoutException:
            raise_erp_timeout("xero")
        except httpx.RequestError:
            raise_erp_unavailable("xero")

    # ----------------------------------------------------------------
    # GET CONTACTS
    # ----------------------------------------------------------------
    async def get_contacts(self, token: str, tenant_id: str,
                           contact_type: str = None) -> list[dict]:
        if _is_dummy_token(token):
            return await self._mock.get_contacts(token, tenant_id, contact_type)
        headers = self._get_headers(token, tenant_id)
        all_contacts = []
        page = 1

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                while True:
                    params = {"page": page}
                    if contact_type == "customer":
                        params["IsCustomer"] = "true"
                    elif contact_type == "supplier":
                        params["IsSupplier"] = "true"

                    response = await client.get(
                        f"{XERO_BASE_URL}/Contacts",
                        headers=headers,
                        params=params
                    )
                    self._check_response(response, "/Contacts")
                    data = response.json()
                    contacts = data.get("Contacts", [])
                    all_contacts.extend([self._normalize_contact(c) for c in contacts])

                    if len(contacts) < 100:
                        break
                    page += 1
        except httpx.TimeoutException:
            raise_erp_timeout("xero")
        except httpx.RequestError:
            raise_erp_unavailable("xero")

        return all_contacts

    # ----------------------------------------------------------------
    # GET SINGLE CONTACT
    # ----------------------------------------------------------------
    async def get_contact(self, token: str, tenant_id: str, contact_id: str,
                          contact_type: str = None) -> dict:
        if _is_dummy_token(token):
            return await self._mock.get_contact(token, tenant_id, contact_id, contact_type)
        # Xero keeps customers/vendors in a single Contacts list (no ID collision
        # risk like QBO), so contact_type is accepted for interface parity but unused.
        headers = self._get_headers(token, tenant_id)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{XERO_BASE_URL}/Contacts/{contact_id}",
                    headers=headers
                )
                self._check_response(response, f"/Contacts/{contact_id}")
                data = response.json()
                contacts = data.get("Contacts", [])
                if not contacts:
                    raise_not_found("xero", f"/Contacts/{contact_id}")
                return self._normalize_contact(contacts[0])
        except httpx.TimeoutException:
            raise_erp_timeout("xero")
        except httpx.RequestError:
            raise_erp_unavailable("xero")

    # ----------------------------------------------------------------
    # GET ACCOUNTS
    # ----------------------------------------------------------------
    async def get_accounts(self, token: str, tenant_id: str) -> list[dict]:
        if _is_dummy_token(token):
            return await self._mock.get_accounts(token, tenant_id)
        headers = self._get_headers(token, tenant_id)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{XERO_BASE_URL}/Accounts",
                    headers=headers
                )
                self._check_response(response, "/Accounts")
                data = response.json()
                accounts = data.get("Accounts", [])
                return [self._normalize_account(a) for a in accounts]
        except httpx.TimeoutException:
            raise_erp_timeout("xero")
        except httpx.RequestError:
            raise_erp_unavailable("xero")

    # ----------------------------------------------------------------
    # CREATE INVOICE
    # ----------------------------------------------------------------
    async def create_invoice(self, token: str, tenant_id: str, data: dict) -> dict:
        if _is_dummy_token(token):
            return await self._mock.create_invoice(token, tenant_id, data)
        headers = self._get_headers(token, tenant_id)

        xero_payload = {
            "Type": "ACCREC",
            "Contact": {"ContactID": data.get("contact_id")},
            "Date": data.get("date"),
            "DueDate": data.get("due_date"),
            "LineItems": [
                {
                    "Description": item.get("description"),
                    "Quantity": item.get("quantity"),
                    "UnitAmount": float(item.get("unit_amount", 0)) / 100.0,
                    "AccountCode": item.get("account_code"),
                }
                for item in data.get("line_items", [])
            ],
            "Status": "DRAFT"
        }
        if data.get("currency"):
            xero_payload["CurrencyCode"] = data["currency"]


        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{XERO_BASE_URL}/Invoices",
                    headers=headers,
                    json=xero_payload
                )
                self._check_response(response, "/Invoices (Create)")
                result = response.json()
                invoices = result.get("Invoices", [])
                if not invoices:
                    return {}
                return self._normalize_invoice(invoices[0])
        except httpx.TimeoutException:
            raise_erp_timeout("xero")
        except httpx.RequestError:
            raise_erp_unavailable("xero")

    # ----------------------------------------------------------------
    # CREATE BILL
    # ----------------------------------------------------------------
    async def create_bill(self, token: str, tenant_id: str, data: dict) -> dict:
        if _is_dummy_token(token):
            return await self._mock.create_bill(token, tenant_id, data)
        headers = self._get_headers(token, tenant_id)

        xero_payload = {
            "Type": "ACCPAY",
            "Contact": {"ContactID": data.get("supplier_id") or data.get("contact_id")},
            "Date": data.get("date"),
            "DueDate": data.get("due_date"),
            "CurrencyCode": data.get("currency", "USD"),
            "LineItems": [
                {
                    "Description": item.get("description"),
                    "Quantity": item.get("quantity"),
                    "UnitAmount": float(item.get("unit_amount", 0)) / 100.0,
                    "AccountCode": item.get("account_code"),
                }
                for item in data.get("line_items", [])
            ],
            "Status": "DRAFT"
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{XERO_BASE_URL}/Invoices",
                    headers=headers,
                    json=xero_payload
                )
                self._check_response(response, "/Invoices (Create Bill)")
                result = response.json()
                bills = result.get("Invoices", [])
                if not bills:
                    return {}
                return self._normalize_bill(bills[0])
        except httpx.TimeoutException:
            raise_erp_timeout("xero")
        except httpx.RequestError:
            raise_erp_unavailable("xero")

    # ----------------------------------------------------------------
    # CREATE CONTACT
    # ----------------------------------------------------------------
    async def create_contact(self, token: str, tenant_id: str, data: dict) -> dict:
        if _is_dummy_token(token):
            return await self._mock.create_contact(token, tenant_id, data)
        headers = self._get_headers(token, tenant_id)

        contact_type = data.get("type", "customer")
        xero_payload = {
            "Name": data.get("name"),
            "EmailAddress": data.get("email"),
            "IsCustomer": (contact_type == "customer"),
            "IsSupplier": (contact_type == "supplier"),
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{XERO_BASE_URL}/Contacts",
                    headers=headers,
                    json=xero_payload
                )
                self._check_response(response, "/Contacts (Create)")
                result = response.json()
                contacts = result.get("Contacts", [])
                if not contacts:
                    return {}
                return self._normalize_contact(contacts[0])
        except httpx.TimeoutException:
            raise_erp_timeout("xero")
        except httpx.RequestError:
            raise_erp_unavailable("xero")

    # ----------------------------------------------------------------
    # RECORD PAYMENT
    # ----------------------------------------------------------------
    async def record_payment(self, token: str, tenant_id: str, data: dict) -> dict:
        if _is_dummy_token(token):
            return await self._mock.record_payment(token, tenant_id, data)
        headers = self._get_headers(token, tenant_id)

        amt_float = float(data.get("amount", 0)) / 100.0
        xero_payload = {
            "Invoice": {"InvoiceID": data.get("invoice_id")},
            "Account": {"Code": data.get("account_code", "090")},
            "Date": data.get("date"),
            "Amount": amt_float,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{XERO_BASE_URL}/Payments",
                    headers=headers,
                    json=xero_payload
                )
                self._check_response(response, "/Payments (Record)")
                result = response.json()
                payments = result.get("Payments", [])
                if not payments:
                    return {}
                payment = payments[0]
                return {
                    "payment_id": str(payment.get("PaymentID", "")),
                    "invoice_id": data.get("invoice_id"),
                    "amount": int(round(float(payment.get("Amount", 0) or 0) * 100)),
                    "date": payment.get("Date"),
                    "status": "success"
                }
        except httpx.TimeoutException:
            raise_erp_timeout("xero")
        except httpx.RequestError:
            raise_erp_unavailable("xero")

    # ----------------------------------------------------------------
    # UPDATE INVOICE
    # ----------------------------------------------------------------
    async def update_invoice(self, token: str, tenant_id: str,
                             invoice_id: str, data: dict) -> dict:
        if _is_dummy_token(token):
            return await self._mock.update_invoice(token, tenant_id, invoice_id, data)
        headers = self._get_headers(token, tenant_id)

        xero_payload = {}
        if data.get("status"):
            status_map = {
                "draft": "DRAFT",
                "authorised": "AUTHORISED",
                "paid": "PAID",
                "voided": "VOIDED",
            }
            xero_payload["Status"] = status_map.get(data.get("status", "").lower(), "DRAFT")
        if data.get("due_date"):
            xero_payload["DueDate"] = data.get("due_date")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{XERO_BASE_URL}/Invoices/{invoice_id}",
                    headers=headers,
                    json=xero_payload
                )
                self._check_response(response, f"/Invoices/{invoice_id} (Update)")
                result = response.json()
                invoices = result.get("Invoices", [])
                if not invoices:
                    return {}
                return self._normalize_invoice(invoices[0])
        except httpx.TimeoutException:
            raise_erp_timeout("xero")
        except httpx.RequestError:
            raise_erp_unavailable("xero")