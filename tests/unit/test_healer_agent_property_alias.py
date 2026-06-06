from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from app.services.agents.healer_agent import (
    IntentSuggestionEvidence,
    MIN_HEALER_CLUSTER_SIZE,
    HealerAgent,
    PrefilterDropSuggestionEvidence,
    PropertyAliasEvidence,
    ProposedHeal,
)
from app.services.agents.healer_runner import scan_all_tenants


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class _MappingResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


@pytest.mark.asyncio
async def test_scan_clusters_by_normalized_mention_and_property_code() -> None:
    agent = HealerAgent()
    tenant_id = UUID("11111111-1111-1111-1111-111111111111")
    rows = [
        PropertyAliasEvidence(
            normalization_id=str(uuid4()),
            selected_mention="100 S Spooky Lane Unit 2D",
            selected_property_code="100SL2D",
            selected_surface="subject",
        ),
        PropertyAliasEvidence(
            normalization_id=str(uuid4()),
            selected_mention="100   s spooky lane unit 2d",
            selected_property_code="100SL2D",
            selected_surface="quoted_context",
        ),
        PropertyAliasEvidence(
            normalization_id=str(uuid4()),
            selected_mention="222 Palm Place",
            selected_property_code="222PALM",
            selected_surface="subject",
        ),
    ]

    with patch.object(agent, "_fetch_disagreement_audits", new=AsyncMock(return_value=rows)), patch.object(
        agent, "_fetch_intent_disagreement_audits", new=AsyncMock(return_value=[])
    ), patch.object(
        agent, "_fetch_prefilter_gate_failure_audits", new=AsyncMock(return_value=[])
    ):
        proposals = await agent.scan_for_proposals(db=AsyncMock(), tenant_id=tenant_id, window_hours=24)

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.proposal_kind == "property_alias_suggestion"
    assert proposal.cluster_size == MIN_HEALER_CLUSTER_SIZE
    assert proposal.proposed_change["canonical_property_code"] == "100SL2D"
    assert proposal.proposed_change["normalized_mention"] == "100 s spooky lane unit 2d"


@pytest.mark.asyncio
async def test_scan_ignores_singletons() -> None:
    agent = HealerAgent()
    tenant_id = UUID("11111111-1111-1111-1111-111111111111")
    rows = [
        PropertyAliasEvidence(
            normalization_id=str(uuid4()),
            selected_mention="111 Driftwood Drive",
            selected_property_code="111DRIFT",
            selected_surface="subject",
        ),
    ]

    with patch.object(agent, "_fetch_disagreement_audits", new=AsyncMock(return_value=rows)), patch.object(
        agent, "_fetch_intent_disagreement_audits", new=AsyncMock(return_value=[])
    ), patch.object(
        agent, "_fetch_prefilter_gate_failure_audits", new=AsyncMock(return_value=[])
    ):
        proposals = await agent.scan_for_proposals(db=AsyncMock(), tenant_id=tenant_id, window_hours=24)

    assert proposals == []


def test_duplicate_runs_produce_same_dedup_key() -> None:
    agent = HealerAgent()
    cluster = [
        PropertyAliasEvidence(
            normalization_id=str(uuid4()),
            selected_mention="100 S Spooky Lane Unit 2D",
            selected_property_code="100SL2D",
            selected_surface="subject",
        ),
        PropertyAliasEvidence(
            normalization_id=str(uuid4()),
            selected_mention="100 s spooky lane unit 2d",
            selected_property_code="100SL2D",
            selected_surface="latest_body",
        ),
    ]

    first = agent._draft_alias_proposal(cluster)
    second = agent._draft_alias_proposal(cluster)

    assert first.dedup_key == second.dedup_key


@pytest.mark.asyncio
async def test_save_proposals_upserts_and_records_audit() -> None:
    agent = HealerAgent()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(uuid4()))
    agent._record_healer_audit = AsyncMock()
    tenant_id = UUID("11111111-1111-1111-1111-111111111111")
    proposal = ProposedHeal(
        proposal_kind="property_alias_suggestion",
        signal_source="property_mention_surface_audit",
        dedup_key="abc123",
        summary="summary",
        evidence=[{"normalization_id": str(uuid4())}],
        proposed_change={"kind": "property_alias_suggestion"},
        confidence=0.7,
        cluster_size=2,
    )

    saved = await agent.save_proposals(db, tenant_id, [proposal])

    assert len(saved) == 1
    db.commit.assert_awaited_once()
    agent._record_healer_audit.assert_awaited_once()
    sql = str(db.execute.await_args_list[0].args[0])
    assert "ON CONFLICT (tenant_id, proposal_kind, dedup_key)" in sql


@pytest.mark.asyncio
async def test_approve_property_alias_proposal_dispatches_to_write_service() -> None:
    agent = HealerAgent()
    db = AsyncMock()
    proposal_id = uuid4()
    db.execute = AsyncMock(
        side_effect=[
            _MappingResult(
                {
                    "proposal_kind": "property_alias_suggestion",
                    "proposed_change": {
                        "extracted_mention": "100 S Spooky Lane Unit 2D",
                        "canonical_property_code": "100SL2D",
                    },
                }
            ),
            _ScalarResult(proposal_id),
        ]
    )
    fake_write_service = AsyncMock()

    with patch(
        "app.services.agents.healer_agent.get_canonical_property_write_service",
        return_value=fake_write_service,
    ):
        approved = await agent.approve_proposal(
            db,
            UUID("11111111-1111-1111-1111-111111111111"),
            proposal_id,
            "ops@example.com",
            review_notes="looks good",
        )

    assert approved is True
    fake_write_service.link_property_identity.assert_awaited_once()
    db.commit.assert_awaited_once()


def test_draft_intent_keyword_proposal_extracts_common_keywords() -> None:
    agent = HealerAgent()
    cluster = [
        IntentSuggestionEvidence(
            normalization_id=str(uuid4()),
            original_intent="local_area",
            escalated_intent="amenities",
            latest_guest_turn="Do you have a high chair and pack and play at the house?",
        ),
        IntentSuggestionEvidence(
            normalization_id=str(uuid4()),
            original_intent="local_area",
            escalated_intent="amenities",
            latest_guest_turn="Can you confirm a high chair and pack and play are available?",
        ),
    ]

    proposal = agent._draft_intent_keyword_proposal(cluster)

    assert proposal.proposal_kind == "intent_classifier_keyword_suggestion"
    assert proposal.proposed_change["target_intent"] == "amenities"
    assert "high" in proposal.proposed_change["suggested_keywords"]
    assert "chair" in proposal.proposed_change["suggested_keywords"]


@pytest.mark.asyncio
async def test_approve_intent_keyword_suggestion_updates_operator_settings_extra() -> None:
    agent = HealerAgent()
    db = AsyncMock()
    proposal_id = uuid4()
    db.execute = AsyncMock(
        side_effect=[
            _MappingResult(
                {
                    "proposal_kind": "intent_classifier_keyword_suggestion",
                    "proposed_change": {
                        "target_intent": "amenities",
                        "suggested_keywords": ["high", "chair", "pack"],
                    },
                }
            ),
            type("FetchOne", (), {"fetchone": lambda self: ({"intent_classifier_keyword_overrides": {"amenities": ["crib"]}},)})(),
            _ScalarResult(None),
            _ScalarResult(proposal_id),
        ]
    )

    approved = await agent.approve_proposal(
        db,
        UUID("11111111-1111-1111-1111-111111111111"),
        proposal_id,
        "ops@example.com",
        review_notes="looks good",
    )

    assert approved is True
    upsert_params = db.execute.await_args_list[2].args[1]
    extra = json.loads(upsert_params["extra"])
    assert sorted(extra["intent_classifier_keyword_overrides"]["amenities"]) == ["chair", "crib", "high", "pack"]


@pytest.mark.asyncio
async def test_scan_all_tenants_counts_created_proposals() -> None:
    fake_db = AsyncMock()
    fake_context = AsyncMock()
    fake_context.__aenter__.return_value = fake_db
    fake_context.__aexit__.return_value = False
    tenant_id = UUID("11111111-1111-1111-1111-111111111111")
    proposal = ProposedHeal(
        proposal_kind="property_alias_suggestion",
        signal_source="property_mention_surface_audit",
        dedup_key="abc123",
        summary="summary",
        evidence=[{"normalization_id": str(uuid4())}],
        proposed_change={"kind": "property_alias_suggestion"},
        confidence=0.7,
        cluster_size=2,
    )
    fake_agent = AsyncMock()
    fake_agent.scan_for_proposals.return_value = [proposal]
    fake_agent.save_proposals.return_value = ["prop-1"]

    with patch("app.services.agents.healer_runner.SessionLocal", return_value=fake_context), patch(
        "app.services.agents.healer_runner._list_recently_active_tenants",
        new=AsyncMock(return_value=[tenant_id]),
    ), patch("app.services.agents.healer_runner.get_healer_agent", return_value=fake_agent):
        counts = await scan_all_tenants(window_hours=24)

    assert counts == {tenant_id: 1}


def test_draft_prefilter_drop_proposal_uses_domain_and_subject_marker() -> None:
    agent = HealerAgent()
    cluster = [
        PrefilterDropSuggestionEvidence(
            normalization_id=str(uuid4()),
            sender_address="receipts+acct_1@stripe.com",
            raw_subject="Your receipt from Stripe",
            latest_guest_turn="Thanks",
            sender_domain="stripe.com",
            subject_marker="receipt",
        ),
        PrefilterDropSuggestionEvidence(
            normalization_id=str(uuid4()),
            sender_address="receipts+acct_2@stripe.com",
            raw_subject="Your receipt from Stripe",
            latest_guest_turn="Thanks again",
            sender_domain="stripe.com",
            subject_marker="receipt",
        ),
    ]

    proposal = agent._draft_prefilter_drop_proposal(cluster)

    assert proposal.proposal_kind == "prefilter_drop_pattern_suggestion"
    assert proposal.proposed_change["sender_domain"] == "stripe.com"
    assert proposal.proposed_change["subject_contains"] == "receipt"


@pytest.mark.asyncio
async def test_approve_prefilter_drop_suggestion_updates_operator_settings_extra() -> None:
    agent = HealerAgent()
    db = AsyncMock()
    proposal_id = uuid4()
    db.execute = AsyncMock(
        side_effect=[
            _MappingResult(
                {
                    "proposal_kind": "prefilter_drop_pattern_suggestion",
                    "proposed_change": {
                        "sender_domain": "stripe.com",
                        "subject_contains": "receipt",
                    },
                }
            ),
            type("FetchOne", (), {"fetchone": lambda self: ({"inbound_prefilter_drop_overrides": []},)})(),
            _ScalarResult(None),
            _ScalarResult(proposal_id),
        ]
    )

    approved = await agent.approve_proposal(
        db,
        UUID("11111111-1111-1111-1111-111111111111"),
        proposal_id,
        "ops@example.com",
        review_notes="looks good",
    )

    assert approved is True
    upsert_params = db.execute.await_args_list[2].args[1]
    extra = json.loads(upsert_params["extra"])
    assert extra["inbound_prefilter_drop_overrides"][0]["sender_domain"] == "stripe.com"
    assert extra["inbound_prefilter_drop_overrides"][0]["subject_contains"] == "receipt"


@pytest.mark.asyncio
async def test_scan_prefilter_clusters_gate_error_rows() -> None:
    agent = HealerAgent()
    tenant_id = UUID("11111111-1111-1111-1111-111111111111")
    rows = [
        PrefilterDropSuggestionEvidence(
            normalization_id=str(uuid4()),
            sender_address="receipts+acct_1@stripe.com",
            raw_subject="Your receipt from Stripe",
            latest_guest_turn="Thanks",
            sender_domain="stripe.com",
            subject_marker="receipt",
        ),
        PrefilterDropSuggestionEvidence(
            normalization_id=str(uuid4()),
            sender_address="receipts+acct_2@stripe.com",
            raw_subject="Your receipt from Stripe",
            latest_guest_turn="Thanks again",
            sender_domain="stripe.com",
            subject_marker="receipt",
        ),
    ]

    with patch.object(agent, "_fetch_disagreement_audits", new=AsyncMock(return_value=[])), patch.object(
        agent, "_fetch_intent_disagreement_audits", new=AsyncMock(return_value=[])
    ), patch.object(
        agent, "_fetch_prefilter_gate_failure_audits", new=AsyncMock(return_value=rows)
    ):
        proposals = await agent.scan_for_proposals(db=AsyncMock(), tenant_id=tenant_id, window_hours=24)

    assert len(proposals) == 1
    assert proposals[0].proposal_kind == "prefilter_drop_pattern_suggestion"
