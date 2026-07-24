"""
Proves the fix for the "works fine for ~1 day, then breaks" bug: two
concurrent refresh attempts (the reactive get_valid_token() path and the
proactive background loop) must NOT both redeem the same refresh token.
Only one real refresh call should reach the ERP; the other should see the
already-refreshed token and skip.
"""
import threading
import time
import pytest
from unittest.mock import patch, MagicMock
import token_manager


@pytest.fixture(autouse=True)
def isolate_token_file(tmp_path, monkeypatch):
    monkeypatch.setattr(token_manager, "TOKEN_FILE", str(tmp_path / ".erp_tokens.json"))
    monkeypatch.setattr(token_manager, "XERO_LEGACY_FILE", str(tmp_path / ".xero_tokens.json"))
    monkeypatch.setattr(token_manager, "CREDENTIALS_FILE", str(tmp_path / ".erp_credentials.json"))
    # Fresh lock per test so tests don't interfere with each other.
    token_manager._refresh_locks["xero"] = threading.Lock()
    yield


def test_concurrent_refresh_calls_only_hit_the_erp_once():
    # Seed an expired-looking Xero token.
    token_manager.save_tokens(
        erp_type="xero",
        access_token="old-access",
        refresh_token="refresh-A",
        tenant_id="tenant-1",
        client_id="client-id",
        client_secret="client-secret",
    )
    # Force it to look expired
    all_tokens = token_manager.load_all_tokens()
    all_tokens["xero"]["saved_at"] = "2000-01-01T00:00:00"
    import json
    with open(token_manager.TOKEN_FILE, "w") as f:
        json.dump(all_tokens, f)

    call_count = {"n": 0}
    real_lock = threading.Lock()

    def fake_refresh(erp_type, refresh_token, client_id, client_secret):
        # Simulate real network latency so both threads are likely to
        # overlap without the lock.
        with real_lock:
            call_count["n"] += 1
            time.sleep(0.05)
            token_manager.save_tokens(
                erp_type=erp_type,
                access_token=f"new-access-{call_count['n']}",
                refresh_token=f"new-refresh-{call_count['n']}",
            )
            return f"new-access-{call_count['n']}"

    with patch.object(token_manager, "refresh_access_token", side_effect=fake_refresh):
        results = []

        def worker():
            results.append(token_manager.get_valid_token("xero"))

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    # The critical assertion: only ONE real refresh should have happened.
    # Before the fix, both threads could race past the "is it expired?"
    # check before either wrote back, causing 2 refresh calls against the
    # same now-shared refresh token — exactly the bug this fixes.
    assert call_count["n"] == 1
    # Both callers should still get a valid (the same) fresh access token back.
    assert results[0] == results[1] == "new-access-1"
