from typing import Optional, Tuple
from fastapi import Header
from config.settings import get_settings
from utils.errors import raise_token_expired
from utils.rate_limiter import check_rate_limit


def _get_credentials_from_manager(erp_type: str) -> Tuple[Optional[str], Optional[str]]:
    """Try to get active token and tenant_id from token_manager for the configured ERP."""
    try:
        from token_manager import get_valid_token, get_tenant_id
        token = get_valid_token(erp_type)
        tenant_id = get_tenant_id(erp_type)
        return token, tenant_id
    except Exception:
        return None, None


async def require_erp_auth(
    x_erp_token: Optional[str] = Header(None, alias="X-ERP-Token"),
    x_erp_tenant_id: Optional[str] = Header(None, alias="X-ERP-Tenant-Id"),
) -> Tuple[str, str]:
    """
    FastAPI dependency to extract and validate X-ERP-Token and X-ERP-Tenant-Id headers.
    If headers are omitted, automatically retrieves active credentials from
    token_manager for the currently configured ERP.
    Strips the 'Bearer ' prefix and enforces the rate limiter.

    Returns:
        Tuple[str, str]: A tuple of (clean_token, tenant_id).
    """
    erp = get_settings().ERP_TYPE

    auto_token, auto_tenant_id = _get_credentials_from_manager(erp)

    if not x_erp_token or not x_erp_token.strip():
        if auto_token:
            x_erp_token = auto_token
        else:
            raise_token_expired(erp)

    if not x_erp_tenant_id or not x_erp_tenant_id.strip():
        if auto_tenant_id:
            x_erp_tenant_id = auto_tenant_id
        else:
            raise_token_expired(erp)

    token = x_erp_token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    if not token:
        raise_token_expired(erp)

    tenant_id = x_erp_tenant_id.strip()

    # Enforce central rate limit per tenant
    await check_rate_limit(tenant_id)

    return token, tenant_id
