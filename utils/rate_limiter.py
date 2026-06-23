import asyncio
import time
from collections import defaultdict
from config.settings import get_settings

class TokenBucketRateLimiter:
    """
    In-memory token bucket rate limiter per ERP Tenant ID.
    If limits are exceeded, requests are queued (delayed) using async sleeps.
    """
    def __init__(self):
        # Map of tenant_id -> list of timestamps of requests made in the last 60s
        self.history = defaultdict(list)
        self._lock = asyncio.Lock()

    async def acquire(self, tenant_id: str):
        settings = get_settings()
        
        # Determine rate limit threshold based on active ERP configuration
        if settings.ERP_TYPE == "xero":
            limit = 60
        else:
            limit = 500

        async with self._lock:
            while True:
                now = time.time()
                # Clean up timestamps older than 60 seconds
                self.history[tenant_id] = [t for t in self.history[tenant_id] if now - t < 60.0]
                
                if len(self.history[tenant_id]) < limit:
                    self.history[tenant_id].append(now)
                    return
                
                # Window is full; calculate duration to sleep until the oldest request falls out
                oldest_timestamp = self.history[tenant_id][0]
                sleep_duration = 60.0 - (now - oldest_timestamp)
                
                if sleep_duration > 0:
                    # Release lock temporarily during the sleep to allow other tasks to check
                    self._lock.release()
                    try:
                        await asyncio.sleep(sleep_duration)
                    finally:
                        await self._lock.acquire()


# Singleton instance
_limiter = TokenBucketRateLimiter()

async def check_rate_limit(tenant_id: str):
    """
    Enforces rate-limiting for the given tenant ID.
    Blocks the execution flow if the request exceeds the limit.
    """
    if not tenant_id:
        return
    await _limiter.acquire(tenant_id)
