# ERP Connector

> **REST microservice that acts as a universal wrapper around Xero and QuickBooks Online (QBO).**  
> Internal services talk to one clean, ERP-agnostic API. The connector handles all ERP quirks internally. It holds no business data (no database), but does include an optional local token cache — see notes below.

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Tech Stack](#tech-stack)
3. [Project Structure](#project-structure)
4. [Team & Ownership](#team--ownership)
5. [Getting Started](#getting-started)
6. [Environment Configuration](#environment-configuration)
7. [API Endpoints](#api-endpoints)
8. [Architecture](#architecture)
9. [Branch Strategy](#branch-strategy)
10. [Running Tests](#running-tests)
11. [Current Build Status](#current-build-status)

---

## Project Overview

The ERP Connector receives requests from internal services, routes them to the correct ERP adapter (Xero or QBO), normalises every response into one consistent schema, and returns clean structured data.

**What it does:**
- Accepts ERP-agnostic REST requests from internal services
- Reads active ERP from `ERP_TYPE` environment variable (set once at startup)
- Translates each request into the correct ERP-specific API call
- Handles pagination, rate limiting, and field-name differences internally
- Normalises every ERP response to a common schema
- Returns unified structured errors — never raw ERP messages
- Generates a `Correlation-ID` for every request for full traceability

**What it does NOT do:**
- Store business data such as invoices/contacts/accounts (no database for ERP data)
- Run background jobs or handle webhooks (future phase)

**Note on tokens:** the connector includes `token_manager.py`, which persists and auto-refreshes OAuth tokens locally, plus `routes/auth.py`, which handles the entire login flow so you never hand-type a token into Swagger. One-time setup:

1. Visit `/auth/setup` and paste in each ERP's Client ID / Client Secret (from the Xero/Intuit developer portal). Saved to a local, gitignored file — never `.env`, never committed.
2. Visit `/auth/xero/login` and/or `/auth/qbo/login` once each, click "Allow" — done. Xero's Tenant ID and QBO's Realm ID are captured automatically from the OAuth redirect, no manual lookup needed.
3. From then on, a background task (started in `main.py`'s lifespan) checks every couple of minutes whether either token is close to expiring and refreshes it proactively — no more logins needed until the refresh token itself expires (Xero: ~60 days if unused; QBO: 100 days).

If you want the service to be fully stateless/credential-agnostic instead, always pass your own valid token per request via `X-ERP-Token` / `X-ERP-Tenant-Id` headers — the local token store is a convenience layer, not a requirement.

**Standalone refresh, without the app running:** `scripts/refresh_xero_token.sh` and `scripts/refresh_qbo_token.sh` refresh a token with plain `curl` + `jq` — no Python, no browser, no running server required. Useful for a cron job, a quick manual check, or refreshing outside the app entirely. Both require the ERP to already be connected once via `/auth/{erp}/login` (that first step needs a browser for both ERPs — that's an OAuth requirement, not something either script can skip). **Important:** both Xero and QBO invalidate the old refresh token the moment a new one is issued — don't run these scripts *and* the app's background refresh loop against the same token file at the same time, or whichever refreshes second will fail with `invalid_grant`. Pick one mechanism as the source of truth (the background loop is fine for normal use; the scripts are for when the app isn't running).

```bash
./scripts/refresh_xero_token.sh   # refreshes .erp_tokens.json in place
./scripts/refresh_qbo_token.sh
```

**Adding a new ERP:** normalization is config-driven — see `config/mappings/*.yaml` and `utils/field_mapper.py`. Most new fields are a plain rename in YAML; only genuinely ERP-specific logic (e.g. deriving a status QBO doesn't expose directly) needs a small named function in `utils/transforms.py`. The HTTP/auth/pagination layer still needs a thin adapter class per ERP, since that part is inherently ERP-specific network code, not configuration.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.13 |
| Framework | FastAPI |
| ASGI Server | Uvicorn |
| HTTP Client | httpx (async) |
| Validation | Pydantic v2 |
| Config | python-dotenv |
| Testing | pytest + pytest-asyncio |
| Version Control | Git / GitHub |

---

## Project Structure

```
erp_connector/
├── main.py                        # FastAPI app entry point, middleware, exception handlers
├── .env                           # Local secrets (gitignored — never commit)
├── .env.example                   # Template with all required keys
├── .gitignore
├── requirements.txt
│
├── adapters/
│   ├── __init__.py                # Adapter registry — get_adapter() factory  ← Dev 1 ✅
│   ├── base_adapter.py            # Abstract interface all adapters must implement  ← Dev 1 ✅
│   ├── xero.py                    # Xero adapter implementation  ← Dev 2 🔄
│   └── qbo.py                     # QBO adapter implementation  ← Dev 3 🔄
│
├── config/
│   ├── __init__.py
│   └── settings.py                # Loads & validates env vars at startup  ← Dev 1 ✅
│
├── models/
│   ├── __init__.py
│   └── schemas.py                 # Frozen Pydantic models (READ-ONLY contract)  ← Dev 1 ✅
│
├── routes/
│   ├── __init__.py
│   └── erp.py                     # All 12 API route stubs with OpenAPI tags  ← Dev 1 ✅
│
├── utils/
│   ├── __init__.py
│   ├── errors.py                  # Unified error builder & exception handlers  ← Dev 1 ✅
│   ├── logger.py                  # Structured JSON logging, no token leakage  ← Dev 1 ✅
│   ├── rate_limiter.py            # Token-bucket rate limiter per tenant  ← Dev 1 ✅
│   └── pagination.py              # Pagination utility (placeholder)
│
└── tests/
    ├── unit/
    │   ├── test_errors.py
    │   ├── test_rate_limiter.py
    │   ├── test_pagination.py
    │   └── test_schemas.py
    └── integration/
        ├── test_health.py         ← ✅ Passing
        ├── test_invoices.py
        ├── test_bills.py
        ├── test_contacts.py
        ├── test_accounts.py
        ├── test_payments.py
        └── test_error_handling.py
```

---

## Team & Ownership

| Developer | Role | Component Ownership | Status |
|-----------|------|--------------------|--------|
| **Mithilesh Kolhapurkar** | Core Engine | `main.py`, `config/`, `models/schemas.py`, `routes/`, `utils/`, `adapters/__init__.py` | ✅ Complete (Production Ready) |
| **Ankita Patil** | QBO Adapter | `adapters/qbo.py` (QuickBooks Integration) | ✅ Complete (Production Ready) |
| **Samreen Shaikh** | Xero Adapter | `adapters/xero.py` (Xero Integration) | ✅ Complete (Production Ready) |



---

## Getting Started

### Prerequisites
- Python 3.11+
- pip

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/MITHILESHK11/ERP_Connector.git
cd ERP_Connector

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 3. Install dependencies
pip install fastapi uvicorn python-dotenv httpx pytest pytest-asyncio

# 4. Copy the environment template
copy .env.example .env        # Windows
# cp .env.example .env        # macOS/Linux

# 5. Edit .env and fill in your ERP_TYPE and tokens
```

### Run the server

```bash
uvicorn main:app --reload --port 8080
```

**Swagger UI** → [http://localhost:8080/erp/docs](http://localhost:8080/erp/docs)

---

## Environment Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ERP_TYPE` | ✅ Yes | — | Must be `xero` or `quickbooks` (or `qbo`). Fails at startup if missing. |
| `PORT` | No | `8080` | Server port |
| `LOG_LEVEL` | No | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `CORS_ORIGIN` | No | `*` | Restrict in production |
| `APP_VERSION` | No | `0.1.0` | Reported in `/erp/health` |
| `XERO_TOKEN` | For Xero | — | OAuth 2.0 access token (30-min expiry) |
| `XERO_TENANT_ID` | For Xero | — | Xero Organisation UUID |
| `QBO_TOKEN` | For QBO | — | Intuit OAuth 2.0 access token (~60-min expiry) |
| `QBO_REALM_ID` | For QBO | — | QuickBooks Online Company/Realm ID |


---

## API Endpoints

All endpoints require two custom headers (except `/erp/health`):

| Header | Description |
|--------|-------------|
| `X-ERP-Token` | OAuth 2.0 Bearer access token |
| `X-ERP-Tenant-Id` | Xero `tenantId` or QBO `realmId` |

### Health

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/erp/health` | ❌ | Liveness check. Returns ERP type and version. |

### Invoices

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/erp/invoices` | List invoices. Query: `from`, `to`, `status` |
| `GET` | `/erp/invoices/{invoice_id}` | Get one invoice by ID |
| `POST` | `/erp/invoices` | Create a new invoice |

### Bills

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/erp/bills` | List bills. Query: `from`, `to` |
| `GET` | `/erp/bills/{bill_id}` | Get one bill by ID |
| `POST` | `/erp/bills` | Create a new bill |

### Contacts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/erp/contacts` | List contacts. Query: `type` (customer/supplier) |
| `GET` | `/erp/contacts/{contact_id}` | Get one contact by ID |
| `POST` | `/erp/contacts` | Create a new contact |

### Accounts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/erp/accounts` | Full chart of accounts |

### Payments

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/erp/payments` | Record a payment against an invoice or bill |

### Response Envelope

**Success (list):**
```json
{
  "success": true,
  "erp": "xero",
  "correlationId": "req-abc-123",
  "count": 42,
  "data": [ ... ]
}
```

**Error:**
```json
{
  "success": false,
  "error": "TOKEN_EXPIRED",
  "message": "Access token has expired. Please refresh and retry.",
  "erp": "xero",
  "correlationId": "req-abc-123",
  "timestamp": "2026-06-23T08:00:00Z"
}
```

---

## Architecture

![ERP Connector Architecture Diagram](docs/images/erp_connector_diagram_1.jpg)

**Flow summary:**
1. **Calling Services** (Variance Analysis Engine, Anomaly Detection, etc.) make REST calls with `X-ERP-Token` + `X-ERP-Tenant-Id` headers.
2. **Entry Layer** validates headers — missing/expired token returns `TOKEN_EXPIRED` immediately.
3. **ERP Router** reads `ERP_TYPE` from config and routes to the correct adapter.
4. **Rate Limiter** (token bucket per `tenant_id`) checks limits before any API call — Xero: 60/min, QBO: 500/min. Requests are queued on breach, never dropped.
5. **Adapter** (Xero or QBO) builds the ERP-specific API call, handles pagination (loops until < 1000 records per page).
6. **Response Pipeline** — on error, translates to a clean `{ error, message, erp, timestamp }` response. On success, maps ERP fields to the common normalised schema and returns the result.

---

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Protected. Production-ready code only. |
| `dev1/` | Mithilesh Kolhapurkar — Core Engine |
| `dev2/` | Ankita Patil — QBO Adapter |
| `dev3/` | Samreen Shaikh — Xero Adapter |

PRs from `dev*/` branches must be reviewed before merging to `main`.

---

## Running Tests

```bash
# Run the complete unit and integration test suite
pytest -v
```

| Test Suite | Status |
|------|--------|
| All Unit & Integration Tests (49/49) | ✅ Passing |

---

## Current Build Status

| Component | Status |
|-----------|--------|
| Project scaffold | ✅ Complete |
| `models/schemas.py` (frozen contract) | ✅ Complete — READ-ONLY |
| `config/settings.py` | ✅ Complete |
| `adapters/base_adapter.py` | ✅ Complete |
| `adapters/__init__.py` (registry) | ✅ Complete |
| `utils/` (logger, errors, rate_limiter) | ✅ Complete |
| `main.py` (app, middleware) | ✅ Complete |
| `routes/erp.py` (13 routes including PUT) | ✅ Complete |
| `adapters/xero.py` (Xero Adapter) | ✅ Complete — 100% |
| `adapters/qbo.py` (QuickBooks Online) | ✅ Complete — 100% |
| Unit & Integration tests | ✅ Complete & Passing |

---

*ERP Connector — Phase 0 | Python FastAPI | June 2026*

