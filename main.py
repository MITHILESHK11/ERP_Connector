import uuid
import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from config.settings import get_settings
from utils.errors import AppError, handle_app_error, handle_generic_error
from utils.logger import correlation_id_var, get_logger

logger = get_logger("main")

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
    Injects a unique X-Correlation-ID into every request context and response.
    Uses the caller-supplied value if present, otherwise generates one.
    """
    async def dispatch(self, request: Request, call_next):
        corr_id = request.headers.get("X-Correlation-ID") or f"req-{uuid.uuid4()}"
        token = correlation_id_var.set(corr_id)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = corr_id
            return response
        finally:
            correlation_id_var.reset(token)


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
app.add_exception_handler(Exception, handle_generic_error)

# Routes
from routes import erp  # noqa: E402 — imported after app creation intentionally
app.include_router(erp.router)
