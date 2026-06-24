import httpx
import logging
from adapters.base_adapter import BaseERPAdapter
from utils.errors import (
    raise_token_expired,
    raise_not_found,
    raise_invalid_request,
    raise_erp_unavailable,
    raise_erp_timeout
)
from utils.pagination import fetch_all_pages

QBO_SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com"
QBO_MINOR_VERSION = "75"
logger = logging.getLogger("erp_connector.qbo")


class QBOHttpClient:
    """
    Thin async HTTP wrapper for QBO sandbox API calls.
    Handles URL construction, auth headers, and error detection.
    One instance per request — do not cache or share instances.
    """
    
    def __init__(self, token: str, realm_id: str):
        self.realm_id = realm_id
        self.base_url = f"{QBO_SANDBOX_BASE}/v3/company/{realm_id}"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        # SECURITY: Never log token. Only log realm_id.
        logger.info(f"QBOHttpClient initialised for realm_id={realm_id}")

    async def query(self, sql: str) -> dict:
        """Run a QueryService SQL-like query. Returns full parsed JSON response."""
        url = f"{self.base_url}/query"
        params = {"query": sql, "minorversion": QBO_MINOR_VERSION}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=self.headers, params=params)
        self._check_response(response)
        return response.json()

    async def get_entity(self, entity: str, entity_id: str) -> dict:
        """GET a single entity by ID."""
        url = f"{self.base_url}/{entity}/{entity_id}"
        params = {"minorversion": QBO_MINOR_VERSION}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=self.headers, params=params)
        self._check_response(response)
        return response.json()

    async def post_entity(self, entity: str, body: dict) -> dict:
        """POST to create OR update an entity. QBO uses POST for both."""
        url = f"{self.base_url}/{entity}"
        params = {"minorversion": QBO_MINOR_VERSION}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=self.headers, 
                                          json=body, params=params)
        self._check_response(response)
        return response.json()

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
            raise_invalid_request("quickbooks", "Bad request — check field values and SyncToken")
        elif response.status_code == 429:
            # Should be handled by rate limiter — log warning
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
    """
    Convert a raw QBO Invoice dict to our normalised schema.
    
    QBO field        → Our field
    Id               → id
    DocNumber        → reference_number
    TxnDate          → date  (already YYYY-MM-DD in QBO)
    DueDate          → due_date
    TotalAmt         → amount (float → int: multiply by 100 for smallest unit)
    CurrencyRef.value → currency
    CustomerRef.value → contact_id
    Balance          → (not in our schema — ignore)
    SyncToken        → (NEVER expose — internal QBO field only)
    Line             → line_items (see below)
    
    Status normalisation:
    QBO does not have a single "status" field. Derive it:
      - If Balance == 0 and TotalAmt > 0 → "paid"
      - If raw.get("EmailStatus") == "NotSet" and Balance == TotalAmt → "draft"  
      - Otherwise → "authorised"
      - If raw.get("PrivateNote") contains "void" (case-insensitive) → "voided"
      (NOTE: For Phase 0 sandbox, default unknown status to "authorised")
    
    Line item mapping:
    Each QBO Line item with DetailType == "SalesItemLineDetail":
      Amount                                     → unit_amount (as int * 100)
      SalesItemLineDetail.ItemRef.name           → description
      SalesItemLineDetail.Qty                    → quantity
      SalesItemLineDetail.ItemAccountRef.value   → account_code (may be missing — use "")
    Skip lines where DetailType != "SalesItemLineDetail" (subtotals, discounts etc.)
    """
    
    def derive_status(r):
        balance = r.get("Balance", 0)
        total = r.get("TotalAmt", 0)
        if total > 0 and balance == 0:
            return "paid"
        return "authorised"
    
    line_items = []
    for line in raw.get("Line", []):
        if line.get("DetailType") == "SalesItemLineDetail":
            detail = line.get("SalesItemLineDetail", {})
            line_items.append({
                "description": detail.get("ItemRef", {}).get("name", ""),
                "quantity": detail.get("Qty", 1),
                "unit_amount": int(line.get("Amount", 0) * 100),
                "account_code": detail.get("ItemAccountRef", {}).get("value", ""),
            })

    return {
        "id": raw.get("Id"),
        "reference_number": raw.get("DocNumber"),
        "date": raw.get("TxnDate"),
        "due_date": raw.get("DueDate"),
        "amount": int(raw.get("TotalAmt", 0) * 100),
        "currency": raw.get("CurrencyRef", {}).get("value", "USD"),
        "status": derive_status(raw),
        "contact_id": raw.get("CustomerRef", {}).get("value"),
        "line_items": line_items,
    }


def format_qbo_address(addr_dict: dict | None) -> str | None:
    if not addr_dict:
        return None
    parts = []
    for key in ["Line1", "Line2", "Line3", "City", "CountrySubDivisionCode", "PostalCode"]:
        val = addr_dict.get(key)
        if val:
            parts.append(str(val).strip())
    return ", ".join(parts) if parts else None


def normalize_qbo_bill(raw: dict) -> dict:
    """
    Convert a raw QBO Bill dict to our normalised schema.
    """
    def derive_status(r):
        balance = float(r.get("Balance") or 0.0)
        if balance == 0.0:
            return "paid"
        return "authorised"
    
    line_items = []
    for line in raw.get("Line", []):
        if line.get("DetailType") == "AccountBasedExpenseLineDetail":
            detail = line.get("AccountBasedExpenseLineDetail", {})
            line_items.append({
                "description": detail.get("AccountRef", {}).get("name", ""),
                "quantity": float(detail.get("Qty") or 1.0),
                "unit_amount": int(round(float(line.get("Amount") or 0.0) * 100)),
                "account_code": detail.get("AccountRef", {}).get("value", "")
            })
            
    total_float = float(raw.get("TotalAmt") or 0.0)
    amount = int(round(total_float * 100))
    
    ref_num = raw.get("DocNumber") or raw.get("Id")
    
    return {
        "id": raw.get("Id"),
        "bill_number": ref_num,
        "date": raw.get("TxnDate"),
        "due_date": raw.get("DueDate"),
        "amount": amount,
        "currency": raw.get("CurrencyRef", {}).get("value", "USD"),
        "status": derive_status(raw),
        "supplier_id": raw.get("VendorRef", {}).get("value"),
        "line_items": line_items,
    }


def normalize_qbo_customer(raw: dict) -> dict:
    """
    QBO Customer → NormalizedContact
    """
    email = raw.get("PrimaryEmailAddr", {}).get("Address") if raw.get("PrimaryEmailAddr") else None
    phone = raw.get("PrimaryPhone", {}).get("FreeFormNumber") if raw.get("PrimaryPhone") else None
    address = format_qbo_address(raw.get("BillAddr"))
    
    return {
        "id": raw.get("Id"),
        "name": raw.get("DisplayName", ""),
        "email": email,
        "phone": phone,
        "type": "customer",
        "address": address
    }


def normalize_qbo_vendor(raw: dict) -> dict:
    """
    QBO Vendor → NormalizedContact
    """
    email = raw.get("PrimaryEmailAddr", {}).get("Address") if raw.get("PrimaryEmailAddr") else None
    phone = raw.get("PrimaryPhone", {}).get("FreeFormNumber") if raw.get("PrimaryPhone") else None
    address = format_qbo_address(raw.get("BillAddr"))
    name = raw.get("PrintOnCheckName") or raw.get("DisplayName", "")
    
    return {
        "id": raw.get("Id"),
        "name": name,
        "email": email,
        "phone": phone,
        "type": "supplier",
        "address": address
    }


def normalize_qbo_account(raw: dict) -> dict:
    """
    QBO Account → NormalizedAccount
    """
    tax_type = raw.get("TaxCodeRef", {}).get("value") if raw.get("TaxCodeRef") else None
    currency_code = raw.get("CurrencyRef", {}).get("value") if raw.get("CurrencyRef") else None
    code = raw.get("AcctNum") or raw.get("Id") or ""
    
    return {
        "id": raw.get("Id"),
        "code": code,
        "name": raw.get("Name", ""),
        "type": raw.get("AccountType", ""),
        "tax_type": tax_type,
        "currency_code": currency_code
    }


def build_qbo_lines_from_items(line_items: list[dict]) -> list[dict]:
    """
    Convert our normalised line_items to QBO Line array format.
    unit_amount in our schema is integer (paise/cents) → divide by 100 for QBO float.
    """
    lines = []
    for item in line_items:
        amount_float = item["unit_amount"] / 100
        qty = item.get("quantity", 1)
        lines.append({
            "Amount": round(amount_float * qty, 2),
            "DetailType": "SalesItemLineDetail",
            "SalesItemLineDetail": {
                "ItemRef": { "value": "1", "name": item.get("description", "") },
                "Qty": qty,
                "UnitPrice": amount_float,
            }
        })
    return lines


# The QBOAdapter class implementation
class QBOAdapter(BaseERPAdapter):

    """
    QBO Adapter — implements BaseERPAdapter for QuickBooks Online.
    All methods call the real QBO sandbox API via QBOHttpClient.
    Token and realm_id are passed per-request — never stored.
    """

    async def get_invoices(self, token: str, tenant_id: str, 
                           from_date: str = None, to_date: str = None, 
                           status: str = None) -> list[dict]:
        """
        Fetch all invoices from QBO using QueryService.
        Handles pagination internally — returns complete merged list.
        """
        client = QBOHttpClient(token, tenant_id)
        
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
        return [normalize_qbo_invoice(inv) for inv in all_raw]

    async def get_invoice(self, token: str, tenant_id: str, 
                          invoice_id: str) -> dict:
        """
        Fetch a single QBO invoice by ID.
        QBO single-entity GET returns { "Invoice": { ...fields... } }
        """
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
        client = QBOHttpClient(token, tenant_id)
        
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

    async def get_contact(self, token: str, tenant_id: str, contact_id: str) -> dict:
        """
        Fetch a single QBO Customer or Vendor contact by ID.
        """
        client = QBOHttpClient(token, tenant_id)
        # Try Customer first
        try:
            response = await client.get_entity("customer", contact_id)
            raw = response.get("Customer")
            if raw:
                return normalize_qbo_customer(raw)
        except Exception:
            pass
            
        # Try Vendor next
        try:
            response = await client.get_entity("vendor", contact_id)
            raw = response.get("Vendor")
            if raw:
                return normalize_qbo_vendor(raw)
        except Exception:
            pass
            
        from utils.errors import raise_not_found
        raise_not_found("quickbooks", f"Contact {contact_id}")

    async def get_accounts(self, token: str, tenant_id: str) -> list[dict]:
        client = QBOHttpClient(token, tenant_id)
        
        async def fetch_page(page: int) -> list:
            start = (page - 1) * 1000 + 1
            sql = f"SELECT * FROM Account WHERE Active = true STARTPOSITION {start} MAXRESULTS 1000"
            resp = await client.query(sql)
            return extract_query_results(resp, "Account")
        
        all_raw = await fetch_all_pages(fetch_page)
        return [normalize_qbo_account(a) for a in all_raw]

    async def create_invoice(self, token: str, tenant_id: str, data: dict) -> dict:
        """
        Create a QBO Invoice (sales invoice — equivalent to Xero ACCREC).
        QBO returns the created invoice in the response body.
        """
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
        """
        Create a QBO Bill (vendor bill — completely separate entity from Invoice in QBO).
        QBO Bills use VendorRef (not CustomerRef) and AccountBasedExpenseLineDetail.
        """
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
        """
        Create a QBO Customer or Vendor based on contact type.
        "customer" → POST to /customer
        "supplier" → POST to /vendor
        """
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
        """
        Record a payment against a QBO Invoice.
        
        Incoming data fields:
          invoice_id   → the QBO Invoice Id to pay
          amount       → payment amount in smallest unit (paise/cents) — divide by 100
          date         → payment date (YYYY-MM-DD)
          account_code → deposit account Id in QBO (e.g. bank account)
        
        Process:
          1. Fetch the invoice to get CustomerRef.value (required for Payment)
          2. Create a Payment entity with LinkedTxn pointing to the invoice
          3. Return the normalised payment result
        """
        client = QBOHttpClient(token, tenant_id)
        invoice_id = data["invoice_id"]
        amount_float = data["amount"] / 100
        
        # Step 1: Fetch invoice to get CustomerRef
        invoice_response = await client.get_entity("invoice", invoice_id)
        raw_invoice = invoice_response.get("Invoice", {})
        if not raw_invoice:
            from utils.errors import raise_not_found
            raise_not_found("quickbooks", f"Invoice {invoice_id}")
        
        customer_ref_value = raw_invoice.get("CustomerRef", {}).get("value")
        if not customer_ref_value:
            raise_invalid_request("quickbooks", 
                "Invoice has no CustomerRef — cannot record payment")
        
        # Step 2: Create the Payment entity
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
        
        # Return a clean success response (not a normalised entity — payment is just a receipt)
        return {
            "success": True,
            "payment_id": raw_payment.get("Id"),
            "invoice_id": invoice_id,
            "amount": data["amount"],
            "date": data["date"],
        }

    async def update_invoice(self, token: str, tenant_id: str, 
                             invoice_id: str, data: dict) -> dict:
        """
        Update a QBO Invoice. Requires SyncToken — fetched internally.
        
        CRITICAL RULE:
        1. Fetch the full invoice (to get SyncToken and complete object)
        2. Merge the caller's changes INTO the full object
        3. POST the complete merged object with SyncToken
        
        Never send partial fields — missing fields will be set to null by QBO.
        'sparse: true' allows partial updates but test this carefully in sandbox first.
        """
        client = QBOHttpClient(token, tenant_id)
        
        # Step 1: Fetch current entity + SyncToken
        sync_token, full_invoice = await get_entity_with_sync_token(
            client, "invoice", invoice_id
        )
        
        # Step 2: Merge caller's changes into the full entity
        # Only update fields that are explicitly passed — don't null others
        if "due_date" in data:
            full_invoice["DueDate"] = data["due_date"]
        if "date" in data:
            full_invoice["TxnDate"] = data["date"]
        
        # Always include SyncToken and Id
        full_invoice["SyncToken"] = sync_token
        full_invoice["Id"] = invoice_id
        full_invoice["sparse"] = True  # Safe partial update mode
        
        # Step 3: POST the full updated object
        response = await client.post_entity("invoice", full_invoice)
        raw = response.get("Invoice", {})
        return normalize_qbo_invoice(raw)




