from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.property_canonical_service import CanonicalPropertyService


class _FakeFetchOneResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeMappingsResult:
    def first(self):
        return None


class _FakeSession:
    def __init__(self):
        self.statements: list[str] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if "FROM canonical_property_refs" in sql:
            return _FakeFetchOneResult(None)
        if "FROM properties" in sql and "LIMIT 1" in sql:
            return _FakeFetchOneResult(("17LL",))
        if "FROM information_schema.columns" in sql:
            return _FakeFetchOneResult(None)
        return _FakeMappingsResult()


@pytest.mark.asyncio
async def test_resolve_property_code_casts_dynamic_name_columns_to_text():
    session = _FakeSession()
    service = CanonicalPropertyService(session)
    service._schema_cache["canonical_property_refs"] = {
        "tenant_id",
        "provider",
        "ref_kind",
        "normalized_ref_value",
        "canonical_property_code",
    }
    service._schema_cache["properties"] = {
        "tenant_id",
        "property_code",
        "external_id",
        "address_street",
        "community",
    }
    service._schema_cache["pms_listings"] = {
        "company_id",
        "external_id",
        "property_name",
        "is_active",
    }

    resolved = await service.resolve_property_code(
        uuid4(),
        property_name="17 Lyonia",
        platform="direct",
    )

    assert resolved == "17LL"
    property_query = next(sql for sql in session.statements if "FROM properties" in sql and "LIMIT 1" in sql)
    assert "LOWER((community)::text)" in property_query
    assert "LOWER((address_street)::text)" in property_query
