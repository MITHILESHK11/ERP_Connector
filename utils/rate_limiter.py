import asyncio
import time
from contextlib import asynccontextmanager
from config.settings import get_settings

# TODO Phase 1: Replace this in-memory dict with Redis INCR + EXPIRE 
# for multi-instance deployments. See Section 14.3 of the Build Guide.

class RateLimiter:
    """
    Per-tenant in-memory rate limiter using a sliding/fixed window token bucket algorithm.
    Enforces concurrency and request rate limits centrally across simultaneous callers.
    """
    def __init__(self):
        # Store state in an in-memory dict: { tenant_id: { "count": int, "window_start": float } }
        self.counters = {}
        # Locks per tenant to make updates thread/coroutine safe
        self._locks = {}
        # Semaphores per tenant for concurrency limiting (specifically QBO max 10 concurrent)
        self._semaphores = {}

    def _get_lock(self, tenant_id: str) -> asyncio.Lock:
        if tenant_id not in self._locks:
            self._locks[tenant_id] = asyncio.Lock()
        return self._locks[tenant_id]

    def _get_semaphore(self, tenant_id: str) -> asyncio.Semaphore:
        if tenant_id not in self._semaphores:
            self._semaphores[tenant_id] = asyncio.Semaphore(10)
        return self._semaphores[tenant_id]

    async def check_and_consume(
        self, tenant_id: str, limit_per_min: int, timeout_seconds: int = 30
    ) -> None:
        """
        Validates rate limit for a given tenant.
        If under limit: increments and returns immediately.
        If limit is exceeded: sleeps until the window expires, or raises rate_limit_timeout if
        waiting duration exceeds timeout_seconds.
        """
        now = time.time()
        lock = self._get_lock(tenant_id)

        async with lock:
            if tenant_id not in self.counters:
                self.counters[tenant_id] = {
                    "count": 1,
                    "window_start": now
                }
                return

            state = self.counters[tenant_id]
            elapsed = now - state["window_start"]

            # If window of 60 seconds has passed, reset the bucket
            if elapsed >= 60.0:
                state["count"] = 1
                state["window_start"] = now
                return

            # If within limit, increment and allow
            if state["count"] < limit_per_min:
                state["count"] += 1
                return

            # Exceeded limit; calculate wait time until window reset
            sleep_duration = 60.0 - elapsed
            if sleep_duration > timeout_seconds:
                from utils.errors import raise_rate_limit_timeout
                raise_rate_limit_timeout(get_settings().ERP_TYPE)

        # Release the lock during sleep so other requests can run/evaluate timeouts
        await asyncio.sleep(sleep_duration)

        # After sleeping, re-acquire lock to consume token in the new window
        async with lock:
            now = time.time()
            state = self.counters[tenant_id]
            elapsed = now - state["window_start"]
            if elapsed >= 60.0:
                state["count"] = 1
                state["window_start"] = now
            else:
                state["count"] += 1

    @asynccontextmanager
    async def limit_concurrency(self, tenant_id: str, timeout_seconds: int = 30):
        """
        Context manager to limit concurrency for a given tenant (e.g., max 10 concurrent for QBO).
        """
        settings = get_settings()
        if settings.ERP_TYPE == "quickbooks":
            sem = self._get_semaphore(tenant_id)
            try:
                await asyncio.wait_for(sem.acquire(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                from utils.errors import raise_rate_limit_timeout
                raise_rate_limit_timeout("quickbooks")
            try:
                yield
            finally:
                sem.release()
        else:
            yield

    def clear(self) -> None:
        """
        Clears all in-memory tenant counters, locks, and semaphores. Used in test teardowns.
        """
        self.counters.clear()
        self._locks.clear()
        self._semaphores.clear()


# Module-level singleton
rate_limiter = RateLimiter()


async def check_rate_limit(tenant_id: str) -> None:
    """
    Wrapper function used by routes and dependencies to enforce configured limits.
    """
    if not tenant_id:
        return
    settings = get_settings()
    limit = 60 if settings.ERP_TYPE == "xero" else 500
    await rate_limiter.check_and_consume(tenant_id, limit)
