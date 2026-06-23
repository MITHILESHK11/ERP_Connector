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
        # Validate ERP_TYPE is set and correct
        erp_type = os.getenv("ERP_TYPE")
        if not erp_type or erp_type.strip().lower() not in ("xero", "quickbooks"):
            raise ValueError(
                f"ERP_TYPE must be set to 'xero' or 'quickbooks' in environment config. Got: {erp_type}"
            )
        
        self.ERP_TYPE: str = erp_type.strip().lower()
        
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
