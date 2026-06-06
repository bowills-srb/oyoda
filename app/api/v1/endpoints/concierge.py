"""
API Endpoints: Concierge.

Exposes concierge functionality:
- POST /concierge/message - Handle guest message
- POST /concierge/decision - Evaluate permission request
- POST /concierge/proactive - Get proactive messages

Phase 1.3b note: POST /concierge/message can route through the messaging
brain orchestrator behind the messaging_brain_runtime feature flag (default
OFF). Flag-OFF behavior is treated as a compatibility contract — see
_handle_via_existing's docstring for the four invariants we maintain.
"""

import logging
from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import TenantContext, get_tenant_context
from app.db.session import get_async_session

from app.services.feature_flags import FeatureFlag, get_feature_flags
from app.services.messaging_brain.knowledge import (
    import_historical_questions as brain_import_historical_questions,
    list_gaps as brain_list_gaps,
    list_global_faq as brain_list_global_faq,
    record_gap as brain_record_gap,
    resolve_gap as brain_resolve_gap,
    upsert_global_faq as brain_upsert_global_faq,
)
from app.services.messaging_brain.knowledge.property_faq import (
    best_faq_answer_with_global,
    load_property_knowledge_bundle,
)
from app.services.orchestration import (
    ConciergeRunner,
    ConciergeRequest,
    get_concierge_runner,
)
from app.services.concierge import get_concierge_maintenance_service
from app.services.concierge import get_concierge_bd_insight_service

from app.domain.concierge import GuestContext, StayStage, GuestType


router = APIRouter(prefix="/concierge", tags=["Concierge"])
logger = logging.getLogger(__name__)


_SECTION_QUESTIONS = {
    "parking": "Where do we park and what are the parking instructions?",
    "door_lock": "How do we access the property and what are the door codes?",
    "pool": "What are the pool and amenity rules?",
    "beach": "What beach gear and access information should we know?",
    "bikes": "Are there bikes available and where are they?",
    "shipping": "Can we ship packages to the property?",
    "transport": "What transportation options are available?",
    "check_in": "What are the full check-in instructions?",
    "check_out": "What are the full check-out instructions?",
    "wifi": "What is the full WiFi information?",
    "hvac": "How do we use the AC and heating?",
    "appliance": "How do we use the appliances?",
}


def _normalize_import_question_key(text: str) -> str:
    import re

    stopwords = {
        "the", "and", "for", "with", "that", "this", "from", "your", "you", "are",
        "can", "could", "would", "should", "what", "when", "where", "which", "who",
        "how", "why", "does", "did", "have", "has", "had", "our", "about", "into",
        "them", "they", "will", "just", "need", "any", "all", "get", "let", "know",
    }
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return " ".join(sorted({w for w in words if len(w) > 2 and w not in stopwords}))


async def _resolve_import_scope(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    external_id: Optional[str],
    property_id: Optional[UUID],
) -> tuple[str, str] | None:
    if property_id:
        return ("property", str(property_id))

    external = str(external_id or "").strip()
    if not external or external == "__all_properties__":
        return ("tenant", str(tenant_id))

    row = (
        await session.execute(
            text(
                """
                SELECT id::text AS property_id
                FROM properties
                WHERE tenant_id = :tenant_id
                  AND (
                        property_code = :external_id
                     OR external_id = :external_id
                  )
                ORDER BY updated_at DESC NULLS LAST, id
                LIMIT 1
                """
            ),
            {"tenant_id": str(tenant_id), "external_id": external},
        )
    ).mappings().first()
    if row and row.get("property_id"):
        return ("property", str(row["property_id"]))
    return None


def _flatten_legacy_import_record(record: Dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source = str(record.get("source") or "guidebook_import")

    for item in record.get("faq") or []:
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if question and answer:
            rows.append(
                {
                    "question_text": question[:500],
                    "answer_text": answer[:4000],
                    "metadata": {"category": "faq", "source_record": source},
                }
            )

    for key, value in (record.get("facts") or {}).items():
        answer = str(value or "").strip()
        if answer:
            rows.append(
                {
                    "question_text": f"What should guests know about {str(key).replace('_', ' ')}?"[:500],
                    "answer_text": answer[:4000],
                    "metadata": {"category": "facts", "source_record": source, "fact_key": str(key)},
                }
            )

    for key, answer in (record.get("sections") or {}).items():
        answer_text = str(answer or "").strip()
        if answer_text:
            rows.append(
                {
                    "question_text": _SECTION_QUESTIONS.get(str(key), f"What should guests know about {str(key).replace('_', ' ')}?")[:500],
                    "answer_text": answer_text[:4000],
                    "metadata": {"category": "guidebook", "source_record": source, "section_key": str(key)},
                }
            )

    return rows


async def _import_records_to_scoped(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    records: List[Dict[str, Any]],
    replace_existing: bool,
) -> Dict[str, Any]:
    from app.services.messaging_brain.knowledge.scoped_knowledge_service import ScopedKnowledgeService

    service = ScopedKnowledgeService()
    inserted = 0
    updated = 0
    skipped = 0

    for record in records:
        scope = await _resolve_import_scope(
            session,
            tenant_id=tenant_id,
            external_id=record.get("property_external_id") or record.get("unit_code"),
            property_id=record.get("property_id"),
        )
        if scope is None:
            skipped += 1
            continue
        scope_type, scope_target_id = scope
        if replace_existing:
            await session.execute(
                text(
                    """
                    UPDATE concierge_scoped_knowledge
                    SET is_active = FALSE,
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id::uuid
                      AND scope_type = :scope_type
                      AND scope_target_id = :scope_target_id::uuid
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "scope_type": scope_type,
                    "scope_target_id": scope_target_id,
                },
            )
        for row in _flatten_legacy_import_record(record):
            question_text = row["question_text"]
            question_key = _normalize_import_question_key(question_text) or question_text.lower()
            existing = (
                await session.execute(
                    text(
                        """
                        SELECT knowledge_entry_id
                        FROM concierge_scoped_knowledge
                        WHERE tenant_id = :tenant_id::uuid
                          AND scope_type = :scope_type
                          AND scope_target_id = :scope_target_id::uuid
                          AND topic_id IS NULL
                          AND question_key = :question_key
                          AND COALESCE(is_active, TRUE) = TRUE
                        LIMIT 1
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id),
                        "scope_type": scope_type,
                        "scope_target_id": scope_target_id,
                        "question_key": question_key,
                    },
                )
            ).first()
            await service.write_scoped_knowledge(
                session=session,
                tenant_id=tenant_id,
                user_id=tenant_id,
                scope_type=scope_type,
                scope_target_id=scope_target_id,
                topic_id=None,
                question_text=question_text,
                answer_text=row["answer_text"],
                tags=[str(row["metadata"].get("category") or "")],
                source=str(record.get("source") or "guidebook_import"),
                metadata=row["metadata"],
            )
            if existing:
                updated += 1
            else:
                inserted += 1

    await session.commit()
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


async def _scoped_knowledge_coverage(
    *,
    session: AsyncSession,
    tenant_id: UUID,
) -> Dict[str, Any]:
    rows = (
        await session.execute(
            text(
                """
                SELECT
                    scope_type,
                    COUNT(*) AS n
                FROM concierge_scoped_knowledge
                WHERE tenant_id = :tenant_id::uuid
                  AND COALESCE(is_active, TRUE) = TRUE
                  AND scope_type IN ('tenant', 'property')
                GROUP BY scope_type
                """
            ),
            {"tenant_id": str(tenant_id)},
        )
    ).mappings().all()
    property_rows = 0
    tenant_rows = 0
    for row in rows:
        if str(row["scope_type"] or "") == "tenant":
            tenant_rows += int(row["n"] or 0)
        else:
            property_rows += int(row["n"] or 0)
    return {
        "total_properties": property_rows,
        "with_faq": property_rows + tenant_rows,
        "with_facts": 0,
        "with_sections": 0,
        "property_ids_mapped": property_rows,
        "property_external_ids": property_rows,
        "schema_mode": "scoped_qna",
        "portfolio_knowledge_rows": tenant_rows,
    }


def _request_stage_to_brain_lifecycle(stage: str):
    from app.services.orchestration.messaging_brain_contracts import MessagingLifecycle

    stage_key = (stage or "").strip().lower()
    mapping = {
        "pre_booking": MessagingLifecycle.PRE_BOOKING,
        "booked": MessagingLifecycle.PRE_ARRIVAL,
        "in_stay": MessagingLifecycle.IN_STAY,
        "post_stay": MessagingLifecycle.POST_STAY,
    }
    return mapping.get(stage_key, MessagingLifecycle.PRE_ARRIVAL)


# =============================================================================
# REQUEST/RESPONSE SCHEMAS
# =============================================================================

class MessageRequest(BaseModel):
    """Request schema for guest message."""
    property_id: UUID
    
    # Message
    message_text: str = Field(..., min_length=1, max_length=2000)
    
    # Guest context
    guest_id: Optional[UUID] = None
    reservation_id: Optional[str] = None
    stage: str = Field("booked", pattern="^(pre_booking|booked|in_stay|post_stay)$")
    property_external_id: Optional[str] = None
    auto_log_gap: bool = True
    auto_track_maintenance: bool = True
    
    # Dates
    check_in_date: Optional[date] = None
    check_out_date: Optional[date] = None


class MessageResponse(BaseModel):
    """Response schema for guest message."""
    response_text: str
    intent: Optional[str] = None
    
    # Suggestions
    suggestions: List[str] = []
    
    # If permission request
    approved: Optional[bool] = None
    requires_escalation: bool = False


class DecisionRequest(BaseModel):
    """Request schema for permission decision."""
    property_id: UUID
    decision_type: str = Field(..., pattern="^(late_checkout|early_checkin)$")
    
    # Request details
    requested_time: str = Field(..., description="Time in HH:MM format")
    
    # Operational state
    next_checkin: Optional[str] = None  # ISO datetime
    staff_capacity: str = Field("normal", pattern="^(strained|normal|flexible)$")


class DecisionResponse(BaseModel):
    """Response schema for permission decision."""
    decision_type: str
    approved: bool
    reason: str
    response_text: str
    requires_escalation: bool = False


class ProactiveRequest(BaseModel):
    """Request schema for proactive messages."""
    property_id: UUID
    market_id: str
    
    # Guest context
    stage: str = Field("booked", pattern="^(pre_booking|booked|in_stay|post_stay)$")
    lead_time_days: Optional[int] = None
    guest_type: str = Field("unknown", pattern="^(family|couple|group|solo|business|unknown)$")
    has_children: bool = False
    
    # Dates
    check_in_date: Optional[date] = None
    check_out_date: Optional[date] = None


class ExperienceSuggestionResponse(BaseModel):
    """A suggested experience."""
    title: str
    description: str
    rationale: str
    urgency: str


class ProactiveResponse(BaseModel):
    """Response schema for proactive messages."""
    messages: List[str]
    suggestions: List[ExperienceSuggestionResponse]


class TripActionResponse(BaseModel):
    type: str
    title: str
    reason: str
    url: Optional[str] = None
    phone: Optional[str] = None
    urgency: str


class TripEventResponse(BaseModel):
    event_id: str
    title: str
    date_window: str
    category: str
    venue_name: Optional[str] = None
    description: str
    demand_impact_score: float
    guest_relevance_score: float
    booking_urgency_score: float
    event_confidence_score: float
    event_class: Optional[str] = None
    actionability: Optional[str] = None
    ticket_url: Optional[str] = None
    ticket_price_range: Optional[str] = None
    source_count: int


class TripPlanRequest(BaseModel):
    property_id: Optional[UUID] = None
    market_id: Optional[str] = None
    check_in_date: date
    check_out_date: date
    question_text: Optional[str] = None
    party_size: int = Field(default=2, ge=1, le=20)
    has_children: bool = False


class TripPlanResponse(BaseModel):
    market_id: Optional[str] = None
    summary: str
    notes: List[str]
    events: List[TripEventResponse]
    action_items: List[TripActionResponse]


class OperatorEventIntelResponse(BaseModel):
    market_id: str
    as_of: str
    days_ahead: int
    windows: List[Any]


class DiningBookRequest(BaseModel):
    restaurant_name: str
    reservation_date: date
    reservation_time: str
    party_size: int = Field(..., ge=1, le=20)
    guest_name: str
    guest_phone: Optional[str] = None
    guest_email: Optional[str] = None
    special_requests: Optional[str] = None
    session_token: Optional[str] = None


class DiningBookResponse(BaseModel):
    success: bool
    status: str
    message: str
    restaurant: str
    date: str
    time: str
    party_size: int
    confirmation_id: Optional[str] = None
    booking_url: Optional[str] = None
    source: str


class KnowledgeImportRequest(BaseModel):
    records: List[Dict[str, Any]]
    replace_existing: bool = False


class KnowledgeImportResponse(BaseModel):
    inserted: int
    updated: int
    skipped: int


class KnowledgeGapRequest(BaseModel):
    property_id: Optional[UUID] = None
    property_external_id: Optional[str] = None
    question_text: str = Field(..., min_length=3, max_length=2000)
    stage: Optional[str] = Field(default=None, pattern="^(pre_booking|booked|in_stay|post_stay)$")
    channel: str = Field(default="text", pattern="^(text|voice|agent)$")
    source: str = Field(default="concierge", max_length=50)
    detected_intent: Optional[str] = None
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeGapResponse(BaseModel):
    gap_id: str
    tenant_id: str
    property_id: Optional[str] = None
    property_external_id: Optional[str] = None
    question_text: str
    stage: Optional[str] = None
    channel: str
    source: str
    detected_intent: Optional[str] = None
    confidence_score: Optional[float] = None
    resolved: bool
    created_at: str
    deduped: bool = False
    duplicate_of_gap_id: Optional[str] = None


class ResolveKnowledgeGapRequest(BaseModel):
    resolution_notes: Optional[str] = None
    faq_answer: Optional[str] = None
    apply_to_similar_properties: bool = True


class HistoricalQuestionsImportRequest(BaseModel):
    records: List[Dict[str, Any]]
    apply_to_similar_properties: bool = True


class GlobalFAQItemRequest(BaseModel):
    question_text: str = Field(..., min_length=3, max_length=2000)
    answer_text: str = Field(..., min_length=1, max_length=4000)
    source: str = Field(default="manual", max_length=50)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GlobalFAQImportRequest(BaseModel):
    records: List[GlobalFAQItemRequest]


class MaintenanceEventRequest(BaseModel):
    property_id: Optional[UUID] = None
    property_external_id: Optional[str] = None
    reservation_id: Optional[str] = None
    issue_text: str = Field(..., min_length=3, max_length=3000)
    source: str = Field(default="manual", max_length=50)
    notes: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MaintenanceResolveRequest(BaseModel):
    notes: Optional[str] = None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/message", response_model=MessageResponse)
async def handle_message(
    request: MessageRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Handle a guest message.

    This is the main REACTIVE endpoint. Detects intent and generates an
    appropriate response.

    Phase 1.3b routing:
      The endpoint checks the messaging_brain_runtime feature flag (resolved
      per property → operator → platform → False) and routes through the
      messaging brain orchestrator when enabled, otherwise falls through to
      the legacy ConciergeRunner path.

      Brain path is gated on TWO conditions:
        1. messaging_brain_runtime flag is enabled for this property/operator
        2. request.auto_track_maintenance is True

      The auto_track_maintenance gate exists because the brain's
      MaintenanceModule unconditionally writes maintenance tracking on
      maintenance-classified messages. When an operator explicitly opts out
      of automatic tracking (auto_track_maintenance=False), routing to the
      brain would override that intent. Falling back to the legacy path
      preserves the operator's stated preference. See seam-map Rule 5.

      Flag OFF (or auto_track_maintenance=False) is a compatibility contract:
        - No brain call
        - No brain-layer audit side effects (persist_inbound, write)
        - No response shape drift
        - No extra writes
      _handle_via_existing's docstring restates this contract; tests in
      tests/unit/test_concierge_endpoint_brain_path.py enforce it.
    """
    # ── Flag check ──────────────────────────────────────────────────────────
    # Two conditions must be true to route to the brain:
    #   1. The runtime flag is enabled for this property/operator
    #   2. The operator has not opted out of automatic tracking for this request
    #
    # Both flags are resolved through the standard three-tier path
    # (property_code → company_id → platform default → False). The default
    # is False, so any uninitialized state lands on the legacy path. That's
    # the safe-by-default behavior we want during phased rollout.
    if request.auto_track_maintenance:
        flags = get_feature_flags(db=session)
        runtime_enabled = await flags.is_enabled(
            FeatureFlag.MESSAGING_BRAIN_RUNTIME,
            company_id=str(tenant.company_id),
            property_code=request.property_external_id,
        )
        if runtime_enabled:
            shadow_mode = await flags.is_enabled(
                FeatureFlag.MESSAGING_BRAIN_SHADOW_MODE,
                company_id=str(tenant.company_id),
                property_code=request.property_external_id,
            )
            return await _handle_via_brain(
                request=request,
                tenant=tenant,
                session=session,
                shadow_mode=shadow_mode,
            )

    return await _handle_via_existing(
        request=request,
        tenant=tenant,
        session=session,
    )


async def _handle_via_existing(
    *,
    request: MessageRequest,
    tenant: TenantContext,
    session: AsyncSession,
) -> MessageResponse:
    """
    Pre-1.3b /concierge/message implementation. UNCHANGED from the prior
    handle_message body — treat as immutable.

    This function is the flag-OFF compatibility contract. The four invariants
    that callers rely on:
      1. No brain call (no GuestMessageBrainOrchestrator instantiated)
      2. No brain-layer audit side effects (no MessageEventStoreAuditWriter
         persist_inbound or write)
      3. No response shape drift — produces the exact MessageResponse shape
         the endpoint produced before 1.3b
      4. No extra writes — only the writes that this function performed
         before 1.3b (knowledge gap logging on weak FAQ matches and unknown
         intents). The concierge maintenance auto-tracking write
         (auto_track_from_message) was retired in Step 10: zero live traffic
         for 30+ days, MaintenanceModule is now the sole automatic writer of
         concierge_maintenance_events (BRAIN_SCHEMA_LOCKDOWN invariant 1).

    Any change here is a behavior change for every operator who has not
    opted into the brain. If you need to modify this function, ask whether
    the change should also apply to _handle_via_brain.
    """
    runner = get_concierge_runner()
    bd_insight_service = get_concierge_bd_insight_service()
    log_ctx = {
        "tenant_id": str(tenant.company_id),
        "property_id": str(request.property_id),
        "property_external_id": request.property_external_id,
        "stage": request.stage,
        "has_dates": bool(request.check_in_date and request.check_out_date),
        "auto_track_maintenance": request.auto_track_maintenance,
        "auto_log_gap": request.auto_log_gap,
    }

    try:
        knowledge_bundle = await load_property_knowledge_bundle(
            session=session,
            tenant_id=tenant.company_id,
            property_id=request.property_id,
        )
    except Exception:
        logger.exception("[concierge.message] load_property_knowledge_bundle failed", extra=log_ctx)
        knowledge_bundle = None

    property_profile = (
        knowledge_bundle.property_profile
        if knowledge_bundle is not None
        else {
            "operational_constraints": {
                "check_in_time": "4:00 PM",
                "check_out_time": "11:00 AM",
                "late_checkout_available": True,
            },
            "access": {
                "wifi_network": "PropertyWiFi",
                "wifi_password": "welcome123",
            },
            "concierge_knowledge": {},
        }
    )

    # FAQ path with optional transfer from similar properties.
    try:
        faq_result = await best_faq_answer_with_global(
            session=session,
            tenant_id=tenant.company_id,
            message_text=request.message_text,
            concierge_knowledge=(
                knowledge_bundle.concierge_knowledge if knowledge_bundle is not None else {}
            ),
        )
    except Exception:
        logger.exception("[concierge.message] best_faq_answer_with_global failed", extra=log_ctx)
        faq_result = {
            "answer": None,
            "match_type": None,
            "score": 0.0,
            "source_property_external_id": None,
            "question": None,
        }
    if faq_result.get("answer"):
        if request.auto_log_gap and float(faq_result.get("score") or 0.0) < 0.68:
            try:
                await brain_record_gap(
                    session=session,
                    tenant_id=tenant.company_id,
                    question_text=request.message_text,
                    property_id=request.property_id,
                    property_external_id=request.property_external_id,
                    stage=request.stage,
                    channel="text",
                    source="concierge_auto",
                    detected_intent="knowledge_faq_weak_match",
                    confidence_score=float(faq_result.get("score") or 0.0),
                    metadata={
                        "reason": "weak_faq_match",
                        "faq_match_type": faq_result.get("match_type"),
                        "source_property_external_id": faq_result.get("source_property_external_id"),
                        "matched_question": faq_result.get("question"),
                    },
                )
            except Exception:
                logger.exception("[concierge.message] record_gap weak_faq_match failed", extra=log_ctx)
                pass
        return MessageResponse(
            response_text=str(faq_result["answer"]),
            intent=(
                "knowledge_faq"
                if faq_result.get("match_type") == "property_faq"
                else "knowledge_faq_global"
                if faq_result.get("match_type") == "global_faq"
                else "knowledge_faq_transfer"
            ),
            suggestions=[],
            approved=None,
            requires_escalation=False,
        )

    if (
        request.check_in_date
        and request.check_out_date
        and request.stage in {"booked", "in_stay", "post_stay", "pre_booking"}
    ):
        from app.services.concierge import get_event_planning_service, is_event_planning_question
        if is_event_planning_question(request.message_text):
            try:
                event_plan = await get_event_planning_service().build_trip_plan(
                    session=session,
                    property_id=request.property_id,
                    check_in_date=request.check_in_date,
                    check_out_date=request.check_out_date,
                    question_text=request.message_text,
                )
            except Exception:
                logger.exception("[concierge.message] build_trip_plan failed", extra=log_ctx)
                event_plan = None
            if event_plan and event_plan.get("summary"):
                return MessageResponse(
                    response_text=str(event_plan["summary"]),
                    intent="trip_event_planning",
                    suggestions=[item["title"] for item in event_plan.get("action_items", [])[:3]],
                    approved=None,
                    requires_escalation=False,
                )

    # Build request
    concierge_request = ConciergeRequest(
        property_id=request.property_id,
        guest_id=request.guest_id,
        reservation_id=request.reservation_id,
        message_text=request.message_text,
        stage=request.stage,
        check_in_date=request.check_in_date,
        check_out_date=request.check_out_date,
    )
    
    # Handle message
    try:
        reply = await runner.handle_message(concierge_request, property_profile)
    except Exception:
        logger.exception("[concierge.message] runner.handle_message failed", extra=log_ctx)
        return MessageResponse(
            response_text=(
                "I can help with that, but I hit a system issue pulling the full answer right now. "
                "A teammate should review this request."
            ),
            intent="system_fallback",
            suggestions=[],
            approved=None,
            requires_escalation=True,
        )

    try:
        bd_insight = bd_insight_service.generate_summary(
            tenant_id=tenant.company_id,
            message_text=request.message_text,
            property_external_id=request.property_external_id,
            property_context=(knowledge_bundle.property_context if knowledge_bundle else {}) or {},
            sections=(knowledge_bundle.sections if knowledge_bundle else {}) or {},
        )
    except Exception:
        logger.exception("[concierge.message] bd_insight_service.generate_summary failed", extra=log_ctx)
        bd_insight = None
    if bd_insight:
        reply.text = f"{reply.text}\n\n{bd_insight}"

    # Auto-capture knowledge gaps for questions we could not confidently handle.
    if request.auto_log_gap:
        detected_intent = (reply.intent or "unknown").strip().lower()
        should_log = False
        confidence_score = None
        reason = None

        if detected_intent == "unknown":
            should_log = True
            confidence_score = 0.2
            reason = "intent_unknown"
        elif reply.requires_escalation and reply.approved is not True:
            should_log = True
            confidence_score = 0.35
            reason = "requires_escalation"

        if should_log:
            try:
                await brain_record_gap(
                    session=session,
                    tenant_id=tenant.company_id,
                    question_text=request.message_text,
                    property_id=request.property_id,
                    property_external_id=request.property_external_id,
                    stage=request.stage,
                    channel="text",
                    source="concierge_auto",
                    detected_intent=reply.intent,
                    confidence_score=confidence_score,
                    metadata={
                        "reason": reason,
                        "response_text": reply.text,
                    },
                )
            except Exception:
                logger.exception("[concierge.message] record_gap post_reply failed", extra=log_ctx)
                pass
    
    return MessageResponse(
        response_text=reply.text,
        intent=reply.intent,
        suggestions=[s.title for s in reply.suggestions] if reply.suggestions else [],
        approved=reply.approved,
        requires_escalation=reply.requires_escalation,
    )


async def _handle_via_brain(
    *,
    request: MessageRequest,
    tenant: TenantContext,
    session: AsyncSession,
    shadow_mode: bool,
) -> MessageResponse:
    """
    Route the guest message through the messaging brain orchestrator.

    Translates between the endpoint's MessageRequest/MessageResponse shapes
    and the brain's InboundGuestMessage/GuestResponseDraft contracts.

    Shape mapping (see seam-map for full detail):
        InboundGuestMessage.message_id        ← f"http_{uuid4()}"  (synthetic)
        InboundGuestMessage.tenant_id          ← tenant.company_id (UUID-as-str)
        InboundGuestMessage.channel            ← "http"
        InboundGuestMessage.source_provider    ← "concierge_api"
        InboundGuestMessage.text               ← request.message_text
        InboundGuestMessage.guest_id           ← request.guest_id (UUID-as-str)
        InboundGuestMessage.reservation_id     ← request.reservation_id
        InboundGuestMessage.property_id        ← request.property_id (UUID-as-str)
        InboundGuestMessage.property_code      ← request.property_external_id
        InboundGuestMessage.lifecycle          ← request.stage mapped to MessagingLifecycle
        InboundGuestMessage.metadata           ← check-in/out date hints for
                                                 canonical helper calls

        GuestResponseDraft.response_text       → MessageResponse.response_text
        contributing_agents[0] (best-effort)   → MessageResponse.intent
        []                                     → MessageResponse.suggestions
        None                                   → MessageResponse.approved
        GuestResponseDraft.escalation_required → MessageResponse.requires_escalation

    Defense in depth: the brain has its own internal error handling
    (handle_inbound_message catches all exceptions and returns an ESCALATE
    draft). This wrapper additionally catches any uncaught construction or
    import errors and returns a "system_fallback" MessageResponse — the
    same shape the legacy path returns when ConciergeRunner crashes.

    Lifecycle is now passed at the API boundary and no longer inferred
    downstream for this path.

    TODO(1.4): GuestResponseDraft does not currently carry the intent_topic
    field; we synthesize intent from contributing_agents[0]. For richer
    intent strings, add intent_topic: Optional[str] to GuestResponseDraft
    and have orchestrator._compose_response set it from the first
    AgentDecision's intent_topic. When that lands, replace the
    _intent_from_agents helper below with draft.intent_topic.
    """
    log_ctx = {
        "tenant_id": str(tenant.company_id),
        "property_id": str(request.property_id),
        "property_external_id": request.property_external_id,
        "stage": request.stage,
        "shadow_mode": shadow_mode,
    }

    try:
        from app.services.messaging_brain import get_messaging_brain_orchestrator
        from app.services.orchestration.messaging_brain_contracts import (
            InboundGuestMessage,
        )

        inbound = InboundGuestMessage(
            message_id=f"http_{uuid4()}",
            tenant_id=str(tenant.company_id),
            channel="http",
            source_provider="concierge_api",
            text=request.message_text,
            guest_id=str(request.guest_id) if request.guest_id else None,
            reservation_id=request.reservation_id or "",
            property_id=str(request.property_id),
            property_code=request.property_external_id,
            lifecycle=_request_stage_to_brain_lifecycle(request.stage),
            metadata={
                "check_in_date": (
                    request.check_in_date.isoformat()
                    if request.check_in_date
                    else None
                ),
                "check_out_date": (
                    request.check_out_date.isoformat()
                    if request.check_out_date
                    else None
                ),
            },
        )

        orch = get_messaging_brain_orchestrator()
        draft = await orch.handle_inbound_message(
            inbound,
            db_session=session,
            shadow_mode=shadow_mode,
        )

        return MessageResponse(
            response_text=draft.response_text,
            intent=_intent_from_agents(draft.contributing_agents),
            suggestions=[],
            approved=None,
            requires_escalation=draft.escalation_required,
        )

    except Exception:
        logger.exception(
            "[concierge.message.brain] brain path failed; returning safe fallback",
            extra=log_ctx,
        )
        return MessageResponse(
            response_text=(
                "I can help with that, but I hit a system issue pulling the full answer right now. "
                "A teammate should review this request."
            ),
            intent="system_fallback",
            suggestions=[],
            approved=None,
            requires_escalation=True,
        )


def _intent_from_agents(contributing_agents: List[str]) -> Optional[str]:
    """
    Phase 1.3b best-effort intent extraction from contributing_agents.

    The brain's GuestResponseDraft does not yet carry classification.intent_topic
    directly; we synthesize an intent string from the first contributing
    agent's name. This is correct for the AC slice (MaintenanceAgent →
    "maintenance") and produces reasonable fallbacks for future agents
    until 1.4 adds intent_topic to GuestResponseDraft.

    Mapping rule:
        first agent name ends with "Agent"  → name.replace("Agent", "").lower()
        empty                                → None
    """
    if not contributing_agents:
        return None
    first = contributing_agents[0]
    if first == "MaintenanceAgent":
        return "maintenance"
    if first.endswith("Agent"):
        return first[:-len("Agent")].lower()
    return first.lower() or None


@router.post("/decision", response_model=DecisionResponse)
async def evaluate_decision(request: DecisionRequest):
    """
    Evaluate a permission request.
    
    Used for late checkout, early check-in, etc.
    """
    from datetime import time, datetime as dt
    
    runner = get_concierge_runner()
    
    # Parse requested time
    try:
        parts = request.requested_time.split(":")
        requested = time(int(parts[0]), int(parts[1]))
    except:
        raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM")
    
    # Parse next checkin if provided
    next_checkin = None
    if request.next_checkin:
        try:
            next_checkin = dt.fromisoformat(request.next_checkin)
        except:
            pass
    
    # Build property profile
    property_profile = {
        "operational_constraints": {
            "check_in_time": "4:00 PM",
            "check_out_time": "11:00 AM",
            "late_checkout_available": True,
            "late_checkout_latest": "2:00 PM",
            "minimum_turnover_hours": 4.0,
        }
    }
    
    # Build operational state
    from app.domain.operations import OperationalState, StaffCapacity
    
    staff_map = {
        "strained": StaffCapacity.STRAINED,
        "normal": StaffCapacity.NORMAL,
        "flexible": StaffCapacity.FLEXIBLE,
    }
    
    ops_state = OperationalState(
        property_id=request.property_id,
        staff_capacity=staff_map.get(request.staff_capacity, StaffCapacity.NORMAL),
        next_checkin=next_checkin,
    )
    
    if request.decision_type == "late_checkout":
        from app.services.execution import LateCheckoutPayload
        
        payload = LateCheckoutPayload(
            property_id=request.property_id,
            requested_time=requested,
            next_checkin=next_checkin,
            staff_capacity=request.staff_capacity,
            late_checkout_available=True,
            late_checkout_latest=time(14, 0),
            minimum_turnover_hours=4.0,
        )
        
        reply = runner.executor.evaluate_late_checkout(payload)
        
        return DecisionResponse(
            decision_type=request.decision_type,
            approved=reply.decision_outcome.approved if reply.decision_outcome else False,
            reason=reply.decision_outcome.reasoning[0] if reply.decision_outcome and reply.decision_outcome.reasoning else "Unknown",
            response_text=reply.response_text,
            requires_escalation=reply.requires_escalation,
        )
    
    # Early check-in (placeholder)
    return DecisionResponse(
        decision_type=request.decision_type,
        approved=False,
        reason="Early check-in evaluation not yet implemented",
        response_text="I'll check on early check-in availability for you.",
        requires_escalation=True,
    )


@router.post("/proactive", response_model=ProactiveResponse)
async def get_proactive_messages(
    request: ProactiveRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Get proactive messages and suggestions.
    
    Call this on booking confirmation or periodically.
    """
    from app.services.messaging_brain.proactive_trigger_adapter import (
        build_preview_intent,
        compose_proactive_draft,
    )

    intent = await build_preview_intent(
        session=session,
        property_id=str(request.property_id),
        market_id=request.market_id,
        stage=request.stage,
        guest_type=request.guest_type,
        has_children=request.has_children,
        lead_time_days=request.lead_time_days,
        check_in_date=request.check_in_date,
        check_out_date=request.check_out_date,
    )
    draft = await compose_proactive_draft(intent, db_session=session)
    messages = [draft.response_text] if draft.response_text else []
    suggestions: list[ExperienceSuggestionResponse] = []

    if request.check_in_date and request.check_out_date:
        from app.services.concierge import get_event_planning_service
        trip_plan = await get_event_planning_service().build_trip_plan(
            session=session,
            property_id=request.property_id,
            market_id=request.market_id,
            check_in_date=request.check_in_date,
            check_out_date=request.check_out_date,
            has_children=request.has_children,
        )
        if trip_plan.get("summary"):
            messages = [trip_plan["summary"], *messages][:3]
        for action in trip_plan.get("action_items", [])[:2]:
            suggestions.append(
                ExperienceSuggestionResponse(
                    title=action["title"],
                    description=action["reason"],
                    rationale=action["reason"],
                    urgency=action["urgency"],
                )
            )

    return ProactiveResponse(
        messages=messages,
        suggestions=[
            s if isinstance(s, ExperienceSuggestionResponse) else ExperienceSuggestionResponse(
                title=s.title,
                description=s.description,
                rationale=s.rationale,
                urgency=s.urgency.value,
            )
            for s in suggestions
        ],
    )


@router.post("/trip-plan", response_model=TripPlanResponse)
async def build_trip_plan(
    request: TripPlanRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Build a stay-window event plan for a booked or soon-arriving guest."""
    from app.services.concierge import get_event_planning_service
    result = await get_event_planning_service().build_trip_plan(
        session=session,
        property_id=request.property_id,
        market_id=request.market_id,
        check_in_date=request.check_in_date,
        check_out_date=request.check_out_date,
        question_text=request.question_text,
        party_size=request.party_size,
        has_children=request.has_children,
    )
    return TripPlanResponse(**result)


@router.get("/operator-event-intel", response_model=OperatorEventIntelResponse)
async def get_operator_event_intel(
    market_id: str,
    days_ahead: int = 90,
    session: AsyncSession = Depends(get_async_session),
):
    """Return tiered 0-7 / 7-30 / 30-90 day event intelligence for operators."""
    from app.services.concierge import get_event_planning_service
    result = await get_event_planning_service().build_operator_event_intel(
        session=session,
        market_id=market_id,
        days_ahead=days_ahead,
    )
    return OperatorEventIntelResponse(**result)


@router.post("/dining/book", response_model=DiningBookResponse)
async def create_dining_booking(
    request: DiningBookRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
):
    """Create or hand off a dining reservation and persist the audit trail."""
    from app.services.concierge import get_dining_service
    result = await get_dining_service().create_reservation(
        operator_id=str(tenant.company_id),
        restaurant_name=request.restaurant_name,
        date=request.reservation_date.isoformat(),
        time=request.reservation_time,
        party_size=request.party_size,
        guest_name=request.guest_name,
        guest_phone=request.guest_phone,
        guest_email=request.guest_email,
        special_requests=request.special_requests,
        session_token=request.session_token,
        db_session=session,
    )
    await session.commit()
    return DiningBookResponse(
        success=result.success,
        status=result.status,
        message=result.message,
        restaurant=result.restaurant,
        date=result.date,
        time=result.time,
        party_size=result.party_size,
        confirmation_id=result.confirmation_id,
        booking_url=result.booking_url,
        source=result.source,
    )


@router.post("/knowledge/import", response_model=KnowledgeImportResponse)
async def import_concierge_knowledge(
    request: KnowledgeImportRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
):
    """Bulk import guidebook-derived knowledge for this tenant."""
    result = await _import_records_to_scoped(
        session=session,
        tenant_id=tenant.company_id,
        records=request.records,
        replace_existing=request.replace_existing,
    )
    return KnowledgeImportResponse(**result)


@router.get("/knowledge/coverage")
async def concierge_knowledge_coverage(
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
):
    """Coverage report for imported concierge knowledge."""
    try:
        data = await _scoped_knowledge_coverage(session=session, tenant_id=tenant.company_id)
    except Exception:
        logger.exception(
            "[concierge.knowledge.coverage] coverage failed",
            extra={"tenant_id": str(tenant.company_id)},
        )
        data = {
            "total_properties": 0,
            "with_faq": 0,
            "with_facts": 0,
            "with_sections": 0,
            "property_ids_mapped": 0,
            "property_external_ids": 0,
            "schema_mode": "error_fallback",
        }
    return {"company_id": str(tenant.company_id), **data}


@router.post("/knowledge/gaps", response_model=KnowledgeGapResponse)
async def create_concierge_knowledge_gap(
    request: KnowledgeGapRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
):
    """Capture a guest question that current knowledge could not answer well."""
    result = await brain_record_gap(
        session=session,
        tenant_id=tenant.company_id,
        question_text=request.question_text,
        property_id=request.property_id,
        property_external_id=request.property_external_id,
        stage=request.stage,
        channel=request.channel,
        source=request.source,
        detected_intent=request.detected_intent,
        confidence_score=request.confidence_score,
        metadata=request.metadata,
    )
    return KnowledgeGapResponse(**result)


@router.get("/knowledge/gaps")
async def list_concierge_knowledge_gaps(
    unresolved_only: bool = True,
    limit: int = 50,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
):
    """List unresolved knowledge gaps to prioritize guidebook/data updates."""
    rows = await brain_list_gaps(
        session=session,
        tenant_id=tenant.company_id,
        unresolved_only=unresolved_only,
        limit=limit,
    )
    return {"company_id": str(tenant.company_id), "count": len(rows), "items": rows}


@router.post("/knowledge/gaps/{gap_id}/resolve")
async def resolve_concierge_knowledge_gap(
    gap_id: UUID,
    request: ResolveKnowledgeGapRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
):
    """Resolve a knowledge gap and optionally convert it into FAQ knowledge."""
    result = await brain_resolve_gap(
        session=session,
        tenant_id=tenant.company_id,
        gap_id=gap_id,
        resolution_notes=request.resolution_notes,
        faq_answer=request.faq_answer,
        apply_to_similar_properties=request.apply_to_similar_properties,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Gap not found")
    from app.core.database import get_db_session
    from app.services.messaging_brain.kb_retry_handler import kb_post_save_retry_held_inquiries

    retry_result = await kb_post_save_retry_held_inquiries(
        db=session,
        db_factory=get_db_session,
        tenant_id=str(tenant.company_id),
        operator_id=str(tenant.company_id),
        topic=result.get("retry_topic"),
    )
    return {"company_id": str(tenant.company_id), **result, **retry_result}


@router.post("/knowledge/gaps/import")
async def import_historical_questions(
    request: HistoricalQuestionsImportRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Import historical guest questions.

    Records with answers are pushed into FAQ knowledge; records without answers
    are stored as unresolved gaps.
    """
    result = await brain_import_historical_questions(
        session=session,
        tenant_id=tenant.company_id,
        records=request.records,
        apply_to_similar_properties=request.apply_to_similar_properties,
    )
    return {"company_id": str(tenant.company_id), **result}


@router.post("/knowledge/global-faq/import")
async def import_global_faq(
    request: GlobalFAQImportRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
):
    """Bulk import tenant-global FAQ records shared across all properties."""
    upserted = 0
    for record in request.records:
        await brain_upsert_global_faq(
            session=session,
            tenant_id=tenant.company_id,
            question_text=record.question_text,
            answer_text=record.answer_text,
            source=record.source,
            tags=record.tags,
            metadata=record.metadata,
        )
        upserted += 1
    return {"company_id": str(tenant.company_id), "upserted": upserted}


@router.get("/knowledge/global-faq")
async def list_global_faq(
    limit: int = 200,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
):
    """List tenant-global FAQ records."""
    items = await brain_list_global_faq(
        session=session,
        tenant_id=tenant.company_id,
        limit=limit,
    )
    return {"company_id": str(tenant.company_id), "count": len(items), "items": items}


@router.post("/maintenance/events")
async def create_maintenance_event(
    request: MaintenanceEventRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a maintenance event for ops tracking/escalation."""
    service = get_concierge_maintenance_service()
    item = await service.create_event(
        session=session,
        tenant_id=tenant.company_id,
        issue_text=request.issue_text,
        property_id=request.property_id,
        property_external_id=request.property_external_id,
        reservation_id=request.reservation_id,
        source=request.source,
        notes=request.notes,
        metadata=request.metadata,
    )
    return {"company_id": str(tenant.company_id), **item}


@router.get("/maintenance/events")
async def list_maintenance_events(
    status: str = "open",
    limit: int = 100,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
):
    """List maintenance events (`open`, `resolved`, or `all`)."""
    service = get_concierge_maintenance_service()
    items = await service.list_events(
        session=session,
        tenant_id=tenant.company_id,
        status=status,
        limit=limit,
    )
    return {"company_id": str(tenant.company_id), "count": len(items), "items": items}


@router.post("/maintenance/events/{event_id}/resolve")
async def resolve_maintenance_event(
    event_id: UUID,
    request: MaintenanceResolveRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_async_session),
):
    """Resolve a maintenance event."""
    service = get_concierge_maintenance_service()
    row = await service.resolve_event(
        session=session,
        tenant_id=tenant.company_id,
        event_id=event_id,
        notes=request.notes,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Maintenance event not found")
    return {"company_id": str(tenant.company_id), **row}
