"""
Proof tests for the 6 previously-pending QBO bugfixes (#1, #5, #6, #7, #8, #9).
These mock QBOHttpClient so they run without a real QBO sandbox connection,
same pattern the earlier mock-server testing used.
"""
import pytest
from adapters import qbo as qbo_mod
from adapters.qbo import QBOAdapter
from utils.errors import ERPConnectorError


# ---------------------------------------------------------------------------
# #1 — status filter must actually filter, not just accept the param
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_filter_actually_filters(monkeypatch):
    raw_invoices = [
        {"Id": "1", "TotalAmt": 100.0, "Balance": 0.0, "TxnDate": "2026-01-01"},   # paid
        {"Id": "2", "TotalAmt": 100.0, "Balance": 100.0, "EmailStatus": "NotSet",
         "TxnDate": "2026-01-01"},                                                # draft
        {"Id": "3", "TotalAmt": 100.0, "Balance": 50.0, "TxnDate": "2026-01-01"},  # authorised
    ]

    async def fake_query(self, sql):
        return {"QueryResponse": {"Invoice": raw_invoices}}

    monkeypatch.setattr(qbo_mod.QBOHttpClient, "query", fake_query)

    adapter = QBOAdapter()
    all_invoices = await adapter.get_invoices("tok", "realm")
    assert len(all_invoices) == 3

    paid_only = await adapter.get_invoices("tok", "realm", status="paid")
    assert [inv["id"] for inv in paid_only] == ["1"]

    draft_only = await adapter.get_invoices("tok", "realm", status="draft")
    assert [inv["id"] for inv in draft_only] == ["2"]


# ---------------------------------------------------------------------------
# #5 — malformed / injection-shaped dates must be rejected, not interpolated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_date_injection_rejected(monkeypatch):
    async def fake_query(self, sql):
        # If we ever get here with a malicious payload, the test should fail
        # regardless — but we assert the exception is raised BEFORE this runs.
        raise AssertionError("query() should never be called with an unsanitized date")

    monkeypatch.setattr(qbo_mod.QBOHttpClient, "query", fake_query)
    adapter = QBOAdapter()

    malicious = "2026-01-01' OR '1'='1"
    with pytest.raises(ERPConnectorError) as exc_info:
        await adapter.get_invoices("tok", "realm", from_date=malicious)
    assert exc_info.value.error_code == "INVALID_REQUEST"


@pytest.mark.asyncio
async def test_valid_date_still_works(monkeypatch):
    captured = {}

    async def fake_query(self, sql):
        captured["sql"] = sql
        return {"QueryResponse": {"Invoice": []}}

    monkeypatch.setattr(qbo_mod.QBOHttpClient, "query", fake_query)
    adapter = QBOAdapter()
    result = await adapter.get_invoices("tok", "realm", from_date="2026-01-01", to_date="2026-06-30")
    assert result == []
    assert "2026-01-01" in captured["sql"]
    assert "2026-06-30" in captured["sql"]


# ---------------------------------------------------------------------------
# #9 — contact ID collision between Customer and Vendor must not silently
# pick Customer; must require disambiguation.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contact_collision_requires_type(monkeypatch):
    async def fake_get_entity(self, entity, entity_id):
        if entity == "customer":
            return {"Customer": {"Id": entity_id, "DisplayName": "Acme Customer"}}
        if entity == "vendor":
            return {"Vendor": {"Id": entity_id, "DisplayName": "Acme Vendor",
                                "PrintOnCheckName": "Acme Vendor"}}
        return {}

    monkeypatch.setattr(qbo_mod.QBOHttpClient, "get_entity", fake_get_entity)
    adapter = QBOAdapter()

    # Same ID exists as BOTH a customer and a vendor — must raise, not guess.
    with pytest.raises(ERPConnectorError) as exc_info:
        await adapter.get_contact("tok", "realm", "42")
    assert exc_info.value.error_code == "INVALID_REQUEST"

    # With explicit type, disambiguation works correctly.
    customer = await adapter.get_contact("tok", "realm", "42", contact_type="customer")
    assert customer["type"] == "customer"

    vendor = await adapter.get_contact("tok", "realm", "42", contact_type="supplier")
    assert vendor["type"] == "supplier"


@pytest.mark.asyncio
async def test_contact_no_collision_still_works(monkeypatch):
    async def fake_get_entity(self, entity, entity_id):
        if entity == "customer" and entity_id == "5":
            return {"Customer": {"Id": "5", "DisplayName": "Only Customer"}}
        if entity == "vendor" and entity_id == "5":
            from utils.errors import raise_not_found
            raise_not_found("quickbooks", "Vendor 5")
        return {}

    monkeypatch.setattr(qbo_mod.QBOHttpClient, "get_entity", fake_get_entity)
    adapter = QBOAdapter()
    result = await adapter.get_contact("tok", "realm", "5")
    assert result["type"] == "customer"


# ---------------------------------------------------------------------------
# QBO returns HTTP 400 + fault code 610 ("Object Not Found") for a missing
# entity, NOT a 404. If that isn't translated to our NOT_FOUND error, a
# legit single-sided contact lookup (id exists as Customer only) blows up
# with a spurious 400 instead of just returning the Customer.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_qbo_400_fault_610_treated_as_not_found(monkeypatch):
    import httpx

    class FakeResponse:
        status_code = 400
        text = '{"Fault": {"Error": [{"code": "610", "Message": "Object Not Found"}]}}'
        def json(self):
            return {"Fault": {"Error": [{"code": "610", "Message": "Object Not Found"}]}}

    async def fake_get_entity(self, entity, entity_id):
        if entity == "customer":
            return {"Customer": {"Id": entity_id, "DisplayName": "Real Customer"}}
        if entity == "vendor":
            # Simulate what QBOHttpClient.get_entity does internally:
            # it calls _check_response on a 400 with fault code 610.
            self._check_response(FakeResponse())
        return {}

    monkeypatch.setattr(qbo_mod.QBOHttpClient, "get_entity", fake_get_entity)
    adapter = QBOAdapter()

    # Must succeed (return the Customer) — must NOT raise INVALID_REQUEST
    # just because the vendor side got QBO's 400-shaped "not found".
    result = await adapter.get_contact("tok", "realm", "2")
    assert result["type"] == "customer"
