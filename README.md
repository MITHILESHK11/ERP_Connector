# ERP Connector

> **REST microservice that acts as a universal wrapper around Xero and QuickBooks Online (QBO).**
> Internal services talk to one clean, ERP-agnostic API. The connector handles all ERP quirks internally — authentication, pagination, rate limits, and field normalization — so callers write one integration instead of two.

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Tech Stack](#tech-stack)
3. [Project Structure](#project-structure)
4. [Getting Started](#getting-started)
5. [Authentication — one click, ever](#authentication--one-click-ever)
6. [Environment Configuration](#environment-configuration)
7. [API Endpoints](#api-endpoints)
8. [Architecture](#architecture)
9. [Adding a New ERP](#adding-a-new-erp)
10. [Running Tests](#running-tests)
11. [Current Build Status](#current-build-status)
12. [Known Limitations & Future Work](#known-limitations--future-work)

---

## Project Overview

The ERP Connector receives requests from internal services, routes them to the correct ERP adapter (Xero or QBO), normalizes every response into one consistent schema, and returns clean structured data.

**What it does:**
- Accepts ERP-agnostic REST requests from internal services
- Reads the active ERP from `ERP_TYPE` (`xero`, `quickbooks`/`qbo`, or `mock` for offline testing)
- Translates each request into the correct ERP-specific API call
- Handles pagination, rate limiting, and field-name differences internally
- Normalizes every ERP response to a common schema — identical shape regardless of ERP
- Automatically retries transient network failures (short backoff, real errors are never retried)
- Returns unified structured errors — never raw ERP messages
- Generates a correlation ID for every request for full traceability
- Handles the entire OAuth login and token-refresh lifecycle automatically — no manual token entry, ever

**What it does NOT do:**
- Store business data such as invoices/contacts/accounts (no database for ERP data — it's a pass-through, not a system of record)
- Push/receive webhooks (pull-only REST interface; a future enhancement, not current scope)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| Framework | FastAPI |
| ASGI Server | Uvicorn |
| HTTP Client | httpx (async) |
| Validation | Pydantic v2 |
| Config | python-dotenv |
| Resilience | tenacity (retry/backoff) |
| Config-driven mapping | PyYAML |
| Testing | pytest + pytest-asyncio |

---

## Project Structure

```
ERP_Connector/
├── main.py                        # FastAPI app entry point, lifespan, middleware
├── token_manager.py                # Token persistence, refresh, background auto-refresh loop
├── .env / .env.example             # Local config (gitignored — placeholders only, never real secrets)
├── .gitignore
├── requirements.txt
│
├── adapters/
│   ├── __init__.py                 # Adapter registry — get_adapter() factory
│   ├── base_adapter.py             # Abstract interface + @register_adapter decorator
│   ├── xero.py                     # Xero adapter
│   ├── qbo.py                      # QuickBooks Online adapter
│   └── mock.py                     # In-memory fake ERP for offline testing (ERP_TYPE=mock)
│
├── config/
│   ├── settings.py                 # Loads & validates env vars at startup
│   └── mappings/
│       ├── xero.yaml               # Field mapping: Xero raw fields to common schema
│       └── qbo.yaml                # Field mapping: QBO raw fields to common schema
│
├── models/
│   └── schemas.py                  # Pydantic request/response models
│
├── routes/
│   ├── erp.py                      # All /erp/* API routes
│   └── auth.py                     # /auth/setup, /auth/{erp}/login, /auth/{erp}/callback
│
├── middleware/
│   └── auth.py                     # Token validation + rate limiting on every request
│
├── utils/
│   ├── errors.py                   # Unified error builder & exception handlers
│   ├── logger.py                   # Structured JSON logging, no token leakage
│   ├── rate_limiter.py             # Token-bucket rate limiter per tenant
│   ├── pagination.py                # Pagination helper
│   ├── field_mapper.py             # Generic YAML-driven normalization engine
│   ├── transforms.py                # Named transform functions for non-rename logic
│   └── resilience.py                # tenacity retry policy for transient network failures
│
├── scripts/
│   ├── refresh_xero_token.sh       # Standalone curl-based token refresh, no app required
│   └── refresh_qbo_token.sh
│
└── tests/
    ├── unit/                        # Adapters, mapping, resilience, race conditions, etc.
    └── integration/                  # Route-level GET/POST/PUT tests + OAuth flow
```

---

## Getting Started

### Prerequisites
- Python 3.11+
- pip

### Installation

```bash
git clone <your-repo-url>
cd ERP_Connector

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt

cp .env.example .env          # macOS/Linux
# copy .env.example .env      # Windows
```

### Run the server

```bash
uvicorn main:app --reload --port 8080
```

Swagger UI -> http://localhost:8080/erp/docs
Connection status page -> http://localhost:8080/

---

## Authentication — one click, ever

No manual token entry, no hand-editing `.env` with secrets. One-time setup per environment:

1. **`/auth/setup`** — paste each ERP's Client ID / Client Secret (from the Xero or Intuit developer portal). Saved to a local, gitignored file (`.erp_credentials.json`) — never `.env`, never committed.
2. **`/auth/xero/login`** and/or **`/auth/qbo/login`** — one click, log in, click Allow. Xero's Tenant ID and QBO's Realm ID are captured automatically from the OAuth redirect — no manual lookup.
3. From then on, a background task (started in `main.py`'s lifespan) checks every ~2 minutes whether either token is close to expiring and refreshes it proactively — no more logins needed until the refresh token itself expires (Xero: ~60 days if unused; QBO: 100 days).

A per-ERP lock prevents the background refresh and any reactive refresh from colliding and invalidating each other's rotated tokens — both Xero and QBO invalidate a refresh token the instant it's redeemed once, so this matters.

If you want the service to be fully stateless/credential-agnostic instead, always pass your own valid token per request via `X-ERP-Token` / `X-ERP-Tenant-Id` headers — the local token store is a convenience layer, not a requirement.

**Standalone refresh, without the app running:** `scripts/refresh_xero_token.sh` and `scripts/refresh_qbo_token.sh` refresh a token with plain `curl` + `jq` — no Python, no browser, no running server required.

```bash
./scripts/refresh_xero_token.sh
./scripts/refresh_qbo_token.sh
```

**Important:** don't run these scripts *and* the app's background refresh loop against the same token file at the same time — whichever refreshes second will fail with `invalid_grant`, since the refresh token is single-use. Pick one mechanism as the source of truth.

---

## Environment Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ERP_TYPE` | Yes | — | `xero`, `quickbooks` (or `qbo`), or `mock` |
| `PORT` | No | `8080` | Server port |
| `LOG_LEVEL` | No | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `CORS_ORIGIN` | No | `*` | Restrict in production |
| `APP_VERSION` | No | `0.1.0` | Reported in `/erp/health` |
| `XERO_CLIENT_ID` / `XERO_CLIENT_SECRET` | For Xero | — | Only needed if not set via `/auth/setup` |
| `QBO_CLIENT_ID` / `QBO_CLIENT_SECRET` | For QBO | — | Only needed if not set via `/auth/setup` |

`.env` never needs live tokens — those are managed entirely through the auth flow described above.

---

## API Endpoints

All endpoints require two headers (except `/erp/health` and the `/auth/*` routes):

| Header | Description |
|--------|-------------|
| `X-ERP-Token` | OAuth 2.0 Bearer access token (auto-supplied by the local token store if omitted) |
| `X-ERP-Tenant-Id` | Xero `tenantId` or QBO `realmId` |

### Health
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/erp/health` | Liveness check |

### Invoices
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/erp/invoices` | List invoices. Query: `from`, `to`, `status` |
| GET | `/erp/invoices/{invoice_id}` | Get one invoice |
| POST | `/erp/invoices` | Create an invoice |
| PUT | `/erp/invoices/{invoice_id}` | Update an invoice |

### Bills
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/erp/bills` | List bills. Query: `from`, `to` |
| GET | `/erp/bills/{bill_id}` | Get one bill |
| POST | `/erp/bills` | Create a bill |

### Contacts
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/erp/contacts` | List contacts. Query: `type` (customer/supplier) |
| GET | `/erp/contacts/{contact_id}` | Get one contact — tries Customer then Vendor if `type` isn't given |
| POST | `/erp/contacts` | Create a contact |

### Accounts & Items
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/erp/accounts` | Full chart of accounts |
| GET | `/erp/items` | List items |

### Payments
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/erp/payments` | Record a payment against an invoice or bill |

### Response Envelope

Success (list):
```json
{
  "success": true,
  "erp": "xero",
  "correlationId": "req-abc-123",
  "count": 42,
  "data": [ ]
}
```

Error:
```json
{
  "success": false,
  "error": "TOKEN_EXPIRED",
  "message": "Access token has expired. Please refresh and retry.",
  "erp": "xero",
  "correlationId": "req-abc-123",
  "timestamp": "2026-07-23T08:00:00Z"
}
```

---

## Architecture

```
Client request
      |
      v
Auth + rate limit   --> validates/refreshes token, throttles per tenant
      |
      v
Adapter registry    --> picks Xero or QBO adapter (decorator-based, no if/elif)
      |
      v
ERP adapter         --> calls the real Xero/QBO API, auto-retries transient failures
      |
      v
Field mapper        --> YAML config + named transforms --> common schema
      |
      v
Normalized response --> identical shape, either ERP
```

Running independently alongside every request: a background loop refreshes both ERPs' tokens proactively every ~2 minutes, so the reactive refresh path rarely has to fire.

---

## Adding a New ERP

Normalization is config-driven — see `config/mappings/*.yaml` and `utils/field_mapper.py`. Most new fields are a plain rename in YAML; only genuinely ERP-specific logic needs a small named function in `utils/transforms.py`.

Steps:
1. Write `adapters/<new_erp>.py`, subclassing `BaseERPAdapter`, decorated with `@register_adapter("name")`.
2. Write `config/mappings/<new_erp>.yaml` for field renames.
3. Add one import line in `adapters/__init__.py` so the adapter registers itself.

The HTTP/auth/pagination layer still needs to be written per ERP — that part is inherently ERP-specific network code, not configuration.

---

## Running Tests

```bash
pytest -v
```

104 tests across unit and integration suites — including full route-level GET/POST/PUT tests against both real ERP shapes (mocked HTTP), the OAuth setup/login/callback flow, cross-ERP response-consistency checks, and regression tests for every bug found during development.

```bash
pytest -v --tb=short
pyflakes .
```

---

## Current Build Status

| Component | Status |
|-----------|--------|
| Core routing, error handling, correlation IDs | Complete |
| Xero adapter | Complete |
| QBO adapter | Complete |
| Mock adapter (offline testing) | Complete |
| Config-driven field mapping | Complete |
| Decorator-based adapter registry | Complete |
| Automatic OAuth login + token refresh | Complete |
| Background proactive token refresh | Complete |
| Retry/resilience on transient network errors | Complete (QBO fully; Xero partial) |
| Standalone curl refresh scripts | Complete |
| Test suite | 104/104 passing |

---

## Known Limitations & Future Work

- **No database** — by design; this is a stateless pass-through, not a system of record.
- **No webhooks** — pull-only REST interface today; push-based event ingestion would be a separate feature.
- **Xero doesn't yet share QBO's centralized retry-wrapped HTTP client** — QBO funnels all calls through one class, making retry-wrapping safe and complete; Xero has more scattered call sites, so retry coverage there is partial.
- **Token refresh uses a blocking HTTP call run in a thread pool**, not a fully async client — acceptable at current scale, worth revisiting under heavy concurrent load.
- **Single-instance token storage** — tokens live in a local file, correct for one running instance. A Redis/Vault-backed token store would only be needed for multi-instance deployment.
- **Reverse (write-direction) YAML mapping** — reads are fully config-driven; write payloads are still adapter-specific Python. A worthwhile future refactor, deferred to avoid risking currently-working, tested code.

---

*ERP Connector — Python 3.12, FastAPI, July 2026*
