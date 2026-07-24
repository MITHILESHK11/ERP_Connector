"""
Regression test: QBOHttpClient must never send Content-Type: application/json
on GET requests, which have no body. Real-world Intuit bug reports show this
can cause the API gateway to attempt parsing an empty body as JSON and fail
with a generic "invalid or unsupported property" error (fault code 2010) —
even on a perfectly well-formed read request. POST requests genuinely have a
JSON body and must keep sending Content-Type.
"""
from unittest.mock import patch, MagicMock
import pytest
from adapters.qbo import QBOHttpClient


@pytest.mark.asyncio
async def test_get_entity_request_has_no_content_type_header():
    captured = {}

    async def fake_request(self, method, url, **kwargs):
        captured["method"] = method
        captured["headers"] = kwargs.get("headers", {})
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"Customer": {"Id": "1"}}
        return response

    with patch.object(QBOHttpClient, "_do_request", fake_request):
        client = QBOHttpClient(token="tok", realm_id="realm-1")
        await client.get_entity("customer", "1")

    assert captured["method"] == "GET"
    assert "Content-Type" not in captured["headers"]
    assert captured["headers"]["Accept"] == "application/json"


@pytest.mark.asyncio
async def test_query_request_has_no_content_type_header():
    captured = {}

    async def fake_request(self, method, url, **kwargs):
        captured["headers"] = kwargs.get("headers", {})
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"QueryResponse": {}}
        return response

    with patch.object(QBOHttpClient, "_do_request", fake_request):
        client = QBOHttpClient(token="tok", realm_id="realm-1")
        await client.query("SELECT * FROM Customer")

    assert "Content-Type" not in captured["headers"]


@pytest.mark.asyncio
async def test_post_entity_request_still_has_content_type_header():
    captured = {}

    async def fake_request(self, method, url, **kwargs):
        captured["method"] = method
        captured["headers"] = kwargs.get("headers", {})
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"Customer": {"Id": "1"}}
        return response

    with patch.object(QBOHttpClient, "_do_request", fake_request):
        client = QBOHttpClient(token="tok", realm_id="realm-1")
        await client.post_entity("customer", {"DisplayName": "Acme"})

    assert captured["method"] == "POST"
    assert captured["headers"]["Content-Type"] == "application/json"
