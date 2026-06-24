import datetime
import httpx
from contextlib import asynccontextmanager
from typing import Optional, Any
from fastapi import APIRouter, Depends, Header, Query, Body
from config.settings import get_settings
from utils.errors import (
    AppError,
    raise_token_expired,
    raise_not_found,
    raise_invalid_request,
    raise_erp_unavailable,
    raise_erp_timeout
)
from utils.rate_limiter import check_rate_limit
from utils.logger import correlation_id_var, get_logger
from adapters import get_adapter as _registry_get_adapter
from models.schemas import CreateInvoiceRequest, CreateBillRequest, CreateContactRequest, RecordPaymentRequest
from middleware.auth import require_erp_auth

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


@asynccontextmanager
async def handle_adapter_errors(erp: str, tenant_id: str, endpoint: str):
    """
    Context manager to wrap adapter calls, log outbound calls,
    and map HTTP exceptions to unified error classes.
    """
    logger.info(
        f"ERP call made: {erp.upper()} {endpoint}",
        extra={"erp": erp, "endpoint": endpoint, "tenant_id": tenant_id}
    )
    try:
        yield
    except httpx.TimeoutException:
        raise_erp_timeout(erp)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code == 401:
            raise_token_expired(erp)
        elif status_code == 404:
            raise_not_found(erp, endpoint)
        elif status_code == 400:
            raise_invalid_request(erp, str(exc))
        elif status_code == 429:
            logger.warning(f"ERP returned 429 rate limit error for ERP {erp}")
            raise_erp_unavailable(erp)
        elif status_code in (500, 503):
            raise_erp_unavailable(erp)
        else:
            raise


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
    """
    Liveness probe. No auth headers required.
    Does NOT contact the upstream ERP — returns config values only.
    """
    s = get_settings()
    return {
        "status": "ok",
        "erp": s.ERP_TYPE,
        "version": s.APP_VERSION,
        "timestamp": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
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
    headers=Depends(require_erp_auth),
    adapter=Depends(get_adapter),
    from_date: Optional[str] = Query(None, alias="from", description="ISO 8601 start date"),
    to_date: Optional[str] = Query(None, alias="to", description="ISO 8601 end date"),
    status: Optional[str] = Query(None, description="draft | authorised | paid | voided"),
):
    token, tenant_id = headers
    erp = get_settings().ERP_TYPE
    async with handle_adapter_errors(erp, tenant_id, "GET /invoices"):
        data = await adapter.get_invoices(
            token=token, tenant_id=tenant_id,
            from_date=from_date, to_date=to_date, status=status
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
    headers=Depends(require_erp_auth),
    adapter=Depends(get_adapter),
):
    token, tenant_id = headers
    erp = get_settings().ERP_TYPE
    async with handle_adapter_errors(erp, tenant_id, f"GET /invoices/{invoice_id}"):
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
    headers=Depends(require_erp_auth),
    adapter=Depends(get_adapter),
    payload: CreateInvoiceRequest = Body(...),
):
    token, tenant_id = headers
    erp = get_settings().ERP_TYPE
    async with handle_adapter_errors(erp, tenant_id, "POST /invoices"):
        data = await adapter.create_invoice(token=token, tenant_id=tenant_id, data=payload.model_dump())
    return _ok(data)


@router.put(
    "/invoices/{invoice_id}",
    tags=["invoices"],
    summary="Update an existing invoice",
    response_description="Updated NormalizedInvoice object",
)
async def update_invoice(
    invoice_id: str,
    headers=Depends(require_erp_auth),
    adapter=Depends(get_adapter),
    payload: dict = Body(...),
):
    token, tenant_id = headers
    erp = get_settings().ERP_TYPE
    async with handle_adapter_errors(erp, tenant_id, f"PUT /invoices/{invoice_id}"):
        data = await adapter.update_invoice(
            token=token, tenant_id=tenant_id, invoice_id=invoice_id, data=payload
        )
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
    headers=Depends(require_erp_auth),
    adapter=Depends(get_adapter),
    from_date: Optional[str] = Query(None, alias="from", description="ISO 8601 start date"),
    to_date: Optional[str] = Query(None, alias="to", description="ISO 8601 end date"),
):
    token, tenant_id = headers
    erp = get_settings().ERP_TYPE
    async with handle_adapter_errors(erp, tenant_id, "GET /bills"):
        data = await adapter.get_bills(
            token=token, tenant_id=tenant_id,
            from_date=from_date, to_date=to_date
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
    headers=Depends(require_erp_auth),
    adapter=Depends(get_adapter),
):
    token, tenant_id = headers
    erp = get_settings().ERP_TYPE
    async with handle_adapter_errors(erp, tenant_id, f"GET /bills/{bill_id}"):
        data = await adapter.get_bill(token=token, tenant_id=tenant_id, bill_id=bill_id)
    return _ok(data)


@router.post(
    "/bills",
    tags=["bills"],
    summary="Create a new vendor bill",
    status_code=201,
    response_description="Created NormalizedBill object",
)
async def create_bill(
    headers=Depends(require_erp_auth),
    adapter=Depends(get_adapter),
    payload: CreateBillRequest = Body(...),
):
    token, tenant_id = headers
    erp = get_settings().ERP_TYPE
    async with handle_adapter_errors(erp, tenant_id, "POST /bills"):
        data = await adapter.create_bill(token=token, tenant_id=tenant_id, data=payload.model_dump())
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
    headers=Depends(require_erp_auth),
    adapter=Depends(get_adapter),
    contact_type: Optional[str] = Query(
        None, alias="type", description="customer | supplier"
    ),
):
    token, tenant_id = headers
    erp = get_settings().ERP_TYPE
    async with handle_adapter_errors(erp, tenant_id, "GET /contacts"):
        data = await adapter.get_contacts(
            token=token, tenant_id=tenant_id, contact_type=contact_type
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
    headers=Depends(require_erp_auth),
    adapter=Depends(get_adapter),
):
    token, tenant_id = headers
    erp = get_settings().ERP_TYPE
    async with handle_adapter_errors(erp, tenant_id, f"GET /contacts/{contact_id}"):
        data = await adapter.get_contact(token=token, tenant_id=tenant_id, contact_id=contact_id)
    return _ok(data)


@router.post(
    "/contacts",
    tags=["contacts"],
    summary="Create a new contact",
    status_code=201,
    response_description="Created NormalizedContact object",
)
async def create_contact(
    headers=Depends(require_erp_auth),
    adapter=Depends(get_adapter),
    payload: CreateContactRequest = Body(...),
):
    token, tenant_id = headers
    erp = get_settings().ERP_TYPE
    async with handle_adapter_errors(erp, tenant_id, "POST /contacts"):
        data = await adapter.create_contact(token=token, tenant_id=tenant_id, data=payload.model_dump())
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
    headers=Depends(require_erp_auth),
    adapter=Depends(get_adapter),
):
    token, tenant_id = headers
    erp = get_settings().ERP_TYPE
    async with handle_adapter_errors(erp, tenant_id, "GET /accounts"):
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
    headers=Depends(require_erp_auth),
    adapter=Depends(get_adapter),
    payload: RecordPaymentRequest = Body(...),
):
    token, tenant_id = headers
    erp = get_settings().ERP_TYPE
    async with handle_adapter_errors(erp, tenant_id, "POST /payments"):
        data = await adapter.record_payment(token=token, tenant_id=tenant_id, data=payload.model_dump())
    return _ok(data)
