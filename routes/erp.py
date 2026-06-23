from fastapi import APIRouter, Depends, Header, Query, Request
from typing import Optional
from config.settings import get_settings
from utils.errors import AppError
from utils.rate_limiter import check_rate_limit
from utils.logger import correlation_id_var, get_logger

router = APIRouter(prefix="/erp")
logger = get_logger("routes.erp")

# Dynamic adapter importer/registry to avoid import errors before Dev 2/3 implement them
def get_adapter():
    settings = get_settings()
    if settings.ERP_TYPE == "xero":
        try:
            from adapters.xero import XeroAdapter
            return XeroAdapter()
        except (ImportError, AttributeError, TypeError):
            raise AppError(
                "ADAPTER_NOT_IMPLEMENTED",
                "Xero adapter has not been implemented yet.",
                501
            )
    elif settings.ERP_TYPE == "quickbooks":
        try:
            from adapters.qbo import QBOAdapter
            return QBOAdapter()
        except (ImportError, AttributeError, TypeError):
            raise AppError(
                "ADAPTER_NOT_IMPLEMENTED",
                "QuickBooks Online adapter has not been implemented yet.",
                501
            )
    else:
        raise AppError("INVALID_CONFIG", f"Unsupported ERP_TYPE: {settings.ERP_TYPE}", 500)


async def get_auth_headers(
    x_erp_token: Optional[str] = Header(None, alias="X-ERP-Token"),
    x_erp_tenant_id: Optional[str] = Header(None, alias="X-ERP-Tenant-Id")
):
    """
    Dependency to validate and retrieve mandatory custom request headers.
    """
    if not x_erp_token:
        raise AppError("MISSING_HEADER", "X-ERP-Token header is required.", 400)
    if not x_erp_tenant_id:
        raise AppError("MISSING_HEADER", "X-ERP-Tenant-Id header is required.", 400)
    
    # Enforce token-bucket rate limiting centrally for the tenant
    await check_rate_limit(x_erp_tenant_id)
    
    return x_erp_token, x_erp_tenant_id


# ==========================================
# 6.2 Health Check Endpoints
# ==========================================

@router.get("/health")
async def health():
    """
    Liveness check. Returns the active ERP type, microservice version, and timestamp.
    Does not require headers or contact the upstream ERP.
    """
    settings = get_settings()
    import datetime
    return {
        "status": "ok",
        "erp": settings.ERP_TYPE,
        "version": settings.APP_VERSION,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    }


# ==========================================
# 6.3 Pull Endpoints (Read operations)
# ==========================================

@router.get("/invoices")
async def get_invoices(
    headers = Depends(get_auth_headers),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    status: Optional[str] = Query(None),
    adapter = Depends(get_adapter)
):
    token, tenant_id = headers
    data = await adapter.get_invoices(
        token=token,
        tenant_id=tenant_id,
        from_date=from_date,
        to_date=to_date,
        status=status
    )
    return {
        "success": True,
        "erp": get_settings().ERP_TYPE,
        "correlationId": correlation_id_var.get(),
        "count": len(data),
        "data": data
    }


@router.get("/invoices/{invoice_id}")
async def get_invoice(
    invoice_id: str,
    headers = Depends(get_auth_headers),
    adapter = Depends(get_adapter)
):
    token, tenant_id = headers
    data = await adapter.get_invoice(token=token, tenant_id=tenant_id, invoice_id=invoice_id)
    return {
        "success": True,
        "erp": get_settings().ERP_TYPE,
        "correlationId": correlation_id_var.get(),
        "data": data
    }


@router.get("/bills")
async def get_bills(
    headers = Depends(get_auth_headers),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    adapter = Depends(get_adapter)
):
    token, tenant_id = headers
    data = await adapter.get_bills(
        token=token,
        tenant_id=tenant_id,
        from_date=from_date,
        to_date=to_date
    )
    return {
        "success": True,
        "erp": get_settings().ERP_TYPE,
        "correlationId": correlation_id_var.get(),
        "count": len(data),
        "data": data
    }


@router.get("/contacts")
async def get_contacts(
    headers = Depends(get_auth_headers),
    contact_type: Optional[str] = Query(None, alias="type"),
    adapter = Depends(get_adapter)
):
    token, tenant_id = headers
    data = await adapter.get_contacts(
        token=token,
        tenant_id=tenant_id,
        contact_type=contact_type
    )
    return {
        "success": True,
        "erp": get_settings().ERP_TYPE,
        "correlationId": correlation_id_var.get(),
        "count": len(data),
        "data": data
    }


@router.get("/accounts")
async def get_accounts(
    headers = Depends(get_auth_headers),
    adapter = Depends(get_adapter)
):
    token, tenant_id = headers
    data = await adapter.get_accounts(token=token, tenant_id=tenant_id)
    return {
        "success": True,
        "erp": get_settings().ERP_TYPE,
        "correlationId": correlation_id_var.get(),
        "count": len(data),
        "data": data
    }


# ==========================================
# 6.4 Push Endpoints (Write operations)
# ==========================================

@router.post("/invoices")
async def create_invoice(
    payload: dict,
    headers = Depends(get_auth_headers),
    adapter = Depends(get_adapter)
):
    token, tenant_id = headers
    data = await adapter.create_invoice(token=token, tenant_id=tenant_id, data=payload)
    return {
        "success": True,
        "erp": get_settings().ERP_TYPE,
        "correlationId": correlation_id_var.get(),
        "data": data
    }


@router.post("/bills")
async def create_bill(
    payload: dict,
    headers = Depends(get_auth_headers),
    adapter = Depends(get_adapter)
):
    token, tenant_id = headers
    data = await adapter.create_bill(token=token, tenant_id=tenant_id, data=payload)
    return {
        "success": True,
        "erp": get_settings().ERP_TYPE,
        "correlationId": correlation_id_var.get(),
        "data": data
    }


@router.post("/contacts")
async def create_contact(
    payload: dict,
    headers = Depends(get_auth_headers),
    adapter = Depends(get_adapter)
):
    token, tenant_id = headers
    data = await adapter.create_contact(token=token, tenant_id=tenant_id, data=payload)
    return {
        "success": True,
        "erp": get_settings().ERP_TYPE,
        "correlationId": correlation_id_var.get(),
        "data": data
    }


@router.post("/payments")
async def record_payment(
    payload: dict,
    headers = Depends(get_auth_headers),
    adapter = Depends(get_adapter)
):
    token, tenant_id = headers
    data = await adapter.record_payment(token=token, tenant_id=tenant_id, data=payload)
    return {
        "success": True,
        "erp": get_settings().ERP_TYPE,
        "correlationId": correlation_id_var.get(),
        "data": data
    }
