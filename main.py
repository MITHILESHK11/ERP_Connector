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
    import asyncio
    from token_manager import background_token_refresh_loop

    logger.info("ERP Connector microservice is ready.")
    refresh_task = asyncio.create_task(background_token_refresh_loop())
    try:
        yield
    finally:
        refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass
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
import yaml

app = FastAPI(
    title="ERP Connector",
    version=settings.APP_VERSION,
    description="Unified REST wrapper for Xero and QuickBooks Online",
    docs_url="/erp/docs",
    redoc_url="/erp/redoc",
    lifespan=lifespan,
)

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    try:
        with open("openapi/openapi.yaml", "r") as f:
            openapi_schema = yaml.safe_load(f)
        app.openapi_schema = openapi_schema
        return app.openapi_schema
    except Exception as exc:
        logger.error(f"Failed to load custom openapi.yaml: {exc}")
        return None

app.openapi = custom_openapi

# CORS
# NOTE: browsers reject credentialed requests (allow_credentials=True) when
# the origin is the wildcard "*" — the two are mutually exclusive per the
# CORS spec. Only allow credentials when a specific origin is configured.
_cors_is_wildcard = settings.CORS_ORIGIN.strip() == "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.CORS_ORIGIN],
    allow_credentials=not _cors_is_wildcard,
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
from routes import erp, auth  # noqa: E402 — imported after app creation intentionally
app.include_router(auth.router)
app.include_router(erp.router)

