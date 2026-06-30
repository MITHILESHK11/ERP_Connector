import json
import os
import logging
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger("erp_connector.token_manager")

TOKEN_FILE = ".erp_tokens.json"
XERO_LEGACY_FILE = ".xero_tokens.json"

# ERP Refresh endpoint configurations
ERP_CONFIGS = {
    "xero": {
        "refresh_url": "https://identity.xero.com/connect/token",
        "default_client_id": "B620A8F61D664F79947B8BB13B3A14A6",
        "default_client_secret": "rJGQ6KrfgtTA9I2QB5X8AfS3vQ0mZUKgzB462k4t5GhkPmUk",
        "default_tenant_id": "7f7fbedf-e62d-4492-ac88-ee8f9e0bbfab",
        "expiry_minutes": 25
    },
    "quickbooks": {
        "refresh_url": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        "default_client_id": "",
        "default_client_secret": "",
        "default_tenant_id": "9341457318163676",
        "expiry_minutes": 50
    }
}


def _get_active_erp_type(erp_type: Optional[str] = None) -> str:
    """Resolve active ERP type parameter, falling back to app settings."""
    if erp_type:
        return erp_type.lower()
    try:
        from config.settings import get_settings
        return get_settings().ERP_TYPE.lower()
    except Exception:
        return "xero"


def load_all_tokens() -> Dict[str, Any]:
    """Load the full tokens registry dictionary from local storage."""
    data = {}
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read {TOKEN_FILE}: {e}")

    # Backward compatibility migration for legacy .xero_tokens.json
    if "xero" not in data and os.path.exists(XERO_LEGACY_FILE):
        try:
            with open(XERO_LEGACY_FILE, "r") as f:
                legacy_xero = json.load(f)
                data["xero"] = {
                    "access_token": legacy_xero.get("access_token"),
                    "refresh_token": legacy_xero.get("refresh_token"),
                    "saved_at": legacy_xero.get("saved_at", datetime.now().isoformat()),
                    "client_id": ERP_CONFIGS["xero"]["default_client_id"],
                    "client_secret": ERP_CONFIGS["xero"]["default_client_secret"],
                    "tenant_id": ERP_CONFIGS["xero"]["default_tenant_id"]
                }
        except Exception as e:
            logger.error(f"Failed to load legacy Xero tokens: {e}")

    return data


def save_tokens(
    erp_type: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    tenant_id: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None
):
    """Save token credentials for a specific ERP system."""
    erp_key = erp_type.lower()
    all_tokens = load_all_tokens()

    existing = all_tokens.get(erp_key, {})
    all_tokens[erp_key] = {
        "access_token": access_token,
        "refresh_token": refresh_token or existing.get("refresh_token", ""),
        "saved_at": datetime.now().isoformat(),
        "tenant_id": tenant_id or existing.get("tenant_id") or ERP_CONFIGS.get(erp_key, {}).get("default_tenant_id"),
        "client_id": client_id or existing.get("client_id") or ERP_CONFIGS.get(erp_key, {}).get("default_client_id"),
        "client_secret": client_secret or existing.get("client_secret") or ERP_CONFIGS.get(erp_key, {}).get("default_client_secret")
    }

    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump(all_tokens, f, indent=2)
        logger.info(f"Tokens saved successfully for ERP: {erp_key}")

        # Keep legacy file updated for Xero for backward compatibility
        if erp_key == "xero":
            with open(XERO_LEGACY_FILE, "w") as f:
                json.dump(all_tokens[erp_key], f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save tokens to disk: {e}")


def is_token_expired(saved_at: str, expiry_minutes: int = 25) -> bool:
    """Check if token is older than the allowed threshold."""
    if not saved_at:
        return True
    try:
        saved_time = datetime.fromisoformat(saved_at)
        return datetime.now() > saved_time + timedelta(minutes=expiry_minutes)
    except Exception:
        return True


def refresh_access_token(erp_type: str, refresh_token: str, client_id: str, client_secret: str) -> Optional[str]:
    """Automated token refresh for any supported ERP system."""
    erp_key = erp_type.lower()
    config = ERP_CONFIGS.get(erp_key)
    if not config:
        logger.error(f"Unsupported ERP type for auto-refresh: {erp_key}")
        return None

    logger.info(f"🔄 Auto-refreshing expired OAuth token for ERP: {erp_key}...")

    try:
        if erp_key == "xero":
            response = httpx.post(
                config["refresh_url"],
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=15.0
            )
            response.raise_for_status()
            result = response.json()
            new_access = result["access_token"]
            new_refresh = result.get("refresh_token", refresh_token)
            save_tokens(erp_key, new_access, new_refresh)
            return new_access

        elif erp_key == "quickbooks":
            response = httpx.post(
                config["refresh_url"],
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                auth=(client_id, client_secret) if (client_id and client_secret) else None,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret
                },
                timeout=15.0
            )
            response.raise_for_status()
            result = response.json()
            new_access = result["access_token"]
            new_refresh = result.get("refresh_token", refresh_token)
            save_tokens(erp_key, new_access, new_refresh)
            return new_access
    except Exception as e:
        logger.error(f"Failed to auto-refresh token for {erp_key}: {e}")
        return None


def get_valid_token(erp_type: Optional[str] = None) -> Optional[str]:
    """
    Universal method to retrieve a valid access token for any ERP system.
    Auto-refreshes expired tokens when refresh tokens are present.
    """
    target_erp = _get_active_erp_type(erp_type)
    all_tokens = load_all_tokens()
    erp_data = all_tokens.get(target_erp, {})

    access_token = erp_data.get("access_token")
    saved_at = erp_data.get("saved_at")
    refresh_token = erp_data.get("refresh_token")
    client_id = erp_data.get("client_id")
    client_secret = erp_data.get("client_secret")

    # Fallback to .env environment variables if token file is empty
    if not access_token:
        if target_erp == "xero":
            access_token = os.getenv("XERO_TOKEN")
        elif target_erp == "quickbooks":
            access_token = os.getenv("QBO_TOKEN")

    if not access_token:
        logger.warning(f"No token credentials found for ERP: {target_erp}")
        return None

    expiry_mins = ERP_CONFIGS.get(target_erp, {}).get("expiry_minutes", 25)
    if is_token_expired(saved_at, expiry_mins) and refresh_token:
        refreshed = refresh_access_token(target_erp, refresh_token, client_id, client_secret)
        if refreshed:
            return refreshed

    return access_token


def get_tenant_id(erp_type: Optional[str] = None) -> Optional[str]:
    """Retrieve the tenant ID / Realm ID for the specified ERP."""
    target_erp = _get_active_erp_type(erp_type)
    all_tokens = load_all_tokens()
    tenant_id = all_tokens.get(target_erp, {}).get("tenant_id")

    if not tenant_id:
        if target_erp == "xero":
            tenant_id = os.getenv("XERO_TENANT_ID") or ERP_CONFIGS["xero"]["default_tenant_id"]
        elif target_erp == "quickbooks":
            tenant_id = os.getenv("QBO_REALM_ID") or ERP_CONFIGS["quickbooks"]["default_tenant_id"]

    return tenant_id


if __name__ == "__main__":
    print("💾 Initializing Universal ERP Token Manager...")
    save_tokens(
        erp_type="xero",
        access_token="eyJhbGciOiJSUzI1NiIsImtpZCI6IjFDQUY4RTY2NzcyRDZEQzAyOEQ2NzI2RkQwMjYxNTcwRUZDMTkiLCJ4NXQiOiJISy1PWm5jdGJjQW8xbkp2MENZVmdWY09fQmsiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL2lkZW50aXR5Lnhlcm8uY29tIiwibmJmIjoxNzgyNTMyNzUxLCJpYXQiOjE3ODI1MzI3NTEsImV4cCI6MTc4MjUzNDU1MSwiYXVkIjoiaHR0cHM6Ly9pZGVudGl0eS54ZXJvLmNvbS9yZXNvdXJjZXMiLCJzY29wZSI6WyJhY2NvdW50aW5nLmludm9pY2VzLnJlYWQiLCJvZmZsaW5lX2FjY2VzcyJdLCJhbXIiOlsicHdkIl0sImNsaWVudF9pZCI6IkI2MjBBOEY2MUQ2NjRGNzk5NDdCOEJCMTNCM0ExNEE2Iiwic3ViIjoiZDA3N2E5N2QwNDE1NWM0ZTk1YzEyNmM1ZWMyODFmZGEiLCJhdXRoX3RpbWUiOjE3ODI1MzI3MTEsInhlcm9fdXNlcmlkIjoiNWMwYzY0ZjYtNGZjOS00ODI5LThhYmItZDQ2NjQ4OTk1NTI5IiwiZ2xvYmFsX3Nlc3Npb25faWQiOiJhNGI4MjgwMjI2MDU0MDg0OTVkMDAxZmY3M2FmZjNmMyIsInNpZCI6ImE0YjgyODAyMjYwNTQwODQ5NWQwMDFmZjczYWZmM2YzIiwiYXV0aGVudGljYXRpb25fZXZlbnRfaWQiOiIzNmJmM2YyMi1lMGJhLTRmOWEtYmJiNy1kOThiNTMzNThmOTkiLCJqdGkiOiIxQjc2RjFENEU2MkREQjY3MUE3NjdFNTBENTlBMDhDMCJ9.jlAeyZ8JtTnwUADCUctLhYxuiUX3bPVf_SfLlg73FLmFuaqNS7NEXvJB31s5TTwz7_LU17CbCF0gm-oj0ZMdvky0HTj09k99QQYdxlsUFjS_gtEX6uW1jncisrJV4n0UVz4fnXHGKcfkMqVAX8XwdGqZIrLECessoUqF3NwtkInqFXajRTstbTNJz0Pc2rO_9hXDK-hdmsOMuf6qhifKWJZwGndJSTS_XMi7_byY85K8NBIiRp4juY2t-1ZlhHSKOJwZWBZw4M1wCx4JRse4QdnxJSd9kMNz82L0Kl0GJAF0wZsXAniq63a1V0v0ooXNS9dM7Po4AR8NI0HWpJY-jQ",
        refresh_token="0Me_MXHyWngzIAh2upfFWSc-6dyjHaTM3Y_NqYqGuO4"
    )
    
    print("\n🧪 Testing Universal Token Manager...")
    xero_t = get_valid_token("xero")
    qbo_t = get_valid_token("quickbooks")
    print(f"✅ Xero Token retrieved: {xero_t[:25]}... (Tenant: {get_tenant_id('xero')})")
    print(f"✅ QBO Token retrieved: {qbo_t[:25] if qbo_t else 'Env token active'}... (Tenant: {get_tenant_id('quickbooks')})")
