"""
utils/resilience.py
====================
Retry policy for transient failures talking to upstream ERPs (Xero/QBO).

Scope, deliberately: this retries only true transport-level blips —
connection timeouts and network errors — NOT validation errors, auth
failures, or "not found" (retrying those would just waste time re-hitting
the same wrong request). Status-code-based retries (429/502/503/504) are a
reasonable next step but require each adapter's response-checking code to
raise before returning, which is a larger change; kept out of scope here to
avoid touching working request/response handling.

Retry delays are intentionally SHORT (well under a second total) — ERP
sandbox/production APIs typically recover from a blip almost immediately,
and long backoff (the tenacity default of several seconds per attempt) would
make real user-facing requests noticeably slow, and would make test suites
that exercise the timeout/error path painfully slow too.
"""
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    retry_if_exception_type,
)

# Retry up to 3 total attempts, waiting a small random amount (0.1s-0.5s)
# between them, only for connection timeouts / network-level errors.
erp_transient_retry = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(min=0.1, max=0.5),
    retry=retry_if_exception_type((httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError)),
)
