from typing import Optional, Tuple
from fastapi import Header
from config.settings import get_settings
from utils.errors import raise_token_expired
from utils.rate_limiter import check_rate_limit

async def require_erp_auth(
    x_erp_token: Optional[str] = Header(None, alias="X-ERP-Token"),
    x_erp_tenant_id: Optional[str] = Header(None, alias="X-ERP-Tenant-Id"),
) -> Tuple[str, str]:
    """
    FastAPI dependency to extract and validate X-ERP-Token and X-ERP-Tenant-Id headers.
    Strips the 'Bearer ' prefix and enforces the rate limiter.
    
    Returns:
        Tuple[str, str]: A tuple of (clean_token, tenant_id).
    """
    erp = get_settings().ERP_TYPE
    
    if not x_erp_token or not x_erp_token.strip():
        raise_token_expired(erp)
        
    if not x_erp_tenant_id or not x_erp_tenant_id.strip():
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
