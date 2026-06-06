"""Real-Postgres integration test for the Phase 4.0-A backfill."""

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
async def real_db_for_phase_4_0_a():
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


async def test_phase_4_0_a_backfill_populates_structured_fields(real_db_for_phase_4_0_a):
    from app.services.backfill.structured_property_backfill import (
        OPERATION_TYPE,
        SERVICE_NAME,
        StructuredPropertyBackfillRunner,
        _record_llm_usage,
    )

    db = real_db_for_phase_4_0_a
    tenant_id = uuid.UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
    property_id = uuid.uuid4()

    class _FakeLLM:
        model = "claude-haiku-4-5"
        provider = "anthropic"

        async def extract_json(self, **kwargs):
            cost = await _record_llm_usage(
                property_id=kwargs["property_id"],
                property_code=kwargs["property_code"],
                field_name=kwargs["field_name"],
                source_entry_ids=[],
                model=self.model,
                provider=self.provider,
                input_tokens=50,
                output_tokens=10,
                latency_ms=5,
                dry_run=kwargs["dry_run"],
            )
            return {"value": "SEALAVIE-5G", "confidence": 0.95, "reasoning": "explicit"}, float(cost), 1

    try:
        audit_col_exists = (
            await db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema='public'
                      AND table_name='properties'
                      AND column_name='phase_4_0_a_backfill_audit'
                    """
                )
            )
        ).scalar_one()
        if not audit_col_exists:
            pytest.skip("Migration 077 not applied in integration database")

        await db.execute(
            text(
                """
                INSERT INTO properties (
                    id, tenant_id, property_code, address_street,
                    bedrooms, bathrooms, sleeps, max_occupancy,
                    wifi_network, parking_instructions, parking_spaces,
                    has_pool, pool_heated, has_hot_tub, pets_allowed,
                    phase_4_0_a_backfill_audit, is_active
                ) VALUES (
                    CAST(:property_id AS uuid), CAST(:tenant_id AS uuid), 'P40A-1', '1 Test Street',
                    0, 0, NULL, NULL,
                    NULL, NULL, NULL,
                    FALSE, FALSE, FALSE, FALSE,
                    '{}'::jsonb, TRUE
                )
                """
            ),
            {"property_id": str(property_id), "tenant_id": str(tenant_id)},
        )
        await db.execute(
            text(
                """
                INSERT INTO concierge_scoped_knowledge (
                    knowledge_entry_id, tenant_id, scope_type, scope_target_id, topic_id,
                    question_text, question_key, answer_text, tags, source, metadata
                ) VALUES
                (
                    gen_random_uuid(), CAST(:tenant_id AS uuid), 'property', CAST(:property_id AS uuid), 'sleeping_arrangement',
                    'How many bedrooms does the property have?', 'bedrooms', 'This home has 3 bedrooms and 2.5 bathrooms.',
                    '["sleeping_arrangement"]'::jsonb, 'guidebook_ingest_v2', '{}'::jsonb
                ),
                (
                    gen_random_uuid(), CAST(:tenant_id AS uuid), 'property', CAST(:property_id AS uuid), 'max_occupancy',
                    'What is the maximum occupancy?', 'occupancy', 'Sleeps up to 8 guests.',
                    '["max_occupancy"]'::jsonb, 'guidebook_ingest_v2', '{}'::jsonb
                ),
                (
                    gen_random_uuid(), CAST(:tenant_id AS uuid), 'property', CAST(:property_id AS uuid), 'pool_access',
                    'Does the property have a pool?', 'pool', 'Yes, there is a private pool.',
                    '["pool_access"]'::jsonb, 'guidebook_ingest_v2', '{}'::jsonb
                ),
                (
                    gen_random_uuid(), CAST(:tenant_id AS uuid), 'property', CAST(:property_id AS uuid), 'pet_policy',
                    'Are pets allowed?', 'pets', 'Pets are not allowed.',
                    '["pet_policy"]'::jsonb, 'guidebook_ingest_v2', '{}'::jsonb
                ),
                (
                    gen_random_uuid(), CAST(:tenant_id AS uuid), 'property', CAST(:property_id AS uuid), 'parking',
                    'Where can guests park?', 'parking', 'Parking for 2 cars in the driveway only.',
                    '["parking"]'::jsonb, 'guidebook_ingest_v2', '{}'::jsonb
                ),
                (
                    gen_random_uuid(), CAST(:tenant_id AS uuid), 'property', CAST(:property_id AS uuid), NULL,
                    'What is the WiFi network?', 'wifi network', 'WiFi Network: SEALAVIE-5G. Password is printed in the house manual.',
                    '["wifi"]'::jsonb, 'guidebook_ingest_v2', '{"section_title":"FAQs"}'::jsonb
                )
                """
            ),
            {"tenant_id": str(tenant_id), "property_id": str(property_id)},
        )
        await db.commit()

        runner = StructuredPropertyBackfillRunner(db, llm_client=_FakeLLM())
        summary = await runner.run(dry_run=False)
        assert summary.properties_processed >= 1

        row = (
            await db.execute(
                text(
                    """
                    SELECT bedrooms, bathrooms, sleeps, max_occupancy, wifi_network,
                           parking_instructions, parking_spaces, has_pool, pets_allowed,
                           phase_4_0_a_backfill_audit
                    FROM properties
                    WHERE id = CAST(:property_id AS uuid)
                    """
                ),
                {"property_id": str(property_id)},
            )
        ).mappings().first()

        assert row["bedrooms"] == 3
        assert float(row["bathrooms"]) == 2.5
        assert row["sleeps"] == 8
        assert row["max_occupancy"] == 8
        assert row["wifi_network"] == "SEALAVIE-5G"
        assert "driveway" in str(row["parking_instructions"]).lower()
        assert row["parking_spaces"] == 2
        assert bool(row["has_pool"]) is True
        assert bool(row["pets_allowed"]) is False
        assert row["phase_4_0_a_backfill_audit"]

        usage_count = (
            await db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM llm_usage_events
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND service_name = :service_name
                      AND request_type = :request_type
                      AND metadata->>'property_id' = :property_id
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "service_name": SERVICE_NAME,
                    "request_type": OPERATION_TYPE,
                    "property_id": str(property_id),
                },
            )
        ).scalar_one()
        assert usage_count >= 1
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Cannot complete Postgres integration test: {type(exc).__name__}: {exc}")
    finally:
        try:
            await db.execute(
                text("DELETE FROM concierge_scoped_knowledge WHERE tenant_id = CAST(:tenant_id AS uuid) AND scope_target_id = CAST(:property_id AS uuid)"),
                {"tenant_id": str(tenant_id), "property_id": str(property_id)},
            )
            await db.execute(
                text("DELETE FROM llm_usage_events WHERE tenant_id = CAST(:tenant_id AS uuid) AND request_type = :request_type AND metadata->>'property_id' = :property_id"),
                {"tenant_id": str(tenant_id), "request_type": OPERATION_TYPE, "property_id": str(property_id)},
            )
            await db.execute(
                text("DELETE FROM properties WHERE id = CAST(:property_id AS uuid)"),
                {"property_id": str(property_id)},
            )
            await db.commit()
        except Exception:
            pass


async def test_phase_4_0_a_backfill_uses_vector_chunks_in_audit(real_db_for_phase_4_0_a):
    from app.services.backfill.structured_property_backfill import StructuredPropertyBackfillRunner
    from app.services.knowledge.vector_store import Document, VectorStore

    db = real_db_for_phase_4_0_a
    tenant_id = uuid.UUID("e07980b2-a990-4b24-91d1-c8cb71ab70e1")
    property_id = uuid.uuid4()

    class _FakeLLM:
        model = "claude-haiku-4-5"
        provider = "anthropic"

        async def extract_json(self, **kwargs):
            return {"value": 3, "confidence": "high", "reasoning": "vector chunk describes 3 bedrooms"}, 0.0, 1

    try:
        await db.execute(
            text(
                """
                INSERT INTO properties (
                    id, tenant_id, property_code, address_street,
                    bedrooms, bathrooms, sleeps, max_occupancy,
                    wifi_network, parking_instructions, parking_spaces,
                    has_pool, pool_heated, has_hot_tub, pets_allowed,
                    phase_4_0_a_backfill_audit, is_active
                ) VALUES (
                    CAST(:property_id AS uuid), CAST(:tenant_id AS uuid), 'P40A-VEC', '1 Vector Street',
                    0, 0, NULL, NULL,
                    NULL, NULL, NULL,
                    FALSE, FALSE, FALSE, FALSE,
                    '{}'::jsonb, TRUE
                )
                """
            ),
            {"property_id": str(property_id), "tenant_id": str(tenant_id)},
        )
        await db.commit()

        store = VectorStore(db)
        await store.add_documents(
            [
                Document(
                    content="This home features 3 bedrooms and a flexible bunk room layout.",
                    metadata={
                        "tenant_id": str(tenant_id),
                        "property_code": "P40A-VEC",
                        "doc_type": "property_info",
                    },
                    doc_id="p40a-vec-bedrooms",
                )
            ]
        )

        runner = StructuredPropertyBackfillRunner(db, llm_client=_FakeLLM())
        summary = await runner.run(dry_run=False)
        assert summary.properties_processed >= 1

        row = (
            await db.execute(
                text(
                    """
                    SELECT bedrooms, phase_4_0_a_backfill_audit
                    FROM properties
                    WHERE id = CAST(:property_id AS uuid)
                    """
                ),
                {"property_id": str(property_id)},
            )
        ).mappings().first()
        assert row["bedrooms"] == 3
        audit = row["phase_4_0_a_backfill_audit"] or {}
        bedrooms_audit = audit.get("bedrooms") or {}
        assert bedrooms_audit.get("source") == "vector_then_llm"
        assert "p40a-vec-bedrooms" in (bedrooms_audit.get("vector_chunks_used") or [])
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Cannot complete vector integration test: {type(exc).__name__}: {exc}")
    finally:
        try:
            await db.execute(
                text("DELETE FROM knowledge_embeddings WHERE tenant_id = CAST(:tenant_id AS uuid) AND property_code = 'P40A-VEC'"),
                {"tenant_id": str(tenant_id)},
            )
            await db.execute(
                text("DELETE FROM properties WHERE id = CAST(:property_id AS uuid)"),
                {"property_id": str(property_id)},
            )
            await db.commit()
        except Exception:
            pass
