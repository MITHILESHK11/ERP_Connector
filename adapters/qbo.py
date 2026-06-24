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


    async def get_bills(self, token, tenant_id, from_date=None, to_date=None):
        raise NotImplementedError("Coming in Build Prompt 3")

    async def get_bill(self, token, tenant_id, bill_id):
        raise NotImplementedError("Coming in Build Prompt 3")

    async def get_contacts(self, token, tenant_id, contact_type=None):
        raise NotImplementedError("Coming in Build Prompt 3")

    async def get_contact(self, token, tenant_id, contact_id):
        raise NotImplementedError("Coming in Build Prompt 3")

    async def get_accounts(self, token, tenant_id):
        raise NotImplementedError("Coming in Build Prompt 3")

    async def create_invoice(self, token, tenant_id, data):
        raise NotImplementedError("Coming in Build Prompt 4")

    async def create_bill(self, token, tenant_id, data):
        raise NotImplementedError("Coming in Build Prompt 4")

    async def create_contact(self, token, tenant_id, data):
        raise NotImplementedError("Coming in Build Prompt 4")

    async def record_payment(self, token, tenant_id, data):
        raise NotImplementedError("Coming in Build Prompt 5")

