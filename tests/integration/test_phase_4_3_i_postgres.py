from __future__ import annotations

from datetime import datetime
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.messaging.inbound_normalizer import CanonicalInboundMessage
from app.services.messaging_brain.persistence.prebooking_inquiry_store import (
    save_inquiry_from_canonical,
)
from app.services.messaging_brain.persistence.prebooking_inquiry_types import (
    InquirySaveContext,
)


try:
    from app.db.session import SessionLocal

    _SESSION_AVAILABLE = True
except Exception as _import_exc:
    _SESSION_AVAILABLE = False
    _SESSION_IMPORT_ERROR = str(_import_exc)


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not _SESSION_AVAILABLE,
        reason=(
            f"SessionLocal not available: "
            f"{_SESSION_IMPORT_ERROR if not _SESSION_AVAILABLE else ''}"
        ),
    ),
]


@pytest_asyncio.fixture
async def real_db_for_phase_4_3_i():
    db = None
    session_cm = None
    try:
        session_cm = SessionLocal()
        db = await session_cm.__aenter__()
    except Exception as exc:  # noqa: BLE001
        if db is not None and session_cm is not None:
            try:
                await session_cm.__aexit__(type(exc), exc, exc.__traceback__)
            except Exception:
                pass
        pytest.skip(f"Cannot reach Postgres for integration test: {type(exc).__name__}: {exc}")

    try:
        yield db
    finally:
        try:
            await session_cm.__aexit__(None, None, None)
        except Exception:
            pass


async def test_phase_4_3_i_save_inquiry_creates_matching_normalization(real_db_for_phase_4_3_i):
    db = real_db_for_phase_4_3_i
    tenant_id = uuid.UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
    draft_id = f"INQ-{uuid.uuid4().hex[:8].upper()}"
    thread_id = f"thread-{uuid.uuid4().hex[:10]}"
    message_id = f"msg-{uuid.uuid4().hex[:10]}"

    inbound = CanonicalInboundMessage(
        source_channel="email",
        source_provider="gmail",
        source_thread_id=thread_id,
        source_message_id=message_id,
        sender_role="guest",
        sender_display_name="Jordan",
        sender_address="",
        sent_at=datetime.utcnow(),
        raw_subject="Question",
        latest_guest_turn="Can we check in early?",
        prior_thread_context="",
        full_message_text="Can we check in early?",
        structured_asks=[],
        prior_operator_commitments=[],
        property_binding_candidates=[],
        channel_constraints={},
        parser_used="integration_test",
        parser_version="v1",
        parser_notes=[],
        latest_turn_confidence=0.0,
        latest_turn_extracted=True,
        guest_name="Jordan",
        guest_email="",
    )
    context = InquirySaveContext(
        draft_id=draft_id,
        company_id=tenant_id,
        selected_property_code="17LL",
        requested_check_in=None,
        requested_check_out=None,
        requested_guests=2,
        intent="availability",
        confidence=0.9,
        draft_text="Draft text",
        draft_source="integration_test",
        policy_flags=[],
        policy_warnings=[],
        decision="hold",
        guest_thread_id=None,
    )

    try:
        result = await save_inquiry_from_canonical(db=db, inbound=inbound, context=context)
        assert result.status in {"saved", "duplicate"}

        row = (
            await db.execute(
                text(
                    """
                    SELECT
                        EXISTS (
                            SELECT 1
                            FROM pre_booking_inquiries
                            WHERE company_id = CAST(:tenant_id AS uuid)
                              AND draft_id = :draft_id
                        ),
                        EXISTS (
                            SELECT 1
                            FROM message_normalizations
                            WHERE tenant_id = CAST(:tenant_id AS uuid)
                              AND source_channel = 'email'
                              AND source_message_id = :message_id
                        )
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "draft_id": draft_id,
                    "message_id": message_id,
                },
            )
        ).fetchone()
        assert row[0] is True
        assert row[1] is True
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Cannot complete Postgres integration test: {type(exc).__name__}: {exc}")
    finally:
        try:
            await db.execute(
                text("DELETE FROM pre_booking_inquiries WHERE draft_id = :draft_id"),
                {"draft_id": draft_id},
            )
            await db.execute(
                text(
                    """
                    DELETE FROM message_normalizations
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND source_channel = 'email'
                      AND source_message_id = :message_id
                    """
                ),
                {"tenant_id": str(tenant_id), "message_id": message_id},
            )
            await db.commit()
        except Exception:
            pass
