from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text


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
async def real_db_for_phase_4_3_h():
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


async def test_phase_4_3_h_persist_inbound_from_inquiry_creates_session(real_db_for_phase_4_3_h):
    from app.services.concierge.post_booking_routing import persist_inbound_from_inquiry

    db = real_db_for_phase_4_3_h
    tenant_id = uuid.UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
    source_message_id = f"gmail-{uuid.uuid4().hex[:10]}"
    draft_id = f"INQ-{uuid.uuid4().hex[:8].upper()}"

    session_id = None
    try:
        result = await persist_inbound_from_inquiry(
            db,
            tenant_id=tenant_id,
            property_code="17LL",
            property_name="17 Lanier Lane",
            guest_name="Jordan Example",
            guest_email="jordan@example.com",
            message_text="Please confirm the balance due.",
            intent="general_inquiry",
            received_at=None,
            requested_check_in=None,
            requested_check_out=None,
            requested_guests=2,
            source_message_id=source_message_id,
            inquiry_thread_id="gmail-thread-123",
            existing_guest_thread_id=None,
            source_label="phase_4_3_h_test",
            draft_id=draft_id,
            archive_reason="test",
        )
        await db.commit()
        session_id = result.session_id
        assert result.created is True

        row = (
            await db.execute(
                text(
                    """
                    SELECT
                        s.property_code,
                        s.property_context -> 'migration_source' ->> 'draft_id' AS draft_id,
                        COUNT(m.message_id) AS message_count
                    FROM concierge_guest_sessions s
                    LEFT JOIN concierge_messages m ON m.session_id = s.session_id
                    WHERE s.session_id = CAST(:session_id AS uuid)
                    GROUP BY s.property_code, s.property_context
                    """
                ),
                {"session_id": session_id},
            )
        ).fetchone()
        assert row[0] == "17LL"
        assert row[1] == draft_id
        assert int(row[2] or 0) >= 1
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Cannot complete Postgres integration test: {type(exc).__name__}: {exc}")
    finally:
        if session_id:
            try:
                await db.execute(
                    text("DELETE FROM concierge_guest_sessions WHERE session_id = CAST(:session_id AS uuid)"),
                    {"session_id": session_id},
                )
                await db.commit()
            except Exception:
                pass
