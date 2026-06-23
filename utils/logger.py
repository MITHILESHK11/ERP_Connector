import logging
import json
import time
import sys
from contextvars import ContextVar

# ContextVar to store the correlation ID for the current request
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

class StructuredJSONFormatter(logging.Formatter):
    """
    Custom formatter that outputs log records as single-line JSON.
    Never prints authorization tokens or credentials.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_var.get()
        }
        
        # Add extra properties if available and safe
        if hasattr(record, "extra_info"):
            # Ensure no tokens are leaked in extra info
            extra = getattr(record, "extra_info")
            if isinstance(extra, dict):
                safe_extra = {k: v for k, v in extra.items() if "token" not in k.lower()}
                log_data.update(safe_extra)
                
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_data)


def get_logger(name: str = "erp_connector") -> logging.Logger:
    """
    Configures and returns a structured logger.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = StructuredJSONFormatter()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
