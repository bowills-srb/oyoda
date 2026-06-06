#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Sequence
from uuid import UUID

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.messaging.inbound_normalizer import CanonicalInboundMessage
from app.services.messaging_brain.persistence.prebooking_inquiry_store import (
    save_inquiry_from_canonical,
)
from app.services.messaging_brain.persistence.prebooking_inquiry_types import (
    InquirySaveContext,
)
from app.services.messaging_brain.pre_booking_lifecycle import (
    _resolve_autonomy_decision,
    _resolve_brain_draft_confidence,
)
from app.services.messaging_brain.pre_booking_retry import (
    _BRAIN_DEFAULT_POLICY,
    _brain_missing_knowledge_topics,
    _requested_nights,
    _run_brain_prebooking_retry,
)
from app.services.messaging_brain.prebooking_runtime import (
    PolicyCheckResult,
    PreBookingClassificationStage,
    PreBookingDecisionStage,
    SendDecision,
)
from app.services.messaging_brain.policy.platform_compliance import (
    apply_pre_booking_draft_source_policy,
    evaluate_pre_booking_policy,
)


FAILED_OUTCOMES = (
    "pre_booking_save_failed",
    "pre_booking_fallback",
    "save_failed",
)


@dataclass(frozen=True)
class ReplayCandidate:
    source_message_id: str
    source_channel: str
    source_provider: str
    route_outcome: str
    created_at: datetime
    selected_property_code: str
    latest_guest_turn: str
    sender_display_name: str
    sender_address: str
    raw_subject: str
    source_thread_id: str
    prior_thread_context: str
    full_message_text: str


class _NoopTokenManager:
    async def get_access_token(self) -> str:  # pragma: no cover
        raise RuntimeError("token access is disabled for this replay path")

    def auth_header(self, token: str) -> dict[str, str]:  # pragma: no cover
        raise RuntimeError("token access is disabled for this replay path")


def _extract_review_verdict(reviewer_flags: list[str], reviewer_warnings: list[str]) -> str | None:
    for warning in reviewer_warnings:
        text_value = str(warning or "")
        marker = "adversarial_review:verdict="
        if marker in text_value:
            verdict = text_value.split(marker, 1)[1].split("|", 1)[0].strip()
            if verdict in {"pass", "revise", "hold"}:
                return verdict
    for flag in reviewer_flags:
        lowered = str(flag or "").lower()
        if "forced operator hold" in lowered:
            return "hold"
        if "revised the brain draft" in lowered:
            return "revise"
    return "pass"


def _candidate_row(candidate: ReplayCandidate) -> SimpleNamespace:
    return SimpleNamespace(
        draft_id=f"REPLAY-{candidate.source_message_id[:12]}",
        platform=candidate.source_provider or "email",
        guest_name=candidate.sender_display_name or "Guest",
        guest_email=candidate.sender_address or "",
        message_text=candidate.latest_guest_turn or candidate.full_message_text or "",
        gmail_message_id="",
        gmail_thread_id="",
        property_external_id=candidate.selected_property_code or "",
        requested_check_in=None,
        requested_check_out=None,
        requested_guests=None,
        status="pending_review",
        thread_id=candidate.source_thread_id or candidate.source_message_id,
        message_id=candidate.source_message_id,
        guest_thread_id=None,
    )


def _canonical_inbound(candidate: ReplayCandidate) -> CanonicalInboundMessage:
    return CanonicalInboundMessage(
        source_channel="email",
        source_provider=candidate.source_provider or "email",
        source_thread_id=candidate.source_thread_id or candidate.source_message_id,
        source_message_id=candidate.source_message_id,
        sender_role="guest",
        sender_display_name=candidate.sender_display_name or "Guest",
        sender_address=candidate.sender_address or "",
        sent_at=candidate.created_at,
        raw_subject=candidate.raw_subject or "",
        latest_guest_turn=candidate.latest_guest_turn or candidate.full_message_text or "",
        prior_thread_context=candidate.prior_thread_context or "",
        full_message_text=candidate.full_message_text or candidate.latest_guest_turn or "",
        structured_asks=[],
        prior_operator_commitments=[],
        property_binding_candidates=[],
        channel_constraints={},
        parser_used="replay_failed_prebooking_messages",
        parser_version="v1",
        parser_notes=[f"replayed_from_route_outcome:{candidate.route_outcome}"],
        latest_turn_confidence=0.0,
        latest_turn_extracted=bool(candidate.prior_thread_context and candidate.latest_guest_turn),
        guest_name=candidate.sender_display_name or "Guest",
        guest_email=candidate.sender_address or "",
    )


async def _load_candidates(
    db,
    *,
    tenant_id: str,
    start_at: str,
    limit: int | None,
    source_message_ids: Sequence[str] | None,
) -> list[ReplayCandidate]:
    filters = [
        "tenant_id = CAST(:tenant_id AS uuid)",
        "created_at >= :start_at",
        "route_outcome = ANY(:failed_outcomes)",
        "source_channel IN ('email', 'gmail')",
        "COALESCE(source_message_id, '') <> ''",
    ]
    params: dict[str, object] = {
        "tenant_id": tenant_id,
        "start_at": datetime.fromisoformat(start_at),
        "failed_outcomes": list(FAILED_OUTCOMES),
    }
    if source_message_ids:
        filters.append("source_message_id = ANY(:source_message_ids)")
        params["source_message_ids"] = list(source_message_ids)

    sql = f"""
        WITH ranked AS (
            SELECT
                source_message_id,
                source_channel,
                COALESCE(source_provider, '') AS source_provider,
                COALESCE(route_outcome, '') AS route_outcome,
                created_at,
                COALESCE(selected_property_code, '') AS selected_property_code,
                COALESCE(latest_guest_turn, '') AS latest_guest_turn,
                COALESCE(sender_display_name, '') AS sender_display_name,
                COALESCE(sender_address, '') AS sender_address,
                COALESCE(raw_subject, '') AS raw_subject,
                COALESCE(source_thread_id, '') AS source_thread_id,
                COALESCE(prior_thread_context, '') AS prior_thread_context,
                COALESCE(full_message_text, '') AS full_message_text,
                ROW_NUMBER() OVER (
                    PARTITION BY source_message_id
                    ORDER BY
                        CASE WHEN source_channel = 'email' THEN 0 ELSE 1 END,
                        created_at DESC
                ) AS rn
            FROM message_normalizations
            WHERE {" AND ".join(filters)}
        )
        SELECT
            source_message_id,
            source_channel,
            source_provider,
            route_outcome,
            created_at,
            selected_property_code,
            latest_guest_turn,
            sender_display_name,
            sender_address,
            raw_subject,
            source_thread_id,
            prior_thread_context,
            full_message_text
        FROM ranked r
        WHERE rn = 1
          AND NOT EXISTS (
              SELECT 1
              FROM pre_booking_inquiries pbi
              WHERE pbi.company_id = CAST(:tenant_id AS uuid)
                AND (
                    pbi.message_id = r.source_message_id
                    OR COALESCE(pbi.gmail_message_id, '') = r.source_message_id
                )
          )
        ORDER BY created_at, source_message_id
    """
    if limit:
        sql += "\nLIMIT :limit"
        params["limit"] = limit

    rows = (await db.execute(text(sql), params)).fetchall()
    return [
        ReplayCandidate(
            source_message_id=str(row.source_message_id),
            source_channel=str(row.source_channel),
            source_provider=str(row.source_provider),
            route_outcome=str(row.route_outcome),
            created_at=row.created_at,
            selected_property_code=str(row.selected_property_code or ""),
            latest_guest_turn=str(row.latest_guest_turn or ""),
            sender_display_name=str(row.sender_display_name or ""),
            sender_address=str(row.sender_address or ""),
            raw_subject=str(row.raw_subject or ""),
            source_thread_id=str(row.source_thread_id or ""),
            prior_thread_context=str(row.prior_thread_context or ""),
            full_message_text=str(row.full_message_text or ""),
        )
        for row in rows
    ]


async def _backfill_one(
    db,
    *,
    tenant_id: str,
    operator_id: str,
    candidate: ReplayCandidate,
) -> dict[str, str]:
    # Use the shared retry pipeline, but force the "stored inquiry" branch by
    # leaving gmail_message_id blank on the synthetic row. This reuses the
    # modern pre-booking brain and property-context loading without making any
    # outbound email/API calls.
    from app.api.v1.endpoints import operator_prebooking as operator_prebooking_module
    from app.services.integrations.gmail_inbox_poller import EmailInboxPollerBase

    poller = EmailInboxPollerBase(
        operator_id=operator_id,
        company_id=UUID(str(tenant_id)),
        token_manager=_NoopTokenManager(),
        watched_email="",
        db=db,
    )
    original_builder = operator_prebooking_module._build_inbox_adapter_for_tenant

    async def _fake_builder(_db, _operator_id, _tenant_id):
        return poller

    operator_prebooking_module._build_inbox_adapter_for_tenant = _fake_builder
    try:
        row = _candidate_row(candidate)
        brain_result, reviewed_draft_text, reviewer_flags, reviewer_warnings, hydrated = await _run_brain_prebooking_retry(
            db=db,
            tenant_id=tenant_id,
            operator_id=operator_id,
            row=row,
        )
    finally:
        operator_prebooking_module._build_inbox_adapter_for_tenant = original_builder

    classification = PreBookingClassificationStage(
        intent=brain_result.legacy_intent or "general",
        confidence=float(brain_result.intent_confidence or 0.0),
        metadata=None,
        shadow_parser_notes=[],
    )
    missing_knowledge_topics = _brain_missing_knowledge_topics(brain_result)
    policy_outcome = evaluate_pre_booking_policy(
        message=hydrated["message_text"],
        intent=classification.intent,
        confidence=classification.confidence,
        requested_nights=_requested_nights(
            SimpleNamespace(
                requested_check_in=hydrated["requested_check_in"],
                requested_check_out=hydrated["requested_check_out"],
            )
        ),
        requested_guests=hydrated["requested_guests"],
        property_data=hydrated["property_data"],
        operator_policies=hydrated["operator_policies"],
        auto_send_threshold=_BRAIN_DEFAULT_POLICY.auto_send_threshold,
        flag_pricing_inquiries=_BRAIN_DEFAULT_POLICY.flag_pricing_inquiries,
        flag_pet_inquiries=_BRAIN_DEFAULT_POLICY.flag_pet_inquiries,
        approval_mode="required",
        missing_knowledge_topics=missing_knowledge_topics,
    )
    policy_outcome = apply_pre_booking_draft_source_policy(
        outcome=policy_outcome,
        draft_source="messaging_brain",
        intent=classification.intent,
        message=hydrated["message_text"],
    )
    decision_stage = PreBookingDecisionStage(
        approval_mode="required",
        auto_send_policy=_BRAIN_DEFAULT_POLICY,
        policy_result=PolicyCheckResult(
            flags=list(policy_outcome.flags),
            warnings=list(policy_outcome.warnings),
            block_send=policy_outcome.block_send,
        ),
        missing_knowledge_topics=list(missing_knowledge_topics),
        knowledge_gap_analysis=None,
        decision=SendDecision.HOLD,
    )
    if reviewer_flags:
        decision_stage.policy_result.flags.extend(reviewer_flags)
    if reviewer_warnings:
        decision_stage.policy_result.warnings.extend(reviewer_warnings)

    review_verdict = _extract_review_verdict(reviewer_flags, reviewer_warnings)
    resolved_confidence_source = (
        "gap_blocked"
        if decision_stage.missing_knowledge_topics
        else "held_for_review"
        if review_verdict == "hold"
        else "model_composer"
        if _resolve_brain_draft_confidence(brain_result) is not None
        else "intent_only"
    )
    resolved_draft_confidence = (
        None if resolved_confidence_source in {"gap_blocked", "held_for_review"}
        else _resolve_brain_draft_confidence(brain_result)
    )

    save_result = await save_inquiry_from_canonical(
        db=db,
        inbound=_canonical_inbound(candidate),
        context=InquirySaveContext(
            draft_id=f"INQ-REPLAY-{candidate.source_message_id[:8].upper()}",
            company_id=UUID(str(tenant_id)),
            selected_property_code=hydrated["property_external_id"] or candidate.selected_property_code,
            requested_check_in=hydrated["requested_check_in"],
            requested_check_out=hydrated["requested_check_out"],
            requested_guests=hydrated["requested_guests"],
            intent=classification.intent,
            confidence=classification.confidence,
            draft_text=reviewed_draft_text,
            draft_source="messaging_brain",
            policy_flags=list(decision_stage.policy_result.flags),
            policy_warnings=list(decision_stage.policy_result.warnings),
            decision=decision_stage.decision.value,
            guest_thread_id=None,
            blocked_by_gap_topics=list(decision_stage.missing_knowledge_topics or []),
            intent_confidence=classification.confidence,
            draft_confidence=resolved_draft_confidence,
            confidence_source=resolved_confidence_source,
            review_verdict=review_verdict,
            autonomy_decision=_resolve_autonomy_decision(
                approval_mode=decision_stage.approval_mode,
                decision=decision_stage.decision,
                missing_knowledge_topics=list(decision_stage.missing_knowledge_topics or []),
                policy_warnings=list(decision_stage.policy_result.warnings or []),
                review_verdict=review_verdict,
            ),
        ),
    )
    return {
        "ok": "true" if save_result.status in {"saved", "duplicate_skipped"} else "false",
        "source_message_id": candidate.source_message_id,
        "save_status": save_result.status,
        "intent": classification.intent,
        "property_code": hydrated["property_external_id"] or candidate.selected_property_code,
    }


async def _count_result_rows(db, *, tenant_id: str, source_message_id: str) -> tuple[int, int]:
    row = (
        await db.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND source_message_id = :source_message_id
                    ) AS normalization_rows,
                    (
                        SELECT COUNT(*)
                        FROM pre_booking_inquiries pbi
                        WHERE pbi.company_id = CAST(:tenant_id AS uuid)
                          AND (
                              pbi.message_id = :source_message_id
                              OR COALESCE(pbi.gmail_message_id, '') = :source_message_id
                          )
                    ) AS inquiry_rows
                FROM message_normalizations
                """
            ),
            {
                "tenant_id": tenant_id,
                "source_message_id": source_message_id,
            },
        )
    ).fetchone()
    return int(row.normalization_rows or 0), int(row.inquiry_rows or 0)


async def _main(args) -> int:
    session_cm = SessionLocal()
    async with session_cm as db:
        candidates = await _load_candidates(
            db,
            tenant_id=args.tenant_id,
            start_at=args.start_at,
            limit=args.limit,
            source_message_ids=args.source_message_id,
        )
        print(f"candidates={len(candidates)} tenant={args.tenant_id} start_at={args.start_at}")
        if not candidates:
            return 0

        for candidate in candidates:
            preview = " ".join(candidate.latest_guest_turn.split())[:100]
            print(
                f"- {candidate.created_at.isoformat()} "
                f"{candidate.source_message_id} "
                f"outcome={candidate.route_outcome} "
                f"prop={candidate.selected_property_code or '-'} "
                f"preview={preview!r}"
            )

        if args.dry_run:
            return 0

        success = 0
        failed = 0
        for candidate in candidates:
            try:
                result = await _backfill_one(
                    db,
                    tenant_id=args.tenant_id,
                    operator_id=args.operator_id,
                    candidate=candidate,
                )
                normalization_rows, inquiry_rows = await _count_result_rows(
                    db,
                    tenant_id=args.tenant_id,
                    source_message_id=candidate.source_message_id,
                )
                if result.get("ok") == "true":
                    success += 1
                else:
                    failed += 1
                print(
                    f"replayed source_message_id={candidate.source_message_id} "
                    f"ok={result.get('ok')} save_status={result.get('save_status', '')} "
                    f"intent={result.get('intent', '')} "
                    f"property_code={result.get('property_code', '')} "
                    f"normalization_rows={normalization_rows} inquiry_rows={inquiry_rows}"
                )
            except Exception as exc:
                failed += 1
                try:
                    await db.rollback()
                except Exception:
                    pass
                print(
                    f"replayed source_message_id={candidate.source_message_id} "
                    f"ok=false error={type(exc).__name__}:{exc}"
                )

        print(f"done success={success} failed={failed}")
        return 0 if failed == 0 else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill failed normalized pre-booking messages into inquiry rows without sending outbound email.",
    )
    parser.add_argument(
        "--tenant-id",
        default="e07980b2-a990-4b24-91d1-c8cb71ab70e1",
        help="Tenant UUID to replay for.",
    )
    parser.add_argument(
        "--operator-id",
        default="4d0721d7-3d36-409a-a648-7209ad347a73",
        help="Operator UUID used for property-context loading.",
    )
    parser.add_argument(
        "--start-at",
        default="2026-05-20T00:00:00-05:00",
        help="Replay failures created at or after this timestamp.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional cap on candidates. 0 means no cap.",
    )
    parser.add_argument(
        "--source-message-id",
        action="append",
        default=[],
        help="Replay only these specific source message ids.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List replay candidates without mutating production state.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    ns = _parse_args()
    ns.limit = ns.limit or None
    raise SystemExit(asyncio.run(_main(ns)))
