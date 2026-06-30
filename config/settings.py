import os
from functools import lru_cache
from dotenv import load_dotenv

# Load variables from .env file into environment
load_dotenv()

class Settings:
    """
    Configuration settings class for the ERP Connector microservice.
    Reads and validates environment configuration parameters on initialization.
    """
    def __init__(self):
        # Normalize and validate ERP_TYPE
        erp_type_raw = os.getenv("ERP_TYPE", "").strip().lower()
        if erp_type_raw == "qbo":
            erp_type_raw = "quickbooks"
            
        if erp_type_raw not in ("xero", "quickbooks"):
            raise ValueError(
                f"ERP_TYPE must be set to 'xero' or 'quickbooks' (or 'qbo') in environment config. Got: {os.getenv('ERP_TYPE')}"
            )
        
        self.ERP_TYPE: str = erp_type_raw
        
        # Load and parse PORT (defaults to 8000)
        port_str = os.getenv("PORT", "8000")
        try:
            self.PORT: int = int(port_str)
        except ValueError:
            self.PORT: int = 8000
            
        # Load other configuration fields with defaults
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
        self.CORS_ORIGIN: str = os.getenv("CORS_ORIGIN", "*")
        self.APP_VERSION: str = os.getenv("APP_VERSION", "0.1.0")


@lru_cache()
def get_settings() -> Settings:
    """
    Returns a cached singleton instance of the Settings class.
    Ensures environment validation runs once at startup.
    """
    return Settings()
