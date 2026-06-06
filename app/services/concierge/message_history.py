"""
Escapia Message History Service

Handles three distinct concerns:

1. HISTORICAL IMPORT
   On first connection, we pull ALL message history from Escapia per listing
   and store it keyed to the Escapia listing ID (external_id), not the
   property name. Property names can change (owner rebrand, sale, operator
   change). The listing ID is stable for the life of the property in Escapia.

   Historical messages are stored as read-only context — they feed the AI
   with knowledge of how this specific property has been communicated about
   in the past (what questions come up, what the host's tone has been, what
   details are commonly requested). They do NOT trigger new drafts or alerts.

2. UNRESOLVABLE PROPERTY ID
   Any incoming message that carries a listing_id we don't recognize in our
   pms_listings table must NOT be silently dropped. Options:
     a) The property was never synced (sync issue)
     b) The listing was deleted/merged in Escapia
     c) The API returned an unexpected ID format
     d) New property added after initial sync

   Action: store in message_orphan_queue, alert operator, provide resolution
   tools (link to existing property, trigger re-sync, mark as irrelevant).

3. STALE MESSAGE DETECTION
   During onboarding, the operator may answer inquiries directly in Escapia
   before we're live. When we poll and find these messages, we need to check
   whether a reply already exists in the thread before generating a draft.

   Stale detection logic:
     - GET /v1/conversations/{thread_id} → check for existing replies
     - If a non-guest reply exists → mark as already_answered, no draft
     - If our own draft was generated for a thread that got answered externally
       → void the draft, mark as superseded
     - Celery task runs a "stale check" on all pending_review drafts hourly

   This prevents double-replies and operator confusion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)


def _normalize_history_question_key(text: str) -> str:
    import re

    stopwords = {
        "the", "and", "for", "with", "that", "this", "from", "your", "you", "are",
        "can", "could", "would", "should", "what", "when", "where", "which", "who",
        "how", "why", "does", "did", "have", "has", "had", "our", "about", "into",
        "them", "they", "will", "just", "need", "any", "all", "get", "let", "know",
    }
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    normalized = sorted({w for w in words if len(w) > 2 and w not in stopwords})
    return " ".join(normalized)


# =============================================================================
# MESSAGE RECORD — canonical representation of any Escapia message
# =============================================================================

class MessageDirection(str, Enum):
    GUEST_TO_HOST = "guest_to_host"
    HOST_TO_GUEST = "host_to_guest"
    SYSTEM        = "system"


class MessageStatus(str, Enum):
    HISTORICAL    = "historical"       # Imported from past, read-only context
    PENDING       = "pending"          # Live, unprocessed
    DRAFT_READY   = "draft_ready"      # AI draft generated, awaiting approval
    REPLIED       = "replied"          # Response sent (by us or externally)
    ALREADY_ANSWERED = "already_answered"  # Answered in Escapia before we got to it
    SUPERSEDED    = "superseded"       # Our draft voided — external reply detected
    ORPHANED      = "orphaned"         # Property ID not found in our system


@dataclass
class EscapiaMessage:
    """Canonical representation of any Escapia message thread entry."""
    message_id: str                         # Escapia message ID
    thread_id: str                          # Escapia conversation thread ID
    listing_external_id: str               # Escapia listing ID — the stable anchor
    company_id: UUID

    direction: MessageDirection
    sender_name: str
    body: str
    platform: str                           # vrbo / airbnb / direct
    sent_at: datetime

    # Booking context (may be empty for pre-booking)
    reservation_id: Optional[str] = None

    # Our processing state
    status: MessageStatus = MessageStatus.HISTORICAL
    our_draft_id: Optional[str] = None      # If we generated a draft for this

    # Resolution tracking (for orphaned messages)
    resolved_listing_id: Optional[str] = None  # Set when operator links it
    resolution_note: Optional[str] = None


# =============================================================================
# HISTORICAL IMPORT SERVICE
# =============================================================================

class HistoricalMessageImporter:
    """
    Pulls full message history from Escapia for all known listings.

    Called once during onboarding, and again after any listing sync that
    adds new properties. Idempotent — safe to run multiple times.

    What we do with historical messages:
      - Store verbatim in escapia_message_history (keyed to external_id)
      - Extract FAQ signal: questions asked + how host responded
      - Feed into the knowledge service as property-specific context
      - Do NOT trigger drafts or alerts

    Why property_external_id not property_name:
      A property at "123 Beachview Blvd" might be listed as:
        - "Gulf Breeze Cottage" (original name)
        - "Beachview 3BR" (after rebrand)
        - "Rodriguez Family Rental" (after ownership change)
      All three are the same Escapia listing ID. We anchor to the ID.
    """

    def __init__(self, api_key: str, company_id: UUID):
        self.api_key = api_key
        self.company_id = company_id
        self.base_url = "https://api.escapia.com/v1"

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    async def import_all_listings(
        self,
        db,
        listing_external_ids: List[str],
        days_back: int = 730,  # 2 years of history
    ) -> Dict[str, Any]:
        """
        Import message history for all known listings.
        Called during onboarding and after re-syncs.
        """
        total_imported = 0
        total_skipped = 0
        errors = []

        for ext_id in listing_external_ids:
            try:
                imported = await self._import_for_listing(db, ext_id, days_back)
                total_imported += imported
            except Exception as e:
                logger.error(f"[HistoricalImport] Failed for listing {ext_id}: {e}")
                errors.append({"listing_id": ext_id, "error": str(e)})

        logger.info(
            f"[HistoricalImport] Complete: {total_imported} messages imported, "
            f"{len(errors)} errors"
        )
        return {
            "imported": total_imported,
            "skipped": total_skipped,
            "errors": errors,
            "listings_processed": len(listing_external_ids),
        }

    async def _import_for_listing(
        self,
        db,
        listing_external_id: str,
        days_back: int,
    ) -> int:
        """Fetch and store all message threads for one listing."""
        since = datetime.utcnow() - timedelta(days=days_back)
        imported = 0

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Fetch conversation list for this listing
                response = await client.get(
                    f"{self.base_url}/listings/{listing_external_id}/conversations",
                    headers=self._auth_headers(),
                    params={
                        "since": since.date().isoformat(),
                        "limit": 100,
                    },
                )

                if response.status_code == 404:
                    logger.debug(f"[HistoricalImport] No conversations endpoint for {listing_external_id}")
                    # Fall back to messages endpoint
                    response = await client.get(
                        f"{self.base_url}/messages",
                        headers=self._auth_headers(),
                        params={
                            "listing_id": listing_external_id,
                            "since": since.date().isoformat(),
                            "limit": 100,
                        },
                    )

                if response.status_code != 200:
                    logger.warning(
                        f"[HistoricalImport] {listing_external_id}: {response.status_code}"
                    )
                    return 0

                data = response.json()
                threads = data.get("conversations", data.get("threads", data.get("data", [])))

                for thread in threads:
                    thread_id = str(thread.get("id") or thread.get("thread_id") or "")
                    if not thread_id:
                        continue

                    # Fetch full thread to get individual messages
                    msgs = await self._fetch_thread_messages(client, thread_id)
                    for msg in msgs:
                        msg["listing_external_id"] = listing_external_id
                        saved = await self._save_historical_message(db, msg)
                        if saved:
                            imported += 1

        except Exception as e:
            logger.error(f"[HistoricalImport] fetch error for {listing_external_id}: {e}")

        return imported

    async def _fetch_thread_messages(
        self,
        client: httpx.AsyncClient,
        thread_id: str,
    ) -> List[Dict]:
        """Fetch all messages in a conversation thread."""
        try:
            response = await client.get(
                f"{self.base_url}/conversations/{thread_id}/messages",
                headers=self._auth_headers(),
                params={"limit": 50},
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("messages", data.get("data", []))
            # Fallback: thread endpoint might return messages inline
            response = await client.get(
                f"{self.base_url}/messages/{thread_id}",
                headers=self._auth_headers(),
            )
            if response.status_code == 200:
                data = response.json()
                msgs = data.get("messages", [])
                if not msgs and "body" in data:
                    msgs = [data]  # Single message response
                return msgs
        except Exception as e:
            logger.debug(f"[HistoricalImport] thread fetch failed {thread_id}: {e}")
        return []

    async def _save_historical_message(self, db, raw: Dict) -> bool:
        """Persist one historical message. Returns True if newly inserted."""
        try:
            from sqlalchemy import text

            message_id = str(raw.get("id") or raw.get("message_id") or "")
            thread_id = str(raw.get("thread_id") or raw.get("conversation_id") or "")
            listing_id = str(raw.get("listing_external_id") or raw.get("listing_id") or "")

            if not message_id or not listing_id:
                return False

            # Determine direction
            sender = str(raw.get("sender_role", raw.get("author_role", ""))).lower()
            if "guest" in sender or "traveler" in sender:
                direction = "guest_to_host"
            elif "host" in sender or "owner" in sender or "manager" in sender:
                direction = "host_to_guest"
            else:
                direction = "system"

            body = raw.get("body") or raw.get("message") or raw.get("text") or ""
            sent_at_raw = raw.get("created_at") or raw.get("sent_at")
            sent_at = datetime.fromisoformat(str(sent_at_raw)[:19]) if sent_at_raw else datetime.utcnow()

            source = str(raw.get("source", raw.get("channel", "unknown"))).lower()
            if "airbnb" in source:
                platform = "airbnb"
            elif "vrbo" in source or "homeaway" in source:
                platform = "vrbo"
            else:
                platform = "direct"

            result = await db.execute(
                text("""
                    INSERT INTO escapia_message_history (
                        message_id, thread_id, company_id,
                        listing_external_id, direction,
                        sender_name, body, platform,
                        sent_at, reservation_id, status,
                        created_at
                    ) VALUES (
                        :msg_id, :thread_id, :company_id,
                        :listing_id, :direction,
                        :sender, :body, :platform,
                        :sent_at, :res_id, 'historical',
                        NOW()
                    )
                    ON CONFLICT (message_id, listing_external_id) DO NOTHING
                    RETURNING id
                """),
                {
                    "msg_id":    message_id,
                    "thread_id": thread_id,
                    "company_id": str(self.company_id),
                    "listing_id": listing_id,
                    "direction": direction,
                    "sender":   raw.get("sender_name", raw.get("author_name", "Unknown")),
                    "body":     body[:4000],  # Cap at 4KB
                    "platform": platform,
                    "sent_at":  sent_at,
                    "res_id":   raw.get("reservation_id"),
                },
            )
            await db.commit()
            return result.fetchone() is not None

        except Exception as e:
            logger.warning(f"[HistoricalImport] save failed: {e}")
            return False

    async def extract_faq_signal(
        self,
        db,
        listing_external_id: str,
        company_id: UUID,
    ) -> int:
        """
        After import, extract Q&A pairs from historical messages and
        feed them into the property's knowledge base.

        Pairs a guest question with the next host reply in the same thread.
        Returns count of FAQ entries added.
        """
        from sqlalchemy import text

        added = 0
        try:
            # Get guest→host paired messages for this listing
            rows = await db.execute(
                text("""
                    SELECT
                        g.body  AS question,
                        h.body  AS answer,
                        g.thread_id,
                        g.sent_at
                    FROM escapia_message_history g
                    JOIN escapia_message_history h
                        ON h.thread_id = g.thread_id
                        AND h.direction = 'host_to_guest'
                        AND h.sent_at > g.sent_at
                        AND h.sent_at <= g.sent_at + INTERVAL '48 hours'
                    WHERE g.listing_external_id = :prop
                      AND g.company_id = :cid::uuid
                      AND g.direction = 'guest_to_host'
                      AND LENGTH(g.body) > 15
                      AND LENGTH(h.body) > 15
                    ORDER BY g.sent_at DESC
                    LIMIT 100
                """),
                {"prop": listing_external_id, "cid": str(company_id)},
            )
            pairs = rows.fetchall()

            if not pairs:
                return 0

            # Feed into scoped knowledge
            from app.services.concierge.db_session_service import DEFAULT_TENANT_ID
            from app.services.messaging_brain.knowledge.scoped_knowledge_service import ScopedKnowledgeService

            prop_row = (
                await db.execute(
                    text(
                        """
                        SELECT id::text AS property_id
                        FROM properties
                        WHERE tenant_id = :tid::uuid
                          AND (
                                property_code = :listing_external_id
                             OR external_id = :listing_external_id
                          )
                        ORDER BY updated_at DESC NULLS LAST, id
                        LIMIT 1
                        """
                    ),
                    {"tid": str(DEFAULT_TENANT_ID), "listing_external_id": listing_external_id},
                )
            ).mappings().first()
            if not prop_row or not prop_row.get("property_id"):
                logger.info(
                    "[HistoricalImport] FAQ signal skipped for %s: no scoped property match",
                    listing_external_id,
                )
                return 0

            service = ScopedKnowledgeService()
            imported_answers = 0
            for p in pairs:
                question_text = str(p.question or "").strip()[:500]
                answer_text = str(p.answer or "").strip()[:1000]
                if not question_text or not answer_text:
                    continue
                await service.write_scoped_knowledge(
                    session=db,
                    tenant_id=DEFAULT_TENANT_ID,
                    user_id=DEFAULT_TENANT_ID,
                    scope_type="property",
                    scope_target_id=prop_row["property_id"],
                    topic_id=None,
                    question_text=question_text,
                    answer_text=answer_text,
                    tags=["historical_import", "escapia"],
                    source="historical_import",
                    metadata={
                        "channel": "escapia",
                        "legacy_property_external_id": listing_external_id,
                        "question_key": _normalize_history_question_key(question_text),
                    },
                )
                imported_answers += 1

            result = {
                "imported_answers": imported_answers,
            }
            added = result.get("imported_answers", 0)
            logger.info(
                f"[HistoricalImport] FAQ signal extracted for {listing_external_id}: "
                f"{added} Q&A pairs added to KB"
            )

        except Exception as e:
            logger.warning(f"[HistoricalImport] FAQ extraction failed: {e}")

        return added


# =============================================================================
# ORPHAN HANDLER — messages with unresolvable property IDs
# =============================================================================

class OrphanMessageHandler:
    """
    Handles incoming messages whose listing_id doesn't match any known property.

    Why this happens:
      1. New property added to Escapia after last sync → run re-sync
      2. Listing ID format changed (Escapia API version change) → mapping issue
      3. Property deleted but old messages still arriving → mark irrelevant
      4. Legitimate unknown → escalate to operator

    Resolution workflow:
      1. Detected → stored in message_orphan_queue with status='unresolved'
      2. Operator alerted via dashboard (not SMS — not urgent enough)
      3. Operator can:
         a) "Link to property" → POST /orphans/{id}/link?listing_id=X
         b) "Trigger re-sync" → automatically re-syncs and re-processes
         c) "Mark irrelevant" → no action needed, hides from queue
      4. System also auto-resolves: if a re-sync happens and the ID is now
         recognized, orphan is automatically linked and re-processed
    """

    async def handle_orphan(
        self,
        db,
        company_id: UUID,
        raw_message: Dict[str, Any],
        unresolved_listing_id: str,
    ) -> str:
        """
        Store an unresolvable message and alert operator.
        Returns the orphan_id for reference.
        """
        from sqlalchemy import text
        import uuid as _uuid

        orphan_id = str(_uuid.uuid4())
        import json

        try:
            await db.execute(
                text("""
                    INSERT INTO message_orphan_queue (
                        id, company_id, unresolved_listing_id,
                        thread_id, message_id, platform,
                        guest_name, message_text, raw_payload,
                        status, created_at
                    ) VALUES (
                        :id, :cid::uuid, :listing_id,
                        :thread_id, :msg_id, :platform,
                        :guest, :body, :raw,
                        'unresolved', NOW()
                    )
                    ON CONFLICT (company_id, message_id) DO UPDATE
                        SET status = 'unresolved',
                            created_at = NOW()
                """),
                {
                    "id": orphan_id,
                    "cid": str(company_id),
                    "listing_id": unresolved_listing_id,
                    "thread_id": raw_message.get("thread_id", ""),
                    "msg_id": raw_message.get("id", raw_message.get("message_id", "")),
                    "platform": raw_message.get("source", "unknown"),
                    "guest": raw_message.get("guest_name", raw_message.get("traveler_name", "Guest")),
                    "body": (raw_message.get("body") or raw_message.get("message") or "")[:1000],
                    "raw": json.dumps(raw_message)[:4000],
                },
            )
            await db.commit()

        except Exception as e:
            logger.error(f"[Orphan] Failed to queue orphan: {e}")
            return orphan_id

        # Alert operator — dashboard notice, not SMS
        await self._alert_orphan(company_id, orphan_id, unresolved_listing_id, raw_message)
        logger.warning(
            f"[Orphan] Unresolvable listing_id={unresolved_listing_id} "
            f"thread={raw_message.get('thread_id')} queued as {orphan_id}"
        )
        return orphan_id

    async def _alert_orphan(
        self,
        company_id: UUID,
        orphan_id: str,
        listing_id: str,
        raw_message: Dict,
    ) -> None:
        """Send a low-priority operator alert about an unlinked message."""
        try:
            from app.services.messaging.operator_alerts import get_alert_router, AlertType
            guest = raw_message.get("guest_name", "Unknown guest")
            body = (raw_message.get("body") or raw_message.get("message") or "")[:150]
            platform = raw_message.get("source", "Unknown platform")

            msg = (
                f"⚠️ Unlinked Message — Property ID Not Found\n\n"
                f"A message arrived from {platform} for listing ID '{listing_id}' "
                f"which isn't in our property database.\n\n"
                f"From: {guest}\n"
                f"Message: \"{body}\"\n\n"
                f"This message is queued and needs to be linked to a property. "
                f"Check the dashboard → Orphaned Messages to resolve.\n\n"
                f"Orphan ID: {orphan_id}"
            )
            router = get_alert_router()
            await router.send_alert(
                company_id=company_id,
                alert_type=AlertType.SYSTEM_NOTICE,
                message=msg,
                alert_id=orphan_id,
            )
        except Exception as e:
            logger.debug(f"[Orphan] alert failed (non-fatal): {e}")

    async def resolve_by_link(
        self,
        db,
        orphan_id: str,
        company_id: UUID,
        correct_listing_id: str,
        resolved_by: str = "operator",
    ) -> bool:
        """
        Operator links an orphan message to the correct listing.
        After linking, re-processes the message through the normal pipeline.
        """
        from sqlalchemy import text

        try:
            # Update orphan record
            result = await db.execute(
                text("""
                    UPDATE message_orphan_queue
                    SET status = 'resolved_linked',
                        resolved_listing_id = :correct_id,
                        resolved_by = :by,
                        resolved_at = NOW()
                    WHERE id = :orphan_id AND company_id = :cid::uuid
                    RETURNING thread_id, message_id, platform, guest_name,
                              message_text, raw_payload
                """),
                {
                    "orphan_id": orphan_id,
                    "cid": str(company_id),
                    "correct_id": correct_listing_id,
                    "by": resolved_by,
                },
            )
            row = result.fetchone()
            await db.commit()

            if not row:
                return False

            # Re-process through normal pipeline with corrected listing ID
            import json
            raw = json.loads(row.raw_payload) if row.raw_payload else {}
            raw["listing_id"] = correct_listing_id
            raw["_orphan_resolved"] = True

            logger.info(
                f"[Orphan] Resolved {orphan_id} → listing {correct_listing_id} by {resolved_by}"
            )
            return True

        except Exception as e:
            logger.error(f"[Orphan] resolve_by_link failed: {e}")
            return False

    async def resolve_by_resync(
        self,
        db,
        orphan_id: str,
        company_id: UUID,
    ) -> bool:
        """
        Trigger a PMS re-sync — the new property will be discovered and
        the orphan auto-resolved on next poll cycle.
        """
        try:
            from app.workers.tasks import sync_pms_for_operator
            sync_pms_for_operator.delay(str(company_id))

            from sqlalchemy import text
            await db.execute(
                text("""
                    UPDATE message_orphan_queue
                    SET status = 'resync_triggered', resolved_at = NOW()
                    WHERE id = :id AND company_id = :cid::uuid
                """),
                {"id": orphan_id, "cid": str(company_id)},
            )
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"[Orphan] resync trigger failed: {e}")
            return False

    async def auto_resolve_after_sync(
        self,
        db,
        company_id: UUID,
    ) -> int:
        """
        After a PMS sync completes, check if any orphans can now be resolved
        because the listing ID is now in pms_listings.
        """
        from sqlalchemy import text

        result = await db.execute(
            text("""
                UPDATE message_orphan_queue o
                SET status = 'auto_resolved',
                    resolved_listing_id = l.external_id,
                    resolved_at = NOW()
                FROM pms_listings l
                WHERE o.company_id = :cid::uuid
                  AND o.status = 'unresolved'
                  AND l.external_id = o.unresolved_listing_id
                  AND l.company_id = :cid::uuid
                RETURNING o.id
            """),
            {"cid": str(company_id)},
        )
        resolved = len(result.fetchall())
        if resolved:
            await db.commit()
            logger.info(f"[Orphan] Auto-resolved {resolved} orphans after sync for {company_id}")
        return resolved


# =============================================================================
# STALE MESSAGE DETECTOR
# =============================================================================

class StaleMessageDetector:
    """
    Detects messages that were already answered before we generated a draft,
    or drafts that were superseded by an external reply.

    Two scenarios:

    A) ALREADY ANSWERED ON ARRIVAL
       When we poll Escapia and find new messages, we check each thread for
       existing replies before generating a draft. If the thread already has
       a host reply more recent than the guest message, we skip draft generation
       and mark the message as 'already_answered'.

    B) DRAFT SUPERSEDED AFTER GENERATION
       Our draft is pending_review. Meanwhile, the operator replies directly
       in Escapia. On the next poll, we check all pending drafts and void any
       whose threads now have an external reply. The operator doesn't have to
       do anything — the system cleans itself up.

    Both scenarios are handled without any operator intervention. The dashboard
    shows 'already answered' messages in a separate tab for reference.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.escapia.com/v1"

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    async def check_thread_already_answered(
        self,
        thread_id: str,
        guest_message_id: str,
        guest_message_sent_at: Optional[datetime] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a thread already has a host reply after the guest message.
        Returns (already_answered, reply_snippet).
        Called before generating a draft.
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}/conversations/{thread_id}/messages",
                    headers=self._auth_headers(),
                    params={"limit": 20},
                )

                if response.status_code == 404:
                    # Try alternative endpoint
                    response = await client.get(
                        f"{self.base_url}/messages/{thread_id}",
                        headers=self._auth_headers(),
                    )

                if response.status_code != 200:
                    # Can't verify — assume not answered (safe default)
                    return False, None

                data = response.json()
                messages = data.get("messages", [])
                if not messages and "body" in data:
                    messages = [data]

                # Find any host/owner reply AFTER the guest message
                for msg in messages:
                    msg_id = str(msg.get("id") or msg.get("message_id") or "")
                    if msg_id == guest_message_id:
                        continue  # That's the message we're checking

                    sender_role = str(
                        msg.get("sender_role") or msg.get("author_role") or ""
                    ).lower()
                    is_host_reply = any(
                        r in sender_role for r in ["host", "owner", "manager", "property"]
                    )
                    if not is_host_reply:
                        continue

                    # Check timing if we have it
                    if guest_message_sent_at:
                        reply_time_raw = msg.get("created_at") or msg.get("sent_at")
                        if reply_time_raw:
                            try:
                                reply_time = datetime.fromisoformat(str(reply_time_raw)[:19])
                                if reply_time <= guest_message_sent_at:
                                    continue  # This reply predates the guest message
                            except (ValueError, TypeError):
                                pass

                    # Found a host reply after the guest message
                    snippet = str(msg.get("body") or msg.get("message") or "")[:100]
                    return True, snippet

        except Exception as e:
            logger.debug(f"[StaleCheck] thread check failed (non-fatal): {e}")

        return False, None

    async def void_superseded_drafts(
        self,
        db,
        company_id: UUID,
        api_key: str,
    ) -> int:
        """
        Celery task: check all pending_review drafts. If the thread now
        has an external reply, void the draft.

        Called hourly. Returns count of drafts voided.
        """
        from sqlalchemy import text

        voided = 0
        try:
            # Load all pending drafts older than 5 minutes (give time for approvals in flight)
            result = await db.execute(
                text("""
                    SELECT draft_id, thread_id, message_id, received_at
                    FROM pre_booking_inquiries
                    WHERE company_id = :cid::uuid
                      AND status = 'pending_review'
                      AND created_at <= NOW() - INTERVAL '5 minutes'
                    ORDER BY created_at ASC
                    LIMIT 50
                """),
                {"cid": str(company_id)},
            )
            pending = result.fetchall()

            for draft in pending:
                already_answered, reply_snippet = await self.check_thread_already_answered(
                    thread_id=draft.thread_id,
                    guest_message_id=draft.message_id,
                    guest_message_sent_at=draft.received_at,
                )

                if already_answered:
                    await db.execute(
                        text("""
                            UPDATE pre_booking_inquiries
                            SET status = 'superseded',
                                resolution_note = :note,
                                replied_at = NOW()
                            WHERE draft_id = :draft_id
                        """),
                        {
                            "draft_id": draft.draft_id,
                            "note": f"Answered externally in Escapia: \"{reply_snippet}\"",
                        },
                    )
                    voided += 1
                    logger.info(
                        f"[StaleCheck] Draft {draft.draft_id} voided — "
                        f"thread {draft.thread_id} already answered externally"
                    )

            if voided:
                await db.commit()

        except Exception as e:
            logger.error(f"[StaleCheck] void_superseded_drafts failed: {e}")

        return voided

    async def check_before_draft(
        self,
        thread_id: str,
        message_id: str,
        received_at: Optional[datetime] = None,
    ) -> bool:
        """
        Quick check before generating any AI draft.
        Returns True if we should skip draft generation (already answered).
        """
        already_answered, _ = await self.check_thread_already_answered(
            thread_id=thread_id,
            guest_message_id=message_id,
            guest_message_sent_at=received_at,
        )
        return already_answered


# =============================================================================
# PROPERTY ID RESOLVER — maps listing IDs through ownership/name changes
# =============================================================================

class PropertyIdResolver:
    """
    Resolves incoming listing IDs to known properties.
    Handles cases where the ID might have changed or be formatted differently.

    Resolution attempts (in order):
      1. Direct match: listing_id == pms_listings.external_id
      2. Alias match: listing_id in listing_id_aliases table (for migrated IDs)
      3. No match → orphan queue
    """

    async def resolve(
        self,
        db,
        company_id: UUID,
        listing_id: str,
    ) -> Tuple[Optional[str], bool]:
        """
        Returns (resolved_external_id, is_new_alias).
        resolved_external_id is None if unresolvable.
        is_new_alias is True if matched via alias table.
        """
        from sqlalchemy import text

        # 1. Direct match
        result = await db.execute(
            text("""
                SELECT external_id FROM pms_listings
                WHERE company_id = :cid::uuid
                  AND external_id = :lid
                LIMIT 1
            """),
            {"cid": str(company_id), "lid": listing_id},
        )
        if result.fetchone():
            return listing_id, False

        # 2. Alias match (for renamed/migrated listings)
        result = await db.execute(
            text("""
                SELECT canonical_external_id FROM listing_id_aliases
                WHERE company_id = :cid::uuid
                  AND alias_external_id = :lid
                LIMIT 1
            """),
            {"cid": str(company_id), "lid": listing_id},
        )
        alias_row = result.fetchone()
        if alias_row:
            return alias_row.canonical_external_id, True

        # 3. Case-insensitive / whitespace-trimmed fuzzy match
        result = await db.execute(
            text("""
                SELECT external_id FROM pms_listings
                WHERE company_id = :cid::uuid
                  AND LOWER(TRIM(external_id)) = LOWER(TRIM(:lid))
                LIMIT 1
            """),
            {"cid": str(company_id), "lid": listing_id},
        )
        fuzzy_row = result.fetchone()
        if fuzzy_row:
            # Store as alias to speed up future lookups
            await self._store_alias(db, company_id, listing_id, fuzzy_row.external_id)
            return fuzzy_row.external_id, True

        return None, False

    async def _store_alias(
        self,
        db,
        company_id: UUID,
        alias_id: str,
        canonical_id: str,
    ) -> None:
        from sqlalchemy import text
        try:
            await db.execute(
                text("""
                    INSERT INTO listing_id_aliases
                        (company_id, alias_external_id, canonical_external_id, created_at)
                    VALUES (:cid::uuid, :alias, :canonical, NOW())
                    ON CONFLICT DO NOTHING
                """),
                {"cid": str(company_id), "alias": alias_id, "canonical": canonical_id},
            )
            await db.commit()
        except Exception:
            pass


# =============================================================================
# INTEGRATED POLL HANDLER — wires all three concerns together
# =============================================================================

async def process_incoming_message(
    db,
    company_id: UUID,
    api_key: str,
    raw_message: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Single entry point for every incoming Escapia message (new or polled).

    Flow:
      1. Resolve listing ID → orphan if unresolvable
      2. Check if already answered → skip draft if so
      3. Store in escapia_message_history
      4. Hand off to pre_booking_auto_send pipeline if new inquiry
    
    Returns a status dict explaining what happened.
    """
    listing_id = str(
        raw_message.get("listing_id")
        or raw_message.get("property_id")
        or ""
    )
    thread_id = str(raw_message.get("thread_id") or raw_message.get("conversation_id") or "")
    message_id = str(raw_message.get("id") or raw_message.get("message_id") or "")

    # 1. Resolve listing ID
    resolver = PropertyIdResolver()
    resolved_id, is_alias = await resolver.resolve(db, company_id, listing_id)

    if not resolved_id:
        # Unresolvable → orphan queue
        handler = OrphanMessageHandler()
        orphan_id = await handler.handle_orphan(db, company_id, raw_message, listing_id)
        return {
            "status": "orphaned",
            "orphan_id": orphan_id,
            "unresolved_listing_id": listing_id,
            "action": "Queued for operator resolution. Check dashboard → Orphaned Messages.",
        }

    if is_alias:
        logger.info(f"[MessagePipeline] Resolved alias {listing_id} → {resolved_id}")

    # 2. Check if already answered (stale detection)
    received_at = None
    if raw_ts := raw_message.get("created_at"):
        try:
            received_at = datetime.fromisoformat(str(raw_ts)[:19])
        except (ValueError, TypeError):
            pass

    detector = StaleMessageDetector(api_key)
    already_answered = await detector.check_before_draft(thread_id, message_id, received_at)

    if already_answered:
        # Store as historical, no draft
        logger.info(f"[MessagePipeline] Thread {thread_id} already answered — storing as historical")
        raw_message["listing_external_id"] = resolved_id
        raw_message["_status"] = "already_answered"
        return {
            "status": "already_answered",
            "thread_id": thread_id,
            "listing_id": resolved_id,
            "action": "Message stored as historical. No draft generated.",
        }

    # 3. Return resolved context for pre-booking pipeline
    return {
        "status": "ready_for_draft",
        "resolved_listing_id": resolved_id,
        "thread_id": thread_id,
        "message_id": message_id,
        "was_alias": is_alias,
    }


# =============================================================================
# DB MIGRATION
# =============================================================================

MIGRATION_SQL = """
-- Full historical message archive, keyed to listing external_id (not name)
CREATE TABLE IF NOT EXISTS escapia_message_history (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id           TEXT NOT NULL,
    thread_id            TEXT NOT NULL,
    company_id           UUID NOT NULL,

    -- Anchor: Escapia listing ID — stable across renames/owner changes
    listing_external_id  TEXT NOT NULL,

    direction            TEXT NOT NULL DEFAULT 'guest_to_host',
    sender_name          TEXT,
    body                 TEXT NOT NULL,
    platform             TEXT NOT NULL DEFAULT 'unknown',

    -- Booking context
    reservation_id       TEXT,

    -- Processing state
    status               TEXT NOT NULL DEFAULT 'historical',
    our_draft_id         TEXT,           -- FK to pre_booking_inquiries.draft_id
    resolution_note      TEXT,

    sent_at              TIMESTAMPTZ NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (message_id, listing_external_id)
);

CREATE INDEX IF NOT EXISTS idx_msg_history_listing
    ON escapia_message_history (listing_external_id, sent_at DESC);

CREATE INDEX IF NOT EXISTS idx_msg_history_thread
    ON escapia_message_history (thread_id, sent_at);

CREATE INDEX IF NOT EXISTS idx_msg_history_company
    ON escapia_message_history (company_id, status, created_at DESC);

-- Listing ID alias table (handles renames, migrations, format changes)
CREATE TABLE IF NOT EXISTS listing_id_aliases (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id           UUID NOT NULL,
    alias_external_id    TEXT NOT NULL,    -- The incoming (possibly old) ID
    canonical_external_id TEXT NOT NULL,   -- The ID in pms_listings.external_id
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, alias_external_id)
);

-- Orphaned messages — unresolvable listing IDs awaiting operator action
CREATE TABLE IF NOT EXISTS message_orphan_queue (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id           UUID NOT NULL,
    unresolved_listing_id TEXT NOT NULL,
    thread_id            TEXT NOT NULL,
    message_id           TEXT NOT NULL,
    platform             TEXT,
    guest_name           TEXT,
    message_text         TEXT,
    raw_payload          TEXT,           -- Full raw message JSON for re-processing

    status               TEXT NOT NULL DEFAULT 'unresolved',
    -- unresolved → resolved_linked | auto_resolved | resync_triggered | irrelevant

    resolved_listing_id  TEXT,           -- Set when linked by operator
    resolved_by          TEXT,           -- 'operator' | 'auto_sync'
    resolved_at          TIMESTAMPTZ,
    resolution_note      TEXT,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_orphan_company_status
    ON message_orphan_queue (company_id, status)
    WHERE status = 'unresolved';

-- Add resolution_note to pre_booking_inquiries for stale/superseded records
ALTER TABLE pre_booking_inquiries
    ADD COLUMN IF NOT EXISTS resolution_note TEXT;
"""
