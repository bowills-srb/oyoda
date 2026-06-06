from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text

from app.services.messaging.inbound_normalizer import CanonicalInboundMessage


logger = logging.getLogger(__name__)


def _first_candidate_value(
    candidates: list[dict[str, Any]],
    candidate_type: str,
) -> str:
    for candidate in candidates:
        if str(candidate.get("candidate_type") or "").strip() != candidate_type:
            continue
        value = str(candidate.get("value") or "").strip()
        if value:
            return value
    return ""


async def _resolve_selected_property_binding(
    db,
    tenant_id: UUID,
    normalized: CanonicalInboundMessage,
) -> tuple[str, str]:
    candidates = list(normalized.property_binding_candidates or [])
    if not candidates:
        return "", ""

    direct_property_code = _first_candidate_value(candidates, "property_code")
    if direct_property_code:
        return direct_property_code, "property_code_candidate"

    platform_listing_id = _first_candidate_value(candidates, "platform_listing_id")
    platform_unit_id = _first_candidate_value(candidates, "platform_unit_id")
    external_id_hint = _first_candidate_value(candidates, "external_id_hint")
    raw_property_mention = _first_candidate_value(candidates, "raw_property_mention")
    property_name = _first_candidate_value(candidates, "property_name")

    if not any(
        [
            platform_listing_id,
            platform_unit_id,
            external_id_hint,
            raw_property_mention,
            property_name,
        ]
    ):
        return "", ""

    try:
        from app.services.property_canonical_service import (
            get_canonical_property_service,
        )

        lookup_name = (
            f"ExternalID:{external_id_hint}"
            if external_id_hint
            else (raw_property_mention or property_name)
        )
        resolved = await get_canonical_property_service(db).resolve_property_code(
            tenant_id,
            platform_listing_id=platform_listing_id,
            platform_unit_id=platform_unit_id,
            property_name=lookup_name,
            platform=normalized.source_provider or "",
        )
    except Exception:
        logger.warning(
            "[CanonicalPersist] property binding resolution failed tenant=%s source_message_id=%s",
            tenant_id,
            normalized.source_message_id,
            exc_info=True,
        )
        try:
            await db.rollback()
        except Exception:
            logger.debug(
                "[CanonicalPersist] rollback after property resolution failure failed",
                exc_info=True,
            )
        return "", ""

    resolved = str(resolved or "").strip()
    if not resolved:
        return "", ""

    if platform_listing_id:
        match_type = "platform_listing_id"
    elif platform_unit_id:
        match_type = "platform_unit_id"
    elif external_id_hint:
        match_type = "external_id_hint"
    elif raw_property_mention:
        match_type = "raw_property_mention"
    elif property_name:
        match_type = "property_name"
    else:
        match_type = "canonical_resolver"

    return resolved, match_type


# IMPORTANT — DO NOT REINTRODUCE A PROCESS-GLOBAL `_TABLE_EXISTS_CACHE` HERE.
#
# An earlier version of this module memoized the result of `_table_exists` in
# a module-level dict that lived for the lifetime of the worker process. The
# cache had no TTL, no invalidation, and treated False results as cacheable.
#
# That produced a silent-data-loss failure mode: if the FIRST call to
# `_table_exists` for a given table happened to fail (DB momentarily
# unavailable at startup, aborted-transaction state from upstream code,
# information_schema query racing migrations, etc.), the cached `False`
# would persist forever. Every subsequent inbound message would early-return
# from `persist_canonical_inbound_message` and `update_normalization_outcome`
# without inserting or updating anything, with no error log line because
# the function returned BEFORE its try/except block. Downstream
# `update_normalization_*` calls would silently UPDATE 0 rows.
#
# `information_schema.tables` is already cached at the Postgres catalog
# level — repeated reads are nearly free. Keeping a Python-side cache only
# duplicates that, while introducing a stateful footgun where the cost of
# being wrong is invisible data loss in the messaging pipeline.
#
# If a perf concern emerges later, the right fix is positive-only caching
# with a short TTL — never a permanent cache of False.


async def _table_exists(db, table_name: str) -> bool:
    """Check whether a table exists. NOT memoized — see comment above."""
    try:
        row = (
            await db.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_name = :table_name
                    )
                    """
                ),
                {"table_name": table_name},
            )
        ).fetchone()
        exists = bool(row[0]) if row else False
    except Exception:
        # A failure here used to be silent. Log it loudly so future
        # incidents don't have to be diagnosed by elimination.
        logger.warning(
            "[MessageEventStore] _table_exists query failed for %s; "
            "treating as not-exists for this call only",
            table_name,
            exc_info=True,
        )
        return False
    if not exists:
        # Logged at DEBUG because in dev/migration-pending environments
        # this is the expected legitimate path. Production should never
        # see this for `message_normalizations`, `channels`, `conversations`,
        # or `messages` — set up an alert on this log line if you want
        # early warning of schema drift.
        logger.debug(
            "[MessageEventStore] table %s reported missing by information_schema",
            table_name,
        )
    return exists


async def persist_canonical_inbound_message(
    db,
    tenant_id: UUID,
    normalized: CanonicalInboundMessage,
) -> Dict[str, Optional[str]]:
    """
    Shadow-write a normalized inbound message into the long-term messaging
    schema and normalization audit table. Fail-open by design.
    """
    if not db:
        return {}

    # Defensive: clear any aborted-transaction state inherited from upstream
    # operations in the same poll cycle. The Gmail poller's
    # `_prepare_parsed_message` chains several DB-touching helpers
    # (`_resolve_property_code`, `_auto_store_property_identity`,
    # `_maybe_record_unmatched_platform_identifier`) before reaching this
    # function. Each of those wraps its own try/except, but a SQLAlchemy
    # async session in `IDLE in transaction (aborted)` state stays poisoned
    # until rolled back at the session level — local catches don't recover
    # the connection. Without this rollback, every query in this function
    # would error with InFailedSQLTransactionError, the outer except below
    # would fire, and we'd silently lose the normalization row.
    #
    # Rollback on a clean session is a no-op, so this is safe in all paths.
    try:
        await db.rollback()
    except Exception:
        logger.debug(
            "[CanonicalPersist] preemptive rollback no-op or failed",
            exc_info=True,
        )

    if not await _table_exists(db, "message_normalizations"):
        return {}

    message_uuid = None
    conversation_id = None
    channel_id = None
    selected_property_code = ""
    selected_property_match_type = ""

    try:
        selected_property_code, selected_property_match_type = (
            await _resolve_selected_property_binding(db, tenant_id, normalized)
        )

        channels_exists = await _table_exists(db, "channels")
        if channels_exists:
            channel_id = await _find_or_create_channel(db, tenant_id, normalized)
        else:
            logger.error(
                "[CanonicalPersist] channels table unavailable for tenant=%s source_message_id=%s",
                tenant_id,
                normalized.source_message_id,
            )

        conversations_exists = await _table_exists(db, "conversations")
        if conversations_exists:
            conversation_id = await _find_or_create_conversation(db, tenant_id, normalized)
        else:
            logger.error(
                "[CanonicalPersist] conversations table unavailable for tenant=%s source_message_id=%s",
                tenant_id,
                normalized.source_message_id,
            )

        messages_exists = await _table_exists(db, "messages")
        if conversation_id:
            if messages_exists:
                message_uuid = await _insert_message(
                    db=db,
                    conversation_id=conversation_id,
                    channel_id=channel_id,
                    normalized=normalized,
                )
            else:
                logger.error(
                    "[CanonicalPersist] messages table unavailable for tenant=%s source_message_id=%s",
                    tenant_id,
                    normalized.source_message_id,
                )
        else:
            logger.error(
                "[CanonicalPersist] conversation resolution returned no id for tenant=%s source_message_id=%s guest_email=%s",
                tenant_id,
                normalized.source_message_id,
                normalized.guest_email,
            )

        norm_id = await _upsert_normalization(
            db=db,
            tenant_id=tenant_id,
            message_uuid=message_uuid,
            normalized=normalized,
            selected_property_code=selected_property_code,
            selected_property_match_type=selected_property_match_type,
        )
        await db.commit()
        return {
            "normalization_id": str(norm_id) if norm_id else None,
            "message_id": str(message_uuid) if message_uuid else None,
            "conversation_id": str(conversation_id) if conversation_id else None,
            "channel_id": str(channel_id) if channel_id else None,
            "selected_property_code": selected_property_code or None,
            "selected_property_match_type": selected_property_match_type or None,
        }
    except Exception:
        await db.rollback()
        logger.error(
            "[CanonicalPersist] failed for tenant=%s source_message_id=%s source_channel=%s",
            tenant_id,
            normalized.source_message_id,
            normalized.source_channel,
            exc_info=True,
        )
        return {}


async def update_normalization_outcome(
    db,
    tenant_id: UUID,
    source_channel: str,
    source_message_id: str,
    *,
    selected_property_code: str = "",
    selected_property_match_type: str = "",
    route_outcome: str = "",
    draft_source: str = "",
    fallback_reason: str = "",
    parser_notes_append: Optional[List[Dict[str, Any]]] = None,
) -> None:
    if not db or not source_message_id:
        return
    try:
        await db.rollback()
    except Exception:
        logger.debug(
            "[MessageEventStore] pre-update rollback no-op or failed",
            exc_info=True,
        )
    if not await _table_exists(db, "message_normalizations"):
        return
    try:
        result = await db.execute(
            text(
                """
                UPDATE message_normalizations
                SET selected_property_code = CASE
                        WHEN :selected_property_code = '' THEN selected_property_code
                        ELSE :selected_property_code
                    END,
                    selected_property_match_type = CASE
                        WHEN :selected_property_match_type = '' THEN selected_property_match_type
                        ELSE :selected_property_match_type
                    END,
                    route_outcome = CASE
                        WHEN :route_outcome = '' THEN route_outcome
                        ELSE :route_outcome
                    END,
                    draft_source = CASE
                        WHEN :draft_source = '' THEN draft_source
                        ELSE :draft_source
                    END,
                    fallback_reason = CASE
                        WHEN :fallback_reason = '' THEN fallback_reason
                        ELSE :fallback_reason
                    END,
                    parser_notes = CASE
                        WHEN :parser_notes_append = '[]' THEN parser_notes
                        ELSE COALESCE(parser_notes, '[]'::jsonb) || CAST(:parser_notes_append AS jsonb)
                    END,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND source_channel = :source_channel
                  AND source_message_id = :source_message_id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "source_channel": source_channel,
                "source_message_id": source_message_id,
                "selected_property_code": selected_property_code or "",
                "selected_property_match_type": selected_property_match_type or "",
                "route_outcome": route_outcome or "",
                "draft_source": draft_source or "",
                "fallback_reason": fallback_reason or "",
                "parser_notes_append": json.dumps(parser_notes_append or []),
            },
        )
        # Detect the silent zero-row UPDATE that previously hid behind the
        # cache poisoning bug. If the row should exist but doesn't, that's
        # an upstream persist failure — make it visible.
        rowcount = getattr(result, "rowcount", None)
        if rowcount == 0:
            logger.warning(
                "[MessageEventStore] update_normalization_outcome matched 0 rows "
                "for tenant=%s source_channel=%s source_message_id=%s — "
                "upstream persist_canonical_inbound_message likely failed to "
                "create the row. route_outcome=%s draft_source=%s",
                tenant_id,
                source_channel,
                source_message_id,
                route_outcome,
                draft_source,
            )
        await db.commit()
    except Exception:
        await db.rollback()


async def update_normalization_composer_metadata(
    db,
    tenant_id: UUID,
    source_channel: str,
    source_message_id: str,
    *,
    composer_source: str,
    composer_response_text: str,
    composer_latency_ms: Optional[int] = None,
    composer_input_tokens: Optional[int] = None,
    composer_output_tokens: Optional[int] = None,
    composer_notes: Optional[List[str]] = None,
) -> None:
    """Session 12 — persist composer fields onto the existing
    message_normalizations row.

    Called from MessageEventStoreAuditWriter._write_outcome when
    record.composer_metadata is not None. Unconditional write of all
    six composer columns; the orchestrator already gated on the
    composer running, so we don't repeat the empty-string-no-op
    pattern from update_normalization_outcome here.

    The columns this writes were added by migration 054. Schema:
      composer_source           TEXT
      composer_response_text    TEXT
      composer_latency_ms       INTEGER
      composer_input_tokens     INTEGER
      composer_output_tokens    INTEGER
      composer_notes            JSONB NOT NULL DEFAULT '[]'::jsonb

    composer_notes serializes via json.dumps; an empty list is a valid
    "composer ran cleanly with no notes" signal and is preserved as such.

    Fail-open: any DB error is rolled back and swallowed. The audit
    writer wraps this call in its own try/except too, so we have
    belt-and-suspenders defense against persistence failures crashing
    the pipeline.
    """
    if not db or not source_message_id:
        return
    try:
        await db.rollback()
    except Exception:
        logger.debug(
            "[MessageEventStore] pre-update rollback no-op or failed",
            exc_info=True,
        )
    if not await _table_exists(db, "message_normalizations"):
        return
    try:
        result = await db.execute(
            text(
                """
                UPDATE message_normalizations
                SET composer_source = :composer_source,
                    composer_response_text = :composer_response_text,
                    composer_latency_ms = :composer_latency_ms,
                    composer_input_tokens = :composer_input_tokens,
                    composer_output_tokens = :composer_output_tokens,
                    composer_notes = CAST(:composer_notes AS jsonb),
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND source_channel = :source_channel
                  AND source_message_id = :source_message_id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "source_channel": source_channel,
                "source_message_id": source_message_id,
                "composer_source": composer_source,
                "composer_response_text": composer_response_text,
                "composer_latency_ms": composer_latency_ms,
                "composer_input_tokens": composer_input_tokens,
                "composer_output_tokens": composer_output_tokens,
                "composer_notes": json.dumps(composer_notes or []),
            },
        )
        # Same zero-row visibility guard as update_normalization_outcome.
        # Composer metadata UPDATEs target a row that should already exist
        # via persist_canonical_inbound_message. If it doesn't, the
        # compare-mode panel in Audit will silently lack data — surface it.
        rowcount = getattr(result, "rowcount", None)
        if rowcount == 0:
            logger.warning(
                "[MessageEventStore] update_normalization_composer_metadata matched "
                "0 rows for tenant=%s source_channel=%s source_message_id=%s — "
                "composer metadata cannot be persisted because the "
                "normalization row does not exist. composer_source=%s",
                tenant_id,
                source_channel,
                source_message_id,
                composer_source,
            )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception(
            "[CanonicalPersist] update_normalization_composer_metadata failed "
            "for tenant=%s source_message_id=%s",
            tenant_id,
            source_message_id,
        )


async def _find_or_create_channel(db, tenant_id: UUID, normalized: CanonicalInboundMessage):
    row = (
        await db.execute(
            text(
                """
                SELECT channel_id
                FROM channels
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND channel_type = :channel_type
                ORDER BY created_at ASC
                LIMIT 1
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "channel_type": normalized.source_channel,
            },
        )
    ).fetchone()
    if row:
        return row[0]

    row = (
        await db.execute(
            text(
                """
                INSERT INTO channels (
                    tenant_id, channel_type, display_name, inbound_enabled,
                    outbound_enabled, status, config
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :channel_type, :display_name, TRUE,
                    TRUE, 'active', CAST(:config AS jsonb)
                )
                RETURNING channel_id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "channel_type": normalized.source_channel,
                "display_name": f"{normalized.source_channel.title()} inbound",
                "config": json.dumps(
                    {
                        "source_provider": normalized.source_provider,
                        "channel_constraints": normalized.channel_constraints,
                    }
                ),
            },
        )
    ).fetchone()
    return row[0] if row else None


async def _find_or_create_conversation(db, tenant_id: UUID, normalized: CanonicalInboundMessage):
    params = {"tenant_id": str(tenant_id)}
    row = None
    if normalized.guest_email:
        params["guest_email"] = normalized.guest_email
        row = (
            await db.execute(
                text(
                    """
                    SELECT conversation_id
                    FROM conversations
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND LOWER(guest_email) = LOWER(:guest_email)
                      AND status = 'active'
                    ORDER BY last_message_at DESC
                    LIMIT 1
                    """
                ),
                params,
            )
        ).fetchone()
    if row:
        await db.execute(
            text(
                """
                UPDATE conversations
                SET last_message_at = GREATEST(last_message_at, :sent_at),
                    updated_at = NOW()
                WHERE conversation_id = CAST(:conversation_id AS uuid)
                """
            ),
            {"conversation_id": str(row[0]), "sent_at": normalized.sent_at},
        )
        return row[0]

    row = (
        await db.execute(
            text(
                """
                INSERT INTO conversations (
                    tenant_id, guest_email, guest_name, stage, status,
                    first_message_at, last_message_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :guest_email, :guest_name, 'pre_booking', 'active',
                    :sent_at, :sent_at
                )
                RETURNING conversation_id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "guest_email": normalized.guest_email or None,
                "guest_name": normalized.guest_name or normalized.sender_display_name or "Guest",
                "sent_at": normalized.sent_at,
            },
        )
    ).fetchone()
    return row[0] if row else None


async def _insert_message(db, conversation_id, channel_id, normalized: CanonicalInboundMessage):
    row = (
        await db.execute(
            text(
                """
                INSERT INTO messages (
                    conversation_id, channel_id, direction, body, subject,
                    channel_reference, author, detected_intent, sent_at
                )
                VALUES (
                    CAST(:conversation_id AS uuid),
                    CAST(:channel_id AS uuid),
                    'inbound',
                    :body,
                    :subject,
                    CAST(:channel_reference AS jsonb),
                    :author,
                    :detected_intent,
                    :sent_at
                )
                RETURNING message_id
                """
            ),
            {
                "conversation_id": str(conversation_id),
                "channel_id": str(channel_id) if channel_id else None,
                "body": normalized.latest_guest_turn,
                "subject": normalized.raw_subject,
                "channel_reference": json.dumps(
                    {
                        "source_channel": normalized.source_channel,
                        "source_provider": normalized.source_provider,
                        "source_thread_id": normalized.source_thread_id,
                        "source_message_id": normalized.source_message_id,
                        "parser_used": normalized.parser_used,
                    }
                ),
                "author": normalized.sender_role,
                "detected_intent": (normalized.structured_asks[0] if normalized.structured_asks else None),
                "sent_at": normalized.sent_at,
            },
        )
    ).fetchone()
    return row[0] if row else None


async def _upsert_normalization(
    db,
    tenant_id: UUID,
    message_uuid,
    normalized: CanonicalInboundMessage,
    *,
    selected_property_code: str = "",
    selected_property_match_type: str = "",
):
    row = (
        await db.execute(
            text(
                """
                INSERT INTO message_normalizations (
                    tenant_id, message_id, source_channel, source_provider,
                    source_thread_id, source_message_id, sender_role,
                    sender_display_name, sender_address, sent_at, raw_subject,
                    latest_guest_turn, prior_thread_context, full_message_text,
                    structured_asks, prior_operator_commitments,
                    property_binding_candidates, channel_constraints,
                    parser_used, parser_version, parser_notes,
                    latest_turn_confidence, latest_turn_extracted,
                    selected_property_code, selected_property_match_type
                )
                VALUES (
                    CAST(:tenant_id AS uuid), CAST(:message_id AS uuid), :source_channel, :source_provider,
                    :source_thread_id, :source_message_id, :sender_role,
                    :sender_display_name, :sender_address, :sent_at, :raw_subject,
                    :latest_guest_turn, :prior_thread_context, :full_message_text,
                    CAST(:structured_asks AS jsonb), CAST(:prior_operator_commitments AS jsonb),
                    CAST(:property_binding_candidates AS jsonb), CAST(:channel_constraints AS jsonb),
                    :parser_used, :parser_version, CAST(:parser_notes AS jsonb),
                    :latest_turn_confidence, :latest_turn_extracted,
                    :selected_property_code, :selected_property_match_type
                )
                ON CONFLICT (tenant_id, source_channel, source_message_id)
                DO UPDATE SET
                    message_id = COALESCE(EXCLUDED.message_id, message_normalizations.message_id),
                    sender_display_name = EXCLUDED.sender_display_name,
                    sender_address = EXCLUDED.sender_address,
                    sent_at = EXCLUDED.sent_at,
                    raw_subject = EXCLUDED.raw_subject,
                    latest_guest_turn = EXCLUDED.latest_guest_turn,
                    prior_thread_context = EXCLUDED.prior_thread_context,
                    full_message_text = EXCLUDED.full_message_text,
                    structured_asks = EXCLUDED.structured_asks,
                    prior_operator_commitments = EXCLUDED.prior_operator_commitments,
                    property_binding_candidates = EXCLUDED.property_binding_candidates,
                    channel_constraints = EXCLUDED.channel_constraints,
                    parser_used = EXCLUDED.parser_used,
                    parser_version = EXCLUDED.parser_version,
                    parser_notes = EXCLUDED.parser_notes,
                    latest_turn_confidence = EXCLUDED.latest_turn_confidence,
                    latest_turn_extracted = EXCLUDED.latest_turn_extracted,
                    selected_property_code = CASE
                        WHEN EXCLUDED.selected_property_code IS NULL OR EXCLUDED.selected_property_code = ''
                            THEN message_normalizations.selected_property_code
                        ELSE EXCLUDED.selected_property_code
                    END,
                    selected_property_match_type = CASE
                        WHEN EXCLUDED.selected_property_match_type IS NULL OR EXCLUDED.selected_property_match_type = ''
                            THEN message_normalizations.selected_property_match_type
                        ELSE EXCLUDED.selected_property_match_type
                    END,
                    updated_at = NOW()
                RETURNING normalization_id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "message_id": str(message_uuid) if message_uuid else None,
                "source_channel": normalized.source_channel,
                "source_provider": normalized.source_provider,
                "source_thread_id": normalized.source_thread_id,
                "source_message_id": normalized.source_message_id,
                "sender_role": normalized.sender_role,
                "sender_display_name": normalized.sender_display_name,
                "sender_address": normalized.sender_address,
                "sent_at": normalized.sent_at,
                "raw_subject": normalized.raw_subject,
                "latest_guest_turn": normalized.latest_guest_turn,
                "prior_thread_context": normalized.prior_thread_context or None,
                "full_message_text": normalized.full_message_text or None,
                "structured_asks": json.dumps(normalized.structured_asks or []),
                "prior_operator_commitments": json.dumps(normalized.prior_operator_commitments or []),
                "property_binding_candidates": json.dumps(normalized.property_binding_candidates or []),
                "channel_constraints": json.dumps(normalized.channel_constraints or {}),
                "parser_used": normalized.parser_used,
                "parser_version": normalized.parser_version,
                "parser_notes": json.dumps(normalized.parser_notes or []),
                "latest_turn_confidence": normalized.latest_turn_confidence,
                "latest_turn_extracted": normalized.latest_turn_extracted,
                "selected_property_code": selected_property_code or "",
                "selected_property_match_type": selected_property_match_type or "",
            },
        )
    ).fetchone()
    return row[0] if row else None
