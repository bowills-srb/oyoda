from __future__ import annotations

import asyncio
from uuid import uuid4

from app.services.property_canonical_write_service import CanonicalPropertyWriteService


class _NoopSession:
    async def execute(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("session.execute should not be called in this unit test")

    async def commit(self):  # pragma: no cover
        return None


def test_register_property_record_accepts_mixed_property_inputs(monkeypatch):
    calls = []
    profile_calls = []

    async def _fake_upsert_ref(
        self,
        tenant_id,
        canonical_property_code,
        provider,
        ref_kind,
        ref_value,
        source,
        confidence,
        metadata,
    ):
        calls.append(
            {
                "tenant_id": tenant_id,
                "canonical_property_code": canonical_property_code,
                "provider": provider,
                "ref_kind": ref_kind,
                "ref_value": ref_value,
                "source": source,
                "confidence": confidence,
                "metadata": metadata,
            }
        )

    async def _fake_upsert_profile(
        self,
        tenant_id,
        canonical_property_code,
        *,
        display_name,
        marketing_name,
        preferred_address,
        source,
        metadata,
    ):
        profile_calls.append(
            {
                "tenant_id": tenant_id,
                "canonical_property_code": canonical_property_code,
                "display_name": display_name,
                "marketing_name": marketing_name,
                "preferred_address": preferred_address,
                "source": source,
            }
        )

    monkeypatch.setattr(CanonicalPropertyWriteService, "_upsert_ref", _fake_upsert_ref)
    monkeypatch.setattr(CanonicalPropertyWriteService, "_upsert_profile", _fake_upsert_profile)

    service = CanonicalPropertyWriteService(_NoopSession())
    tenant_id = uuid4()

    asyncio.run(
        service.register_property_record(
            tenant_id,
            canonical_property_code="178SC",
            property_name="Sun Kissed",
            address_line1="178 Spartina Cir",
            external_ids={"airbnb": "1517439658215941054", "pms": "ESC-178SC"},
            aliases=["Sun Kissed | Pool, Bikes, Prime Seagrove Location", "178 Spartina Cir"],
            ref_pairs=[
                {
                    "provider": "operator_kb",
                    "ref_kind": "property_external_id",
                    "ref_value": "SUN-KISSED",
                    "confidence": 0.95,
                    "metadata": {"source_table": "concierge_knowledge"},
                }
            ],
            source="unit_test",
        )
    )

    assert ("internal", "property_code", "178SC") in {
        (call["provider"], call["ref_kind"], call["ref_value"]) for call in calls
    }
    assert ("internal", "property_name", "Sun Kissed") in {
        (call["provider"], call["ref_kind"], call["ref_value"]) for call in calls
    }
    assert ("internal", "address_line1", "178 Spartina Cir") in {
        (call["provider"], call["ref_kind"], call["ref_value"]) for call in calls
    }
    assert ("airbnb", "external_id", "1517439658215941054") in {
        (call["provider"], call["ref_kind"], call["ref_value"]) for call in calls
    }
    assert ("pms", "unit_id", "ESC-178SC") in {
        (call["provider"], call["ref_kind"], call["ref_value"]) for call in calls
    }
    assert ("operator_kb", "property_external_id", "SUN-KISSED") in {
        (call["provider"], call["ref_kind"], call["ref_value"]) for call in calls
    }
    assert profile_calls
    assert profile_calls[0]["display_name"] == "Sun Kissed"
    assert profile_calls[0]["preferred_address"] == "178 Spartina Cir"


def test_coerce_json_mapping_handles_strings():
    service = CanonicalPropertyWriteService(_NoopSession())

    assert service._coerce_json_mapping('{"airbnb":"abc","vrbo_id":"123"}') == {
        "airbnb": "abc",
        "vrbo_id": "123",
    }
    assert service._coerce_json_mapping("not-json") == {}


def test_upsert_property_profile_registers_display_name_alias(monkeypatch):
    ref_calls = []
    profile_calls = []

    async def _fake_upsert_ref(
        self,
        tenant_id,
        canonical_property_code,
        provider,
        ref_kind,
        ref_value,
        source,
        confidence,
        metadata,
    ):
        ref_calls.append((provider, ref_kind, ref_value, source))

    async def _fake_upsert_profile(
        self,
        tenant_id,
        canonical_property_code,
        *,
        display_name,
        marketing_name,
        preferred_address,
        source,
        metadata,
    ):
        profile_calls.append((canonical_property_code, display_name, marketing_name, preferred_address, source))

    monkeypatch.setattr(CanonicalPropertyWriteService, "_upsert_ref", _fake_upsert_ref)
    monkeypatch.setattr(CanonicalPropertyWriteService, "_upsert_profile", _fake_upsert_profile)

    service = CanonicalPropertyWriteService(_NoopSession())
    asyncio.run(
        service.upsert_property_profile(
            uuid4(),
            canonical_property_code="178SC",
            display_name="Sun Kissed",
            marketing_name="Sun Kissed on 30A",
            preferred_address="178 Spartina Cir",
            source="unit_test_profile",
        )
    )

    assert profile_calls == [("178SC", "Sun Kissed", "Sun Kissed on 30A", "178 Spartina Cir", "unit_test_profile")]
    assert ("internal", "display_name", "Sun Kissed", "unit_test_profile") in ref_calls
    assert ("internal", "property_name", "Sun Kissed on 30A", "unit_test_profile") in ref_calls


def test_observe_resolved_identity_stores_ota_cross_reference(monkeypatch):
    ref_calls = []
    profile_calls = []

    async def _fake_upsert_ref(
        self,
        tenant_id,
        canonical_property_code,
        provider,
        ref_kind,
        ref_value,
        source,
        confidence,
        metadata,
    ):
        ref_calls.append((provider, ref_kind, ref_value, source))

    async def _fake_upsert_profile(
        self,
        tenant_id,
        canonical_property_code,
        *,
        display_name,
        marketing_name,
        preferred_address,
        source,
        metadata,
    ):
        profile_calls.append((canonical_property_code, display_name, marketing_name, preferred_address, source))

    monkeypatch.setattr(CanonicalPropertyWriteService, "_upsert_ref", _fake_upsert_ref)
    monkeypatch.setattr(CanonicalPropertyWriteService, "_upsert_profile", _fake_upsert_profile)

    service = CanonicalPropertyWriteService(_NoopSession())
    asyncio.run(
        service.observe_resolved_identity(
            uuid4(),
            canonical_property_code="178SC",
            platform="vrbo",
            platform_listing_id="3350889",
            platform_unit_id="ESC-178SC",
            property_name="Sun Kissed",
            display_name="Sun Kissed",
            address_line1="178 Spartina Cir",
            source="unit_test_observation",
        )
    )

    assert profile_calls == [("178SC", "Sun Kissed", "Sun Kissed", "178 Spartina Cir", "unit_test_observation")]
    assert ("vrbo", "external_id", "3350889", "unit_test_observation") in ref_calls
    assert ("pms", "unit_id", "ESC-178SC", "unit_test_observation") in ref_calls
    assert ("internal", "alias", "Sun Kissed", "unit_test_observation") in ref_calls


def test_queue_property_link_review_upserts_pending_review(monkeypatch):
    execute_calls = []

    class _ReviewSession:
        async def execute(self, *args, **kwargs):
            execute_calls.append((args, kwargs))
            return None

        async def commit(self):
            return None

    service = CanonicalPropertyWriteService(_ReviewSession())
    asyncio.run(
        service.queue_property_link_review(
            uuid4(),
            canonical_property_code="178SC",
            provider="vrbo",
            ref_kind="alias",
            ref_value="Sun Kissed",
            platform_listing_id="3350889",
            confidence=0.72,
            candidates=[{"property_code": "178SC", "score": 0.72}],
            source="unit_test_review",
        )
    )

    assert execute_calls
