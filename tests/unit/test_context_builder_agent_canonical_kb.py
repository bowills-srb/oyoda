from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.messaging_brain.agents.context_builder_agent import (
    ContextBuilderAgent,
)
from app.services.orchestration.messaging_brain_contracts import (
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    OutboundIntent,
    Urgency,
)


SEAM = "app.services.messaging_brain.agents.context_builder_agent"


def _make_inbound(
    *,
    tenant_id: str = "11111111-1111-1111-1111-111111111111",
    property_code: str = "100SL2C",
) -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="MSG_CANONICAL_001",
        tenant_id=tenant_id,
        channel="sms",
        source_provider="twilio",
        text="Can we bring our dog and where do we park?",
        guest_phone="+18505551234",
        property_code=property_code,
    )


def _make_classification() -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic="house_rules",
        confidence=0.8,
        urgency=Urgency.LOW,
    )


def _make_outbound(
    *,
    tenant_id: str = "11111111-1111-1111-1111-111111111111",
    property_code: str = "100SL2C",
) -> OutboundIntent:
    return OutboundIntent(
        tenant_id=tenant_id,
        trigger_type="system_pre_arrival",
        property_code=property_code,
    )


def _legacy_knowledge():
    return SimpleNamespace(
        facts={"wifi": "network + password"},
        sections={},
        faq=[{"question": "Legacy Q", "answer": "Legacy A"}],
    )


def _canonical_profile(*, with_concierge: bool = True) -> dict:
    concierge = {
        "property_context": {"headline": "Steps from the beach"},
        "facts": {
            "wifi": "BeachWifi / password123",
            "check_in": "4pm",
            "check_out": "10am",
            "parking": "Two spaces in driveway",
        },
        "sections": {"overview": "Bright beach home with pool access."},
        "faq": [
            {"question": "Are pets allowed?", "answer": "Dogs allowed with fee."},
            {"question": "Where do we park?", "answer": "Driveway only."},
        ],
        "source": "unified",
    } if with_concierge else {
        "property_context": {},
        "facts": {},
        "sections": {},
        "faq": [],
        "source": "",
    }
    return {
        "property_name": "Beach House",
        "display_name": "Beach House",
        "property_external_id": "100SL2C",
        "external_id": "100SL2C",
        "preferred_address": "100 Spooky Lane Unit 2C",
        "bedrooms": 4,
        "bathrooms": 3,
        "max_guests": 10,
        "has_pool": True,
        "pool_heated": False,
        "has_hot_tub": False,
        "has_waterfront": False,
        "pet_friendly": True,
        "beach_access_type": "private",
        "parking_summary": "Driveway for 2 cars",
        "wifi_available": True,
        "property_summary": "Ocean-adjacent family home",
        "description": "A great beach stay.",
        "community_name": "WaterColor",
        "check_in_time": "4pm",
        "check_out_time": "10am",
        "operator_policies": {"min_nights": 3, "pet_policy": "allowed"},
        "concierge_knowledge": concierge,
        "source_provenance": {"properties": True, "concierge_knowledge": with_concierge},
    }


def _setup_canonical_enabled(monkeypatch, *, profile=None, exc: Exception | None = None):
    monkeypatch.setattr(
        f"{SEAM}.is_messaging_brain_canonical_kb_read_enabled",
        AsyncMock(return_value=True),
    )
    canonical_service = MagicMock()
    if exc is not None:
        canonical_service.build_profile = AsyncMock(side_effect=exc)
    else:
        canonical_service.build_profile = AsyncMock(return_value=profile)
    get_service = MagicMock(return_value=canonical_service)
    monkeypatch.setattr(f"{SEAM}.get_canonical_property_service", get_service)
    return canonical_service, get_service


@pytest.mark.asyncio
async def test_flag_off_uses_legacy_path(monkeypatch):
    monkeypatch.setattr(
        f"{SEAM}.is_messaging_brain_canonical_kb_read_enabled",
        AsyncMock(return_value=False),
    )
    get_service = MagicMock()
    monkeypatch.setattr(f"{SEAM}.get_canonical_property_service", get_service)

    fake_service = MagicMock()
    fake_service.get_for_property = AsyncMock(return_value=_legacy_knowledge())
    agent = ContextBuilderAgent(knowledge_service=fake_service)

    bundle = await agent.build(_make_inbound(), _make_classification(), db_session=MagicMock())

    fake_service.get_for_property.assert_awaited_once()
    get_service.assert_not_called()
    assert bundle.property_knowledge["faq_count"] == 1


@pytest.mark.asyncio
async def test_flag_on_uses_canonical_profile(monkeypatch):
    canonical_service, _ = _setup_canonical_enabled(
        monkeypatch,
        profile=_canonical_profile(),
    )
    fake_service = MagicMock()
    fake_service.get_for_property = AsyncMock(return_value=_legacy_knowledge())
    agent = ContextBuilderAgent(knowledge_service=fake_service)

    bundle = await agent.build(_make_inbound(), _make_classification(), db_session=MagicMock())

    canonical_service.build_profile.assert_awaited_once()
    fake_service.get_for_property.assert_not_awaited()
    assert bundle.property_facts["bedrooms"] == 4
    assert bundle.operator_policies["pet_policy"] == "allowed"


@pytest.mark.asyncio
async def test_canonical_profile_merges_into_bundle(monkeypatch):
    _setup_canonical_enabled(monkeypatch, profile=_canonical_profile())
    fake_service = MagicMock()
    fake_service.get_for_property = AsyncMock(return_value=None)
    agent = ContextBuilderAgent(knowledge_service=fake_service)

    bundle = await agent.build(_make_inbound(), _make_classification(), db_session=MagicMock())

    assert bundle.property_facts["bedrooms"] == 4
    assert bundle.property_facts["bathrooms"] == 3
    assert bundle.property_facts["beach_access_type"] == "private"
    assert bundle.property_knowledge["faq_count"] == 2
    assert bundle.operator_policies["pet_policy"] == "allowed"
    assert bundle.guidebook_knowledge["facts"]["wifi"] == "BeachWifi / password123"
    assert "property_facts.bedrooms" in bundle.evidence_keys
    assert "property_knowledge.faq" in bundle.evidence_keys
    assert "operator_policies.pet_policy" in bundle.evidence_keys
    assert "property_knowledge.source_provenance" in bundle.evidence_keys


@pytest.mark.asyncio
async def test_empty_canonical_profile_signals_missing_context(monkeypatch):
    _setup_canonical_enabled(monkeypatch, profile=_canonical_profile(with_concierge=False))
    fake_service = MagicMock()
    fake_service.get_for_property = AsyncMock(return_value=None)
    agent = ContextBuilderAgent(knowledge_service=fake_service)

    bundle = await agent.build(_make_inbound(), _make_classification(), db_session=MagicMock())

    assert "no_canonical_knowledge_for_property" in bundle.missing_context
    assert bundle.property_facts["bedrooms"] == 4
    assert "faq" not in bundle.property_knowledge
    fake_service.get_for_property.assert_not_awaited()


@pytest.mark.asyncio
async def test_canonical_profile_load_failure_fails_loud(monkeypatch):
    _setup_canonical_enabled(monkeypatch, exc=RuntimeError("boom"))
    fake_service = MagicMock()
    fake_service.get_for_property = AsyncMock(return_value=_legacy_knowledge())
    agent = ContextBuilderAgent(knowledge_service=fake_service)

    bundle = await agent.build(_make_inbound(), _make_classification(), db_session=MagicMock())

    assert any("canonical_profile_load_failed: RuntimeError" == item for item in bundle.missing_context)
    fake_service.get_for_property.assert_awaited_once()
    assert bundle.property_knowledge["faq_count"] == 1


@pytest.mark.asyncio
async def test_proactive_path_uses_canonical_under_flag(monkeypatch):
    canonical_service, _ = _setup_canonical_enabled(
        monkeypatch,
        profile=_canonical_profile(),
    )
    fake_service = MagicMock()
    fake_service.get_for_property = AsyncMock(return_value=_legacy_knowledge())
    agent = ContextBuilderAgent(knowledge_service=fake_service)

    bundle = await agent.build_for_proactive(_make_outbound(), db_session=MagicMock())

    canonical_service.build_profile.assert_awaited_once()
    fake_service.get_for_property.assert_not_awaited()
    assert bundle.operator_policies["pet_policy"] == "allowed"
    assert bundle.property_facts["parking_summary"] == "Driveway for 2 cars"


@pytest.mark.asyncio
async def test_no_legacy_fallback_in_canonical_path(monkeypatch):
    _setup_canonical_enabled(monkeypatch, profile=_canonical_profile(with_concierge=False))
    fake_service = MagicMock()
    fake_service.get_for_property = AsyncMock(return_value=_legacy_knowledge())
    agent = ContextBuilderAgent(knowledge_service=fake_service)

    bundle = await agent.build(_make_inbound(), _make_classification(), db_session=MagicMock())

    fake_service.get_for_property.assert_not_awaited()
    assert "no_canonical_knowledge_for_property" in bundle.missing_context
    assert "guidebook_knowledge" not in bundle.evidence_keys
