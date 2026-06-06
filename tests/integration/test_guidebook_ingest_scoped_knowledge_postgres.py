from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.concierge.guidebook_ingest_service import (
    GuideFetchResponse,
    GuidebookIngestService,
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


class _FakeVectorStore:
    def __init__(self):
        self.calls = []

    async def add_documents(self, documents, batch_size=100):
        self.calls.append((documents, batch_size))
        return {"inserted": len(documents), "updated": 0}


@pytest_asyncio.fixture
async def real_db_for_dual_write():
    db = None
    session_cm = None
    try:
        session_cm = SessionLocal()
        db = await session_cm.__aenter__()
        await db.execute(text("SELECT 1"))
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


async def _fetch_response(*args, **kwargs):
    return GuideFetchResponse(
        status=200,
        final_url="https://api.breezeway.io/public/guides/test",
        content_type="application/json",
        body=(
            b'{"pages":[{"title":"Arrival","sections":[{"title":"Check-In","blocks":'
            b'[{"title":"Arrival Details","data":"<p>Check in starts at 4 PM. '
            b'Use the keypad on the front door with your unique code when you arrive.</p>"}]},'
            b'{"title":"House Rules","blocks":[{"title":"WiFi","data":"<p>The WiFi password is posted inside the home, '
            b'on the welcome card by the kitchen, and in your arrival message for easy reference during your stay.</p>"}]}]}]}'
        ),
    )


async def test_ingest_dual_write_persists_scoped_knowledge_and_is_idempotent(
    real_db_for_dual_write,
    monkeypatch,
):
    db = real_db_for_dual_write
    tenant_id = uuid4()
    property_id = uuid4()
    property_code = f"ITEST-{uuid4().hex[:8].upper()}"
    guidebook_url = "https://guide.breezeway.io/test"

    service = GuidebookIngestService(db)
    service.vector_store = _FakeVectorStore()
    monkeypatch.setattr(
        "app.services.concierge.guidebook_ingest_service.fetch_guide_payload",
        _fetch_response,
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
                "address_street": "123 Main",
                "property_guide_url": guidebook_url,
            },
        )
        await db.commit()

        result_one = await service.ingest_property_guidebook(
            tenant_id=tenant_id,
            property_code=property_code,
            property_address="123 Main",
            guidebook_url=guidebook_url,
        )
        result_two = await service.ingest_property_guidebook(
            tenant_id=tenant_id,
            property_code=property_code,
            property_address="123 Main",
            guidebook_url=guidebook_url,
        )

        rows = (
            await db.execute(
                text(
                    """
                    SELECT topic_id, question_text, answer_text, source, metadata
                    FROM concierge_scoped_knowledge
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND scope_type = 'property'
                      AND scope_target_id = CAST(:property_id AS uuid)
                      AND source = 'guidebook_ingest_v2'
                      AND is_active = true
                    ORDER BY COALESCE(topic_id, question_text)
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "property_id": str(property_id),
                },
            )
        ).mappings().all()

        assert result_one.scoped_knowledge_written >= 1
        assert result_one.scoped_knowledge_failed == 0
        assert result_one.scoped_knowledge_skipped_no_property is False
        assert result_two.scoped_knowledge_failed == 0
        assert rows, "Expected scoped knowledge rows to be written for the property."
        assert any(row["topic_id"] == "check_in_process" for row in rows)
        assert any(row["topic_id"] is None for row in rows)
        assert all(row["source"] == "guidebook_ingest_v2" for row in rows)
        assert all((row["metadata"] or {}).get("guidebook_url") == guidebook_url for row in rows)

        count_row = (
            await db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM concierge_scoped_knowledge
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND scope_type = 'property'
                      AND scope_target_id = CAST(:property_id AS uuid)
                      AND source = 'guidebook_ingest_v2'
                      AND is_active = true
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "property_id": str(property_id),
                },
            )
        ).fetchone()
        assert int(count_row[0] or 0) == len(rows)
    finally:
        try:
            await db.execute(
                text(
                    """
                    DELETE FROM concierge_scoped_knowledge_history
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND knowledge_entry_id IN (
                        SELECT knowledge_entry_id
                        FROM concierge_scoped_knowledge
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND scope_target_id = CAST(:property_id AS uuid)
                      )
                    """
                ),
                {"tenant_id": str(tenant_id), "property_id": str(property_id)},
            )
            await db.execute(
                text(
                    """
                    DELETE FROM concierge_scoped_knowledge
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND scope_target_id = CAST(:property_id AS uuid)
                    """
                ),
                {"tenant_id": str(tenant_id), "property_id": str(property_id)},
            )
            await db.execute(
                text(
                    """
                    DELETE FROM properties
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:property_id AS uuid)
                    """
                ),
                {"tenant_id": str(tenant_id), "property_id": str(property_id)},
            )
            await db.commit()
        except Exception:
            pass
