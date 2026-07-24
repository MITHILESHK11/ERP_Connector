"""
routes/auth.py
===============
Everything needed to connect Xero and/or QuickBooks Online WITHOUT ever
hand-typing a token into Swagger, and without writing secrets into .env.

Flow for each ERP:
  1. (once) GET /auth/setup           -> enter that ERP's app Client ID/Secret
  2. GET /auth/{erp}/login             -> redirects to the ERP's consent screen
  3. User logs in / clicks Allow once
  4. GET /auth/{erp}/callback          -> exchanges the code for tokens
                                          instantly and automatically, saves
                                          them to the local token store
  5. From then on: token_manager.py's background refresh loop (main.py
     lifespan) keeps the access token valid in the background, forever,
     with no further logins needed until the refresh token itself expires
     (Xero: ~60 days unused, QBO: 100 days).

Nothing here ever writes a token or secret into .env — everything OAuth-
related is persisted only to the gitignored local files token_manager.py
manages (.erp_tokens.json / .erp_credentials.json).
"""
import secrets
import httpx
from fastapi import APIRouter, Request, HTTPException, Query, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from token_manager import (
    save_tokens,
    save_credentials,
    get_app_credentials,
    get_valid_token,
    get_tenant_id,
    ERP_CONFIGS,
)
from utils.logger import get_logger

logger = get_logger("routes.auth")
router = APIRouter(tags=["auth"])

XERO_CONNECTIONS_URL = "https://api.xero.com/connections"

# In-memory store of OAuth state values we've issued, so each callback can
# reject any request whose `state` we didn't generate ourselves (CSRF check).
# Fine for a single-process dev/demo server; use a shared store (Redis etc.)
# if this ever runs behind multiple worker processes.
_PENDING_OAUTH_STATES: set[str] = set()


def _connection_status_html() -> str:
    xero_connected = bool(get_valid_token("xero"))
    qbo_connected = bool(get_valid_token("quickbooks"))

    def _row(name: str, connected: bool, erp_path: str, tenant_label: str):
        if connected:
            tenant = get_tenant_id(erp_path if erp_path != "qbo" else "quickbooks") or "unknown"
            return (
                f"<li>✅ <strong>{name}</strong> — connected "
                f"({tenant_label}: {tenant})</li>"
            )
        return (
            f"<li>⬜ <strong>{name}</strong> — not connected. "
            f"<a href='/auth/{erp_path}/login'>Connect {name}</a></li>"
        )

    return (
        "<ul style='list-style:none; padding:0;'>"
        + _row("Xero", xero_connected, "xero", "Tenant ID")
        + _row("QuickBooks Online", qbo_connected, "qbo", "Realm ID")
        + "</ul>"
    )


@router.get("/", summary="Root endpoint — connection status & quick links")
async def root(request: Request, code: str = Query(None), state: str = Query(None)):
    # QBO's callback historically redirects to the app's configured root with
    # code/realmId/state — if we ever see a bare `code` land on `/` instead of
    # a dedicated callback path, treat it as a misconfigured redirect rather
    # than silently doing nothing.
    if code:
        return HTMLResponse(
            "<h3>Received an OAuth code on the root path.</h3>"
            "<p>Your app's redirect URI is probably set to '/' instead of "
            "'/auth/xero/callback' or '/auth/qbo/callback'. Update it in the "
            "Xero/Intuit developer portal and try connecting again.</p>",
            status_code=400,
        )
    return HTMLResponse(
        "<h2>ERP Connector Microservice is running</h2>"
        "<p>API documentation: <a href='/erp/docs'>/erp/docs</a></p>"
        "<h3>Connections</h3>"
        + _connection_status_html()
        + "<p>First time here? <a href='/auth/setup'>Enter your app credentials</a> "
        "before connecting.</p>"
    )


# ---------------------------------------------------------------------------
# One-time credential setup — replaces hand-editing .env for OAuth app creds
# ---------------------------------------------------------------------------

@router.get("/auth/setup", summary="One-time OAuth app credential setup form")
async def setup_form():
    xero_creds = get_app_credentials("xero")
    qbo_creds = get_app_credentials("quickbooks")
    return HTMLResponse(f"""
    <html>
      <body style="font-family: sans-serif; max-width: 640px; margin: 40px auto;">
        <h2>ERP Connector — Initial Setup</h2>
        <p>Enter each app's Client ID / Client Secret <em>once</em>. These are
        saved locally (never into .env, never committed) and reused for every
        future login and background token refresh.</p>

        <h3>Xero</h3>
        <form method="post" action="/auth/setup/xero">
          <label>Client ID</label><br>
          <input name="client_id" style="width:100%" value="{xero_creds['client_id']}" required><br><br>
          <label>Client Secret</label><br>
          <input name="client_secret" type="password" style="width:100%" required><br><br>
          <label>Redirect URI</label><br>
          <input name="redirect_uri" style="width:100%" value="{xero_creds['redirect_uri']}"><br><br>
          <label>Scopes (space-separated)</label><br>
          <input name="scopes" style="width:100%" value="{xero_creds.get('scopes', '')}"><br><br>
          <button type="submit">Save Xero credentials</button>
        </form>

        <hr>

        <h3>QuickBooks Online</h3>
        <form method="post" action="/auth/setup/qbo">
          <label>Client ID</label><br>
          <input name="client_id" style="width:100%" value="{qbo_creds['client_id']}" required><br><br>
          <label>Client Secret</label><br>
          <input name="client_secret" type="password" style="width:100%" required><br><br>
          <label>Redirect URI</label><br>
          <input name="redirect_uri" style="width:100%" value="{qbo_creds['redirect_uri']}"><br><br>
          <label>Scopes (space-separated)</label><br>
          <input name="scopes" style="width:100%" value="{qbo_creds.get('scopes', '')}"><br><br>
          <button type="submit">Save QBO credentials</button>
        </form>

        <p style="margin-top:2em;"><a href="/">← Back to connection status</a></p>
      </body>
    </html>
    """)


@router.post("/auth/setup/xero", summary="Save Xero app credentials")
async def setup_xero(client_id: str = Form(...), client_secret: str = Form(...),
                      redirect_uri: str = Form(None), scopes: str = Form(None)):
    save_credentials("xero", client_id, client_secret, redirect_uri, scopes)
    return RedirectResponse("/auth/setup?saved=xero", status_code=303)


@router.post("/auth/setup/qbo", summary="Save QBO app credentials")
async def setup_qbo(client_id: str = Form(...), client_secret: str = Form(...),
                     redirect_uri: str = Form(None), scopes: str = Form(None)):
    save_credentials("quickbooks", client_id, client_secret, redirect_uri, scopes)
    return RedirectResponse("/auth/setup?saved=qbo", status_code=303)


# ---------------------------------------------------------------------------
# Xero login + callback
# ---------------------------------------------------------------------------

@router.get("/auth/xero/login", summary="Initiate Xero OAuth flow")
async def xero_login():
    creds = get_app_credentials("xero")
    if not creds["client_id"]:
        return RedirectResponse("/auth/setup?error=missing_xero_credentials")

    state = secrets.token_urlsafe(16)
    _PENDING_OAUTH_STATES.add(state)
    scope_str = creds.get("scopes") or ERP_CONFIGS['xero']['scopes']
    auth_uri = (
        f"{ERP_CONFIGS['xero']['auth_url']}?"
        f"response_type=code&"
        f"client_id={creds['client_id']}&"
        f"redirect_uri={creds['redirect_uri']}&"
        f"scope={scope_str.replace(' ', '%20')}&"
        f"state={state}"
    )
    return RedirectResponse(auth_uri)


@router.get("/auth/xero/callback", summary="Xero OAuth callback endpoint")
async def xero_callback(code: str = Query(None), state: str = Query(None)):
    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' from Xero redirect.")
    if not state or state not in _PENDING_OAUTH_STATES:
        logger.warning("Rejected Xero OAuth callback with missing/unrecognized state (possible CSRF).")
        raise HTTPException(status_code=400, detail="Invalid or missing OAuth state parameter.")
    _PENDING_OAUTH_STATES.discard(state)

    creds = get_app_credentials("xero")
    if not creds["client_id"] or not creds["client_secret"]:
        raise HTTPException(status_code=500, detail="Xero credentials not configured — visit /auth/setup first.")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ERP_CONFIGS["xero"]["refresh_url"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": creds["redirect_uri"],
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )
        if resp.status_code != 200:
            logger.error(f"Failed to exchange Xero auth code: {resp.text}")
            return HTMLResponse(f"<h3>OAuth Code Exchange Error</h3><pre>{resp.text}</pre>", status_code=400)

        token_data = resp.json()
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")

        # Instantly, automatically fetch which tenant(s) this login has access
        # to — no manual tenant ID lookup needed.
        conn_resp = await client.get(
            XERO_CONNECTIONS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )
        tenants = conn_resp.json() if conn_resp.status_code == 200 else []
        tenant_id, tenant_name = "", ""
        # NOTE: preferring a tenant with "demo" in its name is a sandbox-testing
        # convenience — a real user connecting a real org has no "demo" tenant,
        # so this simply falls through to "first tenant returned" for them.
        for t in tenants:
            if "demo" in t.get("tenantName", "").lower():
                tenant_id, tenant_name = t["tenantId"], t.get("tenantName", "")
                break
        if not tenant_id and tenants:
            tenant_id = tenants[0]["tenantId"]
            tenant_name = tenants[0].get("tenantName", "Unknown")

    save_tokens(
        erp_type="xero",
        access_token=access_token,
        refresh_token=refresh_token,
        tenant_id=tenant_id,
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
    )

    return HTMLResponse(f"""
    <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
        <h1 style="color: #008000;">✅ Xero connected!</h1>
        <p><strong>Tenant:</strong> {tenant_name} ({tenant_id})</p>
        <p>Token saved. It will auto-refresh in the background from now on —
        you won't need to log in again unless you disconnect the app in Xero.</p>
        <p><a href="/erp/docs">Go to API Documentation</a> · <a href="/">Home</a></p>
    </body></html>
    """)


# ---------------------------------------------------------------------------
# QuickBooks Online login + callback
# ---------------------------------------------------------------------------

@router.get("/auth/qbo/login", summary="Initiate QuickBooks Online OAuth flow")
async def qbo_login():
    creds = get_app_credentials("quickbooks")
    if not creds["client_id"]:
        return RedirectResponse("/auth/setup?error=missing_qbo_credentials")

    state = secrets.token_urlsafe(16)
    _PENDING_OAUTH_STATES.add(state)
    scope_str = creds.get("scopes") or ERP_CONFIGS['quickbooks']['scopes']
    auth_uri = (
        f"{ERP_CONFIGS['quickbooks']['auth_url']}?"
        f"client_id={creds['client_id']}&"
        f"redirect_uri={creds['redirect_uri']}&"
        f"response_type=code&"
        f"scope={scope_str.replace(' ', '%20')}&"
        f"state={state}"
    )
    return RedirectResponse(auth_uri)


@router.get("/auth/qbo/callback", summary="QuickBooks Online OAuth callback endpoint")
async def qbo_callback(code: str = Query(None), state: str = Query(None), realmId: str = Query(None)):
    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' from QuickBooks redirect.")
    if not state or state not in _PENDING_OAUTH_STATES:
        logger.warning("Rejected QBO OAuth callback with missing/unrecognized state (possible CSRF).")
        raise HTTPException(status_code=400, detail="Invalid or missing OAuth state parameter.")
    _PENDING_OAUTH_STATES.discard(state)

    if not realmId:
        raise HTTPException(status_code=400, detail="Missing 'realmId' from QuickBooks redirect.")

    creds = get_app_credentials("quickbooks")
    if not creds["client_id"] or not creds["client_secret"]:
        raise HTTPException(status_code=500, detail="QBO credentials not configured — visit /auth/setup first.")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ERP_CONFIGS["quickbooks"]["refresh_url"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": creds["redirect_uri"],
            },
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            auth=(creds["client_id"], creds["client_secret"]),
            timeout=15.0,
        )
        if resp.status_code != 200:
            logger.error(f"Failed to exchange QBO auth code: {resp.text}")
            return HTMLResponse(f"<h3>OAuth Code Exchange Error</h3><pre>{resp.text}</pre>", status_code=400)

        token_data = resp.json()
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")

    # QBO hands us the Realm ID (its tenant ID) directly on the callback —
    # no extra lookup call needed, unlike Xero.
    save_tokens(
        erp_type="quickbooks",
        access_token=access_token,
        refresh_token=refresh_token,
        tenant_id=realmId,
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
    )

    return HTMLResponse(f"""
    <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
        <h1 style="color: #008000;">✅ QuickBooks Online connected!</h1>
        <p><strong>Realm ID:</strong> {realmId}</p>
        <p>Token saved. It will auto-refresh in the background from now on —
        you won't need to log in again unless you disconnect the app in QBO.</p>
        <p><a href="/erp/docs">Go to API Documentation</a> · <a href="/">Home</a></p>
    </body></html>
    """)
