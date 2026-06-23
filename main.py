import uuid
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from config.settings import get_settings
from routes import erp
from utils.errors import AppError, handle_app_error, handle_generic_error
from utils.logger import correlation_id_var, get_logger

# Initialize logger
logger = get_logger("main")

# Load configuration settings
try:
    settings = get_settings()
    logger.info(f"Loaded configuration. Active ERP Type: {settings.ERP_TYPE.upper()}")
except Exception as e:
    logger.error(f"Failed to load configuration: {str(e)}")
    raise e


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware that extracts or generates a unique correlation ID for every request,
    stores it in ContextVars for structured logging, and appends it to response headers.
    """
    async def dispatch(self, request: Request, call_next):
        # Check header
        corr_id = request.headers.get("X-Correlation-ID")
        if not corr_id:
            corr_id = f"req-{uuid.uuid4()}"
            
        # Store in ContextVar
        token = correlation_id_var.set(corr_id)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = corr_id
            return response
        finally:
            correlation_id_var.reset(token)


# Create FastAPI App Instance
app = FastAPI(
    title="ERP Connector Microservice",
    description="Stateless REST wrapper interface around Xero and QuickBooks Online.",
    version=settings.APP_VERSION,
    docs_url="/erp/docs",
    redoc_url=None
)

# Apply Middlewares
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.CORS_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception Handlers
app.add_exception_handler(AppError, handle_app_error)
app.add_exception_handler(Exception, handle_generic_error)

# Include Router
app.include_router(erp.router)


@app.on_event("startup")
async def startup_event():
    logger.info("ERP Connector microservice has successfully started.")
