import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from utils.errors import (
    ERPConnectorError,
    handle_erp_connector_error,
    raise_token_expired,
    raise_not_found,
    raise_invalid_request,
    raise_erp_unavailable,
    raise_erp_timeout,
    raise_rate_limit_timeout,
    build_error_response
)

# Test convenience raisers
def test_raise_token_expired():
    with pytest.raises(ERPConnectorError) as exc_info:
        raise_token_expired("xero")
    assert exc_info.value.error_code == "TOKEN_EXPIRED"
    assert exc_info.value.http_status == 401
    assert exc_info.value.erp == "xero"
    assert exc_info.value.message == "Access token has expired. Please refresh and retry."


def test_raise_not_found():
    with pytest.raises(ERPConnectorError) as exc_info:
        raise_not_found("quickbooks", "Invoice-123")
    assert exc_info.value.error_code == "NOT_FOUND"
    assert exc_info.value.http_status == 404
    assert exc_info.value.erp == "quickbooks"
    assert "Invoice-123" in exc_info.value.message


def test_raise_invalid_request():
    with pytest.raises(ERPConnectorError) as exc_info:
        raise_invalid_request("xero", "Invalid field 'amount'")
    assert exc_info.value.error_code == "INVALID_REQUEST"
    assert exc_info.value.http_status == 400
    assert exc_info.value.erp == "xero"
    assert exc_info.value.message == "Invalid field 'amount'"


def test_raise_erp_unavailable():
    with pytest.raises(ERPConnectorError) as exc_info:
        raise_erp_unavailable("xero")
    assert exc_info.value.error_code == "ERP_UNAVAILABLE"
    assert exc_info.value.http_status == 502
    assert exc_info.value.erp == "xero"


def test_raise_erp_timeout():
    with pytest.raises(ERPConnectorError) as exc_info:
        raise_erp_timeout("quickbooks")
    assert exc_info.value.error_code == "ERP_TIMEOUT"
    assert exc_info.value.http_status == 504
    assert exc_info.value.erp == "quickbooks"


def test_raise_rate_limit_timeout():
    with pytest.raises(ERPConnectorError) as exc_info:
        raise_rate_limit_timeout("xero")
    assert exc_info.value.error_code == "RATE_LIMIT_TIMEOUT"
    assert exc_info.value.http_status == 429
    assert exc_info.value.erp == "xero"


# Test build_error_response shape and types
def test_build_error_response():
    resp = build_error_response("TEST_CODE", "Test message", "xero", 418)
    assert resp.status_code == 418
    
    import json
    data = json.loads(resp.body.decode("utf-8"))
    assert data["success"] is False
    assert data["error"] == "TEST_CODE"
    assert data["message"] == "Test message"
    assert data["erp"] == "xero"
    assert "timestamp" in data
    assert data["timestamp"].endswith("Z")


# Test integration via FastAPI TestClient
def test_exception_handler_integration():
    app = FastAPI()
    app.add_exception_handler(ERPConnectorError, handle_erp_connector_error)

    @app.get("/trigger")
    def trigger_error():
        raise_token_expired("xero")

    client = TestClient(app)
    response = client.get("/trigger")
    
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "TOKEN_EXPIRED"
    assert data["erp"] == "xero"
    assert "timestamp" in data
