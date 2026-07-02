import logging
import httpx
from adapters.base_adapter import BaseERPAdapter
from utils.errors import (
    raise_token_expired,
    raise_not_found,
    raise_invalid_request,
    raise_erp_unavailable,
    raise_erp_timeout,
    ERPConnectorError
)

XERO_BASE_URL = "https://api.xero.com/api.xro/2.0"
logger = logging.getLogger("erp_connector.xero")


class XeroAdapter(BaseERPAdapter):
    """
    Concrete adapter implementation for Xero.
    Handles authentication headers, endpoint queries, error translation,
    and output normalization to match the common ERP Connector schema contract.
    """

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
            raise_invalid_request("xero", response.text[:200])
        elif response.status_code in (429, 500, 502, 503):
            raise_erp_unavailable("xero")
        else:
            raise_erp_unavailable("xero")

    def _map_status(self, xero_status: str) -> str:
        """Map Xero status values to our normalised schema."""
        if not xero_status:
            return "draft"
        mapping = {
            "DRAFT": "draft",
            "SUBMITTED": "draft",
            "AUTHORISED": "authorised",
            "PAID": "paid",
            "VOIDED": "voided",
            "DELETED": "voided",
        }
        return mapping.get(xero_status.upper(), "draft")

    def _normalize_line_items(self, items: list) -> list[dict]:
        normalized = []
        for item in items or []:
            unit_amt_float = float(item.get("UnitAmount", 0) or 0)
            normalized.append({
                "description": item.get("Description", "") or "Item",
                "quantity": float(item.get("Quantity", 1.0) or 1.0),
                "unit_amount": int(round(unit_amt_float * 100)),
                "account_code": str(item.get("AccountCode", "") or "")
            })
        return normalized

    def _normalize_invoice(self, inv: dict) -> dict:
        total_float = float(inv.get("Total", 0) or 0)
        return {
            "id": str(inv.get("InvoiceID", "")),
            "reference_number": str(inv.get("InvoiceNumber", "") or inv.get("InvoiceID", "")),
            "date": inv.get("DateString", "")[:10] if inv.get("DateString") else (inv.get("Date", "")[:10] if inv.get("Date") else ""),
            "due_date": inv.get("DueDateString", "")[:10] if inv.get("DueDateString") else (inv.get("DueDate", "")[:10] if inv.get("DueDate") else ""),
            "amount": int(round(total_float * 100)),
            "currency": str(inv.get("CurrencyCode", "USD")),
            "status": self._map_status(inv.get("Status", "")),
            "contact_id": str(inv.get("Contact", {}).get("ContactID", "")),
            "line_items": self._normalize_line_items(inv.get("LineItems", []))
        }

    def _normalize_bill(self, bill: dict) -> dict:
        total_float = float(bill.get("Total", 0) or 0)
        return {
            "id": str(bill.get("InvoiceID", "")),
            "bill_number": str(bill.get("InvoiceNumber", "") or bill.get("InvoiceID", "")),
            "date": bill.get("DateString", "")[:10] if bill.get("DateString") else (bill.get("Date", "")[:10] if bill.get("Date") else ""),
            "due_date": bill.get("DueDateString", "")[:10] if bill.get("DueDateString") else (bill.get("DueDate", "")[:10] if bill.get("DueDate") else ""),
            "amount": int(round(total_float * 100)),
            "currency": str(bill.get("CurrencyCode", "USD")),
            "status": self._map_status(bill.get("Status", "")),
            "supplier_id": str(bill.get("Contact", {}).get("ContactID", "")),
            "line_items": self._normalize_line_items(bill.get("LineItems", []))
        }

    def _normalize_contact(self, contact: dict) -> dict:
        is_customer = contact.get("IsCustomer", False)
        contact_type = "customer" if is_customer else "supplier"
        
        phone_val = None
        phones = contact.get("Phones", [])
        for p in phones:
            if p.get("PhoneType") == "DEFAULT" and p.get("PhoneNumber"):
                phone_val = p.get("PhoneNumber")
                break
        if not phone_val and phones:
            phone_val = phones[0].get("PhoneNumber")

        address_val = None
        addresses = contact.get("Addresses", [])
        for a in addresses:
            if a.get("AddressType") == "POSTAL" and a.get("AddressLine1"):
                address_val = a.get("AddressLine1")
                break
        if not address_val and addresses:
            address_val = addresses[0].get("AddressLine1")

        return {
            "id": str(contact.get("ContactID", "")),
            "name": str(contact.get("Name", "")),
            "email": contact.get("EmailAddress"),
            "phone": phone_val,
            "type": contact_type,
            "address": address_val
        }

    def _normalize_account(self, account: dict) -> dict:
        return {
            "id": str(account.get("AccountID", "")),
            "code": str(account.get("Code", "")),
            "name": str(account.get("Name", "")),
            "type": str(account.get("Type", "")).lower(),
            "tax_type": account.get("TaxType"),
            "currency_code": account.get("CurrencyCode")
        }

    # ----------------------------------------------------------------
    # GET INVOICES
    # ----------------------------------------------------------------
    async def get_invoices(self, token: str, tenant_id: str, from_date: str = None,
                           to_date: str = None, status: str = None) -> list[dict]:
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
    async def get_contact(self, token: str, tenant_id: str, contact_id: str) -> dict:
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
        headers = self._get_headers(token, tenant_id)

        xero_payload = {
            "Type": "ACCREC",
            "Contact": {"ContactID": data.get("contact_id")},
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

    # ----------------------------------------------------------------
    # GET PAYMENTS
    # ----------------------------------------------------------------
    async def get_payments(self, token: str, tenant_id: str) -> list[dict]:
        headers = self._get_headers(token, tenant_id)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{XERO_BASE_URL}/Payments",
                    headers=headers
                )
                self._check_response(response, "/Payments (List)")
                result = response.json()
                payments = result.get("Payments", [])
                normalized = []
                for p in payments:
                    inv_id = p.get("Invoice", {}).get("InvoiceID") or p.get("CreditNote", {}).get("CreditNoteID") or ""
                    date_str = p.get("Date")
                    if date_str and len(date_str) >= 10:
                        date_str = date_str[:10]
                    normalized.append({
                        "id": str(p.get("PaymentID", "")),
                        "invoice_id": str(inv_id),
                        "amount": int(round(float(p.get("Amount", 0) or 0) * 100)),
                        "date": date_str or "",
                        "account_code": str(p.get("Account", {}).get("Code") or p.get("Account", {}).get("AccountID") or ""),
                    })
                return normalized
        except httpx.TimeoutException:
            raise_erp_timeout("xero")
        except httpx.RequestError:
            raise_erp_unavailable("xero")