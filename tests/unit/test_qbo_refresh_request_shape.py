"""
Regression test for a real bug: QBO's refresh_access_token() used to send
client_id/client_secret BOTH in the Authorization: Basic header AND in the
POST body. Intuit's token endpoint rejects that combination with 401,
regardless of whether the credentials themselves are correct — which is
exactly why "I changed the client secret and it's still failing" didn't
help; the request shape itself was wrong.
"""
from unittest.mock import patch, MagicMock
import token_manager


def test_qbo_refresh_request_does_not_duplicate_credentials_in_body():
    captured = {}

    def fake_post(url, headers=None, auth=None, data=None, timeout=None):
        captured["auth"] = auth
        captured["data"] = data
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = lambda: None
        response.json.return_value = {"access_token": "new-tok", "refresh_token": "new-refresh"}
        return response

    with patch("httpx.post", side_effect=fake_post):
        result = token_manager.refresh_access_token(
            "quickbooks", "old-refresh-tok", "my-client-id", "my-client-secret"
        )

    assert result == "new-tok"
    # Credentials must be in the Basic Auth tuple...
    assert captured["auth"] == ("my-client-id", "my-client-secret")
    # ...and NEVER also duplicated in the request body.
    assert "client_id" not in captured["data"]
    assert "client_secret" not in captured["data"]
    assert captured["data"]["grant_type"] == "refresh_token"
    assert captured["data"]["refresh_token"] == "old-refresh-tok"
