"""
Proves the resilience retry wrapper actually retries on transient network
failures and succeeds, instead of just trusting the decorator is wired up.
"""
import httpx
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from adapters.qbo import QBOHttpClient


@pytest.mark.asyncio
async def test_qbo_get_entity_retries_then_succeeds_on_transient_timeout():
    success_response = MagicMock()
    success_response.status_code = 200
    success_response.json.return_value = {"Id": "1", "DisplayName": "Acme"}

    call_count = {"n": 0}

    async def flaky_get(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise httpx.ConnectTimeout("simulated transient timeout")
        return success_response

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request.side_effect = flaky_get
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        client = QBOHttpClient(token="tok", realm_id="realm-1")
        result = await client.get_entity("Customer", "1")

    assert result == {"Id": "1", "DisplayName": "Acme"}
    assert call_count["n"] == 2  # failed once, succeeded on retry


@pytest.mark.asyncio
async def test_qbo_get_entity_gives_up_after_repeated_timeouts():
    async def always_times_out(*args, **kwargs):
        raise httpx.ConnectTimeout("simulated persistent timeout")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request.side_effect = always_times_out
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        client = QBOHttpClient(token="tok", realm_id="realm-1")
        with pytest.raises(Exception):  # converted to ERPConnectorError by existing error handling
            await client.get_entity("Customer", "1")

    # Should have actually retried multiple times before giving up, not just once.
    assert mock_client.request.call_count == 3
