import datetime
from fastapi import Request
from fastapi.responses import JSONResponse
from utils.logger import correlation_id_var, get_logger
from config.settings import get_settings

logger = get_logger("errors")


class AppError(Exception):
    """
    Unified Application Error representation for general routing and settings errors.
    """
    def __init__(self, error_code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


class ERPConnectorError(Exception):
    """
    Custom exception class for all errors originating from or related to ERP adapters.
    """
    def __init__(self, error_code: str, message: str, http_status: int, erp: str = None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.http_status = http_status
        self.erp = erp or get_settings().ERP_TYPE


def build_error_response(error_code: str, message: str, erp: str, http_status: int) -> JSONResponse:
    """
    Returns a FastAPI JSONResponse matching the unified error schema.
    """
    content = {
        "success": False,
        "error": error_code,
        "message": message,
        "erp": erp,
        "timestamp": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    return JSONResponse(status_code=http_status, content=content)


def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    """
    Exception handler for AppError.
    """
    settings = get_settings()
    logger.error(
        f"AppError [{exc.error_code}]: {exc.message}",
        extra={"extra_info": {
            "error_code": exc.error_code,
            "status_code": exc.status_code,
            "erp": settings.ERP_TYPE,
            "path": request.url.path
        }}
    )
    return build_error_response(exc.error_code, exc.message, settings.ERP_TYPE, exc.status_code)


def handle_erp_connector_error(request: Request, exc: ERPConnectorError) -> JSONResponse:
    """
    FastAPI exception handler for ERPConnectorError.
    Logs only tenant_id and error_code (never authorization tokens).
    """
    tenant_id = request.headers.get("X-ERP-Tenant-Id", "unknown")
    logger.error(
        f"ERPConnectorError [{exc.error_code}]: {exc.message}",
        extra={"extra_info": {
            "error_code": exc.error_code,
            "tenant_id": tenant_id,
            "erp": exc.erp,
            "path": request.url.path
        }}
    )
    return build_error_response(exc.error_code, exc.message, exc.erp, exc.http_status)


def handle_generic_error(request: Request, exc: Exception) -> JSONResponse:
    """
    Fallthrough exception handler for unexpected system exceptions.
    """
    settings = get_settings()
    logger.error(
        f"Unhandled Exception: {str(exc)}",
        exc_info=True,
        extra={"extra_info": {
            "erp": settings.ERP_TYPE,
            "path": request.url.path
        }}
    )
    return build_error_response("INTERNAL_ERROR", "An unexpected internal server error occurred.", settings.ERP_TYPE, 500)


# ---------------------------------------------------------------------------
# Convenience functions for raising specific ERP-related errors
# ---------------------------------------------------------------------------

def raise_token_expired(erp: str):
    """Raises a 401 TOKEN_EXPIRED error."""
    raise ERPConnectorError(
        error_code="TOKEN_EXPIRED",
        message="Access token has expired. Please refresh and retry.",
        http_status=401,
        erp=erp
    )


def raise_not_found(erp: str, resource: str):
    """Raises a 404 NOT_FOUND error."""
    raise ERPConnectorError(
        error_code="NOT_FOUND",
        message=f"Resource '{resource}' not found.",
        http_status=404,
        erp=erp
    )


def raise_invalid_request(erp: str, msg: str):
    """Raises a 400 INVALID_REQUEST error."""
    raise ERPConnectorError(
        error_code="INVALID_REQUEST",
        message=msg,
        http_status=400,
        erp=erp
    )


def raise_erp_unavailable(erp: str):
    """Raises a 502 ERP_UNAVAILABLE error."""
    raise ERPConnectorError(
        error_code="ERP_UNAVAILABLE",
        message="The upstream ERP service is unavailable.",
        http_status=502,
        erp=erp
    )


def raise_erp_timeout(erp: str):
    """Raises a 504 ERP_TIMEOUT error."""
    raise ERPConnectorError(
        error_code="ERP_TIMEOUT",
        message="The request to the upstream ERP service timed out.",
        http_status=504,
        erp=erp
    )


def raise_rate_limit_timeout(erp: str):
    """Raises a 429 RATE_LIMIT_TIMEOUT error."""
    raise ERPConnectorError(
        error_code="RATE_LIMIT_TIMEOUT",
        message="The request to the ERP service timed out due to rate limiting.",
        http_status=429,
        erp=erp
    )
