"""Step 5: real-Postgres integration test for ContextBuilderAgent.build()
with rich context enabled.

Pins three cross-system contracts that the unit tests cannot:
  - ConciergeKnowledgeService.get_for_property returns a real shape that
    flows through extract_guidebook_knowledge ->
    to_legacy_prebooking_property_data -> the shared concierge helpers
    (assess_prebooking_knowledge_richness,
    retrieve_prebooking_property_evidence) without raising.
  - build_preference_context runs against a real session and returns ""
    when there is no operator learning data, without raising.
  - The full build() return populates guidebook_richness,
    guidebook_evidence, and learned_preferences_block consistent with
    the seeded data.

The feature flag check is patched at the Python layer rather than
seeded as a flag override row, because the cross-system contract we
care about is brain -> knowledge service -> concierge helpers, not
brain -> feature flag service. The flag service has its own tests.
"""

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
async def real_db_for_brain():
    """Real Postgres session for brain build()-path integration tests."""
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


async def test_build_rich_context_end_to_end_against_postgres(
    real_db_for_brain, monkeypatch,
):
    from app.services.concierge.knowledge_service import ConciergeKnowledgeService
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

    db = real_db_for_brain

    monkeypatch.setattr(
        context_builder_agent,
        "is_messaging_brain_rich_context_enabled",
        AsyncMock(return_value=True),
    )

    run_token = uuid.uuid4().hex[:12]
    tenant_id = uuid.uuid4()
    property_external_id = f"itest_prop_{run_token}"

    knowledge_service = ConciergeKnowledgeService()

    try:
        await knowledge_service.create_dashboard_entry(
            session=db,
            tenant_id=tenant_id,
            question="Is there wifi?",
            answer="Yes, the wifi password is beachhouse2024.",
            category="Amenities",
            property_external_id=property_external_id,
        )
        await knowledge_service.create_dashboard_entry(
            session=db,
            tenant_id=tenant_id,
            question="Where do we park?",
            answer="Two spaces in the driveway. No street parking.",
            category="Parking",
            property_external_id=property_external_id,
        )
        await knowledge_service.create_dashboard_entry(
            session=db,
            tenant_id=tenant_id,
            question="Are pets allowed?",
            answer="Sorry, no pets allowed at this property.",
            category="Policies",
            property_external_id=property_external_id,
        )

        agent = ContextBuilderAgent(knowledge_service=knowledge_service)

        message = InboundGuestMessage(
            message_id=f"itest_msg_{run_token}",
            tenant_id=str(tenant_id),
            channel="sms",
            source_provider="twilio",
            text="what is the wifi password please",
            guest_phone="+18505551234",
            property_code=property_external_id,
        )
        classification = MessageClassification(
            intent_type=IntentType.QUESTION,
            intent_topic="amenities",
            confidence=0.8,
            urgency=Urgency.LOW,
        )

        bundle = await agent.build(message, classification, db_session=db)

        assert bundle.guidebook_knowledge != {}, (
            "guidebook_knowledge should be populated from seeded concierge "
            "knowledge; empty result suggests get_for_property returned "
            "None or extract_guidebook_knowledge filtered everything out."
        )
        assert any(
            key in bundle.guidebook_knowledge
            for key in ("facts", "sections", "faq")
        )

        assert bundle.guidebook_richness != {}
        assert bundle.guidebook_richness.get("label") in {
            "rich", "medium", "sparse",
        }, (
            f"Expected non-'none' richness label given seeded content; "
            f"got {bundle.guidebook_richness!r}"
        )

        assert isinstance(bundle.guidebook_evidence, list)
        assert len(bundle.guidebook_evidence) >= 1, (
            "Expected at least one evidence hit for wifi-targeted message "
            "against seeded wifi FAQ; got empty list."
        )
        flat = " ".join(str(hit) for hit in bundle.guidebook_evidence).lower()
        assert "wifi" in flat or "beachhouse2024" in flat

        assert bundle.learned_preferences_block == "", (
            f"Expected empty preference block (no operator learning seeded); "
            f"got {bundle.learned_preferences_block!r}"
        )

        assert "guidebook_richness" in bundle.evidence_keys
        assert "guidebook_evidence" in bundle.evidence_keys
        assert "learned_preferences_block" not in bundle.evidence_keys

    finally:
        try:
            await db.execute(
                text(
                    "DELETE FROM concierge_knowledge "
                    "WHERE tenant_id = :tenant_id "
                    "AND property_external_id = :property_external_id"
                ),
                {
                    "tenant_id": str(tenant_id),
                    "property_external_id": property_external_id,
                },
            )
            await db.commit()
        except Exception:
            pass
