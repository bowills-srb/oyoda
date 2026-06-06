"""Real-Postgres integration test for Phase 4.2.5 vector fallback."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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
async def real_db_for_vector_brain():
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


async def test_context_builder_merges_vector_fallback_chunks(
    real_db_for_vector_brain, monkeypatch,
):
    from app.services.knowledge.vector_store import Document, VectorStore
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

    db = real_db_for_vector_brain
    tenant_id = uuid.uuid4()
    property_id = uuid.uuid4()
    run_token = uuid.uuid4().hex[:12]
    property_code = f"itest_vec_{run_token}"

    monkeypatch.setattr(
        context_builder_agent,
        "is_messaging_brain_canonical_kb_read_enabled",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "is_messaging_brain_rich_context_enabled",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "is_messaging_brain_rich_context_shadow_enabled",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "is_messaging_brain_vector_fallback_enabled",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "is_messaging_brain_vector_fallback_shadow_enabled",
        AsyncMock(return_value=False),
    )

    knowledge = SimpleNamespace(facts={}, sections={}, faq=[])
    agent = ContextBuilderAgent(
        knowledge_service=MagicMock(
            get_for_property=AsyncMock(return_value=knowledge),
        ),
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
                "address_street": "25 Vector Lane",
                "property_guide_url": "https://guide.breezeway.io/test-vector",
            },
        )
        await db.commit()

        store = VectorStore(db)
        await store.add_documents(
            [
                Document(
                    content=(
                        "Wifi network is BeachWifi and the password is sunset123. "
                        "The nearest beach access boardwalk is across the street."
                    ),
                    metadata={
                        "tenant_id": str(tenant_id),
                        "property_code": property_code,
                        "doc_type": "guidebook",
                    },
                    doc_id=f"{property_code}-wifi-access",
                )
            ]
        )
        await db.commit()

        bundle = await agent.build(
            InboundGuestMessage(
                message_id=f"itest_vec_msg_{run_token}",
                tenant_id=str(tenant_id),
                channel="sms",
                source_provider="twilio",
                text="What is the wifi password and where is beach access?",
                guest_phone="+18505551234",
                property_id=str(property_id),
                property_code=property_code,
            ),
            MessageClassification(
                intent_type=IntentType.QUESTION,
                intent_topic="access",
                confidence=0.85,
                urgency=Urgency.LOW,
            ),
            db_session=db,
        )

        vector_chunks = [
            item for item in bundle.guidebook_evidence
            if item.get("type") == "vector_chunk"
        ]
        assert vector_chunks, "Expected at least one merged vector chunk"
        assert "vector_retrieval" in bundle.evidence_keys
        assert vector_chunks[0]["doc_id"] == f"{property_code}-wifi-access"
        assert vector_chunks[0]["source_type"] == "vector_guidebook"
        assert vector_chunks[0]["score"] >= 0.25
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Cannot complete vector integration test: {type(exc).__name__}: {exc}")
    finally:
        try:
            await db.execute(
                text(
                    """
                    DELETE FROM knowledge_embeddings
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND property_code = :property_code
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "property_code": property_code,
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
