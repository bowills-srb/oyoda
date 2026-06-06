"""Real-Postgres integration tests for record_rich_context_shadow_observation."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.messaging_brain.agents.rich_context_shadow_store import (
    record_rich_context_shadow_observation,
)


try:
    from app.db.session import SessionLocal

    _SESSION_LOCAL_AVAILABLE = True
except Exception:
    SessionLocal = None  # type: ignore[assignment]
    _SESSION_LOCAL_AVAILABLE = False


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not _SESSION_LOCAL_AVAILABLE,
        reason="SessionLocal not importable",
    ),
]


@pytest_asyncio.fixture
async def real_db_for_shadow():
    if SessionLocal is None:
        pytest.skip("SessionLocal not available")

    session = SessionLocal()
    ready = False
    try:
        try:
            await session.execute(text("SELECT 1"))
        except Exception as exc:
            pytest.skip(f"Postgres unreachable: {exc}")

        await session.execute(
            text(
                "DELETE FROM rich_context_shadow_observations "
                "WHERE tenant_id LIKE 'shadow-test-%'"
            )
        )
        await session.commit()
        ready = True

        yield session
    finally:
        try:
            if ready:
                await session.execute(
                    text(
                        "DELETE FROM rich_context_shadow_observations "
                        "WHERE tenant_id LIKE 'shadow-test-%'"
                    )
                )
                await session.commit()
        finally:
            try:
                await session.close()
            except Exception:
                pass


async def test_writer_inserts_row_with_full_values(real_db_for_shadow):
    await record_rich_context_shadow_observation(
        real_db_for_shadow,
        tenant_id="shadow-test-1",
        property_code="BH-001",
        message_id="shadow-test-msg-1",
        intent="amenity_question",
        richness_shadow={"score": 0.42, "missing": ["pet_policy"]},
        evidence_shadow=[
            {"source": "facts", "label": "pool", "text": "Heated", "score": 0.9},
        ],
        preferences_block_shadow="Guest prefers high floors.",
        shadow_exceptions={},
    )

    row = (
        await real_db_for_shadow.execute(
            text(
                """
                SELECT tenant_id, property_code, message_id, intent,
                       richness_shadow, evidence_shadow,
                       preferences_block_shadow, shadow_exceptions
                FROM rich_context_shadow_observations
                WHERE message_id = :mid
                """
            ),
            {"mid": "shadow-test-msg-1"},
        )
    ).first()

    assert row is not None
    assert row.tenant_id == "shadow-test-1"
    assert row.property_code == "BH-001"
    assert row.intent == "amenity_question"
    assert row.richness_shadow == {"score": 0.42, "missing": ["pet_policy"]}
    assert row.evidence_shadow == [
        {"source": "facts", "label": "pool", "text": "Heated", "score": 0.9},
    ]
    assert row.preferences_block_shadow == "Guest prefers high floors."
    assert row.shadow_exceptions == {}


async def test_writer_stores_empty_exceptions_as_jsonb_object(real_db_for_shadow):
    await record_rich_context_shadow_observation(
        real_db_for_shadow,
        tenant_id="shadow-test-2",
        property_code=None,
        message_id="shadow-test-msg-2",
        intent="general",
        richness_shadow={},
        evidence_shadow=[],
        preferences_block_shadow="",
        shadow_exceptions={},
    )

    row = (
        await real_db_for_shadow.execute(
            text(
                "SELECT shadow_exceptions FROM "
                "rich_context_shadow_observations WHERE message_id = :mid"
            ),
            {"mid": "shadow-test-msg-2"},
        )
    ).first()

    assert row.shadow_exceptions == {}


async def test_writer_stores_single_exception_under_correct_key(real_db_for_shadow):
    await record_rich_context_shadow_observation(
        real_db_for_shadow,
        tenant_id="shadow-test-3",
        property_code="BH-002",
        message_id="shadow-test-msg-3",
        intent="amenity_question",
        richness_shadow={"score": 0.5},
        evidence_shadow=[],
        preferences_block_shadow="",
        shadow_exceptions={
            "evidence": {"type": "RuntimeError", "message": "retrieval failed"},
        },
    )

    row = (
        await real_db_for_shadow.execute(
            text(
                "SELECT shadow_exceptions FROM "
                "rich_context_shadow_observations WHERE message_id = :mid"
            ),
            {"mid": "shadow-test-msg-3"},
        )
    ).first()

    assert row.shadow_exceptions == {
        "evidence": {"type": "RuntimeError", "message": "retrieval failed"},
    }
