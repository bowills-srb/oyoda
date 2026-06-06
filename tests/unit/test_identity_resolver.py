from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.services.messaging.identity_resolver import (
    clear_identity_resolution_cache,
    resolve_guest_identity,
)


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_identity_resolution_cache()
    yield
    clear_identity_resolution_cache()


@pytest.mark.asyncio
async def test_resolve_guest_identity_identified_from_active_session():
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(
                    SimpleNamespace(
                        token="gh_test_123",
                        status="active",
                        reservation_id="res-123",
                        guest_name="Jordan Smith",
                        guest_email="jordan@example.com",
                        guest_phone="+15555550123",
                        property_code="SUNSET_1",
                        check_in=date(2026, 5, 24),
                        check_out=date(2026, 5, 28),
                    )
                )
            ]
        )
    )

    identity = await resolve_guest_identity(
        db=db,
        tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
        session_token="gh_test_123",
    )

    assert identity.state == "identified"
    assert identity.resolution_source == "session_token"
    assert identity.reservation_id == "res-123"
    assert identity.check_in_date == "2026-05-24"


@pytest.mark.asyncio
async def test_resolve_guest_identity_linked_from_pms_booking_email_match():
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(
                    SimpleNamespace(
                        external_id="res-456",
                        guest_first_name="Casey",
                        guest_last_name="Guest",
                        guest_email="casey@example.com",
                        guest_phone="+15555550124",
                        check_in=date(2026, 6, 1),
                        check_out=date(2026, 6, 5),
                    )
                ),
            ]
        )
    )

    identity = await resolve_guest_identity(
        db=db,
        tenant_id="11111111-1111-1111-1111-111111111111",
        guest_email="casey@example.com",
    )

    assert identity.state == "linked"
    assert identity.resolution_source == "reservation_match"
    assert identity.reservation_id == "res-456"
    assert identity.guest_name == "Casey Guest"


@pytest.mark.asyncio
async def test_resolve_guest_identity_marks_masked_ota_email_pseudonymous():
    db = SimpleNamespace(execute=AsyncMock(side_effect=[_Result(None)]))

    identity = await resolve_guest_identity(
        db=db,
        tenant_id="11111111-1111-1111-1111-111111111111",
        guest_email="abc123@messages.vrbo.com",
        guest_name="Taylor",
    )

    assert identity.state == "pseudonymous"
    assert identity.resolution_source == "ota_masked_email"


@pytest.mark.asyncio
async def test_resolve_guest_identity_defaults_to_anonymous():
    db = SimpleNamespace(execute=AsyncMock(side_effect=[_Result(None)]))

    identity = await resolve_guest_identity(
        db=db,
        tenant_id="11111111-1111-1111-1111-111111111111",
        guest_email="",
        guest_name="",
    )

    assert identity.state == "anonymous"
    assert identity.resolution_source == "none"
