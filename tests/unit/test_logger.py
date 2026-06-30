import pytest
import json
import logging
from utils.logger import (
    request_id_var,
    generate_request_id,
    sanitise_log_data,
    StructuredJSONFormatter
)

def test_generate_request_id():
    req_id = generate_request_id()
    assert isinstance(req_id, str)
    assert len(req_id) == 36  # UUID length


def test_sanitise_log_data_redaction():
    # Test removal of sensitive keys
    raw_data = {
        "x-erp-token": "secret_abc123",
        "authorization": "Bearer token_xyz",
        "normal_field": "safe_value",
        "nested": {
            "password": "my_password",
            "safe_nested": 123
        }
    }
    
    cleaned = sanitise_log_data(raw_data)
    
    # Assert keys are removed or redacted
    assert "x-erp-token" not in cleaned
    assert "authorization" not in cleaned
    assert "password" not in cleaned["nested"]
    assert cleaned["normal_field"] == "safe_value"
    assert cleaned["nested"]["safe_nested"] == 123


def test_sanitise_log_data_bearer_pattern():
    # Test pattern replacement in values
    raw_message = "Call failed with header Authorization: Bearer xero_token_secret_12345"
    cleaned_message = sanitise_log_data(raw_message)
    assert "xero_token_secret_12345" not in cleaned_message
    assert cleaned_message == "Call failed with header Authorization: Bearer [REDACTED]"


def test_structured_json_formatter():
    formatter = StructuredJSONFormatter()
    
    # Mock a LogRecord
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Triggering test log with Authorization: Bearer my_secret_token",
        args=None,
        exc_info=None
    )
    
    # Set request id context variable
    token = request_id_var.set("test-request-id-123")
    try:
        formatted = formatter.format(record)
        log_data = json.loads(formatted)
        
        # Verify JSON properties
        assert log_data["level"] == "INFO"
        assert log_data["logger"] == "test_logger"
        assert log_data["request_id"] == "test-request-id-123"
        # Verify message redaction
        assert "my_secret_token" not in log_data["message"]
        assert log_data["message"] == "Triggering test log with Authorization: Bearer [REDACTED]"
        assert "timestamp" in log_data
    finally:
        request_id_var.reset(token)
