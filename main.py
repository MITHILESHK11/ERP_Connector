import uuid
import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from config.settings import get_settings
from utils.errors import (
    AppError,
    handle_app_error,
    handle_generic_error,
    ERPConnectorError,
    handle_erp_connector_error,
    handle_validation_error
)
from fastapi.exceptions import RequestValidationError
from utils.logger import request_id_var, get_logger, generate_request_id

logger = get_logger("erp_connector")

# ---------------------------------------------------------------------------
# Load & validate config at import time — fails fast on bad ERP_TYPE
# ---------------------------------------------------------------------------
settings = get_settings()
logger.info(f"ERP Connector starting — ERP_TYPE={settings.ERP_TYPE.upper()}")


# ---------------------------------------------------------------------------
# Lifespan (replaces deprecated @app.on_event)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ERP Connector microservice is ready.")
    yield
    logger.info("ERP Connector microservice is shutting down.")


# ---------------------------------------------------------------------------
# Correlation-ID middleware
# ---------------------------------------------------------------------------
class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware that generates/extracts a request-scoped correlation ID,
    stores it in a contextvar, and logs the request-response lifecycle events.
    """
    async def dispatch(self, request: Request, call_next):
        import time
        request_id = request.headers.get("X-Correlation-ID") or generate_request_id()
        tenant_id = request.headers.get("X-ERP-Tenant-Id", "unknown")
        
        token = request_id_var.set(request_id)
        
        # Log request received: method, path, tenant_id, request_id (never token)
        logger.info(
            f"Request received: {request.method} {request.url.path}",
            extra={"tenant_id": tenant_id, "request_id": request_id}
        )
        
        start_time = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            
            # Log response returned: status_code, duration_ms
            logger.info(
                f"Response returned: {response.status_code}",
                extra={"status_code": response.status_code, "duration_ms": duration_ms}
            )
            
            response.headers["X-Correlation-ID"] = request_id
            return response
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(
                f"Request failed: {str(exc)}",
                exc_info=True,
                extra={"duration_ms": duration_ms}
            )
            raise
        finally:
            request_id_var.reset(token)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="ERP Connector",
    version=settings.APP_VERSION,
    description="Stateless REST wrapper for Xero and QuickBooks Online",
    docs_url="/erp/docs",
    redoc_url="/erp/redoc",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.CORS_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["X-ERP-Token", "X-ERP-Tenant-Id", "Content-Type"],
)

# Correlation-ID
app.add_middleware(CorrelationIDMiddleware)

# Exception handlers
app.add_exception_handler(AppError, handle_app_error)
app.add_exception_handler(ERPConnectorError, handle_erp_connector_error)
app.add_exception_handler(RequestValidationError, handle_validation_error)
app.add_exception_handler(Exception, handle_generic_error)

# Routes
from routes import erp  # noqa: E402 — imported after app creation intentionally
app.include_router(erp.router)
