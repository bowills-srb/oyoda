"""Real-Postgres integration test for Phase 4.2 canonical KB read path."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

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
async def real_db_for_canonical_brain():
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
        pytest.skip(
            f"Cannot reach Postgres for integration test: "
            f"{type(exc).__name__}: {exc}"
        )

    try:
        yield db
    finally:
        try:
            await session_cm.__aexit__(None, None, None)
        except Exception:
            pass


async def test_context_builder_reads_canonical_scoped_knowledge(
    real_db_for_canonical_brain, monkeypatch,
):
    from app.services.messaging_brain.knowledge.scoped_knowledge_service import ScopedKnowledgeService
    from app.services.messaging_brain.agents import context_builder_agent
    from app.services.messaging_brain.agents.context_builder_agent import (
        ContextBuilderAgent,
    )
    from app.services.orchestration.messaging_brain_contracts import (
        InboundGuestMessage,
        IntentType,
        MessageClassification,
        Urgency,
    )

    db = real_db_for_canonical_brain
    tenant_id = uuid.uuid4()
    property_id = uuid.uuid4()
    run_token = uuid.uuid4().hex[:12]
    property_code = f"itest_can_{run_token}"

    monkeypatch.setattr(
        context_builder_agent,
        "is_messaging_brain_canonical_kb_read_enabled",
        AsyncMock(return_value=True),
    )

    try:
        await db.execute(
            text(
                """
                INSERT INTO properties (
                    id,
                    tenant_id,
                    property_code,
                    address_street,
                    property_guide_url,
                    is_active,
                    data_source
                ) VALUES (
                    CAST(:id AS uuid),
                    CAST(:tenant_id AS uuid),
                    :property_code,
                    :address_street,
                    :property_guide_url,
                    true,
                    'import'
                )
                """
            ),
            {
                "id": str(property_id),
                "tenant_id": str(tenant_id),
                "property_code": property_code,
                "address_street": "123 Canonical Way",
                "property_guide_url": "https://guide.breezeway.io/test-canonical",
            },
        )

        scoped = ScopedKnowledgeService()
        await scoped.write_scoped_knowledge(
            session=db,
            tenant_id=tenant_id,
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            scope_type="property",
            scope_target_id=property_id,
            topic_id="pet_policy",
            question_text="Are pets allowed?",
            answer_text="Dogs allowed with prior approval.",
            tags=["pet_policy"],
            source="guidebook_ingest_v2",
            metadata={"guidebook_url": "https://guide.breezeway.io/test-canonical"},
        )
        await scoped.write_scoped_knowledge(
            session=db,
            tenant_id=tenant_id,
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            scope_type="property",
            scope_target_id=property_id,
            topic_id=None,
            question_text="Where do we park?",
            answer_text="Two spaces in the driveway.",
            tags=["parking"],
            source="guidebook_ingest_v2",
            metadata={"guidebook_url": "https://guide.breezeway.io/test-canonical"},
        )
        await db.commit()

        bundle = await ContextBuilderAgent().build(
            InboundGuestMessage(
                message_id=f"itest_msg_{run_token}",
                tenant_id=str(tenant_id),
                channel="sms",
                source_provider="twilio",
                text="Can we bring our dog and where do we park?",
                guest_phone="+18505551234",
                property_id=str(property_id),
                property_code=property_code,
            ),
            MessageClassification(
                intent_type=IntentType.QUESTION,
                intent_topic="house_rules",
                confidence=0.8,
                urgency=Urgency.LOW,
            ),
            db_session=db,
        )

        assert bundle.operator_policies.get("pet_policy") == "not_allowed"
        assert bundle.property_knowledge.get("faq_count") == 2
        assert bundle.guidebook_knowledge.get("faq")
        assert bundle.guidebook_knowledge["faq"][0]["source"] == "guidebook_ingest_v2"
        assert "operator_policies.pet_policy" in bundle.evidence_keys
        assert "property_knowledge.faq" in bundle.evidence_keys
        assert "guidebook_knowledge" in bundle.evidence_keys
        assert "no_canonical_knowledge_for_property" not in bundle.missing_context

    finally:
        try:
            await db.execute(
                text(
                    """
                    DELETE FROM concierge_scoped_knowledge_history
                    WHERE knowledge_entry_id IN (
                        SELECT knowledge_entry_id
                        FROM concierge_scoped_knowledge
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND scope_target_id = CAST(:property_id AS uuid)
                    )
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "property_id": str(property_id),
                },
            )
            await db.execute(
                text(
                    """
                    DELETE FROM concierge_scoped_knowledge
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND scope_target_id = CAST(:property_id AS uuid)
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "property_id": str(property_id),
                },
            )
            await db.execute(
                text(
                    """
                    DELETE FROM properties
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:property_id AS uuid)
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "property_id": str(property_id),
                },
            )
            await db.commit()
        except Exception:
            pass
