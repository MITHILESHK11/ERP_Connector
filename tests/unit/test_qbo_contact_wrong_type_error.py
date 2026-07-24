"""
Regression test for a real bug: get_contact() checks both Customer and
Vendor to detect ID collisions between the two. But some QBO environments
return a generic validation fault (e.g. code 2010) instead of a clean
NOT_FOUND when probing the WRONG entity type for a real ID — previously,
that non-NOT_FOUND error was re-raised immediately, crashing the whole
request even though the Customer side had already matched successfully.
"""
import pytest
from unittest.mock import patch
import adapters.qbo as qbo_mod
from adapters.qbo import QBOAdapter
from utils.errors import ERPConnectorError, raise_invalid_request


@pytest.mark.asyncio
async def test_get_contact_survives_non_standard_error_on_wrong_type_probe():
    async def fake_get_entity(self, entity, entity_id):
        if entity == "customer":
            return {"Customer": {"Id": entity_id, "DisplayName": "Real Customer"}}
        if entity == "vendor":
            # Simulate QBO returning a generic validation fault (like the
            # real-world 2010 case) instead of a clean NOT_FOUND for an ID
            # that only exists as a Customer.
            raise_invalid_request("quickbooks", "Bad request — check field values")
        return {}

    with patch.object(qbo_mod.QBOHttpClient, "get_entity", fake_get_entity):
        adapter = QBOAdapter()
        result = await adapter.get_contact("tok", "realm", "59")

    assert result["type"] == "customer"
    assert result["id"] == "59"
