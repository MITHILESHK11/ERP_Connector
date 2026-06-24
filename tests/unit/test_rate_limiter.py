import pytest
import asyncio
import time
from utils.rate_limiter import rate_limiter
from utils.errors import ERPConnectorError

@pytest.fixture(autouse=True)
def cleanup_limiter():
    rate_limiter.clear()
    yield
    rate_limiter.clear()


@pytest.mark.anyio
async def test_rate_limiter_under_limit():
    # Consume 5 requests for tenant under limit of 10
    for _ in range(5):
        await rate_limiter.check_and_consume("tenant_abc", limit_per_min=10, timeout_seconds=1)
    
    assert "tenant_abc" in rate_limiter.counters
    assert rate_limiter.counters["tenant_abc"]["count"] == 5


@pytest.mark.anyio
async def test_rate_limiter_expires_window():
    # Consume 1 request
    await rate_limiter.check_and_consume("tenant_abc", limit_per_min=2, timeout_seconds=1)
    # Artificially shift the window back in time by 61 seconds
    rate_limiter.counters["tenant_abc"]["window_start"] -= 61.0
    
    # Consume another request — should reset counter instead of incrementing/waiting
    await rate_limiter.check_and_consume("tenant_abc", limit_per_min=2, timeout_seconds=1)
    assert rate_limiter.counters["tenant_abc"]["count"] == 1


@pytest.mark.anyio
async def test_rate_limiter_timeout_exceeded():
    # Consume limit
    await rate_limiter.check_and_consume("tenant_abc", limit_per_min=1, timeout_seconds=2)
    
    # Next request immediately exceeds limit and would need 60 seconds sleep, which is > 2 seconds timeout
    with pytest.raises(ERPConnectorError) as exc_info:
        await rate_limiter.check_and_consume("tenant_abc", limit_per_min=1, timeout_seconds=2)
        
    assert exc_info.value.error_code == "RATE_LIMIT_TIMEOUT"
    assert exc_info.value.http_status == 429


@pytest.mark.anyio
async def test_rate_limiter_wait_and_proceed():
    # Set limit to 2
    await rate_limiter.check_and_consume("tenant_abc", limit_per_min=2, timeout_seconds=2)
    await rate_limiter.check_and_consume("tenant_abc", limit_per_min=2, timeout_seconds=2)
    
    # Artificially modify window_start to make the window expire in 0.5 seconds
    rate_limiter.counters["tenant_abc"]["window_start"] = time.time() - 59.5
    
    start_time = time.time()
    # This should block for ~0.5 seconds and then succeed
    await rate_limiter.check_and_consume("tenant_abc", limit_per_min=2, timeout_seconds=2)
    duration = time.time() - start_time
    
    assert duration >= 0.4
    assert rate_limiter.counters["tenant_abc"]["count"] == 1


@pytest.mark.anyio
async def test_concurrency_limit_quickbooks(monkeypatch):
    # Mock settings.ERP_TYPE to quickbooks
    from config import settings
    class MockSettings:
        ERP_TYPE = "quickbooks"
        APP_VERSION = "0.1.0"
    
    # Use monkeypatch to patch get_settings
    monkeypatch.setattr("utils.rate_limiter.get_settings", lambda: MockSettings())
    
    # Acquire 10 concurrent slots
    slots = []
    for _ in range(10):
        ctx = rate_limiter.limit_concurrency("tenant_qbo", timeout_seconds=1)
        await ctx.__aenter__()
        slots.append(ctx)
        
    # Attempting to acquire the 11th should timeout and raise RATE_LIMIT_TIMEOUT
    with pytest.raises(ERPConnectorError) as exc_info:
        async with rate_limiter.limit_concurrency("tenant_qbo", timeout_seconds=1):
            pass
            
    assert exc_info.value.error_code == "RATE_LIMIT_TIMEOUT"
    assert exc_info.value.http_status == 429
    
    # Clean up entered context managers
    for ctx in slots:
        await ctx.__aexit__(None, None, None)
