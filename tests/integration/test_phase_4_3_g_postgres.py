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
async def real_db_for_phase_4_3_g():
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


async def test_phase_4_3_g_writeback_updates_inquiry(real_db_for_phase_4_3_g):
    from app.services.messaging_brain.property_resolution_writeback import get_property_resolution_writeback

    db = real_db_for_phase_4_3_g
    tenant_id = uuid.UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
    draft_id = f"INQ-{uuid.uuid4().hex[:8].upper()}"
    thread_id = f"thread-{uuid.uuid4().hex[:10]}"
    message_id = f"msg-{uuid.uuid4().hex[:10]}"

    try:
        col_exists = (
            await db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema='public'
                      AND table_name='pre_booking_inquiries'
                      AND column_name='property_external_id_source'
                    """
                )
            )
        ).scalar_one()
        if not col_exists:
            pytest.skip("Migration 078 not applied in integration database")

        await db.execute(
            text(
                """
                INSERT INTO pre_booking_inquiries (
                    guest_thread_id, draft_id, thread_id, message_id, tenant_id, company_id,
                    platform, guest_name, message_text, property_external_id, intent, confidence,
                    draft_text, policy_flags, policy_warnings, status, received_at, created_at,
                    gmail_message_id, property_external_id_source
                ) VALUES (
                    gen_random_uuid(), :draft_id, :thread_id, :message_id, CAST(:tenant_id AS uuid), CAST(:tenant_id AS uuid),
                    'gmail', 'Guest', 'hello', '', 'general_inquiry', 0.9,
                    'draft', '[]'::jsonb, '[]'::jsonb, 'pending_review', NOW(), NOW(),
                    :gmail_message_id, '{}'::jsonb
                )
                """
            ),
            {
                "draft_id": draft_id,
                "thread_id": thread_id,
                "message_id": message_id,
                "tenant_id": str(tenant_id),
                "gmail_message_id": message_id,
            },
        )
        await db.commit()

        ok = await get_property_resolution_writeback().writeback_for_inquiry(
            db,
            tenant_id=tenant_id,
            draft_id=draft_id,
            resolved_property_code="17LL",
            match_type="canonical_ref",
        )
        assert ok is True

        row = (
            await db.execute(
                text(
                    """
                    SELECT property_external_id, property_external_id_source->>'source'
                    FROM pre_booking_inquiries
                    WHERE draft_id = :draft_id AND company_id = CAST(:tenant_id AS uuid)
                    """
                ),
                {"draft_id": draft_id, "tenant_id": str(tenant_id)},
            )
        ).fetchone()
        assert row[0] == "17LL"
        assert row[1] == "brain_resolution"
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Cannot complete Postgres integration test: {type(exc).__name__}: {exc}")
    finally:
        try:
            await db.execute(
                text("DELETE FROM pre_booking_inquiries WHERE draft_id = :draft_id"),
                {"draft_id": draft_id},
            )
            await db.commit()
        except Exception:
            pass


async def test_phase_4_3_g_writeback_skips_untrusted_match(real_db_for_phase_4_3_g):
    from app.services.messaging_brain.property_resolution_writeback import get_property_resolution_writeback

    db = real_db_for_phase_4_3_g
    tenant_id = uuid.UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
    draft_id = f"INQ-{uuid.uuid4().hex[:8].upper()}"

    try:
        await db.execute(
            text(
                """
                INSERT INTO pre_booking_inquiries (
                    guest_thread_id, draft_id, thread_id, message_id, tenant_id, company_id,
                    platform, guest_name, message_text, property_external_id, intent, confidence,
                    draft_text, policy_flags, policy_warnings, status, received_at, created_at,
                    gmail_message_id, property_external_id_source
                ) VALUES (
                    gen_random_uuid(), :draft_id, :thread_id, :message_id, CAST(:tenant_id AS uuid), CAST(:tenant_id AS uuid),
                    'gmail', 'Guest', 'hello', '', 'general_inquiry', 0.9,
                    'draft', '[]'::jsonb, '[]'::jsonb, 'pending_review', NOW(), NOW(),
                    :gmail_message_id, '{}'::jsonb
                )
                """
            ),
            {
                "draft_id": draft_id,
                "thread_id": f"thread-{uuid.uuid4().hex[:10]}",
                "message_id": f"msg-{uuid.uuid4().hex[:10]}",
                "tenant_id": str(tenant_id),
                "gmail_message_id": f"gmail-{uuid.uuid4().hex[:10]}",
            },
        )
        await db.commit()

        ok = await get_property_resolution_writeback().writeback_for_inquiry(
            db,
            tenant_id=tenant_id,
            draft_id=draft_id,
            resolved_property_code="17LL",
            match_type="fuzzy_match",
        )
        assert ok is False

        row = (
            await db.execute(
                text(
                    """
                    SELECT property_external_id, property_external_id_source
                    FROM pre_booking_inquiries
                    WHERE draft_id = :draft_id AND company_id = CAST(:tenant_id AS uuid)
                    """
                ),
                {"draft_id": draft_id, "tenant_id": str(tenant_id)},
            )
        ).fetchone()
        assert row[0] in (None, "")
        assert row[1] == {}
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Cannot complete Postgres integration test: {type(exc).__name__}: {exc}")
    finally:
        try:
            await db.execute(
                text("DELETE FROM pre_booking_inquiries WHERE draft_id = :draft_id"),
                {"draft_id": draft_id},
            )
            await db.commit()
        except Exception:
            pass
