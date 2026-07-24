import json
import os
import logging
import asyncio
import threading
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger("erp_connector.token_manager")

TOKEN_FILE = ".erp_tokens.json"
XERO_LEGACY_FILE = ".xero_tokens.json"
CREDENTIALS_FILE = ".erp_credentials.json"  # gitignored — holds client_id/secret/redirect_uri only

# ---------------------------------------------------------------------------
# Per-ERP refresh locks
#
# There are two independent places that can trigger a token refresh:
#   1. get_valid_token() — reactive, runs inline on any incoming request
#      whose token happens to look stale.
#   2. background_token_refresh_loop() — proactive, runs every ~2 minutes.
#
# Both Xero and QBO invalidate a refresh token the instant it's used once —
# if these two paths ever fire close together, both could read the SAME
# refresh token before either writes back, and both try to redeem it. Only
# one succeeds; the other gets invalid_grant. A lock per ERP, held for the
# full read-check-refresh-write sequence, prevents this: whichever caller
# loses the race simply re-reads the just-refreshed token from disk instead
# of trying to redeem the now-dead one itself.
# ---------------------------------------------------------------------------
_refresh_locks: Dict[str, threading.Lock] = {
    "xero": threading.Lock(),
    "quickbooks": threading.Lock(),
}

# ERP OAuth app configuration.
#
# client_id/client_secret ONLY come from environment variables or the local
# (gitignored) credentials file saved via the one-time /auth/setup step —
# never hardcoded here. If neither is set, refresh fails with a clear warning
# instead of silently using a placeholder value.
ERP_CONFIGS = {
    "xero": {
        "auth_url": "https://login.xero.com/identity/connect/authorize",
        "refresh_url": "https://identity.xero.com/connect/token",
        "default_client_id": os.getenv("XERO_CLIENT_ID", ""),
        "default_client_secret": os.getenv("XERO_CLIENT_SECRET", ""),
        "default_tenant_id": os.getenv("XERO_TENANT_ID", ""),
        "default_redirect_uri": os.getenv("XERO_REDIRECT_URI", "http://localhost:8080/auth/xero/callback"),
        "scopes": os.getenv(
            "XERO_SCOPES",
            "openid profile email accounting.settings accounting.contacts accounting.invoices accounting.payments offline_access"
        ),
        "expiry_minutes": 25
    },
    "quickbooks": {
        "auth_url": "https://appcenter.intuit.com/connect/oauth2",
        "refresh_url": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        "default_client_id": os.getenv("QBO_CLIENT_ID", ""),
        "default_client_secret": os.getenv("QBO_CLIENT_SECRET", ""),
        "default_tenant_id": os.getenv("QBO_REALM_ID", ""),
        "default_redirect_uri": os.getenv("QBO_REDIRECT_URI", "http://localhost:8080/auth/qbo/callback"),
        "scopes": os.getenv(
            "QBO_SCOPES",
            "com.intuit.quickbooks.accounting com.intuit.quickbooks.payment"
        ),
        "expiry_minutes": 50
    }
}


# ---------------------------------------------------------------------------
# One-time credential setup (client_id / client_secret / redirect_uri)
#
# Previously the ONLY way to configure these was hand-editing .env — which is
# exactly how real secrets ended up committed to a project zip earlier. This
# store lives in a separate, gitignored file so the setup flow never has to
# touch .env at all, and never displays or logs the raw secret afterwards.
# ---------------------------------------------------------------------------

def load_credentials() -> Dict[str, Any]:
    """Load saved OAuth app credentials (client_id/secret/redirect_uri) per ERP."""
    if not os.path.exists(CREDENTIALS_FILE):
        return {}
    try:
        with open(CREDENTIALS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read {CREDENTIALS_FILE}: {e}")
        return {}


def save_credentials(erp_type: str, client_id: str, client_secret: str,
                      redirect_uri: Optional[str] = None,
                      scopes: Optional[str] = None) -> None:
    """Save OAuth app credentials for one ERP, once, via the /auth/setup flow."""
    erp_key = erp_type.lower()
    all_creds = load_credentials()
    entry = {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri or ERP_CONFIGS.get(erp_key, {}).get("default_redirect_uri", ""),
    }
    if scopes:
        entry["scopes"] = scopes
    all_creds[erp_key] = entry
    try:
        with open(CREDENTIALS_FILE, "w") as f:
            json.dump(all_creds, f, indent=2)
        logger.info(f"Saved OAuth app credentials for ERP: {erp_key} (client_secret not logged)")
    except Exception as e:
        logger.error(f"Failed to save credentials to disk: {e}")


def _looks_like_placeholder(value: str) -> bool:
    """
    .env.example / .env ship with human-readable placeholders like
    'your_xero_app_client_id_here' so the file is self-documenting. Those are
    non-empty strings, so a naive `if value:` check treats them as configured
    real credentials — which silently breaks the login flow (Xero/QBO reject
    the bogus client_id) instead of correctly prompting for real setup.
    """
    if not value:
        return True
    lowered = value.strip().lower()
    return lowered.startswith("your_") and lowered.endswith("_here")


def get_app_credentials(erp_type: str) -> Dict[str, str]:
    """
    Resolve client_id/client_secret/redirect_uri/scopes for one ERP, checking (in order):
    1. Saved credentials file (from /auth/setup)
    2. Environment variables / .env defaults (ignoring unfilled placeholders)
    """
    erp_key = erp_type.lower()
    saved = load_credentials().get(erp_key, {})
    config = ERP_CONFIGS.get(erp_key, {})

    env_client_id = config.get("default_client_id", "")
    env_client_secret = config.get("default_client_secret", "")

    client_id = saved.get("client_id") or (env_client_id if not _looks_like_placeholder(env_client_id) else "")
    client_secret = saved.get("client_secret") or (env_client_secret if not _looks_like_placeholder(env_client_secret) else "")

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": saved.get("redirect_uri") or config.get("default_redirect_uri", ""),
        "scopes": saved.get("scopes") or config.get("scopes", ""),
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
            # Intuit's token endpoint requires client_id/client_secret ONLY in
            # the Basic Auth header. Including them in the body too (even
            # alongside a correct Authorization header) gets rejected outright
            # with 401 — the body must contain just grant_type + refresh_token.
            response = httpx.post(
                config["refresh_url"],
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                auth=(client_id, client_secret),
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
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
    app_creds = get_app_credentials(target_erp)
    client_id = erp_data.get("client_id") or app_creds["client_id"]
    client_secret = erp_data.get("client_secret") or app_creds["client_secret"]

    # Fallback to .env environment variables if token file is empty
    # (ignoring unfilled placeholders like "your_xero_access_token_here" —
    # see _looks_like_placeholder for why a naive truthiness check is wrong here)
    if not access_token:
        if target_erp == "xero":
            env_token = os.getenv("XERO_TOKEN")
        elif target_erp == "quickbooks":
            env_token = os.getenv("QBO_TOKEN")
        else:
            env_token = None
        access_token = env_token if env_token and not _looks_like_placeholder(env_token) else None

    if not access_token:
        logger.warning(f"No token credentials found for ERP: {target_erp}")
        return None

    expiry_mins = ERP_CONFIGS.get(target_erp, {}).get("expiry_minutes", 25)
    if is_token_expired(saved_at, expiry_mins) and refresh_token:
        # If credentials are missing, warn clearly rather than silently
        # falling back to the (already expired) access token below.
        if not client_id or not client_secret:
            logger.warning(
                f"⚠️ Cannot refresh {target_erp} token: client_id/client_secret "
                f"missing (set {target_erp.upper()}_CLIENT_ID / "
                f"{target_erp.upper()}_CLIENT_SECRET). Falling back to the "
                f"existing token, which may already be expired."
            )
        else:
            # Hold this ERP's lock for the whole check+refresh so this
            # reactive path can never redeem the same refresh_token the
            # background loop is (or just did) redeeming concurrently.
            lock = _refresh_locks.setdefault(target_erp, threading.Lock())
            with lock:
                # Re-read after acquiring the lock — if another caller
                # already refreshed while we were waiting, use that fresh
                # token instead of racing to redeem the now-dead one.
                latest = load_all_tokens().get(target_erp, {})
                latest_saved_at = latest.get("saved_at")
                latest_access = latest.get("access_token")
                if latest_saved_at and not is_token_expired(latest_saved_at, expiry_mins):
                    return latest_access

                refreshed = refresh_access_token(
                    target_erp, latest.get("refresh_token", refresh_token), client_id, client_secret
                )
            if refreshed:
                return refreshed
            logger.warning(
                f"⚠️ Token refresh failed for {target_erp} — continuing with "
                f"the existing (possibly expired) access token. Upstream calls "
                f"may now fail with 401."
            )

    return access_token


def get_tenant_id(erp_type: Optional[str] = None) -> Optional[str]:
    """Retrieve the tenant ID / Realm ID for the specified ERP."""
    target_erp = _get_active_erp_type(erp_type)
    all_tokens = load_all_tokens()
    tenant_id = all_tokens.get(target_erp, {}).get("tenant_id")

    if not tenant_id:
        if target_erp == "xero":
            candidate = os.getenv("XERO_TENANT_ID") or ERP_CONFIGS["xero"]["default_tenant_id"]
        elif target_erp == "quickbooks":
            candidate = os.getenv("QBO_REALM_ID") or ERP_CONFIGS["quickbooks"]["default_tenant_id"]
        else:
            candidate = None
        tenant_id = candidate if candidate and not _looks_like_placeholder(candidate) else None

    return tenant_id


if __name__ == "__main__":
    # Quick manual status check — reads from environment variables and the
    # local token store, does nothing destructive if nothing is configured.
    print("💾 Universal ERP Token Manager — status check")
    print("(To seed a token for local testing, set XERO_TOKEN/QBO_TOKEN env vars")
    print(" or call save_tokens() yourself with a token from your own sandbox app.)")

    seed_access = os.getenv("SEED_XERO_ACCESS_TOKEN")
    seed_refresh = os.getenv("SEED_XERO_REFRESH_TOKEN")
    if seed_access and seed_refresh:
        save_tokens(erp_type="xero", access_token=seed_access, refresh_token=seed_refresh)
        print("✅ Seeded Xero tokens from SEED_XERO_ACCESS_TOKEN/SEED_XERO_REFRESH_TOKEN env vars.")

    print("\n🧪 Checking Universal Token Manager...")
    xero_t = get_valid_token("xero")
    qbo_t = get_valid_token("quickbooks")
    print(f"Xero token present: {bool(xero_t)} (Tenant: {get_tenant_id('xero')})")
    print(f"QBO token present:  {bool(qbo_t)} (Tenant: {get_tenant_id('quickbooks')})")


# ---------------------------------------------------------------------------
# Background auto-refresh
#
# get_valid_token() above refreshes REACTIVELY — only when something calls it
# and finds the token already expired. That's fine, but it means the very
# first request after expiry pays the refresh latency, and if nothing calls
# it for a while, an expired token just sits there until it's needed.
#
# This loop refreshes PROACTIVELY in the background — a bit before actual
# expiry — for any ERP that has a saved refresh_token, so a valid access
# token is basically always sitting ready. It's started once from main.py's
# lifespan and runs for the life of the process.
# ---------------------------------------------------------------------------

# Refresh this many minutes before the token's real expiry — gives headroom
# so an in-flight request never gets caught using a token that expires
# mid-call.
_REFRESH_SAFETY_MARGIN_MINUTES = 5


async def _refresh_one_erp_if_due(erp_key: str) -> None:
    all_tokens = load_all_tokens()
    erp_data = all_tokens.get(erp_key, {})
    refresh_token = erp_data.get("refresh_token")
    saved_at = erp_data.get("saved_at")
    if not refresh_token or not saved_at:
        return  # nothing connected yet for this ERP — nothing to refresh

    expiry_mins = ERP_CONFIGS.get(erp_key, {}).get("expiry_minutes", 25)
    due_mins = max(expiry_mins - _REFRESH_SAFETY_MARGIN_MINUTES, 1)
    if not is_token_expired(saved_at, due_mins):
        return  # still comfortably valid, nothing to do yet

    app_creds = get_app_credentials(erp_key)
    client_id = erp_data.get("client_id") or app_creds["client_id"]
    client_secret = erp_data.get("client_secret") or app_creds["client_secret"]
    if not client_id or not client_secret:
        logger.warning(f"⚠️ Background refresh skipped for {erp_key}: client_id/client_secret missing.")
        return

    # Same lock as get_valid_token()'s reactive path — see the comment above
    # _refresh_locks for why this matters. Acquiring a threading.Lock blocks
    # the calling thread, so do it inside the to_thread call, not on the
    # event loop thread.
    def _locked_refresh():
        lock = _refresh_locks.setdefault(erp_key, threading.Lock())
        with lock:
            latest = load_all_tokens().get(erp_key, {})
            latest_saved_at = latest.get("saved_at")
            if latest_saved_at and not is_token_expired(latest_saved_at, due_mins):
                return None  # someone else (the reactive path) already refreshed it — nothing to do
            return refresh_access_token(
                erp_key, latest.get("refresh_token", refresh_token), client_id, client_secret
            )

    # refresh_access_token() does a blocking httpx.post — run it off the
    # event loop thread so it can't stall other requests while it waits
    # on the network.
    refreshed = await asyncio.to_thread(_locked_refresh)
    if refreshed:
        logger.info(f"🔄 Background auto-refresh succeeded for {erp_key}.")
    else:
        logger.warning(f"⚠️ Background auto-refresh failed for {erp_key} — will retry on next cycle.")


async def background_token_refresh_loop(interval_seconds: int = 120) -> None:
    """
    Runs forever (until cancelled at shutdown), checking every `interval_seconds`
    whether either connected ERP's token is close to expiring, and refreshing
    it proactively in the background if so. Safe to run even when nothing is
    connected yet — each check is a fast no-op in that case.
    """
    logger.info(f"Background token refresh loop started (checking every {interval_seconds}s).")
    try:
        while True:
            for erp_key in ("xero", "quickbooks"):
                try:
                    await _refresh_one_erp_if_due(erp_key)
                except Exception as e:
                    logger.error(f"Background refresh check failed for {erp_key}: {e}")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("Background token refresh loop stopped.")
        raise
