import datetime
from typing import Optional, Any
from fastapi import APIRouter, Depends, Header, Query, Body
from config.settings import get_settings
from utils.errors import AppError
from utils.rate_limiter import check_rate_limit
from utils.logger import correlation_id_var, get_logger
from adapters import get_adapter as _registry_get_adapter

router = APIRouter(prefix="/erp")
logger = get_logger("routes.erp")


# ---------------------------------------------------------------------------
# Internal helpers / FastAPI dependencies
# ---------------------------------------------------------------------------

def get_adapter():
    """
    FastAPI dependency — resolves the active adapter via the registry.
    Maps registry errors to structured HTTP error responses.
    """
    try:
        return _registry_get_adapter()
    except NotImplementedError as exc:
        raise AppError("ADAPTER_NOT_IMPLEMENTED", str(exc), 501)
    except ValueError as exc:
        raise AppError("INVALID_CONFIG", str(exc), 500)


async def auth_headers(
    x_erp_token: Optional[str] = Header(None, alias="X-ERP-Token"),
    x_erp_tenant_id: Optional[str] = Header(None, alias="X-ERP-Tenant-Id"),
):
    """
    Dependency — validates mandatory auth headers and enforces rate limiting.
    Returns (token, tenant_id) tuple consumed by every protected route.
    """
    if not x_erp_token:
        raise AppError("MISSING_HEADER", "X-ERP-Token header is required.", 400)
    if not x_erp_tenant_id:
        raise AppError("MISSING_HEADER", "X-ERP-Tenant-Id header is required.", 400)
    await check_rate_limit(x_erp_tenant_id)
    return x_erp_token, x_erp_tenant_id


def _ok(data: Any, count: int | None = None) -> dict:
    """Build a standard success envelope."""
    payload: dict = {
        "success": True,
        "erp": get_settings().ERP_TYPE,
        "correlationId": correlation_id_var.get(),
    }
    if count is not None:
        payload["count"] = count
    payload["data"] = data
    return payload


# ---------------------------------------------------------------------------
# TAG: health
# ---------------------------------------------------------------------------

@router.get(
    "/health",
    tags=["health"],
    summary="Liveness check",
    response_description="Service status, active ERP type, and version",
)
async def health():
    # TODO: T-00 — verify /health returns 200 with status/erp/version keys
    """
    Liveness probe. No auth headers required.
    Does NOT contact the upstream ERP — returns config values only.
    """
    s = get_settings()
    return {
        "status": "ok",
        "erp": s.ERP_TYPE,
        "version": s.APP_VERSION,
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# TAG: invoices
# ---------------------------------------------------------------------------

@router.get(
    "/invoices",
    tags=["invoices"],
    summary="List sales invoices",
    response_description="Paginated list of NormalizedInvoice objects",
)
async def list_invoices(
    headers=Depends(auth_headers),
    adapter=Depends(get_adapter),
    from_date: Optional[str] = Query(None, alias="from", description="ISO 8601 start date"),
    to_date: Optional[str] = Query(None, alias="to", description="ISO 8601 end date"),
    status: Optional[str] = Query(None, description="draft | authorised | paid | voided"),
):
    # TODO: T-01 — verify GET /erp/invoices returns list with correct schema
    token, tenant_id = headers
    data = await adapter.get_invoices(
        token=token, tenant_id=tenant_id,
        from_date=from_date, to_date=to_date, status=status,
    )
    return _ok(data, count=len(data))


@router.get(
    "/invoices/{invoice_id}",
    tags=["invoices"],
    summary="Get a single invoice by ID",
    response_description="NormalizedInvoice object",
)
async def get_invoice(
    invoice_id: str,
    headers=Depends(auth_headers),
    adapter=Depends(get_adapter),
):
    # TODO: T-02 — verify GET /erp/invoices/{id} returns correct invoice
    token, tenant_id = headers
    data = await adapter.get_invoice(token=token, tenant_id=tenant_id, invoice_id=invoice_id)
    return _ok(data)


@router.post(
    "/invoices",
    tags=["invoices"],
    summary="Create a new sales invoice",
    status_code=201,
    response_description="Created NormalizedInvoice object",
)
async def create_invoice(
    headers=Depends(auth_headers),
    adapter=Depends(get_adapter),
    payload: dict = Body(...),
):
    # TODO: T-03 — verify POST /erp/invoices creates invoice and returns id/status
    token, tenant_id = headers
    data = await adapter.create_invoice(token=token, tenant_id=tenant_id, data=payload)
    return _ok(data)


# ---------------------------------------------------------------------------
# TAG: bills
# ---------------------------------------------------------------------------

@router.get(
    "/bills",
    tags=["bills"],
    summary="List vendor bills",
    response_description="Paginated list of NormalizedBill objects",
)
async def list_bills(
    headers=Depends(auth_headers),
    adapter=Depends(get_adapter),
    from_date: Optional[str] = Query(None, alias="from", description="ISO 8601 start date"),
    to_date: Optional[str] = Query(None, alias="to", description="ISO 8601 end date"),
):
    # TODO: T-04 — verify GET /erp/bills returns list with correct schema
    token, tenant_id = headers
    data = await adapter.get_bills(
        token=token, tenant_id=tenant_id,
        from_date=from_date, to_date=to_date,
    )
    return _ok(data, count=len(data))


@router.get(
    "/bills/{bill_id}",
    tags=["bills"],
    summary="Get a single bill by ID",
    response_description="NormalizedBill object",
)
async def get_bill(
    bill_id: str,
    headers=Depends(auth_headers),
    adapter=Depends(get_adapter),
):
    # TODO: T-05 — verify GET /erp/bills/{id} returns correct bill
    token, tenant_id = headers
    # BaseERPAdapter does not have get_bill — delegate to get_bills and filter
    # Dev 2/3 may add get_bill(); until then surface a clear 501
    raise AppError(
        "ADAPTER_NOT_IMPLEMENTED",
        "GET /erp/bills/{bill_id} requires adapters to implement get_bill(). "
        "Dev 2 (Xero) and Dev 3 (QBO) must add this method.",
        501,
    )


@router.post(
    "/bills",
    tags=["bills"],
    summary="Create a new vendor bill",
    status_code=201,
    response_description="Created NormalizedBill object",
)
async def create_bill(
    headers=Depends(auth_headers),
    adapter=Depends(get_adapter),
    payload: dict = Body(...),
):
    # TODO: T-06 — verify POST /erp/bills creates bill and returns id/status
    token, tenant_id = headers
    data = await adapter.create_bill(token=token, tenant_id=tenant_id, data=payload)
    return _ok(data)


# ---------------------------------------------------------------------------
# TAG: contacts
# ---------------------------------------------------------------------------

@router.get(
    "/contacts",
    tags=["contacts"],
    summary="List contacts filtered by type",
    response_description="List of NormalizedContact objects",
)
async def list_contacts(
    headers=Depends(auth_headers),
    adapter=Depends(get_adapter),
    contact_type: Optional[str] = Query(
        None, alias="type", description="customer | supplier"
    ),
):
    # TODO: T-07 — verify GET /erp/contacts returns list, optionally filtered by type
    token, tenant_id = headers
    data = await adapter.get_contacts(
        token=token, tenant_id=tenant_id, contact_type=contact_type,
    )
    return _ok(data, count=len(data))


@router.get(
    "/contacts/{contact_id}",
    tags=["contacts"],
    summary="Get a single contact by ID",
    response_description="NormalizedContact object",
)
async def get_contact(
    contact_id: str,
    headers=Depends(auth_headers),
    adapter=Depends(get_adapter),
):
    # TODO: T-08 — verify GET /erp/contacts/{id} returns correct contact
    token, tenant_id = headers
    raise AppError(
        "ADAPTER_NOT_IMPLEMENTED",
        "GET /erp/contacts/{contact_id} requires adapters to implement get_contact(). "
        "Dev 2 (Xero) and Dev 3 (QBO) must add this method.",
        501,
    )


@router.post(
    "/contacts",
    tags=["contacts"],
    summary="Create a new contact",
    status_code=201,
    response_description="Created NormalizedContact object",
)
async def create_contact(
    headers=Depends(auth_headers),
    adapter=Depends(get_adapter),
    payload: dict = Body(...),
):
    # TODO: T-09 — verify POST /erp/contacts creates contact and returns id
    token, tenant_id = headers
    data = await adapter.create_contact(token=token, tenant_id=tenant_id, data=payload)
    return _ok(data)


# ---------------------------------------------------------------------------
# TAG: accounts
# ---------------------------------------------------------------------------

@router.get(
    "/accounts",
    tags=["accounts"],
    summary="Fetch the full chart of accounts",
    response_description="List of NormalizedAccount objects",
)
async def list_accounts(
    headers=Depends(auth_headers),
    adapter=Depends(get_adapter),
):
    # TODO: T-10 — verify GET /erp/accounts returns list with code/name/type fields
    token, tenant_id = headers
    data = await adapter.get_accounts(token=token, tenant_id=tenant_id)
    return _ok(data, count=len(data))


# ---------------------------------------------------------------------------
# TAG: payments
# ---------------------------------------------------------------------------

@router.post(
    "/payments",
    tags=["payments"],
    summary="Record a payment against an invoice or bill",
    status_code=201,
    response_description="Recorded payment confirmation",
)
async def record_payment(
    headers=Depends(auth_headers),
    adapter=Depends(get_adapter),
    payload: dict = Body(...),
):
    # TODO: T-11 — verify POST /erp/payments records payment and links to invoice/bill
    token, tenant_id = headers
    data = await adapter.record_payment(token=token, tenant_id=tenant_id, data=payload)
    return _ok(data)
