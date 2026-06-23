from fastapi import Request
from fastapi.responses import JSONResponse
from datetime import datetime
from utils.logger import correlation_id_var, get_logger
from config.settings import get_settings

logger = get_logger("errors")

class AppError(Exception):
    """
    Unified Application Error representation.
    """
    def __init__(self, error_code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    """
    Exception handler for known/raised AppError.
    Formats the response to match the ErrorResponse schema contract.
    """
    settings = get_settings()
    correlation_id = correlation_id_var.get()
    
    logger.error(
        f"AppError [{exc.error_code}]: {exc.message}",
        extra={"extra_info": {
            "error_code": exc.error_code,
            "status_code": exc.status_code,
            "erp": settings.ERP_TYPE,
            "path": request.url.path
        }}
    )
    
    content = {
        "success": False,
        "error": exc.error_code,
        "message": exc.message,
        "erp": settings.ERP_TYPE,
        "correlationId": correlation_id,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    return JSONResponse(status_code=exc.status_code, content=content)


def handle_generic_error(request: Request, exc: Exception) -> JSONResponse:
    """
    Fallthrough exception handler for any unexpected system errors.
    """
    settings = get_settings()
    correlation_id = correlation_id_var.get()
    
    logger.error(
        f"Unhandled Exception: {str(exc)}",
        exc_info=True,
        extra={"extra_info": {
            "erp": settings.ERP_TYPE,
            "path": request.url.path
        }}
    )
    
    content = {
        "success": False,
        "error": "INTERNAL_ERROR",
        "message": "An unexpected internal server error occurred.",
        "erp": settings.ERP_TYPE,
        "correlationId": correlation_id,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    return JSONResponse(status_code=500, content=content)
