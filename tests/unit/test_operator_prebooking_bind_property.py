from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.v1.endpoints.operator_prebooking import _bind_inquiry_property


class _FakeResult:
    def __init__(self, mapping=None):
        self._mapping = mapping

    def mappings(self):
        return self

    def first(self):
        return self._mapping


class _FakeSession:
    def __init__(self, inquiry_row):
        self.inquiry_row = inquiry_row
        self.calls = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params or {}))
        if "FROM pre_booking_inquiries" in sql and "SELECT draft_id, status, gmail_message_id, property_external_id" in sql:
          return _FakeResult(self.inquiry_row)
        return _FakeResult()

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_bind_inquiry_property_updates_inquiry_and_normalization(monkeypatch):
    session = _FakeSession(
        {
            "draft_id": "INQ-123",
            "status": "pending_review",
            "gmail_message_id": "gmail-123",
            "property_external_id": "",
        }
    )
    captured = {}

    async def _fake_lookup_property_for_binding(_db, *, tenant_id, property_code):
        assert tenant_id
        assert property_code == "17LL"
        return {"property_name": "Sea La Vie"}

    async def _fake_table_columns(_db, table_name):
        assert table_name == "pre_booking_inquiries"
        return {"property_external_id_source"}

    async def _fake_update_normalization_outcome(_db, tenant_id, source_channel, source_message_id, **kwargs):
        captured["tenant_id"] = tenant_id
        captured["source_channel"] = source_channel
        captured["source_message_id"] = source_message_id
        captured["kwargs"] = kwargs

    monkeypatch.setattr(
        "app.api.v1.endpoints.operator_prebooking._lookup_property_for_binding",
        _fake_lookup_property_for_binding,
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.operator_prebooking._table_columns",
        _fake_table_columns,
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.operator_prebooking.update_normalization_outcome",
        _fake_update_normalization_outcome,
    )

    result = await _bind_inquiry_property(
        session,
        tenant_id=str(uuid4()),
        operator_label="ops@example.com",
        draft_id="INQ-123",
        property_code="17LL",
        selected_candidate_value="Sea La Vie",
        selected_candidate_type="raw_property_mention",
        search_query="sea la vie",
    )

    assert result["ok"] is True
    assert result["property_code"] == "17LL"
    assert result["property_name"] == "Sea La Vie"
    assert session.commits == 1
    update_sql, update_params = session.calls[1]
    assert "UPDATE pre_booking_inquiries" in update_sql
    assert update_params["property_code"] == "17LL"
    audit = json.loads(update_params["audit"])
    assert audit["source"] == "operator_manual"
    assert captured["source_channel"] == "gmail"
    assert captured["source_message_id"] == "gmail-123"
    assert captured["kwargs"]["selected_property_code"] == "17LL"
    assert captured["kwargs"]["selected_property_match_type"] == "operator_manual"


@pytest.mark.asyncio
async def test_bind_inquiry_property_rejects_actioned_draft(monkeypatch):
    session = _FakeSession(
        {
            "draft_id": "INQ-123",
            "status": "replied",
            "gmail_message_id": "gmail-123",
            "property_external_id": "",
        }
    )

    async def _fake_lookup_property_for_binding(_db, *, tenant_id, property_code):
        return {"property_name": "Sea La Vie"}

    monkeypatch.setattr(
        "app.api.v1.endpoints.operator_prebooking._lookup_property_for_binding",
        _fake_lookup_property_for_binding,
    )

    result = await _bind_inquiry_property(
        session,
        tenant_id=str(uuid4()),
        operator_label="ops@example.com",
        draft_id="INQ-123",
        property_code="17LL",
    )

    assert result["ok"] is False
    assert result["code"] == "draft_already_actioned"
    assert session.commits == 0
