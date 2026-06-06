from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.messaging_brain.property_resolution_writeback import (
    TRUSTED_MATCH_TYPES,
    PropertyResolutionWriteback,
)


class _FakeResult:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeSession:
    def __init__(self, row=None):
        self.row = row
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params or {}))
        if "SELECT property_external_id" in sql:
            return _FakeResult(self.row)
        return _FakeResult()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_writeback_succeeds_for_trusted_match_type():
    session = _FakeSession(row=("",))
    service = PropertyResolutionWriteback()
    ok = await service.writeback_for_inquiry(
        session,
        tenant_id=uuid4(),
        draft_id="INQ-123",
        resolved_property_code="17LL",
        match_type="canonical_ref",
    )
    assert ok is True
    assert session.commits == 1
    update_sql, update_params = session.calls[1]
    assert "UPDATE pre_booking_inquiries" in update_sql
    assert update_params["new_property"] == "17LL"
    audit = json.loads(update_params["audit"])
    assert audit["source"] == "brain_resolution"
    assert audit["match_type"] == "canonical_ref"


@pytest.mark.asyncio
async def test_writeback_skips_for_untrusted_match_type():
    session = _FakeSession(row=("",))
    service = PropertyResolutionWriteback()
    ok = await service.writeback_for_inquiry(
        session,
        tenant_id=uuid4(),
        draft_id="INQ-123",
        resolved_property_code="17LL",
        match_type="fuzzy_match",
    )
    assert ok is False
    assert session.calls == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_writeback_noop_when_already_set():
    session = _FakeSession(row=("17LL",))
    service = PropertyResolutionWriteback()
    ok = await service.writeback_for_inquiry(
        session,
        tenant_id=uuid4(),
        draft_id="INQ-123",
        resolved_property_code="17LL",
        match_type="pms_exact",
    )
    assert ok is False
    assert len(session.calls) == 1
    assert session.commits == 0


@pytest.mark.asyncio
async def test_writeback_audit_records_previous_and_new():
    session = _FakeSession(row=("OLDPROP",))
    service = PropertyResolutionWriteback()
    ok = await service.writeback_for_inquiry(
        session,
        tenant_id=uuid4(),
        draft_id="INQ-123",
        resolved_property_code="NEWPROP",
        match_type="address_exact",
    )
    assert ok is True
    audit = json.loads(session.calls[1][1]["audit"])
    assert audit["previous_value"] == "OLDPROP"
    assert audit["new_value"] == "NEWPROP"


@pytest.mark.asyncio
async def test_writeback_handles_missing_inquiry_gracefully():
    session = _FakeSession(row=None)
    service = PropertyResolutionWriteback()
    ok = await service.writeback_for_inquiry(
        session,
        tenant_id=uuid4(),
        draft_id="INQ-404",
        resolved_property_code="17LL",
        match_type="community_unique",
    )
    assert ok is False
    assert session.commits == 0


@pytest.mark.asyncio
async def test_writeback_tenant_scoped():
    tenant_id = uuid4()
    session = _FakeSession(row=("",))
    service = PropertyResolutionWriteback()
    ok = await service.writeback_for_inquiry(
        session,
        tenant_id=tenant_id,
        draft_id="INQ-123",
        resolved_property_code="17LL",
        match_type=next(iter(TRUSTED_MATCH_TYPES)),
    )
    assert ok is True
    select_params = session.calls[0][1]
    update_params = session.calls[1][1]
    assert select_params["tid"] == str(tenant_id)
    assert update_params["tid"] == str(tenant_id)


@pytest.mark.asyncio
async def test_writeback_silent_on_empty_resolution():
    session = _FakeSession(row=("",))
    service = PropertyResolutionWriteback()
    ok = await service.writeback_for_inquiry(
        session,
        tenant_id=uuid4(),
        draft_id="INQ-123",
        resolved_property_code="",
        match_type="canonical_ref",
    )
    assert ok is False
    assert session.calls == []
