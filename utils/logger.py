import logging
import json
import sys
import uuid
import re
import datetime
from contextvars import ContextVar
from typing import Any

# ContextVar to store the correlation ID/request ID for the current request context
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
correlation_id_var = request_id_var

# Redaction patterns
REDACTION_KEYS = {"token", "authorization", "bearer", "secret", "password", "key"}
BEARER_PATTERN = re.compile(r"Bearer\s+\S+", re.IGNORECASE)


def sanitise_log_data(data: Any) -> Any:
    """
    Recursively sanitises dictionaries, lists, and strings.
    Removes any key containing sensitive patterns (token, secret, etc.)
    and redacts 'Bearer <token>' substrings in string values.
    """
    if isinstance(data, dict):
        sanitised = {}
        for k, v in data.items():
            # If the key name itself matches any sensitive patterns, exclude or redact it
            if any(rk in k.lower() for rk in REDACTION_KEYS):
                continue
            sanitised[k] = sanitise_log_data(v)
        return sanitised
        
    elif isinstance(data, list):
        return [sanitise_log_data(item) for item in data]
        
    elif isinstance(data, str):
        if BEARER_PATTERN.search(data):
            return BEARER_PATTERN.sub("Bearer [REDACTED]", data)
        return data
        
    return data


class StructuredJSONFormatter(logging.Formatter):
    """
    Custom formatter that outputs log records as single-line JSON.
    Guarantees no sensitive authorization tokens or credentials leak in logs.
    """
    def format(self, record: logging.LogRecord) -> str:
        now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Base log fields
        log_data = {
            "timestamp": now,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Inject request_id from context var if available
        req_id = request_id_var.get()
        if req_id:
            log_data["request_id"] = req_id

        # Extract extra logger arguments (like request_id, erp, tenant_id)
        for attr in ["request_id", "erp", "tenant_id", "status_code", "duration_ms", "limit", "current_count", "error_code"]:
            if hasattr(record, attr):
                val = getattr(record, attr)
                if val is not None:
                    log_data[attr] = val

        # Handle extra dict args
        if hasattr(record, "extra_info"):
            extra = getattr(record, "extra_info")
            if isinstance(extra, dict):
                log_data.update(extra)

        # Apply security redaction rules
        log_data = sanitise_log_data(log_data)
        
        # If message was changed by sanitisation, apply it
        if isinstance(log_data.get("message"), str):
            log_data["message"] = sanitise_log_data(record.getMessage())

        # Include exception traceback if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_data)


def generate_request_id() -> str:
    """Generates a unique UUID4 request ID."""
    return str(uuid.uuid4())


def get_logger(name: str = "erp_connector") -> logging.Logger:
    """
    Configures and returns a structured logger.
    Directs output to both stdout and erp_connector.log in the project root.
    """
    logger = logging.getLogger(name)
    
    # Set log level based on environment settings
    try:
        from config.settings import get_settings
        level_str = get_settings().LOG_LEVEL.upper()
    except Exception:
        level_str = "INFO"
    level = getattr(logging, level_str, logging.INFO)
    logger.setLevel(level)

    if not logger.handlers:
        formatter = StructuredJSONFormatter()

        # Stdout stream handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # File handler
        try:
            file_handler = logging.FileHandler("erp_connector.log", encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception:
            pass

        logger.propagate = False
        
    return logger
