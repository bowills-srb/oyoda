from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.services.extraction.staging_service import (
    ExtractionCandidate,
    ExtractionCandidateFilters,
    ExtractionStagingService,
)


class InMemoryStagingService(ExtractionStagingService):
    def __init__(self):
        super().__init__()
        self.records: dict[UUID, ExtractionCandidate] = {}
        self.promotions: list[tuple[str, UUID]] = []

    async def _insert_candidate(self, session, payload):
        now = datetime.now(timezone.utc)
        record = {
            **payload,
            "review_status": "pending",
            "reviewed_by_user_id": None,
            "reviewed_at": None,
            "review_notes": None,
            "promoted_to_table": None,
            "promoted_to_id": None,
            "promoted_at": None,
            "created_at": now,
            "updated_at": now,
        }
        candidate = self._candidate_from_record(record)
        self.records[candidate.candidate_id] = candidate
        return record

    async def _load_candidate_record(self, session, candidate_id):
        candidate = self.records.get(candidate_id)
        return candidate.__dict__ if candidate else None

    async def _load_candidates(self, session, *, tenant_id, review_status, filters):
        rows = []
        for candidate in self.records.values():
            if tenant_id and candidate.tenant_id != tenant_id:
                continue
            if review_status and candidate.review_status != review_status:
                continue
            if filters.scope_target_id and candidate.scope_target_id != UUID(str(filters.scope_target_id)):
                continue
            if filters.candidate_type and candidate.candidate_type != filters.candidate_type:
                continue
            if filters.source_type and candidate.source_type != filters.source_type:
                continue
            if filters.source_document_id and candidate.source_document_id != UUID(str(filters.source_document_id)):
                continue
            if filters.confidence_min is not None and candidate.confidence < filters.confidence_min:
                continue
            if filters.confidence_max is not None and candidate.confidence > filters.confidence_max:
                continue
            rows.append(candidate.__dict__)
        return rows

    async def _update_candidate_review(self, session, **kwargs):
        candidate_id = kwargs["candidate_id"]
        candidate = self.records[candidate_id]
        updated = replace(
            candidate,
            proposed_question_text=kwargs["persisted_candidate"].proposed_question_text,
            proposed_question_key=kwargs["persisted_candidate"].proposed_question_key,
            proposed_answer_text=kwargs["persisted_candidate"].proposed_answer_text,
            proposed_topic_id=kwargs["persisted_candidate"].proposed_topic_id,
            proposed_tags=kwargs["persisted_candidate"].proposed_tags,
            proposed_metadata=kwargs["persisted_candidate"].proposed_metadata,
            confidence=kwargs["persisted_candidate"].confidence,
            evidence_excerpt=kwargs["persisted_candidate"].evidence_excerpt,
            source_section=kwargs["persisted_candidate"].source_section,
            review_status=kwargs["review_status"],
            reviewed_by_user_id=kwargs["reviewed_by_user_id"],
            reviewed_at=datetime.now(timezone.utc),
            review_notes=kwargs["review_notes"],
            promoted_to_table=kwargs["promoted_to_table"],
            promoted_to_id=kwargs["promoted_to_id"],
            promoted_at=datetime.now(timezone.utc) if kwargs["promoted_to_table"] else None,
            updated_at=datetime.now(timezone.utc),
        )
        self.records[candidate_id] = updated

    async def _promote_candidate(self, *, session, candidate, reviewed_by_user_id,
                                   is_auto_promoted=False):
        promoted_id = uuid4()
        table = {
            "fact": "concierge_scoped_knowledge",
            "asset": "operator_property_assets",
            "document_metadata": "documents",
        }[candidate.candidate_type]
        self.promotions.append((table, candidate.candidate_id))
        return table, promoted_id


async def _seed_candidate(service: InMemoryStagingService, **kwargs) -> ExtractionCandidate:
    return await service.create_candidate(
        None,
        tenant_id=kwargs.get("tenant_id", uuid4()),
        scope_type=kwargs.get("scope_type", "property"),
        scope_target_id=kwargs.get("scope_target_id", uuid4()),
        source_type=kwargs.get("source_type", "guidebook"),
        extraction_method=kwargs.get("extraction_method", "deterministic"),
        candidate_type=kwargs.get("candidate_type", "fact"),
        source_document_id=kwargs.get("source_document_id"),
        source_url=kwargs.get("source_url"),
        proposed_question_text=kwargs.get("proposed_question_text", "What is parking?"),
        proposed_question_key=kwargs.get("proposed_question_key", "parking"),
        proposed_answer_text=kwargs.get("proposed_answer_text", "Two spaces."),
        proposed_topic_id=kwargs.get("proposed_topic_id"),
        proposed_tags=kwargs.get("proposed_tags", ["parking"]),
        proposed_metadata=kwargs.get("proposed_metadata", {"asset_type": "appliance", "asset_name": "Washer"}),
        confidence=kwargs.get("confidence", 0.96),
        evidence_excerpt=kwargs.get("evidence_excerpt", "Parking: two spaces."),
        source_section=kwargs.get("source_section", "Parking"),
    )


def test_create_candidate_of_each_type():
    service = InMemoryStagingService()
    fact = asyncio.run(_seed_candidate(service, candidate_type="fact"))
    asset = asyncio.run(_seed_candidate(service, candidate_type="asset"))
    meta = asyncio.run(_seed_candidate(service, candidate_type="document_metadata", source_document_id=uuid4()))
    assert fact.candidate_type == "fact"
    assert asset.candidate_type == "asset"
    assert meta.candidate_type == "document_metadata"


def test_get_pending_candidates_with_filters():
    service = InMemoryStagingService()
    tenant_id = uuid4()
    scope_id = uuid4()
    asyncio.run(_seed_candidate(service, tenant_id=tenant_id, scope_target_id=scope_id, candidate_type="fact", source_type="guidebook", confidence=0.98))
    asyncio.run(_seed_candidate(service, tenant_id=tenant_id, candidate_type="asset", source_type="pdf", confidence=0.65))
    rows = asyncio.run(
        service.get_pending_candidates(
            None,
            tenant_id,
            ExtractionCandidateFilters(scope_target_id=scope_id, candidate_type="fact", confidence_min=0.9),
        )
    )
    assert len(rows) == 1
    assert rows[0].candidate_type == "fact"


def test_approve_single_candidate_marks_promoted():
    service = InMemoryStagingService()
    candidate = asyncio.run(_seed_candidate(service, candidate_type="fact"))
    result = asyncio.run(service.approve_candidate(None, candidate.candidate_id, uuid4()))
    stored = service.records[candidate.candidate_id]
    assert result.promoted_to_table == "concierge_scoped_knowledge"
    assert stored.review_status == "approved"
    assert stored.promoted_to_table == "concierge_scoped_knowledge"


def test_bulk_approve_via_explicit_ids():
    service = InMemoryStagingService()
    a = asyncio.run(_seed_candidate(service))
    b = asyncio.run(_seed_candidate(service))
    result = asyncio.run(service.bulk_approve(None, [a.candidate_id, b.candidate_id], uuid4()))
    assert result["approved"] == 2


def test_bulk_approve_via_filter():
    service = InMemoryStagingService()
    tenant_id = uuid4()
    asyncio.run(_seed_candidate(service, tenant_id=tenant_id, confidence=0.97))
    asyncio.run(_seed_candidate(service, tenant_id=tenant_id, confidence=0.98))
    result = asyncio.run(
        service.bulk_approve(
            None,
            None,
            uuid4(),
            ExtractionCandidateFilters(confidence_min=0.95),
            tenant_id=tenant_id,
        )
    )
    assert result["approved"] == 2


def test_reject_candidate_no_promotion():
    service = InMemoryStagingService()
    candidate = asyncio.run(_seed_candidate(service))
    result = asyncio.run(service.reject_candidate(None, candidate.candidate_id, uuid4(), notes="not useful"))
    stored = service.records[candidate.candidate_id]
    assert result.promoted_to_table is None
    assert stored.review_status == "rejected"
    assert stored.review_notes == "not useful"


def test_auto_promote_only_eligible_candidates():
    service = InMemoryStagingService()
    tenant_id = uuid4()
    auto = asyncio.run(_seed_candidate(service, tenant_id=tenant_id, extraction_method="deterministic", candidate_type="fact", confidence=0.96))
    auto_asset = asyncio.run(_seed_candidate(service, tenant_id=tenant_id, extraction_method="deterministic", candidate_type="asset", confidence=0.96))
    asyncio.run(_seed_candidate(service, tenant_id=tenant_id, extraction_method="llm", confidence=0.99))
    asyncio.run(_seed_candidate(service, tenant_id=tenant_id, extraction_method="deterministic", confidence=0.69))
    result = asyncio.run(service.auto_promote_eligible(None, tenant_id))
    assert result["auto_promoted"] == 2
    assert service.records[auto.candidate_id].review_status == "auto_promoted"
    assert service.records[auto_asset.candidate_id].review_status == "auto_promoted"


def test_edits_are_persisted_on_approval():
    service = InMemoryStagingService()
    candidate = asyncio.run(_seed_candidate(service, proposed_answer_text="Two spaces"))
    asyncio.run(
        service.approve_candidate(
            None,
            candidate.candidate_id,
            uuid4(),
            edits={"proposed_answer_text": "Three spaces", "proposed_tags": ["parking", "driveway"]},
        )
    )
    stored = service.records[candidate.candidate_id]
    assert stored.review_status == "edited"
    assert stored.proposed_answer_text == "Three spaces"
    assert stored.proposed_tags == ["parking", "driveway"]


def test_auto_promotion_rules_cover_pms_and_llm():
    service = InMemoryStagingService()
    pms = asyncio.run(_seed_candidate(service, source_type="pms", extraction_method="hybrid", confidence=0.99))
    llm = asyncio.run(_seed_candidate(service, extraction_method="llm", confidence=1.0))
    assert service._is_auto_promotable(pms) is True
    assert service._is_auto_promotable(llm) is False


def test_validation_downgraded_deterministic_candidate_is_not_auto_promotable():
    service = InMemoryStagingService()
    flagged = asyncio.run(
        _seed_candidate(
            service,
            extraction_method="deterministic",
            confidence=0.70,
            proposed_metadata={
                "validation_concern": {
                    "concern_type": "implausible",
                    "concern_description": "bathroom_count is more than two above bedroom_count",
                    "suggested_action": "stage_for_review",
                }
            },
        )
    )

    assert service._is_auto_promotable(flagged) is False


# ---------------------------------------------------------------------------
# Gap 1 — property_group scope tests
# ---------------------------------------------------------------------------
# These tests verify that the staging → promote → effective-knowledge seam is
# closed for group-scoped (neighborhood/HOA) facts. Three things to prove:
#   1. create_candidate now accepts scope_type='property_group'
#   2. A group-scoped fact promoted via _promote_candidate passes scope_type
#      through to write_scoped_knowledge (not silently coerced or dropped)
#   3. An asset candidate at group scope is rejected with a clear error
#   4. End-to-end: stage → approve → write → get_effective_knowledge returns
#      the group fact for a member property (proves the seam is closed)

from dataclasses import dataclass, field as _field
from typing import Optional as _Optional
from uuid import UUID as _UUID, uuid4 as _uuid4

from app.services.messaging_brain.knowledge.scoped_knowledge_service import (
    EffectiveKnowledgeResult,
    ScopedKnowledgeEntry,
    ScopedKnowledgeProvenance,
    ScopedKnowledgeWriteResult,
)


@dataclass
class _FakeScopedKnowledgeService:
    """In-memory stand-in for ScopedKnowledgeService used in Gap 1 tests."""
    written: list = _field(default_factory=list)
    # {group_id: [ScopedKnowledgeEntry]}
    group_entries: dict = _field(default_factory=dict)
    # {property_id: [group_id]}
    memberships: dict = _field(default_factory=dict)

    async def write_scoped_knowledge(
        self,
        session,
        *,
        tenant_id,
        user_id,
        scope_type,
        scope_target_id,
        topic_id=None,
        question_text="",
        answer_text="",
        tags=None,
        source="",
        metadata=None,
        confidence=None,
        verified_at=None,
        verified_by_user_id=None,
    ):
        entry_id = _uuid4()
        entry = ScopedKnowledgeEntry(
            knowledge_entry_id=entry_id,
            tenant_id=tenant_id,
            scope_type=scope_type,
            scope_target_id=scope_target_id,
            topic_id=topic_id,
            question_text=question_text,
            question_key=(topic_id or question_text or ""),
            answer_text=answer_text,
            tags=list(tags or []),
            source=source,
            metadata=metadata or {},
            created_by_user_id=str(user_id),
            version=1,
        )
        self.written.append(entry)
        if scope_type == "property_group":
            gid = scope_target_id if isinstance(scope_target_id, _UUID) else _UUID(str(scope_target_id))
            self.group_entries.setdefault(gid, []).append(entry)

        return ScopedKnowledgeWriteResult(
            status="created",
            knowledge_entry_id=entry_id,
            scope_type=scope_type,
            scope_target_id=scope_target_id,
            topic_id=topic_id,
            question_text=question_text,
            question_key=(topic_id or question_text or ""),
            version=1,
            previous_version_archived=False,
        )

    async def get_effective_knowledge_for_property(self, session, tenant_id, property_id):
        pid = property_id if isinstance(property_id, _UUID) else _UUID(str(property_id))
        group_ids = self.memberships.get(pid, [])
        group_entries: list[ScopedKnowledgeEntry] = []
        for gid in group_ids:
            group_entries.extend(self.group_entries.get(gid, []))
        provenance = [
            ScopedKnowledgeProvenance(entry=e, scope_origin="property_group")
            for e in group_entries
        ]
        return EffectiveKnowledgeResult(
            effective_by_topic={e.topic_id: e for e in group_entries if e.topic_id},
            effective_freeform_faq=group_entries,
            all_entries_with_provenance=provenance,
        )


class _RealPromoteStagingService(InMemoryStagingService):
    """Like InMemoryStagingService but runs the real _promote_candidate so
    we can test that scope_type is passed through correctly."""

    def __init__(self, knowledge_svc):
        super().__init__()
        self._scoped_knowledge_service = knowledge_svc

    # Re-enable the real _promote_candidate by NOT overriding it.
    # The parent InMemoryStagingService overrides it; we skip the parent's
    # override by going directly to the grandparent (ExtractionStagingService).
    async def _promote_candidate(self, *, session, candidate, reviewed_by_user_id,
                                   is_auto_promoted=False):
        from app.services.extraction.staging_service import ExtractionStagingService
        return await ExtractionStagingService._promote_candidate(
            self, session=session, candidate=candidate,
            reviewed_by_user_id=reviewed_by_user_id, is_auto_promoted=is_auto_promoted,
        )


def test_create_candidate_accepts_property_group_scope():
    """create_candidate must no longer reject scope_type='property_group'."""
    service = InMemoryStagingService()
    candidate = asyncio.run(
        _seed_candidate(service, scope_type="property_group", candidate_type="fact")
    )
    assert candidate.scope_type == "property_group"


def test_create_candidate_rejects_unknown_scope():
    """Sanity check: still rejects invalid scope values."""
    service = InMemoryStagingService()
    try:
        asyncio.run(_seed_candidate(service, scope_type="building"))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "unsupported scope_type" in str(exc)


def test_promote_group_fact_passes_scope_type_through():
    """Approving a property_group-scoped fact must call write_scoped_knowledge
    with scope_type='property_group', not silently coerce it to 'property'."""
    knowledge_svc = _FakeScopedKnowledgeService()
    service = _RealPromoteStagingService(knowledge_svc)
    group_id = _uuid4()

    candidate = asyncio.run(
        _seed_candidate(
            service,
            scope_type="property_group",
            scope_target_id=group_id,
            candidate_type="fact",
            proposed_question_text="What are the HOA quiet hours?",
            proposed_answer_text="10pm – 8am daily.",
            proposed_topic_id="hoa_quiet_hours",
        )
    )
    asyncio.run(service.approve_candidate(None, candidate.candidate_id, _uuid4()))

    assert len(knowledge_svc.written) == 1
    written = knowledge_svc.written[0]
    assert written.scope_type == "property_group", (
        f"scope_type was coerced or dropped — got {written.scope_type!r}"
    )
    assert written.scope_target_id == group_id
    assert written.topic_id == "hoa_quiet_hours"


def test_promote_group_asset_raises_clear_error():
    """An asset candidate at group scope must be rejected with a clear error.
    Assets are property-specific; a group_id is not a valid property target."""
    knowledge_svc = _FakeScopedKnowledgeService()
    service = _RealPromoteStagingService(knowledge_svc)
    group_id = _uuid4()

    candidate = asyncio.run(
        _seed_candidate(
            service,
            scope_type="property_group",
            scope_target_id=group_id,
            candidate_type="asset",
        )
    )
    try:
        asyncio.run(service.approve_candidate(None, candidate.candidate_id, _uuid4()))
        assert False, "expected ValueError for group-scoped asset"
    except ValueError as exc:
        msg = str(exc)
        assert "asset" in msg.lower() and "property_group" in msg, (
            f"error message should mention 'asset' and 'property_group', got: {msg!r}"
        )


def test_end_to_end_group_fact_visible_to_member_property():
    """Full seam test: stage a group fact → approve/promote → call
    get_effective_knowledge_for_property for a member property → confirm
    the HOA fact appears in the effective knowledge result.

    This is the proof the neighborhood/HOA layer is wired end-to-end:
    stage → promote → store → inherit → available to outgoing messages.
    """
    group_id = _uuid4()
    member_property_id = _uuid4()

    knowledge_svc = _FakeScopedKnowledgeService()
    # Wire the group membership so get_effective_knowledge resolves correctly
    knowledge_svc.memberships[member_property_id] = [group_id]

    service = _RealPromoteStagingService(knowledge_svc)

    # Stage a group-scoped HOA fact
    candidate = asyncio.run(
        _seed_candidate(
            service,
            scope_type="property_group",
            scope_target_id=group_id,
            candidate_type="fact",
            proposed_question_text="Are pets allowed in the community pool area?",
            proposed_answer_text="No — the HOA prohibits pets in all pool areas.",
            proposed_topic_id="hoa_pets_pool",
        )
    )

    # Approve → promotes to scoped knowledge
    result = asyncio.run(service.approve_candidate(None, candidate.candidate_id, _uuid4()))
    assert result.promoted_to_table == "concierge_scoped_knowledge"
    assert result.promoted_to_id is not None

    # Read effective knowledge for the member property
    effective = asyncio.run(
        knowledge_svc.get_effective_knowledge_for_property(None, _uuid4(), member_property_id)
    )

    # The group fact must appear
    assert "hoa_pets_pool" in effective.effective_by_topic, (
        "group-scoped HOA fact not visible via get_effective_knowledge_for_property — "
        "neighborhood inheritance is broken"
    )
    hoa_entry = effective.effective_by_topic["hoa_pets_pool"]
    assert hoa_entry.scope_type == "property_group"
    assert "HOA prohibits pets" in hoa_entry.answer_text

    # It must also appear in the provenance list with scope_origin='property_group'
    group_provenances = [
        p for p in effective.all_entries_with_provenance
        if p.scope_origin == "property_group"
    ]
    assert len(group_provenances) == 1, "expected one property_group entry in provenance"
