#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence
from unittest.mock import AsyncMock, patch
from uuid import UUID

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.session import SessionLocal
from app.services.integrations.email_dispatch import dispatch_pre_booking
from app.services.integrations.email_inbound import ParsedEmailMessage
from app.services.integrations.gmail_inbox_poller import EmailInboxPollerBase
from app.services.messaging.inbound_normalizer import InboundMessageNormalizer
from app.services.messaging.message_event_store import _upsert_normalization


@dataclass(frozen=True)
class ReplaySource:
    draft_id: str
    route_outcome: str
    draft_source: str
    confidence_source: str
    tenant_id: str
    platform: str
    guest_name: str
    guest_email: str
    message_text: str
    property_code: str
    thread_id: str
    message_id: str
    received_at: datetime
    requested_check_in: Any
    requested_check_out: Any
    requested_guests: Any
    source_provider: str
    source_thread_id: str
    source_message_id: str
    sender_display_name: str
    sender_address: str
    raw_subject: str
    latest_guest_turn: str
    prior_thread_context: str
    full_message_text: str
    structured_asks: list[str]
    parser_used: str
    selected_property_code: str
    selected_property_match_type: str


class _NoopTokenManager:
    async def get_access_token(self) -> str:  # pragma: no cover
        raise RuntimeError("token access is disabled for this replay path")

    def auth_header(self, token: str) -> dict[str, str]:  # pragma: no cover
        raise RuntimeError("token access is disabled for this replay path")


def _default_watched_email() -> str:
    return (
        os.getenv("GMAIL_WATCHED_EMAIL_BH")
        or os.getenv("GMAIL_WATCHED_EMAIL")
        or "info@beachhabitats30a.com"
    )


def _parse_json_array(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if not value:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item or "").strip()]
    return []


async def _load_sources(
    db,
    *,
    tenant_id: str,
    draft_ids: Sequence[str],
    source_message_ids: Sequence[str],
) -> list[ReplaySource]:
    filters = ["p.company_id = CAST(:tenant_id AS uuid)"]
    params: dict[str, object] = {"tenant_id": tenant_id}

    if draft_ids:
        filters.append("p.draft_id = ANY(:draft_ids)")
        params["draft_ids"] = list(draft_ids)
    if source_message_ids:
        filters.append(
            "(p.message_id = ANY(:source_message_ids) OR COALESCE(p.gmail_message_id, '') = ANY(:source_message_ids))"
        )
        params["source_message_ids"] = list(source_message_ids)
    rows = (
        await db.execute(
            text(
                f"""
                SELECT
                    p.draft_id,
                    COALESCE(p.status, '') AS inquiry_status,
                    COALESCE(n.draft_source, '') AS draft_source,
                    COALESCE(p.confidence_source::text, '') AS confidence_source,
                    p.company_id::text AS tenant_id,
                    COALESCE(p.platform, '') AS platform,
                    COALESCE(p.guest_name, '') AS guest_name,
                    COALESCE(p.guest_email, n.sender_address, '') AS guest_email,
                    COALESCE(p.message_text, '') AS message_text,
                    COALESCE(p.property_external_id, '') AS property_code,
                    COALESCE(p.thread_id, '') AS thread_id,
                    COALESCE(p.message_id, '') AS message_id,
                    COALESCE(p.received_at, p.created_at) AS received_at,
                    p.requested_check_in,
                    p.requested_check_out,
                    p.requested_guests,
                    COALESCE(n.source_provider, '') AS source_provider,
                    COALESCE(n.source_thread_id, '') AS source_thread_id,
                    COALESCE(n.source_message_id, '') AS source_message_id,
                    COALESCE(n.sender_display_name, '') AS sender_display_name,
                    COALESCE(n.sender_address, '') AS sender_address,
                    COALESCE(n.raw_subject, '') AS raw_subject,
                    COALESCE(n.latest_guest_turn, '') AS latest_guest_turn,
                    COALESCE(n.prior_thread_context, '') AS prior_thread_context,
                    COALESCE(n.full_message_text, '') AS full_message_text,
                    COALESCE(n.structured_asks::text, '[]') AS structured_asks,
                    COALESCE(n.parser_used, p.parser_source, '') AS parser_used,
                    COALESCE(n.selected_property_code, '') AS selected_property_code,
                    COALESCE(n.selected_property_match_type, '') AS selected_property_match_type,
                    COALESCE(n.route_outcome, '') AS route_outcome
                FROM pre_booking_inquiries p
                LEFT JOIN LATERAL (
                    SELECT *
                    FROM message_normalizations n
                    WHERE n.tenant_id = p.company_id
                      AND (
                          n.source_message_id = p.message_id
                          OR n.source_message_id = COALESCE(p.gmail_message_id, '')
                      )
                    ORDER BY COALESCE(n.updated_at, n.created_at) DESC NULLS LAST
                    LIMIT 1
                ) n ON TRUE
                WHERE {" AND ".join(filters)}
                {"AND COALESCE(n.route_outcome, '') IN ('pre_booking_fallback', 'pre_booking_save_failed')" if not draft_ids and not source_message_ids else ""}
                ORDER BY COALESCE(p.received_at, p.created_at) DESC
                """
            ),
            params,
        )
    ).fetchall()

    return [
        ReplaySource(
            draft_id=str(row.draft_id or ""),
            route_outcome=str(row.route_outcome or ""),
            draft_source=str(row.draft_source or ""),
            confidence_source=str(row.confidence_source or ""),
            tenant_id=str(row.tenant_id or tenant_id),
            platform=str(row.platform or "email"),
            guest_name=str(row.guest_name or "Guest"),
            guest_email=str(row.guest_email or row.sender_address or ""),
            message_text=str(row.message_text or ""),
            property_code=str(row.selected_property_code or row.property_code or ""),
            thread_id=str(row.source_thread_id or row.thread_id or ""),
            message_id=str(row.source_message_id or row.message_id or ""),
            received_at=row.received_at,
            requested_check_in=row.requested_check_in,
            requested_check_out=row.requested_check_out,
            requested_guests=row.requested_guests,
            source_provider=str(row.source_provider or "email"),
            source_thread_id=str(row.source_thread_id or row.thread_id or ""),
            source_message_id=str(row.source_message_id or row.message_id or ""),
            sender_display_name=str(row.sender_display_name or row.guest_name or "Guest"),
            sender_address=str(row.sender_address or ""),
            raw_subject=str(row.raw_subject or ""),
            latest_guest_turn=str(row.latest_guest_turn or row.message_text or ""),
            prior_thread_context=str(row.prior_thread_context or ""),
            full_message_text=str(row.full_message_text or row.message_text or ""),
            structured_asks=_parse_json_array(row.structured_asks),
            parser_used=str(row.parser_used or "phase1_replay_source"),
            selected_property_code=str(row.selected_property_code or row.property_code or ""),
            selected_property_match_type=str(row.selected_property_match_type or ""),
        )
        for row in rows
    ]


def _build_shadow_parsed(
    source: ReplaySource,
    *,
    replay_suffix: str,
) -> ParsedEmailMessage:
    base_message_id = source.source_message_id or source.message_id or source.draft_id
    replay_message_id = f"{base_message_id}::{replay_suffix}"
    replay_thread_id = source.source_thread_id or source.thread_id or f"thread::{source.draft_id}"
    sender_name = source.sender_display_name or source.guest_name or "Guest"
    sender_address = (source.sender_address or source.guest_email or "").strip().lower()
    raw_from = f"{sender_name} <{sender_address}>" if sender_address else sender_name
    latest_guest_turn = source.latest_guest_turn or source.message_text
    full_message_text = source.full_message_text or latest_guest_turn

    return ParsedEmailMessage(
        source_message_id=replay_message_id,
        source_thread_id=replay_thread_id,
        source_provider=source.source_provider or "email",
        gmail_message_id=replay_message_id,
        gmail_thread_id=replay_thread_id,
        message_id_header="",
        guest_name=source.guest_name or sender_name,
        guest_email=sender_address,
        sender_role="guest",
        reply_channel_address=sender_address,
        subject=source.raw_subject or "",
        body=latest_guest_turn,
        latest_guest_message=latest_guest_turn,
        conversation_context=source.prior_thread_context or "",
        full_body=full_message_text,
        asks=list(source.structured_asks or []),
        platform=(source.platform or source.source_provider or "email").lower(),
        is_inquiry=True,
        lifecycle_stage="pre_booking",
        parser_source=source.parser_used or "phase1_replay",
        property_name=source.selected_property_code or source.property_code or "",
        property_code=source.selected_property_code or source.property_code or "",
        property_match_type=source.selected_property_match_type or "",
        raw_property_mention=source.selected_property_code or source.property_code or "",
        platform_listing_id="",
        platform_unit_id="",
        source_interaction_id=replay_thread_id,
        source_property_id="",
        source_account_id="",
        provider_property_id="",
        provider_account_id="",
        reservation_id="",
        ota_site="",
        conversation_id="",
        message_type="",
        recipient_type="",
        intake_layer1_decision="guest",
        intake_layer1_reason="phase1_replay_seed",
        requested_check_in=source.requested_check_in,
        requested_check_out=source.requested_check_out,
        requested_guests=source.requested_guests,
        received_at=source.received_at,
        raw_from=raw_from,
    )


async def _seed_shadow_normalization(
    db,
    *,
    tenant_id: UUID,
    watched_email: str,
    parsed: ParsedEmailMessage,
) -> None:
    normalizer = InboundMessageNormalizer()
    normalized = normalizer.normalize_email_message(parsed, watched_email=watched_email)
    await _upsert_normalization(
        db,
        tenant_id,
        None,
        normalized,
        selected_property_code=parsed.property_code or "",
        selected_property_match_type=parsed.property_match_type or "",
    )


async def _capture_shadow_result(
    db,
    *,
    tenant_id: str,
    replay_message_id: str,
) -> dict[str, Any]:
    inquiry_row = (
        await db.execute(
            text(
                """
                SELECT
                    draft_id,
                    status,
                    confidence_source,
                    review_verdict,
                    autonomy_decision,
                    intent,
                    confidence,
                    draft_confidence,
                    policy_warnings,
                    policy_flags,
                    blocked_by_gap_topics,
                    draft_text
                FROM pre_booking_inquiries
                WHERE company_id = CAST(:tenant_id AS uuid)
                  AND message_id = :message_id
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "message_id": replay_message_id},
        )
    ).fetchone()
    normalization_row = (
        await db.execute(
            text(
                """
                SELECT
                    route_outcome,
                    draft_source,
                    fallback_reason,
                    selected_property_code,
                    selected_property_match_type
                FROM message_normalizations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND source_channel = 'email'
                  AND source_message_id = :message_id
                ORDER BY COALESCE(updated_at, created_at) DESC NULLS LAST
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "message_id": replay_message_id},
        )
    ).fetchone()
    return {
        "inquiry": None
        if inquiry_row is None
        else {
            "draft_id": inquiry_row.draft_id,
            "status": inquiry_row.status,
            "confidence_source": inquiry_row.confidence_source,
            "review_verdict": inquiry_row.review_verdict,
            "autonomy_decision": inquiry_row.autonomy_decision,
            "intent": inquiry_row.intent,
            "confidence": float(inquiry_row.confidence or 0.0) if inquiry_row.confidence is not None else None,
            "draft_confidence": (
                float(inquiry_row.draft_confidence)
                if inquiry_row.draft_confidence is not None
                else None
            ),
            "policy_warnings": inquiry_row.policy_warnings,
            "policy_flags": inquiry_row.policy_flags,
            "blocked_by_gap_topics": inquiry_row.blocked_by_gap_topics,
            "draft_preview": " ".join((inquiry_row.draft_text or "").split())[:220],
        },
        "normalization": None
        if normalization_row is None
        else {
            "route_outcome": normalization_row.route_outcome,
            "draft_source": normalization_row.draft_source,
            "fallback_reason": normalization_row.fallback_reason,
            "selected_property_code": normalization_row.selected_property_code,
            "selected_property_match_type": normalization_row.selected_property_match_type,
        },
    }


async def _replay_one(
    db,
    *,
    source: ReplaySource,
    operator_id: str,
    watched_email: str,
    replay_suffix: str,
) -> dict[str, Any]:
    parsed = _build_shadow_parsed(source, replay_suffix=replay_suffix)
    tenant_uuid = UUID(source.tenant_id)
    poller = EmailInboxPollerBase(
        operator_id=operator_id,
        company_id=tenant_uuid,
        token_manager=_NoopTokenManager(),
        watched_email=watched_email,
        db=db,
    )

    original_commit = db.commit
    captured_lifecycle: dict[str, Any] = {}
    captured_normalization: list[dict[str, Any]] = []

    async def _shadow_commit() -> None:
        await db.flush()

    from app.services.messaging_brain import pre_booking_lifecycle as prebooking_lifecycle_module
    from app.services.integrations import email_dispatch as email_dispatch_module

    original_run_lifecycle = prebooking_lifecycle_module.run_brain_pre_booking_lifecycle
    original_update_normalization = email_dispatch_module.update_normalization_outcome

    async def _capture_lifecycle(*args, **kwargs):
        result = await original_run_lifecycle(*args, **kwargs)
        captured_lifecycle.clear()
        captured_lifecycle.update(result or {})
        return result

    async def _capture_normalization(*args, **kwargs):
        captured_normalization.append(
            {
                "route_outcome": kwargs.get("route_outcome", ""),
                "draft_source": kwargs.get("draft_source", ""),
                "fallback_reason": kwargs.get("fallback_reason", ""),
                "source_message_id": args[3] if len(args) > 3 else kwargs.get("source_message_id", ""),
            }
        )
        return await original_update_normalization(*args, **kwargs)

    db.commit = _shadow_commit  # type: ignore[method-assign]
    try:
        await _seed_shadow_normalization(
            db,
            tenant_id=tenant_uuid,
            watched_email=watched_email,
            parsed=parsed,
        )
        with (
            patch(
                "app.services.feature_flags.is_brain_prebooking_lifecycle_primary_enabled",
                AsyncMock(return_value=True),
            ),
            patch.object(
                prebooking_lifecycle_module,
                "run_brain_pre_booking_lifecycle",
                new=_capture_lifecycle,
            ),
            patch.object(
                email_dispatch_module,
                "update_normalization_outcome",
                new=_capture_normalization,
            ),
            patch(
                "app.services.messaging_brain.pre_booking_lifecycle.send_prebooking_review_alert",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.messaging_brain.pre_booking_lifecycle._log_required_mode_event",
                new=AsyncMock(return_value=None),
            ),
        ):
            dispatch_outcome = await dispatch_pre_booking(
                services=poller._email_dispatch_services(),
                parsed=parsed,
            )
        captured = await _capture_shadow_result(
            db,
            tenant_id=source.tenant_id,
            replay_message_id=parsed.message_id,
        )
        return {
            "source": {
                "draft_id": source.draft_id,
                "message_id": source.message_id,
                "route_outcome": source.route_outcome,
                "draft_source": source.draft_source,
                "confidence_source": source.confidence_source,
                "property_code": source.property_code,
            },
            "shadow_ids": {
                "source_message_id": parsed.source_message_id,
                "thread_id": parsed.thread_id,
            },
            "dispatch_outcome": dispatch_outcome,
            "brain_lifecycle_result": dict(captured_lifecycle),
            "normalization_attempts": list(captured_normalization),
            **captured,
        }
    finally:
        db.commit = original_commit  # type: ignore[method-assign]
        await db.rollback()


async def _main(args: argparse.Namespace) -> int:
    async with SessionLocal() as db:
        sources = await _load_sources(
            db,
            tenant_id=args.tenant_id,
            draft_ids=args.draft_id,
            source_message_ids=args.source_message_id,
        )
        if not sources:
            print("no_sources_found")
            return 1

        if args.list_only:
            for source in sources:
                preview = " ".join((source.latest_guest_turn or source.message_text).split())[:140]
                print(
                    json.dumps(
                        {
                            "draft_id": source.draft_id,
                            "message_id": source.message_id,
                            "route_outcome": source.route_outcome,
                            "draft_source": source.draft_source,
                            "confidence_source": source.confidence_source,
                            "property_code": source.property_code,
                            "preview": preview,
                        }
                    )
                )
            return 0

        exit_code = 0
        for index, source in enumerate(sources, start=1):
            result = await _replay_one(
                db,
                source=source,
                operator_id=args.operator_id,
                watched_email=args.watched_email,
                replay_suffix=f"{args.replay_suffix}-{index}",
            )
            print(json.dumps(result, default=str))
            inquiry = result.get("inquiry") or {}
            normalization = result.get("normalization") or {}
            lifecycle = result.get("brain_lifecycle_result") or {}
            normalization_attempts = result.get("normalization_attempts") or []
            final_attempt = normalization_attempts[-1] if normalization_attempts else {}
            if not lifecycle:
                exit_code = 1
                continue
            if (lifecycle.get("draft_source") or final_attempt.get("draft_source")) != "messaging_brain":
                exit_code = 1
            if "brain_runtime_not_primary" in str(
                normalization.get("fallback_reason") or final_attempt.get("fallback_reason") or ""
            ):
                exit_code = 1
        return exit_code


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Shadow-replay pre-booking inquiries through dispatch_pre_booking with "
            "brain_prebooking_lifecycle_primary forced on, then roll back."
        )
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
        "--watched-email",
        default=_default_watched_email(),
        help="Watched inbox address used for normalization/channel constraints.",
    )
    parser.add_argument(
        "--draft-id",
        action="append",
        default=[],
        help="Replay a specific pre_booking_inquiries.draft_id. Repeatable.",
    )
    parser.add_argument(
        "--source-message-id",
        action="append",
        default=[],
        help="Replay by source message id / inquiry message id. Repeatable.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="List candidate source rows without replaying them.",
    )
    parser.add_argument(
        "--replay-suffix",
        default="brain-primary-replay",
        help="Suffix added to shadow source_message_id values.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parse_args())))
