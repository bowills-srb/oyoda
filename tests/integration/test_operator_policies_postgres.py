"""Real-Postgres integration test for operator policy authoring and profile reads."""

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
async def real_db_for_operator_policies():
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


async def test_build_profile_returns_authored_operator_policies(real_db_for_operator_policies):
    from app.services.property_canonical_service import CanonicalPropertyService

    db = real_db_for_operator_policies
    tenant_id = uuid.uuid4()
    property_id = uuid.uuid4()
    property_code = f"opolicy_{uuid.uuid4().hex[:8]}"

    try:
        await db.execute(
            text(
                """
                INSERT INTO properties (
                    id, tenant_id, property_code, address_street, is_active, data_source
                ) VALUES (
                    CAST(:id AS uuid), CAST(:tenant_id AS uuid), :property_code, :address_street, true, 'import'
                )
                """
            ),
            {
                "id": str(property_id),
                "tenant_id": str(tenant_id),
                "property_code": property_code,
                "address_street": "123 Policy Way",
            },
        )
        await db.execute(
            text(
                """
                INSERT INTO operator_policies (
                    id, tenant_id, pets_allowed, pet_fee, discount_policies, created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), CAST(:tenant_id AS uuid), 'yes', 50.0, :discount_policies::jsonb, NOW(), NOW()
                )
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "discount_policies": '{"rules":[]}',
            },
        )
        await db.commit()

        profile = await CanonicalPropertyService(db).build_profile(
            tenant_id=tenant_id,
            property_code=property_code,
        )

        assert profile["operator_policies"]["_authored"] is True
        assert profile["operator_policies"]["pets_allowed"] == "yes"
        assert profile["operator_policies"]["pet_policy"] == "allowed"
    except PermissionError as exc:
        pytest.skip(f"Cannot reach Postgres for integration test: {type(exc).__name__}: {exc}")
    finally:
        try:
            await db.execute(
                text("DELETE FROM operator_policies WHERE tenant_id = CAST(:tenant_id AS uuid)"),
                {"tenant_id": str(tenant_id)},
            )
            await db.execute(
                text("DELETE FROM properties WHERE tenant_id = CAST(:tenant_id AS uuid)"),
                {"tenant_id": str(tenant_id)},
            )
            await db.commit()
        except Exception:
            pass
