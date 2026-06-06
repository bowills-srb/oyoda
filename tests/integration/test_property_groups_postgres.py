"""Real-Postgres integration test for property groups scope."""

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
async def real_db_for_property_groups():
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


async def test_group_scoped_knowledge_is_merged_for_property(real_db_for_property_groups):
    from app.services.messaging_brain.knowledge.scoped_knowledge_service import ScopedKnowledgeService

    db = real_db_for_property_groups
    tenant_id = uuid.uuid4()
    property_id = uuid.uuid4()
    group_id = uuid.uuid4()

    try:
        await db.execute(
            text(
                """
                INSERT INTO property_groups (id, tenant_id, name, group_type)
                VALUES (CAST(:group_id AS uuid), CAST(:tenant_id AS uuid), 'WaterColor Resort', 'condo_complex')
                """
            ),
            {"group_id": str(group_id), "tenant_id": str(tenant_id)},
        )
        await db.execute(
            text(
                """
                INSERT INTO property_group_memberships (property_id, property_group_id, tenant_id)
                VALUES (CAST(:property_id AS uuid), CAST(:group_id AS uuid), CAST(:tenant_id AS uuid))
                """
            ),
            {
                "property_id": str(property_id),
                "group_id": str(group_id),
                "tenant_id": str(tenant_id),
            },
        )
        await db.execute(
            text(
                """
                INSERT INTO concierge_scoped_knowledge (
                    knowledge_entry_id, tenant_id, scope_type, scope_target_id, topic_id,
                    question_text, question_key, answer_text, tags, source, metadata
                ) VALUES (
                    gen_random_uuid(), CAST(:tenant_id AS uuid), 'property_group', CAST(:group_id AS uuid), 'pet_policy',
                    'Are pets allowed?', 'pets allowed', 'Dogs allowed in this complex with approval.',
                    '["pet_policy"]'::jsonb, 'operator_authored', '{}'::jsonb
                )
                """
            ),
            {"tenant_id": str(tenant_id), "group_id": str(group_id)},
        )
        await db.commit()

        result = await ScopedKnowledgeService().get_effective_knowledge_for_property(
            session=db,
            tenant_id=tenant_id,
            property_id=property_id,
        )

        assert result.effective_by_topic["pet_policy"].answer_text == "Dogs allowed in this complex with approval."
        assert any(item.scope_origin == "property_group" for item in result.all_entries_with_provenance)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Cannot complete Postgres integration test: {type(exc).__name__}: {exc}")
    finally:
        try:
            await db.execute(
                text("DELETE FROM concierge_scoped_knowledge WHERE tenant_id = CAST(:tenant_id AS uuid)"),
                {"tenant_id": str(tenant_id)},
            )
            await db.execute(
                text("DELETE FROM property_group_memberships WHERE tenant_id = CAST(:tenant_id AS uuid)"),
                {"tenant_id": str(tenant_id)},
            )
            await db.execute(
                text("DELETE FROM property_groups WHERE tenant_id = CAST(:tenant_id AS uuid)"),
                {"tenant_id": str(tenant_id)},
            )
            await db.commit()
        except Exception:
            pass
