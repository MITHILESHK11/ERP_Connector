import httpx
import logging
from adapters.base_adapter import BaseERPAdapter, register_adapter
from utils.errors import (
    raise_token_expired,
    raise_not_found,
    raise_invalid_request,
    raise_erp_unavailable,
    raise_erp_timeout,
    ERPConnectorError
)
from utils.pagination import fetch_all_pages
from utils.field_mapper import load_mapping, map_record
from utils.transforms import TRANSFORMS
from utils.resilience import erp_transient_retry

import os
import re

_INVOICE_MAPPING = load_mapping("qbo", "invoice")
_BILL_MAPPING = load_mapping("qbo", "bill")
_CUSTOMER_MAPPING = load_mapping("qbo", "customer")
_VENDOR_MAPPING = load_mapping("qbo", "vendor")
_ACCOUNT_MAPPING = load_mapping("qbo", "account")
QBO_SANDBOX_BASE = os.getenv("QBO_SANDBOX_BASE_OVERRIDE", "https://sandbox-quickbooks.api.intuit.com")
QBO_MINOR_VERSION = "75"
logger = logging.getLogger("erp_connector.qbo")

# QBO's QueryService has no parameterized-query support, so any value
# interpolated into the SQL-like string is a potential injection point. Since
# from_date/to_date only ever need to be calendar dates, whitelist the exact
# shape instead of trying to escape special characters.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _sanitize_qbo_date(value: str | None, field_name: str) -> str | None:
    """Validate a date filter is strictly YYYY-MM-DD before it touches a query string."""
    if value is None:
        return None
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise_invalid_request(
            "quickbooks",
            f"Invalid {field_name}: must be an ISO date in YYYY-MM-DD format"
        )
    return value


class QBOHttpClient:
    """
    Thin async HTTP wrapper for QBO sandbox API calls.
    Handles URL construction, auth headers, and error detection.
    One instance per request — do not cache or share instances.
    """
    
    def __init__(self, token: str, realm_id: str):
        self.realm_id = realm_id
        self.base_url = f"{QBO_SANDBOX_BASE}/v3/company/{realm_id}"
        # Base headers for GET requests — no Content-Type, since a GET has no
        # body. Sending Content-Type: application/json alongside an empty
        # body can cause QBO's API gateway to attempt parsing that (empty)
        # body as JSON and fail with a generic "invalid or unsupported
        # property" (fault code 2010) error — a real, observed cause of that
        # error on plain read requests, not just on malformed writes.
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        # POST/PUT requests genuinely have a JSON body, so they need
        # Content-Type — kept as a separate header set rather than mutating
        # self.headers, so GET calls never accidentally pick it up.
        self.write_headers = {**self.headers, "Content-Type": "application/json"}
        # SECURITY: Never log token. Only log realm_id.
        logger.info(f"QBOHttpClient initialised for realm_id={realm_id}")

    @erp_transient_retry
    async def _do_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """
        The actual network call, isolated so @erp_transient_retry can see and
        retry the RAW httpx exception. If this lived inside query()/get_entity()/
        post_entity() directly, their own try/except would catch and convert
        the exception to ERPConnectorError before tenacity ever saw it — silently
        defeating the retry (it would "succeed" at raising the wrong thing on
        attempt 1 every time).
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.request(method, url, **kwargs)

    async def query(self, sql: str) -> dict:
        """Run a QueryService SQL-like query. Returns full parsed JSON response."""
        url = f"{self.base_url}/query"
        params = {"query": sql, "minorversion": QBO_MINOR_VERSION}
        try:
            response = await self._do_request("GET", url, headers=self.headers, params=params)
            self._check_response(response)
            return response.json()
        except httpx.TimeoutException:
            logger.error(f"QBO request timed out for realm_id={self.realm_id}")
            raise_erp_timeout("quickbooks")
        except httpx.RequestError as exc:
            logger.error(f"QBO network error: {exc} realm_id={self.realm_id}")
            raise_erp_unavailable("quickbooks")

    async def get_entity(self, entity: str, entity_id: str) -> dict:
        """GET a single entity by ID."""
        url = f"{self.base_url}/{entity}/{entity_id}"
        params = {"minorversion": QBO_MINOR_VERSION}
        try:
            response = await self._do_request("GET", url, headers=self.headers, params=params)
            self._check_response(response)
            return response.json()
        except httpx.TimeoutException:
            logger.error(f"QBO request timed out for realm_id={self.realm_id}")
            raise_erp_timeout("quickbooks")
        except httpx.RequestError as exc:
            logger.error(f"QBO network error: {exc} realm_id={self.realm_id}")
            raise_erp_unavailable("quickbooks")

    async def post_entity(self, entity: str, body: dict) -> dict:
        """POST to create OR update an entity. QBO uses POST for both."""
        url = f"{self.base_url}/{entity}"
        params = {"minorversion": QBO_MINOR_VERSION}
        try:
            response = await self._do_request("POST", url, headers=self.write_headers,
                                               json=body, params=params)
            self._check_response(response)
            return response.json()
        except httpx.TimeoutException:
            logger.error(f"QBO request timed out for realm_id={self.realm_id}")
            raise_erp_timeout("quickbooks")
        except httpx.RequestError as exc:
            logger.error(f"QBO network error: {exc} realm_id={self.realm_id}")
            raise_erp_unavailable("quickbooks")

    def _check_response(self, response: httpx.Response) -> None:
        """
        Check HTTP status. Raise appropriate ERPConnectorError on failure.
        NEVER pass raw QBO error body to the caller. Log it server-side only.
        """
        if response.status_code == 200:
            return
        # Log raw error body for debugging — never expose to caller
        logger.error(
            f"QBO API error: status={response.status_code} "
            f"realm_id={self.realm_id} body={response.text[:200]}"
        )
        if response.status_code == 401:
            raise_token_expired("quickbooks")
        elif response.status_code == 404:
            raise_not_found("quickbooks", "entity")
        elif response.status_code == 400:
            try:
                body = response.json()
                fault = body.get("Fault", {})
                error_list = fault.get("Error", [{}])
                if error_list:
                    error_code = error_list[0].get("code", "")
                    if error_code == "5010":
                        raise_invalid_request(
                            "quickbooks",
                            "Version conflict — record was updated by another process. Retry."
                        )
                    # QBO's REST API returns HTTP 400 (not 404) with fault
                    # code 610 when a GET-by-id targets an entity that doesn't
                    # exist. Without this, a genuinely missing entity (e.g. an
                    # id that's a Customer but not a Vendor) was misreported as
                    # a validation error instead of "not found" — which broke
                    # get_contact's customer/vendor collision check, since it
                    # only treats real NOT_FOUND as "that entity doesn't exist"
                    # and re-raises anything else.
                    if error_code == "610":
                        raise_not_found("quickbooks", "entity")
            except ERPConnectorError:
                raise
            except Exception:
                pass
            raise_invalid_request("quickbooks", "Bad request — check field values")
        elif response.status_code == 429:
            logger.warning(f"QBO 429 reached adapter for realm_id={self.realm_id}")
            from utils.errors import raise_rate_limit_timeout
            raise_rate_limit_timeout("quickbooks")
        elif response.status_code in (500, 503):
            raise_erp_unavailable("quickbooks")
        else:
            raise_erp_unavailable("quickbooks")



def extract_query_results(response: dict, entity_name: str) -> list:
    """
    Safely extract the entity list from a QBO QueryResponse.
    Returns [] if QueryResponse exists but entity list is empty.
    QBO uses PascalCase entity names: "Invoice", "Bill", "Customer", "Vendor", "Account"
    """
    return response.get("QueryResponse", {}).get(entity_name, [])


async def get_entity_with_sync_token(client: QBOHttpClient, 
                                      entity: str, 
                                      entity_id: str) -> tuple[str, dict]:
    """
    Fetch a QBO entity and return (sync_token: str, full_entity: dict).
    MUST be called before any update operation.
    QBO increments SyncToken on every save — always fetch fresh before updating.
    """
    response = await client.get_entity(entity, entity_id)
    # QBO single-entity GET returns { "EntityName": { ...fields... }, "time": "..." }
    # The entity key is PascalCase matching the URL segment
    entity_key = entity.capitalize()
    full_entity = response.get(entity_key, response)
    sync_token = str(full_entity.get("SyncToken", "0"))
    logger.info(f"Fetched SyncToken={sync_token} for {entity}={entity_id}")
    return sync_token, full_entity


def normalize_qbo_invoice(raw: dict) -> dict:
    """Convert a raw QBO Invoice dict to our normalised schema (config-driven)."""
    return map_record(raw, _INVOICE_MAPPING, TRANSFORMS)


def normalize_qbo_bill(raw: dict) -> dict:
    """Convert a raw QBO Bill dict to our normalised schema (config-driven)."""
    return map_record(raw, _BILL_MAPPING, TRANSFORMS)


def normalize_qbo_customer(raw: dict) -> dict:
    """QBO Customer -> NormalizedContact (config-driven)."""
    return map_record(raw, _CUSTOMER_MAPPING, TRANSFORMS)


def normalize_qbo_vendor(raw: dict) -> dict:
    """QBO Vendor -> NormalizedContact (config-driven)."""
    return map_record(raw, _VENDOR_MAPPING, TRANSFORMS)


def normalize_qbo_account(raw: dict) -> dict:
    """QBO Account -> NormalizedAccount (config-driven)."""
    return map_record(raw, _ACCOUNT_MAPPING, TRANSFORMS)


def format_qbo_address(addr_dict: dict | None) -> str | None:
    """Kept for backward compatibility — same logic now lives in transforms.qbo_address."""
    if not addr_dict:
        return None
    parts = []
    for key in ["Line1", "Line2", "Line3", "City", "CountrySubDivisionCode", "PostalCode"]:
        val = addr_dict.get(key)
        if val:
            parts.append(str(val).strip())
    return ", ".join(parts) if parts else None



def build_qbo_lines_from_items(line_items: list[dict]) -> list[dict]:
    """
    Convert our normalised line_items to QBO Line array format.
    unit_amount in our schema is integer (paise/cents) → divide by 100 for QBO float.
    """
    lines = []
    for item in line_items:
        amount_float = item["unit_amount"] / 100
        qty = item.get("quantity", 1)
        # Use the caller's actual item/account reference — never hardcode.
        item_ref_value = item.get("item_id") or item.get("account_code") or "1"
        lines.append({
            "Amount": round(amount_float * qty, 2),
            "DetailType": "SalesItemLineDetail",
            "SalesItemLineDetail": {
                "ItemRef": { "value": item_ref_value, "name": item.get("description", "") },
                "Qty": qty,
                "UnitPrice": amount_float,
            }
        })
    return lines


def _is_dummy_token(token: str) -> bool:
    if not token:
        return True
    clean = token.replace("Bearer ", "").strip()
    return any(clean.startswith(prefix) for prefix in ("your_", "mock", "test-token", "demo", "dummy"))


# The QBOAdapter class implementation
@register_adapter("quickbooks", "qbo")
class QBOAdapter(BaseERPAdapter):

    """
    QBO Adapter — implements BaseERPAdapter for QuickBooks Online.
    All methods call the real QBO sandbox API via QBOHttpClient.
    Token and realm_id are passed per-request — never stored.
    Delegates to MockAdapter for testing/demo tokens.
    """

    def __init__(self):
        from adapters.mock import MockAdapter
        self._mock = MockAdapter()

    async def get_invoices(self, token: str, tenant_id: str, 
                           from_date: str = None, to_date: str = None, 
                           status: str = None) -> list[dict]:
        """
        Fetch all invoices from QBO using QueryService.
        Handles pagination internally — returns complete merged list.
        """
        if _is_dummy_token(token):
            return await self._mock.get_invoices(token, tenant_id, from_date, to_date, status)

        client = QBOHttpClient(token, tenant_id)

        # Reject anything that isn't a plain YYYY-MM-DD date before
        # it gets anywhere near the query string.
        from_date = _sanitize_qbo_date(from_date, "from_date")
        to_date = _sanitize_qbo_date(to_date, "to_date")

        # Build WHERE clause from optional filters
        conditions = []
        if from_date:
            conditions.append(f"TxnDate >= '{from_date}'")
        if to_date:
            conditions.append(f"TxnDate <= '{to_date}'")
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        base_query = f"SELECT * FROM Invoice {where_clause}".strip()
        
        # Pagination: use fetch_all_pages utility from Dev 1
        # Pass a lambda that calls fetch_page(page_number) and returns list
        async def fetch_page(page: int) -> list:
            start_position = (page - 1) * 1000 + 1
            sql = f"{base_query} STARTPOSITION {start_position} MAXRESULTS 1000"
            response = await client.query(sql)
            return extract_query_results(response, "Invoice")
        
        all_raw = await fetch_all_pages(fetch_page)
        normalized = [normalize_qbo_invoice(inv) for inv in all_raw]

        # Status is a derived field (QBO has no single status column),
        # so it can't go in the SQL WHERE clause — filter in Python after normalizing.
        if status:
            normalized = [inv for inv in normalized if inv["status"] == status]

        return normalized

    async def get_invoice(self, token: str, tenant_id: str, 
                          invoice_id: str) -> dict:
        """
        Fetch a single QBO invoice by ID.
        QBO single-entity GET returns { "Invoice": { ...fields... } }
        """
        if _is_dummy_token(token):
            return await self._mock.get_invoice(token, tenant_id, invoice_id)

        client = QBOHttpClient(token, tenant_id)
        response = await client.get_entity("invoice", invoice_id)
        raw = response.get("Invoice")
        if not raw:
            from utils.errors import raise_not_found
            raise_not_found("quickbooks", f"Invoice {invoice_id}")
        return normalize_qbo_invoice(raw)

    async def get_bills(self, token: str, tenant_id: str,
                        from_date: str = None, to_date: str = None) -> list[dict]:
        """
        Fetch all QBO Bills.
        IMPORTANT: QBO Bill is a SEPARATE entity from Invoice.
        Use 'SELECT * FROM Bill' — NOT 'SELECT * FROM Invoice'.
        """
        if _is_dummy_token(token):
            return await self._mock.get_bills(token, tenant_id, from_date, to_date)

        client = QBOHttpClient(token, tenant_id)

        # Same date whitelist as get_invoices.
        from_date = _sanitize_qbo_date(from_date, "from_date")
        to_date = _sanitize_qbo_date(to_date, "to_date")

        conditions = []
        if from_date:
            conditions.append(f"TxnDate >= '{from_date}'")
        if to_date:
            conditions.append(f"TxnDate <= '{to_date}'")
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        base_query = f"SELECT * FROM Bill {where_clause}".strip()
        
        async def fetch_page(page: int) -> list:
            start = (page - 1) * 1000 + 1
            sql = f"{base_query} STARTPOSITION {start} MAXRESULTS 1000"
            response = await client.query(sql)
            return extract_query_results(response, "Bill")
        
        all_raw = await fetch_all_pages(fetch_page)
        return [normalize_qbo_bill(b) for b in all_raw]

    async def get_bill(self, token: str, tenant_id: str, bill_id: str) -> dict:
        """
        Fetch a single QBO Bill by ID.
        """
        if _is_dummy_token(token):
            return await self._mock.get_bill(token, tenant_id, bill_id)

        client = QBOHttpClient(token, tenant_id)
        response = await client.get_entity("bill", bill_id)
        raw = response.get("Bill")
        if not raw:
            from utils.errors import raise_not_found
            raise_not_found("quickbooks", f"Bill {bill_id}")
        return normalize_qbo_bill(raw)

    async def get_contacts(self, token: str, tenant_id: str,
                           contact_type: str = None) -> list[dict]:
        """
        Fetch QBO contacts. 
        QBO has SEPARATE Customer and Vendor entities (unlike Xero's single /Contacts).
        
        contact_type == "customer"  → query Customer only
        contact_type == "supplier"  → query Vendor only
        contact_type == None        → query both and merge
        """
        if _is_dummy_token(token):
            return await self._mock.get_contacts(token, tenant_id, contact_type)

        client = QBOHttpClient(token, tenant_id)
        result = []
        
        if contact_type in (None, "customer"):
            async def fetch_customers(page: int) -> list:
                start = (page - 1) * 1000 + 1
                sql = f"SELECT * FROM Customer WHERE Active = true STARTPOSITION {start} MAXRESULTS 1000"
                resp = await client.query(sql)
                return extract_query_results(resp, "Customer")
            customers = await fetch_all_pages(fetch_customers)
            result.extend([normalize_qbo_customer(c) for c in customers])
        
        if contact_type in (None, "supplier"):
            async def fetch_vendors(page: int) -> list:
                start = (page - 1) * 1000 + 1
                sql = f"SELECT * FROM Vendor WHERE Active = true STARTPOSITION {start} MAXRESULTS 1000"
                resp = await client.query(sql)
                return extract_query_results(resp, "Vendor")
            vendors = await fetch_all_pages(fetch_vendors)
            result.extend([normalize_qbo_vendor(v) for v in vendors])
        
        return result

    async def get_contact(self, token: str, tenant_id: str, contact_id: str,
                          contact_type: str = None) -> dict:
        """
        Fetch a single QBO Customer or Vendor contact by ID.
        """
        if _is_dummy_token(token):
            return await self._mock.get_contact(token, tenant_id, contact_id, contact_type)

        client = QBOHttpClient(token, tenant_id)

        async def _try_customer():
            try:
                response = await client.get_entity("customer", contact_id)
                raw = response.get("Customer")
                return normalize_qbo_customer(raw) if raw else None
            except ERPConnectorError:
                # This is a "does this ID exist as a Customer?" probe, not a
                # user-facing validation call — QBO doesn't always return a
                # clean NOT_FOUND for a type-mismatched ID (some environments
                # return a generic validation fault instead), so treat ANY
                # error here as "no match under this type", not just the
                # strict NOT_FOUND case.
                return None

        async def _try_vendor():
            try:
                response = await client.get_entity("vendor", contact_id)
                raw = response.get("Vendor")
                return normalize_qbo_vendor(raw) if raw else None
            except ERPConnectorError:
                return None

        from utils.errors import raise_not_found

        if contact_type == "customer":
            result = await _try_customer()
            if result:
                return result
            raise_not_found("quickbooks", f"Customer {contact_id}")

        if contact_type == "supplier":
            result = await _try_vendor()
            if result:
                return result
            raise_not_found("quickbooks", f"Vendor {contact_id}")

        customer_result = await _try_customer()
        vendor_result = await _try_vendor()

        if customer_result and vendor_result:
            raise_invalid_request(
                "quickbooks",
                f"Contact id {contact_id} matches both a Customer and a Vendor — "
                f"pass type=customer or type=supplier to disambiguate."
            )
        if customer_result:
            return customer_result
        if vendor_result:
            return vendor_result

        raise_not_found("quickbooks", f"Contact {contact_id}")

    async def get_accounts(self, token: str, tenant_id: str) -> list[dict]:
        if _is_dummy_token(token):
            return await self._mock.get_accounts(token, tenant_id)

        client = QBOHttpClient(token, tenant_id)
        
        async def fetch_page(page: int) -> list:
            start = (page - 1) * 1000 + 1
            sql = f"SELECT * FROM Account WHERE Active = true STARTPOSITION {start} MAXRESULTS 1000"
            resp = await client.query(sql)
            return extract_query_results(resp, "Account")
        
        all_raw = await fetch_all_pages(fetch_page)
        return [normalize_qbo_account(a) for a in all_raw]

    async def get_items(self, token: str, tenant_id: str) -> list[dict]:
        if _is_dummy_token(token):
            return await self._mock.get_items(token, tenant_id)

        client = QBOHttpClient(token, tenant_id)

        async def fetch_page(page: int) -> list:
            start = (page - 1) * 1000 + 1
            sql = f"SELECT * FROM Item WHERE Active = true STARTPOSITION {start} MAXRESULTS 1000"
            resp = await client.query(sql)
            return extract_query_results(resp, "Item")

        all_raw = await fetch_all_pages(fetch_page)
        return [
            {
                "id": item.get("Id"),
                "name": item.get("Name"),
                "type": item.get("Type"),
                "unit_price": item.get("UnitPrice"),
                "income_account_id": item.get("IncomeAccountRef", {}).get("value"),
            }
            for item in all_raw
        ]

    async def create_invoice(self, token: str, tenant_id: str, data: dict) -> dict:
        if _is_dummy_token(token):
            return await self._mock.create_invoice(token, tenant_id, data)

        client = QBOHttpClient(token, tenant_id)
        
        qbo_body = {
            "Line": build_qbo_lines_from_items(data.get("line_items", [])),
            "CustomerRef": { "value": data["contact_id"] },
            "TxnDate": data["date"],
            "DueDate": data["due_date"],
            "CurrencyRef": { "value": data.get("currency", "USD") },
        }
        
        response = await client.post_entity("invoice", qbo_body)
        raw = response.get("Invoice", {})
        return normalize_qbo_invoice(raw)

    async def create_bill(self, token: str, tenant_id: str, data: dict) -> dict:
        if _is_dummy_token(token):
            return await self._mock.create_bill(token, tenant_id, data)

        client = QBOHttpClient(token, tenant_id)
        
        bill_lines = []
        for item in data.get("line_items", []):
            amount_float = item["unit_amount"] / 100
            bill_lines.append({
                "Amount": round(amount_float * item.get("quantity", 1), 2),
                "DetailType": "AccountBasedExpenseLineDetail",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {
                        "value": item.get("account_code", "1"),
                        "name": item.get("description", ""),
                    }
                }
            })
        
        qbo_body = {
            "Line": bill_lines,
            "VendorRef": { "value": data["supplier_id"] },
            "TxnDate": data["date"],
            "DueDate": data.get("due_date"),
            "CurrencyRef": { "value": data.get("currency", "USD") },
        }
        
        response = await client.post_entity("bill", qbo_body)
        raw = response.get("Bill", {})
        return normalize_qbo_bill(raw)

    async def create_contact(self, token: str, tenant_id: str, data: dict) -> dict:
        if _is_dummy_token(token):
            return await self._mock.create_contact(token, tenant_id, data)

        client = QBOHttpClient(token, tenant_id)
        contact_type = data.get("type", "customer")
        
        if contact_type == "customer":
            qbo_body = {
                "DisplayName": data["name"],
                "PrimaryEmailAddr": {"Address": data.get("email")} if data.get("email") else None,
                "PrimaryPhone": {"FreeFormNumber": data.get("phone")} if data.get("phone") else None,
            }
            qbo_body = {k: v for k, v in qbo_body.items() if v is not None}
            response = await client.post_entity("customer", qbo_body)
            return normalize_qbo_customer(response.get("Customer", {}))
        
        elif contact_type == "supplier":
            qbo_body = {
                "DisplayName": data["name"],
                "PrimaryEmailAddr": {"Address": data.get("email")} if data.get("email") else None,
                "PrintOnCheckName": data["name"],
            }
            qbo_body = {k: v for k, v in qbo_body.items() if v is not None}
            response = await client.post_entity("vendor", qbo_body)
            return normalize_qbo_vendor(response.get("Vendor", {}))
        
        else:
            raise_invalid_request("quickbooks", f"Invalid contact type: {contact_type}")

    async def record_payment(self, token: str, tenant_id: str, data: dict) -> dict:
        if _is_dummy_token(token):
            return await self._mock.record_payment(token, tenant_id, data)

        client = QBOHttpClient(token, tenant_id)
        invoice_id = data["invoice_id"]
        amount_float = data["amount"] / 100
        
        invoice_response = await client.get_entity("invoice", invoice_id)
        raw_invoice = invoice_response.get("Invoice", {})
        if not raw_invoice:
            from utils.errors import raise_not_found
            raise_not_found("quickbooks", f"Invoice {invoice_id}")
        
        customer_ref_value = raw_invoice.get("CustomerRef", {}).get("value")
        if not customer_ref_value:
            raise_invalid_request("quickbooks", 
                "Invoice has no CustomerRef — cannot record payment")
        
        payment_body = {
            "TotalAmt": amount_float,
            "CustomerRef": { "value": customer_ref_value },
            "DepositToAccountRef": { "value": data.get("account_code", "1") },
            "TxnDate": data["date"],
            "Line": [
                {
                    "Amount": amount_float,
                    "LinkedTxn": [
                        { "TxnId": invoice_id, "TxnType": "Invoice" }
                    ]
                }
            ]
        }
        
        response = await client.post_entity("payment", payment_body)
        raw_payment = response.get("Payment", {})
        
        logger.info(
            f"Payment recorded for invoice={invoice_id} "
            f"amount={amount_float} realm_id={tenant_id}"
        )
        
        return {
            "payment_id": raw_payment.get("Id"),
            "invoice_id": invoice_id,
            "amount": data["amount"],
            "date": data["date"],
            "status": "success",
        }

    async def update_invoice(self, token: str, tenant_id: str, 
                             invoice_id: str, data: dict) -> dict:
        if _is_dummy_token(token):
            return await self._mock.update_invoice(token, tenant_id, invoice_id, data)

        client = QBOHttpClient(token, tenant_id)
        
        sync_token, full_invoice = await get_entity_with_sync_token(
            client, "invoice", invoice_id
        )
        
        if "due_date" in data:
            full_invoice["DueDate"] = data["due_date"]
        if "date" in data:
            full_invoice["TxnDate"] = data["date"]
        
        full_invoice["SyncToken"] = sync_token
        full_invoice["Id"] = invoice_id
        full_invoice["sparse"] = True
        
        response = await client.post_entity("invoice", full_invoice)
        raw = response.get("Invoice", {})
        return normalize_qbo_invoice(raw)