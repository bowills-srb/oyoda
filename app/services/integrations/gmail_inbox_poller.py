"""
gmail_inbox_poller.py — Gmail-based universal messaging connector.

Instead of relying on one PMS inbox API, we poll the operator's Gmail inbox
directly. Every STR platform — Vrbo, Airbnb, Booking.com, direct — sends
email copies of guest messages to the operator's inbox. This is a universal
message transport pattern across platforms and PMS setups.

Inbox transport is not the same thing as booking truth. Gmail gives Oyvoda a
universal way to ingest guest conversations and supporting OTA/system emails,
but PMS and connected OTA sync remain the authoritative source for reservation
state, cancellations, refunds, guest session identity, and other booking
operations facts. Email events are used to:
  - capture guest conversation turns
  - reconcile or backfill session state when PMS sync is delayed
  - preserve audit context from OTA/system notifications

For messaging, we read from Gmail, process with the existing pipelines, and
reply via Gmail. The reply flows back through the same email thread, which the
platform or PMS can route back to the guest on their channel.

Architecture:
  1. GmailPoller polls INBOX every 5 minutes for unread messages
  2. GmailEmailParser extracts: platform, guest name, message, property,
     thread context, and any requested dates
  3. Messages route to:
     - Pre-booking pipeline (inquiry before a confirmed booking)
     - In-stay pipeline (message during an active booking session)
     - Post-stay pipeline (review request, late questions)
  4. GmailReplySender sends approved replies back via Gmail API
     into the same thread so the conversation stays coherent

Gmail API setup (OAuth2 with refresh token):
  The operator's Google account owner completes a one-time OAuth flow.
  The refresh token is stored in Railway as GMAIL_REFRESH_TOKEN_{OPERATOR_ID}.
  The access token is refreshed automatically by this service.

  For Beach Habitats:
    GMAIL_CLIENT_ID         = from Google Cloud Console OAuth2 credentials
    GMAIL_CLIENT_SECRET     = from Google Cloud Console OAuth2 credentials
    GMAIL_REFRESH_TOKEN     = from one-time OAuth flow for info@beachhabitats30a.com
    GMAIL_WATCHED_EMAIL     = info@beachhabitats30a.com
    GMAIL_POLL_LABEL        = INBOX (or a filtered label if they use Gmail filters)

  For subsequent operators:
    GMAIL_REFRESH_TOKEN_{OPERATOR_CODE} = their refresh token
    GMAIL_WATCHED_EMAIL_{OPERATOR_CODE} = their inbox address

Known email formats parsed:
  - Vrbo/HomeAway: "New inquiry from [name]" / "Message from [name]"
  - Airbnb: "You have a new message from [name]"
  - Booking.com: "New message from guest"
  - Escapia direct: "Guest Message: [property]"
  - Direct email: anything else (treated as general inquiry)

Deduplication:
  Each processed email is tracked by Gmail Message-ID in the
  gmail_processed_messages table. We never process the same email twice.

Cost:
  Gmail API is free. No per-message charges. 1B free quota units/day.
  Each poll = 1 list call + N get calls (one per unread message).
  At 5-minute poll intervals with ~10 messages/day: negligible.

────────────────────────────────────────────────────────────────────────────
SESSION-STATE HARDENING NOTE (2026-05-06 incident follow-up):

Many of the DB-touching helpers in this file follow the pattern:

    try:
        await self.db.execute(...)
    except Exception:
        logger.debug("...")
        return  # or return default value

This pattern is dangerous in async-SQLAlchemy / asyncpg context: when a
query throws, the underlying Postgres connection enters
`IDLE in transaction (aborted)` state. Every subsequent query on the same
session errors with:

    asyncpg.exceptions.InFailedSQLTransactionError:
    current transaction is aborted, commands ignored until end of
    transaction block

…until the session is rolled back at the session level. Local try/except
blocks do NOT recover the connection — they only catch the Python-side
exception. The aborted state remains.

The 2026-05-06 incident traced through this exact mechanism: an upstream
helper threw, swallowed the exception silently, then the next call to
`message_event_store.persist_canonical_inbound_message` hit the poisoned
session at its very first query (`_table_exists`) and silently returned
`{}`, blocking the entire normalization + composer pipeline.

Fix shape applied here:

    try:
        await self.db.execute(...)
    except Exception:
        try:
            await self.db.rollback()
        except Exception:
            pass
        logger.debug("...")
        return

Rollback on a clean session is a no-op, so adding it on every except path
is safe in all cases. The rollback is wrapped in its own try/except
because rollback can itself raise on certain pathological connection
states; we don't want the cleanup to mask the original failure or crash
the caller.

The architectural lesson: any helper that catches a DB exception in an
async session context MUST roll back before returning. Otherwise it
leaves a poisoned session for whatever runs next in the same task.
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import base64
import email
import email.header
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import text

from app.db.session_safety import safe_rollback as _safe_rollback
from app.services.integrations.email_inbound import EmailIntakeEnvelope, ParsedEmailMessage
from app.services.integrations.email_dispatch import (
    EmailDispatchServices,
    dispatch_confirmed_guest,
    dispatch_in_stay,
    dispatch_pre_booking,
    dispatch_system_event,
)
from app.services.integrations.email_pipeline import EmailPipelineServices, process_routed_email
from app.services.integrations.reservation_aware_routing import ReservationAwareRoutingService
from app.services.integrations.email_reply import EmailReplySenderBase
from app.services.integrations.direct_email_parsers import ParsedDirectInquiry
from app.services.integrations.email_lifecycle_inference import (
    infer_lifecycle_stage_from_message,
)
from app.services.integrations.email_parser_router import parse_structured_inbound_email
from app.services.integrations.llm_email_extractor import (
    ExtractedEmailFields,
    LLMEmailExtractor,
    LLMEmailExtractorParseFailure,
)
from app.services.integrations.message_ask_taxonomy import detect_message_asks
from app.services.integrations.property_mention_surfaces import (
    build_surface_audit_payload,
    extract_property_mention_candidates,
    select_best_candidate,
    surface_for_mention,
)
from app.services.integrations.ota_email_parsers import ParsedOtaInquiry
from app.services.integrations.ota_reservation_events import ParsedOtaReservationEvent
from app.services.integrations.review_feedback_signals import (
    extract_review_feedback_signals,
    summarize_feedback_signal_outcome,
)
from app.services.property_canonical_service import get_canonical_property_service
from app.services.property_canonical_write_service import get_canonical_property_write_service
from app.services.messaging.identity_resolver import resolve_guest_identity
from app.services.messaging.inbound_transport import get_inbound_transport_capability
from app.services.messaging.inbound_normalizer import CanonicalInboundMessage, InboundMessageNormalizer
from app.services.messaging.message_event_store import (
    persist_canonical_inbound_message,
    update_normalization_outcome,
)

logger = logging.getLogger(__name__)

GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE  = "https://gmail.googleapis.com/gmail/v1"
_PROCESSING_STATUS_PROCESSED = "processed"
_PROCESSING_STATUS_NON_GUEST = "non_guest"
_PROCESSING_STATUS_FAILED_RETRYABLE = "failed_retryable"
_PROCESSING_STATUS_QUARANTINED = "quarantined"
_MAX_PARSE_FAILURE_ATTEMPTS = 3
LINK_CONTEXT_ALLOWED_DOMAINS = (
    "airbnb.com",
    "vrbo.com",
    "homeaway.com",
    "booking.com",
    "escapia.com",
    "tripadvisor.com",
    "expediagroup.com",
)


# ─────────────────────────────────────────────────────────────────────────────
# OAuth2 token management
# ─────────────────────────────────────────────────────────────────────────────

class GmailTokenManager:
    """
    Manages Gmail OAuth2 access tokens using a stored refresh token.
    Access tokens expire after 1 hour — this refreshes them automatically.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ):
        self.client_id     = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    async def get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        if self._access_token and self._token_expires_at:
            # Refresh 5 minutes before expiry
            from datetime import timezone
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if now < self._token_expires_at:
                return self._access_token

        return await self._refresh()

    async def _refresh(self) -> str:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                GMAIL_TOKEN_URL,
                data={
                    "client_id":     self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type":    "refresh_token",
                },
            )
            if resp.is_error:
                detail = ""
                try:
                    payload = resp.json()
                    error_code = str(payload.get("error") or "").strip()
                    error_description = str(payload.get("error_description") or "").strip()
                    detail = " · ".join(part for part in [error_code, error_description] if part)
                    if error_code == "invalid_grant":
                        raise RuntimeError("gmail_reauth_required: Token has been expired or revoked.")
                except RuntimeError:
                    raise
                except Exception:
                    detail = (resp.text or "").strip()
                raise RuntimeError(f"gmail_token_refresh_failed: {detail or resp.status_code}")
            data = resp.json()

        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        from datetime import timezone, timedelta
        self._token_expires_at = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            + timedelta(seconds=expires_in - 300)
        )
        logger.debug("[GmailPoller] Access token refreshed, expires in %ds", expires_in)
        return self._access_token

    def auth_header(self, token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────────────────────
# Parsed email message
# ─────────────────────────────────────────────────────────────────────────────

ParsedGmailMessage = ParsedEmailMessage


def _extract_reply_headers(headers: Dict[str, str]) -> tuple[str, List[str]]:
    in_reply_to = (headers.get("in-reply-to", "") or "").strip()
    references_raw = (headers.get("references", "") or "").strip()
    references = [part.strip() for part in references_raw.split() if part.strip()]
    return in_reply_to, references


def _build_canonical_from_parsed_gmail(parsed: ParsedGmailMessage) -> CanonicalInboundMessage:
    """Build the canonical inbound shape used by the fallback inquiry writer."""
    full_message = (parsed.full_body or parsed.body or parsed.latest_guest_message or "").strip()
    latest_guest_turn = (parsed.latest_guest_message or parsed.body or full_message).strip()
    prior_context = (parsed.conversation_context or "").strip()
    sender_name = (parsed.guest_name or "Guest").strip() or "Guest"
    sender_email = (parsed.guest_email or "").strip().lower()
    parser_used = "fallback_gmail_poller"
    parser_notes: List[str] = []
    if parsed.parser_source:
        parser_notes.append(f"original_parser:{parsed.parser_source}")
    if parsed.platform:
        parser_notes.append(f"platform:{parsed.platform}")

    return CanonicalInboundMessage(
        source_channel="gmail",
        source_provider=(parsed.platform or parsed.source_provider or "email").strip() or "email",
        source_thread_id=parsed.gmail_thread_id or parsed.source_thread_id or "",
        source_message_id=parsed.gmail_message_id or parsed.source_message_id or "",
        sender_role=(parsed.sender_role or "guest").strip() or "guest",
        sender_display_name=sender_name,
        sender_address=sender_email,
        sent_at=parsed.received_at,
        raw_subject=(parsed.subject or "").strip(),
        latest_guest_turn=latest_guest_turn,
        prior_thread_context=prior_context,
        full_message_text=full_message or latest_guest_turn,
        structured_asks=list(parsed.asks or []),
        prior_operator_commitments=[],
        property_binding_candidates=[],
        channel_constraints={},
        parser_used=parser_used,
        parser_version="v1",
        parser_notes=parser_notes,
        latest_turn_confidence=0.0,
        latest_turn_extracted=bool(prior_context and latest_guest_turn),
        guest_name=sender_name,
        guest_email=sender_email,
    )


def _is_platform_automation_email(email: str) -> bool:
    value = (email or "").strip().lower()
    if not value:
        return False
    return any(
        domain in value
        for domain in (
            "@airbnb.com",
            "@guest.airbnb.com",
            "@automated-messages.airbnb.com",
            "@messages.homeaway.com",
            "@messages.vrbo.com",
            "@vrbo.com",
            "@homeaway.com",
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Email parser — extracts structured data from platform email formats
# ─────────────────────────────────────────────────────────────────────────────

class GmailEmailParser:
    """
    Parses emails from Vrbo, Airbnb, Booking.com, and direct senders
    into structured ParsedGmailMessage objects.

    Each platform has a slightly different email format. We use a combination
    of sender address matching, subject line patterns, and body parsing.
    """

    # Platform detection by sender domain
    PLATFORM_SENDERS: List[Tuple[str, str]] = [
        ("vrbo.com",          "vrbo"),
        ("homeaway.com",      "vrbo"),
        ("vacationrentals.com", "vrbo"),
        ("airbnb.com",        "airbnb"),
        ("booking.com",       "booking"),
        ("tripadvisor.com",   "tripadvisor"),
        ("escapia.com",       "escapia"),
    ]

    # Subject patterns for pre-booking inquiries
    INQUIRY_SUBJECTS = [
        r"new inquiry",
        r"inquiry from",
        r"question about",
        r"message from .+ about",
        r"potential guest",
        r"traveler message",
        r"new message from",
        r"guest message",
        r"you have a new message",
        r"inquiry for",
    ]

    PROPERTY_SUBJECT_SUFFIXES: List[Tuple[str, ...]] = [
        ("reservation", "request"),
        ("booking", "inquiry"),
        ("rental", "inquiry"),
        ("reservation",),
        ("inquiry",),
        ("booking",),
        ("availability",),
        ("question",),
        ("rental",),
        ("trip",),
        ("stay",),
    ]

    PROPERTY_SUBJECT_MONTHS = {
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
        "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    }

    _BODY_ADDRESS_STOPWORDS = PROPERTY_SUBJECT_MONTHS | {
        "monday", "mon", "tuesday", "tue", "wednesday", "wed", "thursday", "thu",
        "friday", "fri", "saturday", "sat", "sunday", "sun",
        "on", "at", "the", "for", "and", "thank", "thanks", "best", "available",
    }

    # Common US street-type suffixes. A trimmed address span ending in one of
    # these is strongly more likely to be a real address than a number-led
    # noise phrase ("24 hours", "4 wrist bands"). NOTE: starting set tuned for
    # common cases; the resolver-healer (backlog) is the intended mechanism to
    # widen this from real operator address data.
    _BODY_ADDRESS_STREET_TYPES = {
        "street", "st", "road", "rd", "drive", "dr", "lane", "ln",
        "circle", "cir", "court", "ct", "boulevard", "blvd", "way",
        "place", "pl", "avenue", "ave", "trail", "trl", "cove", "loop",
        "walk", "terrace", "ter", "parkway", "pkwy", "highway", "hwy",
    }

    PROPERTY_SUBJECT_GENERIC_CANDIDATES = {
        "availability",
        "booking",
        "condo",
        "guest",
        "home",
        "house",
        "inquiry",
        "property",
        "question",
        "rental",
        "reservation",
        "stay",
        "trip",
        "vacation",
    }

    NON_GUEST_SUBJECT_PATTERNS = [
        r"review reminder",
        r"leave a review",
        r"write a review",
        r"you have \d+ days? left to (write|leave) a review",
        r"booking confirmation",
        r"reservation confirmed",
        r"payment receipt",
        r"payout",
        r"listing update",
        r"newsletter",
    ]

    NON_GUEST_BODY_PATTERNS = [
        r"%opentrack%",
        r"there (?:are|is) only \d+ days? left to (?:write|leave) a review",
        r"\bwrite a review\b",
        r"\bleave a review\b",
        r"\breview your guest\b",
        r"\breview your host\b",
        r"\bhow was (?:your|jeanette(?:’|')s|the) stay\b",
        r"\bshare your feedback\b",
        r"\bprivacy policy\b",
        r"\bunsubscribe\b",
    ]

    THREAD_SPLIT_PATTERNS = [
        re.compile(r"(?im)^\s*on .+ wrote:\s*$"),
        re.compile(r"(?im)^\s*[- ]*original message[- ]*$"),
        re.compile(r"(?im)^\s*[- ]*forwarded message[- ]*$"),
        re.compile(r"(?im)^\s*from:\s.+$"),
        re.compile(r"(?im)^\s*sent:\s.+$"),
        re.compile(r"(?im)^\s*subject:\s.+$"),
        re.compile(r"(?im)^\s*_+\s*$"),
    ]

    _BODY_ADDRESS_PATTERN = re.compile(
        r"\b(\d{1,4}\s+(?:[NSEW]\.?\s+)?[A-Za-z][A-Za-z'.]*"
        r"(?:\s+[A-Za-z][A-Za-z'.]*){0,3})\b"
    )

    def detect_platform(self, from_address: str) -> str:
        from_lower = from_address.lower()
        for domain, platform in self.PLATFORM_SENDERS:
            if domain in from_lower:
                return platform
        return "direct"

    def is_inquiry_subject(self, subject: str) -> bool:
        subject_lower = subject.lower()
        return any(re.search(pat, subject_lower) for pat in self.INQUIRY_SUBJECTS)

    def is_non_guest_email(self, subject: str, body: str) -> bool:
        subject_lower = (subject or "").lower()
        body_lower = (body or "").lower()
        if any(re.search(pat, subject_lower) for pat in self.NON_GUEST_SUBJECT_PATTERNS):
            return True
        if any(re.search(pat, body_lower) for pat in self.NON_GUEST_BODY_PATTERNS):
            return True
        return False

    def extract_guest_name(
        self,
        subject: str,
        body: str,
        platform: str,
        display_name: str = "",
        from_email: str = "",
    ) -> str:
        """Extract guest name with conservative precedence.

        Priority:
          1. Platform-specific subject line
          2. Direct sender display name (for non-platform inbox mail)
          3. Body self-introduction as a last resort
        """
        # Vrbo: "New inquiry from John Smith" or "Message from John Smith"
        m = re.search(r"(?:inquiry|message) from ([A-Z][a-z]+(?: [A-Z][a-z]+)?)", subject, re.I)
        if m:
            return m.group(1).strip()

        # Airbnb: "You have a new message from John"
        m = re.search(r"new message from ([A-Z][a-z]+)", subject, re.I)
        if m:
            return m.group(1).strip()

        # Direct-email fallback: trust the sender display name before scraping
        # the body, which may contain forwarded or quoted names from others.
        if platform == "direct":
            cleaned_display = re.sub(r"[\"'<>]", "", (display_name or "")).strip()
            if cleaned_display:
                m = re.match(r"([A-Z][a-z]+(?: [A-Z][a-z]+)?)", cleaned_display)
                if m:
                    return m.group(1).strip()

        # Body fallback: "Hi, I'm [name]" or "My name is [name]"
        m = re.search(r"(?:I'm|I am|my name is) ([A-Z][a-z]+(?: [A-Z][a-z]+)?)", body, re.I)
        if m:
            return m.group(1).strip()

        # Final fallback: if the email local-part looks human, use it.
        if platform == "direct" and from_email:
            local = from_email.split("@", 1)[0].replace(".", " ").replace("_", " ").strip()
            m = re.match(r"([A-Za-z]{2,})(?:\s+([A-Za-z]{2,}))?", local)
            if m:
                candidate = " ".join([g for g in m.groups() if g]).strip().title()
                if candidate:
                    return candidate

        return "Guest"

    def extract_property_name(self, subject: str, body: str) -> str:
        """Extract property name from subject or body."""
        # "Inquiry for Sunset Cottage" or "about your listing [name]"
        m = re.search(r"(?:for|about|re:|re\s) ([A-Z][^,\n]{3,40})", subject, re.I)
        if m:
            candidate = m.group(1).strip()
            # Filter out generic words
            if not any(w in candidate.lower() for w in ["your", "the ", "our ", "a "]):
                return candidate

        # Try body: property names often appear in quotes or bold in HTML-stripped text
        m = re.search(r'"([A-Z][^"]{3,40})"', body)
        if m:
            return m.group(1)

        # Natural direct-email subjects like "Sunrise and Sunset July Reservation"
        candidate = self._extract_property_from_natural_subject(subject)
        if candidate:
            return candidate

        return ""

    def _trim_body_property_candidate(self, candidate: str) -> str:
        """Trim a raw address span: cut at sentence punctuation, strip
        trailing connective/stopword tokens. Recall-neutral — only ever
        shortens the span, never rejects it."""
        candidate = re.split(r"[.!?]\s", candidate.strip(), maxsplit=1)[0].strip()
        words = [w for w in candidate.split() if w]
        while len(words) > 1:
            tail = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", words[-1]).casefold()
            if not tail or tail in self._BODY_ADDRESS_STOPWORDS:
                words.pop()
                continue
            break
        return " ".join(words).strip()

    def _extract_body_property_mention(self, body: str) -> str:
        """Best-effort property mention from message body prose.

        OUTAGE-MODE FALLBACK ONLY. Reached solely via GmailEmailParser.parse()
        -> fallback_parse, which the router calls only after the LLM extractor
        (Groq/Anthropic) raises LLMEmailExtractorFallback. The LLM extractor is
        the primary property-mention source on the normal path; this regex is
        the degraded-mode net.

        Selection: the bare regex matches every number-led span, including
        prose noise ("24 hours and will need"). Among trimmed candidates,
        prefer those ending in a known street-type suffix; only fall back to
        longest-span when none qualify. Recall-neutral — never rejects a
        candidate the regex found, only orders them.
        """
        text = (body or "").strip()
        if not text:
            return ""
        raw = self._BODY_ADDRESS_PATTERN.findall(text[:600])
        if not raw:
            return ""
        trimmed = [self._trim_body_property_candidate(c) for c in raw]
        trimmed = [c for c in trimmed if c]
        if not trimmed:
            return ""
        street_typed = [
            c for c in trimmed
            if c.split() and c.split()[-1].casefold() in self._BODY_ADDRESS_STREET_TYPES
        ]
        pool = street_typed if street_typed else trimmed
        return max(pool, key=len)

    def _select_property_mention_across_surfaces(
        self,
        *,
        subject: str,
        body: str,
        latest_body: str,
        quoted_context: str,
    ) -> tuple[str, dict[str, Any]]:
        candidates = extract_property_mention_candidates(
            subject=subject,
            latest_body=latest_body,
            quoted_context=quoted_context,
        )
        best = select_best_candidate(candidates)
        if best is not None:
            return best.mention, build_surface_audit_payload(
                parser_path="deterministic_fallback",
                extracted_mention=best.mention,
                subject=subject,
                latest_body=latest_body,
                quoted_context=quoted_context,
                selected_surface=best.surface,
                selected_confidence=best.confidence,
            )

        legacy_subject_or_body = self.extract_property_name(subject, body)
        if legacy_subject_or_body:
            return legacy_subject_or_body, build_surface_audit_payload(
                parser_path="deterministic_fallback",
                extracted_mention=legacy_subject_or_body,
                subject=subject,
                latest_body=latest_body,
                quoted_context=quoted_context,
                selected_surface=surface_for_mention(
                    legacy_subject_or_body,
                    subject=subject,
                    latest_body=latest_body,
                    quoted_context=quoted_context,
                ),
            )

        legacy_body_only = self._extract_body_property_mention(body)
        if legacy_body_only:
            return legacy_body_only, build_surface_audit_payload(
                parser_path="deterministic_fallback",
                extracted_mention=legacy_body_only,
                subject=subject,
                latest_body=latest_body,
                quoted_context=quoted_context,
                selected_surface=surface_for_mention(
                    legacy_body_only,
                    subject=subject,
                    latest_body=latest_body,
                    quoted_context=quoted_context,
                ),
            )

        return "", build_surface_audit_payload(
            parser_path="deterministic_fallback",
            extracted_mention="",
            subject=subject,
            latest_body=latest_body,
            quoted_context=quoted_context,
        )

    def _extract_property_from_natural_subject(self, subject: str) -> str:
        """Extract a likely property name from natural-language subject lines.

        This is a conservative fallback for direct-email subjects that append
        booking intent to the property name, e.g. "Sunrise and Sunset July
        Reservation". If the guess is bad, canonical resolution downstream
        safely falls back to no match.
        """
        if not subject:
            return ""

        cleaned_subject = re.sub(r"^(?:re|fwd?):\s*", "", subject, flags=re.I).strip(" -_:,")
        if not cleaned_subject:
            return ""

        original_tokens = cleaned_subject.split()
        if not original_tokens:
            return ""

        keep_count = len(original_tokens)
        lowered_tokens = [token.strip(".,!?;:()[]{}\"'").lower() for token in original_tokens]

        for suffix in self.PROPERTY_SUBJECT_SUFFIXES:
            if len(lowered_tokens) >= len(suffix) and tuple(lowered_tokens[-len(suffix):]) == suffix:
                keep_count -= len(suffix)
                lowered_tokens = lowered_tokens[:-len(suffix)]
                break

        while keep_count > 0:
            token = lowered_tokens[keep_count - 1]
            if token in self.PROPERTY_SUBJECT_MONTHS or re.fullmatch(r"\d{4}", token):
                keep_count -= 1
                continue
            break

        if keep_count <= 0:
            return ""

        candidate = " ".join(original_tokens[:keep_count]).strip(" -_:,")
        if len(candidate) < 4:
            return ""

        candidate_lower = candidate.lower()
        if candidate_lower in self.PROPERTY_SUBJECT_GENERIC_CANDIDATES:
            return ""

        words = [word.strip(".,!?;:()[]{}\"'") for word in candidate.split()]
        if not words:
            return ""
        if not any(word and word[0].isupper() for word in words):
            return ""

        return candidate

    def extract_dates(self, body: str) -> Tuple[Optional[date], Optional[date]]:
        """Extract check-in/check-out dates from email body."""
        check_in = check_out = None

        # Pattern: "Check-in: January 15, 2026" or "Arrival: 01/15/2026"
        date_patterns = [
            r"(?:check[- ]?in|arrival|from)[:\s]+(\w+ \d{1,2},? \d{4})",
            r"(?:check[- ]?in|arrival|from)[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
            r"(?:check[- ]?in|arrival|from)[:\s]+(\d{4}-\d{2}-\d{2})",
        ]
        checkout_patterns = [
            r"(?:check[- ]?out|departure|to)[:\s]+(\w+ \d{1,2},? \d{4})",
            r"(?:check[- ]?out|departure|to)[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
            r"(?:check[- ]?out|departure|to)[:\s]+(\d{4}-\d{2}-\d{2})",
        ]

        for pat in date_patterns:
            m = re.search(pat, body, re.I)
            if m:
                check_in = self._parse_date_str(m.group(1))
                break

        for pat in checkout_patterns:
            m = re.search(pat, body, re.I)
            if m:
                check_out = self._parse_date_str(m.group(1))
                break

        return check_in, check_out

    def _parse_date_str(self, s: str) -> Optional[date]:
        """Try multiple date formats."""
        s = s.strip().rstrip(",")
        for fmt in ("%B %d %Y", "%B %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%b %d %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                pass
        return None

    def extract_guest_count(self, body: str) -> Optional[int]:
        """Extract number of guests from body."""
        m = re.search(r"(\d+)\s*(?:guests?|people|adults?|persons?)", body, re.I)
        if m:
            n = int(m.group(1))
            return n if 1 <= n <= 20 else None
        return None

    def extract_plain_text_body(self, raw_email: str) -> str:
        """
        Normalize an already-decoded message body to plain text.

        The caller passes the result of `_decode_gmail_payload(...)` or a
        provider-supplied HTML body, not a raw RFC 2822 message. Re-parsing
        that body through Python's email package can silently drop leading
        `Word: value` lines by treating them as headers.
        """
        body = raw_email or ""
        if re.search(r"<(?:html|body|div|p|br|table|tr|td|span)\b", body, re.I):
            body = self._strip_html(body)

        # Clean up: remove excessive whitespace, quoted reply blocks
        body = re.sub(r"\n{3,}", "\n\n", body)
        body = re.sub(r"(?m)^>.*$", "", body)           # strip quoted reply lines
        body = re.sub(r"On .+ wrote:", "", body)         # strip "On Mon... wrote:" headers
        body = self._trim_forwarded_or_footer_noise(body)
        return body.strip()[:3000]                        # cap at 3000 chars

    def _trim_forwarded_or_footer_noise(self, body: str) -> str:
        """Keep the newest guest content and strip common email/footer noise."""
        text = body or ""
        # Trim common forwarded / prior-thread delimiters.
        split_patterns = [
            r"(?im)^[- ]*forwarded message[- ]*$",
            r"(?im)^[- ]*original message[- ]*$",
            r"(?im)^from:\s.+$\n^sent:\s.+$\n^to:\s.+$\n^subject:\s.+$",
            r"(?im)^on .+ wrote:$",
        ]
        for pat in split_patterns:
            m = re.search(pat, text)
            if m:
                text = text[:m.start()]
                break

        # Drop common footer / tracking lines that add noise but no draft value.
        noise_patterns = [
            r"(?im)^unsubscribe.*$",
            r"(?im)^manage preferences.*$",
            r"(?im)^privacy policy.*$",
            r"(?im)^view in browser.*$",
            r"(?im)^do not reply.*$",
            r"(?im)^this email was sent to.*$",
        ]
        for pat in noise_patterns:
            text = re.sub(pat, "", text)

        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _strip_html(self, html: str) -> str:
        """Very basic HTML→text conversion."""
        text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
        text = re.sub(r"<p[^>]*>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        return text

    def extract_links(self, raw_email: str) -> List[str]:
        urls = re.findall(r"https?://[^\s<>'\"()]+", raw_email or "", flags=re.I)
        cleaned: List[str] = []
        seen = set()
        for url in urls:
            candidate = url.rstrip(".,);]>")
            if candidate and candidate not in seen:
                seen.add(candidate)
                cleaned.append(candidate)
        return cleaned[:10]

    def dissect_thread_content(self, body: str) -> Tuple[str, str]:
        """
        Split a flattened email body into the newest guest turn and older
        quoted/thread context. This helps drafting stay grounded in the latest
        ask without throwing away useful prior context.
        """
        text = (body or "").strip()
        if not text:
            return "", ""

        split_at = None
        for pattern in self.THREAD_SPLIT_PATTERNS:
            match = pattern.search(text)
            if match and (split_at is None or match.start() < split_at):
                split_at = match.start()

        latest = text[:split_at].strip() if split_at is not None else text
        older = text[split_at:].strip() if split_at is not None else ""

        latest = self._clean_message_segment(latest)
        older = self._clean_thread_context(older)
        if not latest:
            latest = self._clean_message_segment(text)

        return latest[:3000], older[:1500]

    def _clean_message_segment(self, text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        cleaned = re.sub(r"(?m)^\s*>.*$", "", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        blocks = []
        for block in re.split(r"\n{2,}", cleaned):
            piece = block.strip()
            if not piece:
                continue
            if re.fullmatch(r"(from|sent|to|subject):.*", piece, flags=re.I):
                continue
            blocks.append(piece)

        return "\n\n".join(blocks).strip()

    def _clean_thread_context(self, text: str) -> str:
        context = (text or "").strip()
        if not context:
            return ""
        context = re.sub(r"(?m)^\s*> ?", "", context)
        context = re.sub(r"\n{3,}", "\n\n", context)
        return context.strip()

    def extract_html_body(self, gmail_message: Dict[str, Any]) -> str:
        return self._extract_part_by_mime(gmail_message.get("payload", {}), "text/html")

    def parse(self, gmail_message: Dict[str, Any]) -> Optional[ParsedGmailMessage]:
        """
        Parse a Gmail API message object into a ParsedGmailMessage.
        Returns None if the email should be skipped (automated, bounce, etc.)
        """
        headers = {
            h["name"].lower(): h["value"]
            for h in gmail_message.get("payload", {}).get("headers", [])
        }

        subject     = headers.get("subject", "")
        from_raw    = headers.get("from", "")
        date_header = headers.get("date", "")
        msg_id_hdr  = headers.get("message-id", "")
        in_reply_to, references = _extract_reply_headers(headers)

        # Parse display name + email address
        display_name, from_email = parseaddr(from_raw)
        from_email = from_email.lower()

        # Skip automated/noreply emails
        skip_patterns = [
            "noreply", "no-reply", "donotreply", "do-not-reply",
            "mailer-daemon", "postmaster", "bounce",
            "notifications@", "automated@",
        ]
        if any(p in from_email for p in skip_patterns):
            # But don't skip platform notification emails — they contain guest messages
            platform_keywords = ["vrbo", "airbnb", "booking", "homeaway", "escapia", "tripadvisor"]
            if not any(k in from_email for k in platform_keywords):
                return None

        # Detect platform
        platform = self.detect_platform(from_email)

        # Decode subject
        decoded_subject = ""
        for part, enc in email.header.decode_header(subject):
            if isinstance(part, bytes):
                decoded_subject += part.decode(enc or "utf-8", errors="replace")
            else:
                decoded_subject += str(part)

        # Get raw email body
        raw_body = self._decode_gmail_payload(gmail_message.get("payload", {}))
        body = self.extract_plain_text_body(raw_body) if raw_body else ""
        extracted_links = self.extract_links(raw_body or "")

        # If body is empty this is probably a metadata-only message
        if len(body.strip()) < 10:
            return None

        # Skip non-guest operational / review-reminder emails even if they
        # come from a platform domain. These create noisy bogus drafts.
        if self.is_non_guest_email(decoded_subject, body):
            return None

        # Extract structured data
        guest_name    = self.extract_guest_name(
            decoded_subject,
            body,
            platform,
            display_name=display_name,
            from_email=from_email,
        )
        latest_guest_message, conversation_context = self.dissect_thread_content(body)
        property_name, property_surface_audit = self._select_property_mention_across_surfaces(
            subject=decoded_subject,
            body=body,
            latest_body=latest_guest_message or body,
            quoted_context=conversation_context,
        )
        check_in, check_out = self.extract_dates(body)
        guests = self.extract_guest_count(body)
        is_inquiry = self.is_inquiry_subject(decoded_subject)
        effective_body = latest_guest_message or body
        asks = detect_message_asks(effective_body)
        lifecycle_stage = infer_lifecycle_stage_from_message(
            current_stage="pre_booking",
            subject=decoded_subject,
            message=effective_body,
            asks=asks,
        )

        # Parse received date
        try:
            received_at = parsedate_to_datetime(date_header).replace(tzinfo=None)
        except Exception:
            received_at = datetime.utcnow()

        return ParsedGmailMessage(
            source_provider    = "gmail",
            source_message_id  = gmail_message["id"],
            source_thread_id   = gmail_message["threadId"],
            gmail_message_id  = gmail_message["id"],
            gmail_thread_id   = gmail_message["threadId"],
            message_id_header = msg_id_hdr,
            in_reply_to       = in_reply_to,
            references        = references,
            guest_name        = guest_name,
            guest_email       = from_email,
            subject           = decoded_subject,
            body              = effective_body,
            latest_guest_message = latest_guest_message or effective_body,
            conversation_context = conversation_context,
            full_body         = body,
            extracted_links   = extracted_links,
            asks              = asks,
            platform          = platform,
            is_inquiry        = is_inquiry,
            lifecycle_stage   = lifecycle_stage,
            parser_source     = "generic_gmail_parser",
            property_name     = property_name,
            property_mention_surface_audit = property_surface_audit,
            property_code     = "",  # resolved later against DB
            platform_listing_id = "",
            platform_unit_id    = "",
            requested_check_in  = check_in,
            requested_check_out = check_out,
            requested_guests    = guests,
            received_at         = received_at,
            raw_from            = from_raw,
        )

    def _decode_gmail_payload(self, payload: Dict[str, Any], depth: int = 0) -> str:
        """Decode Gmail API payload into raw email string."""
        if depth > 5:
            return ""

        body_data = payload.get("body", {}).get("data")
        if body_data:
            try:
                return base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
            except Exception:
                return ""

        # Multipart: reconstruct as pseudo-MIME for our parser
        parts = payload.get("parts", [])
        for part in parts:
            mime_type = part.get("mimeType", "")
            if mime_type in ("text/plain", "text/html"):
                data = part.get("body", {}).get("data", "")
                if data:
                    try:
                        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
                    except Exception:
                        continue
            elif mime_type.startswith("multipart/"):
                result = self._decode_gmail_payload(part, depth + 1)
                if result:
                    return result

        return ""

    def _extract_part_by_mime(
        self,
        payload: Dict[str, Any],
        target_mime: str,
        depth: int = 0,
    ) -> str:
        if depth > 8:
            return ""

        if payload.get("mimeType") == target_mime:
            data = payload.get("body", {}).get("data")
            if data:
                try:
                    return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
                except Exception:
                    return ""

        for part in payload.get("parts", []) or []:
            result = self._extract_part_by_mime(part, target_mime, depth + 1)
            if result:
                return result

        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Gmail Poller — fetches and processes unread messages
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GmailPollResult:
    """Result of one poll cycle."""
    messages_found: int
    messages_processed: int
    messages_skipped: int
    pre_booking_routed: int
    in_stay_routed: int
    errors: List[str]
    already_processed_skips: int = 0
    non_guest_skips: int = 0
    missing_message_skips: int = 0
    duplicate_inquiry_skips: int = 0
    pre_live_skips: int = 0
    save_failed_inquiries: int = 0
    new_pending_inquiries: int = 0
    fallback_inquiries_saved: int = 0
    gate_review_routed: int = 0
    gate_skipped: int = 0
    gate_errors: int = 0
    parse_failure_skips: int = 0
    quarantined_skips: int = 0
    query_mode: str = "unread"
    polled_at: datetime = field(default_factory=datetime.utcnow)


GmailIntakeEnvelope = EmailIntakeEnvelope


class EmailInboxPollerBase:
    """
    Polls an operator email inbox every N minutes for unread guest messages.

    Gmail remains one concrete adapter, but the polling and routing pipeline
    below is intentionally email-provider agnostic.

    Operator config (per operator, stored in Railway env vars):
      GMAIL_CLIENT_ID          Google OAuth2 client ID
      GMAIL_CLIENT_SECRET      Google OAuth2 client secret
      GMAIL_REFRESH_TOKEN      Refresh token for this operator's inbox
      GMAIL_WATCHED_EMAIL      The inbox address (e.g. info@beachhabitats30a.com)
      GMAIL_POLL_LABEL         Gmail label to poll (default: INBOX)
      GMAIL_PROCESSED_LABEL    Deprecated legacy setting; poller progress is
                               tracked in the database only

    For multiple operators, suffix env vars with operator code:
      GMAIL_REFRESH_TOKEN_BH   Beach Habitats refresh token
      GMAIL_WATCHED_EMAIL_BH   info@beachhabitats30a.com
    """

    def __init__(
        self,
        operator_id: str,
        company_id: UUID,
        token_manager: GmailTokenManager,
        watched_email: str,
        poll_label: str = "INBOX",
        processed_label: str = "Oyvoda-Processed",
        db=None,
    ):
        self.operator_id     = operator_id
        self.company_id      = company_id
        self.token_manager   = token_manager
        self.watched_email   = watched_email
        self.poll_label      = poll_label
        self.processed_label = processed_label
        self.db              = db
        self._parser         = GmailEmailParser()
        self._processed_label_id: Optional[str] = None
        self._kb_gap_threshold_pct: Optional[int] = None
        self._normalizer = InboundMessageNormalizer()
        self._schema_cache: Dict[str, set[str]] = {}
        self._last_non_guest_reason: str = ""
        self._inbox_go_live_at: Optional[datetime] = None

    @property
    def provider(self) -> str:
        return "gmail"

    def transport_capability(self):
        return get_inbound_transport_capability(self.provider)

    async def _table_columns(self, table_name: str) -> set[str]:
        if table_name in self._schema_cache:
            return self._schema_cache[table_name]
        if not self.db:
            return set()
        try:
            rows = (
                await self.db.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = :table_name
                        """
                    ),
                    {"table_name": table_name},
                )
            ).fetchall()
            cols = {str(row[0]) for row in rows}
            self._schema_cache[table_name] = cols
            return cols
        except Exception:
            await _safe_rollback(self.db)
            return set()

    async def _ensure_processing_tracking_schema(self) -> None:
        """Ensure gmail_processed_messages can track terminal and retryable failures."""
        if not self.db:
            return
        columns = await self._table_columns("gmail_processed_messages")
        required = {
            "processing_status",
            "failure_count",
            "last_failure_reason",
            "first_seen_at",
            "last_attempted_at",
        }
        if required.issubset(columns):
            return
        try:
            await self.db.execute(
                text(
                    """
                    ALTER TABLE gmail_processed_messages
                        ADD COLUMN IF NOT EXISTS processing_status TEXT NOT NULL DEFAULT 'processed',
                        ADD COLUMN IF NOT EXISTS failure_count INTEGER NOT NULL DEFAULT 0,
                        ADD COLUMN IF NOT EXISTS last_failure_reason TEXT,
                        ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        ADD COLUMN IF NOT EXISTS last_attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    """
                )
            )
            await self.db.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_gmail_processed_op_status
                        ON gmail_processed_messages (operator_id, processing_status, processed_at DESC)
                    """
                )
            )
            await self.db.commit()
            self._schema_cache.pop("gmail_processed_messages", None)
        except Exception:
            await _safe_rollback(self.db)
            logger.debug("[GmailPoller] processing tracking schema ensure failed", exc_info=True)

    async def _load_inbox_go_live_at(self) -> Optional[datetime]:
        if self._inbox_go_live_at is not None or not self.db:
            return self._inbox_go_live_at
        try:
            row = (
                await self.db.execute(
                    text(
                        """
                        SELECT inbox_go_live_at
                        FROM operator_gmail_creds
                        WHERE operator_id = CAST(:operator_id AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"operator_id": self.operator_id},
                )
            ).first()
            self._inbox_go_live_at = self._normalize_timestamp(row[0]) if row and row[0] else None
        except Exception:
            await _safe_rollback(self.db)
            logger.debug("[GmailPoller] inbox go-live load failed", exc_info=True)
            self._inbox_go_live_at = None
        return self._inbox_go_live_at

    @staticmethod
    def _normalize_timestamp(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def _raw_message_received_at(self, raw_message: Dict[str, Any]) -> datetime:
        internal_date = raw_message.get("internalDate")
        if internal_date:
            try:
                return datetime.fromtimestamp(int(str(internal_date)) / 1000.0, tz=timezone.utc).replace(tzinfo=None)
            except Exception:
                pass
        headers = {
            str(header.get("name") or "").lower(): str(header.get("value") or "")
            for header in raw_message.get("payload", {}).get("headers", []) or []
        }
        date_header = headers.get("date", "")
        if date_header:
            try:
                parsed = parsedate_to_datetime(date_header)
                if parsed.tzinfo is not None:
                    return parsed.astimezone(timezone.utc).replace(tzinfo=None)
                return parsed
            except Exception:
                pass
        return datetime.utcnow()

    async def _is_before_inbox_go_live(self, raw_message: Dict[str, Any]) -> bool:
        go_live_at = await self._load_inbox_go_live_at()
        if go_live_at is None:
            return False
        return self._raw_message_received_at(raw_message) < go_live_at

    @staticmethod
    def _first_existing(columns: set[str], *candidates: str) -> Optional[str]:
        for candidate in candidates:
            if candidate in columns:
                return candidate
        return None

    async def _property_table_meta(self) -> dict:
        columns = await self._table_columns("properties")
        return {
            "columns": columns,
            "tenant_col": self._first_existing(columns, "tenant_id", "company_id"),
            "id_col": self._first_existing(columns, "property_id", "id"),
            "canonical_code_col": self._first_existing(
                columns,
                "property_code",
                "internal_code",
                "external_id",
                "property_external_id",
                "code",
            ),
            "code_cols": [
                col
                for col in ("property_code", "internal_code", "external_id", "property_external_id", "code")
                if col in columns
            ],
            "name_cols": [
                col
                for col in (
                    "property_name",
                    "name",
                    "address_street",
                    "address_line1",
                    "community",
                    "property_code",
                    "external_id",
                )
                if col in columns
            ],
            "json_external_ids_col": self._first_existing(columns, "external_ids"),
            "json_extra_col": self._first_existing(columns, "extra_data"),
            "amenities_col": self._first_existing(columns, "amenities"),
            "description_col": self._first_existing(columns, "description", "general_notes"),
        }

    async def _pms_table_meta(self) -> dict:
        columns = await self._table_columns("pms_listings")
        return {
            "columns": columns,
            "tenant_col": self._first_existing(columns, "company_id", "tenant_id"),
            "canonical_code_col": self._first_existing(columns, "external_id"),
            "name_col": self._first_existing(columns, "property_name", "name"),
        }

    @staticmethod
    def _dictish(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "y", "private", "public"}
        return False

    # ── Main poll cycle ───────────────────────────────────────────────────────

    async def poll(self) -> GmailPollResult:
        """Run one full unread-only poll cycle. Called every 5 minutes."""
        return await self.poll_with_mode(query_mode="unread")

    async def poll_message_ids(
        self,
        message_ids: list[str],
        *,
        query_mode: str = "specific_ids",
    ) -> GmailPollResult:
        """Process an explicit set of Gmail message IDs without listing mailbox state."""
        result = GmailPollResult(
            messages_found=0,
            messages_processed=0,
            messages_skipped=0,
            pre_booking_routed=0,
            in_stay_routed=0,
            errors=[],
            query_mode=query_mode,
        )

        try:
            await self._ensure_processing_tracking_schema()
            await self._load_inbox_go_live_at()
            token = await self.token_manager.get_access_token()
            headers = self.token_manager.auth_header(token)

            deduped_ids: list[str] = []
            seen_ids: set[str] = set()
            for msg_id in message_ids:
                raw = str(msg_id or "").strip()
                if not raw or raw in seen_ids:
                    continue
                seen_ids.add(raw)
                deduped_ids.append(raw)
            result.messages_found = len(deduped_ids)

            if not deduped_ids:
                await self._record_poll_heartbeat(result)
                return result

            for msg_id in deduped_ids:
                try:
                    await self._process_one_message(msg_id, headers, result)
                except Exception as e:
                    result.errors.append(f"msg {msg_id}: {e}")
                    logger.warning("[GmailPoller] Error processing %s: %s", msg_id, e)
                    await self._record_retryable_failure(
                        gmail_message_id=msg_id,
                        rfc_message_id="",
                        reason=f"processing_exception:{type(e).__name__}",
                        headers=headers,
                    )
                    await _safe_rollback(self.db)
        except Exception as e:
            result.errors.append(f"poll error: {e}")
            logger.error("[GmailPoller] Poll failed for %s: %s", self.operator_id, e)
            await _safe_rollback(self.db)

        logger.info(
            "[GmailPoller] %s mode=%s: found=%d processed=%d pre_booking=%d in_stay=%d errors=%d",
            self.operator_id, result.query_mode, result.messages_found, result.messages_processed,
            result.pre_booking_routed, result.in_stay_routed, len(result.errors),
        )
        await self._record_poll_heartbeat(result)
        return result

    async def poll_with_mode(self, query_mode: str = "unread") -> GmailPollResult:
        """Run one poll cycle using the requested Gmail query mode."""
        result = GmailPollResult(
            messages_found=0, messages_processed=0,
            messages_skipped=0, pre_booking_routed=0,
            in_stay_routed=0, errors=[],
            query_mode=query_mode,
        )

        try:
            await self._ensure_processing_tracking_schema()
            await self._load_inbox_go_live_at()
            token = await self.token_manager.get_access_token()
            headers = self.token_manager.auth_header(token)

            # Automatic polling stays unread-only. Manual support flows can
            # choose a broader recent-inbox query when needed.
            message_ids = await self._list_message_ids(headers, query_mode=query_mode)
            result.messages_found = len(message_ids)

            if not message_ids:
                await self._record_poll_heartbeat(result)
                return result

            for msg_id in message_ids:
                try:
                    await self._process_one_message(msg_id, headers, result)
                except Exception as e:
                    result.errors.append(f"msg {msg_id}: {e}")
                    logger.warning("[GmailPoller] Error processing %s: %s", msg_id, e)
                    await self._record_retryable_failure(
                        gmail_message_id=msg_id,
                        rfc_message_id="",
                        reason=f"processing_exception:{type(e).__name__}",
                        headers=headers,
                    )
                    # Each message gets a fresh, clean session state. If
                    # processing this message left an aborted transaction
                    # uncaught somewhere downstream, clear it so the next
                    # message in the loop doesn't inherit poisoned state.
                    await _safe_rollback(self.db)

        except Exception as e:
            result.errors.append(f"poll error: {e}")
            logger.error("[GmailPoller] Poll failed for %s: %s", self.operator_id, e)
            await _safe_rollback(self.db)

        logger.info(
            "[GmailPoller] %s mode=%s: found=%d processed=%d pre_booking=%d in_stay=%d errors=%d",
            self.operator_id, result.query_mode, result.messages_found, result.messages_processed,
            result.pre_booking_routed, result.in_stay_routed, len(result.errors),
        )
        await self._record_poll_heartbeat(result)
        return result

    async def poll_from_history(
        self,
        start_history_id: str,
        *,
        end_history_id: str | None = None,
    ) -> GmailPollResult:
        """
        Process only the Gmail message IDs surfaced by the history delta.

        Falls back to the bounded recent-inbox scan only when Gmail cannot honor
        the supplied history window (for example, an expired startHistoryId).
        """
        history_start = str(start_history_id or "").strip()
        history_end = str(end_history_id or "").strip()
        if not history_start:
            return await self.poll_with_mode(query_mode="recent_inbox")

        try:
            token = await self.token_manager.get_access_token()
            headers = self.token_manager.auth_header(token)
            message_ids = await self._list_history_message_ids(
                headers,
                start_history_id=history_start,
                end_history_id=history_end or None,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                logger.info(
                    "[GmailPoller] history window expired for %s start=%s; falling back to recent_inbox",
                    self.operator_id,
                    history_start,
                )
                return await self.poll_with_mode(query_mode="recent_inbox")
            raise

        return await self.poll_message_ids(message_ids, query_mode="gmail_history")

    async def _record_poll_heartbeat(self, result: GmailPollResult) -> None:
        """Persist last-poll state for operator-facing inbox health."""
        if not self.db:
            return
        try:
            from sqlalchemy import text
            error_text = " | ".join(result.errors[:3]) if result.errors else None
            summary = (
                f"found={result.messages_found}, new={result.new_pending_inquiries}, "
                f"dupes={result.duplicate_inquiry_skips}, save_failed={result.save_failed_inquiries}, "
                f"processed={result.messages_processed}"
            )
            if error_text:
                if "gmail_reauth_required" in error_text:
                    summary = "Inbox authorization expired — reconnect Gmail to resume polling."
                else:
                    summary = f"Polling issue — {error_text[:180]}"
            await self.db.execute(text("""
                UPDATE operator_gmail_creds
                SET last_polled_at = NOW(),
                    last_poll_success = :success,
                    last_poll_summary = :summary,
                    last_poll_error = :error,
                    last_messages_found = :found,
                    last_new_pending_inquiries = :new_pending,
                    last_query_mode = :query_mode,
                    updated_at = NOW()
                WHERE operator_id = CAST(:op AS uuid)
            """), {
                "op": self.operator_id,
                "success": not bool(result.errors),
                "summary": summary,
                "error": error_text,
                "found": result.messages_found,
                "new_pending": result.new_pending_inquiries,
                "query_mode": result.query_mode,
            })
            await self.db.commit()
        except Exception as exc:
            await _safe_rollback(self.db)
            logger.debug("[GmailPoller] heartbeat update failed: %s", exc)

    async def _list_message_ids(self, headers: Dict, query_mode: str = "unread") -> List[str]:
        """List message IDs in the watched label for the chosen query mode."""
        watched = (self.watched_email or "").strip()
        if query_mode == "recent_inbox":
            query = f"label:{self.poll_label} newer_than:14d"
        else:
            query = f"is:unread label:{self.poll_label}"
        if watched:
            # Forwarded Escapia / Vrbo mail may preserve Delivered-To even when
            # the visible To header changes, so search both.
            query = f'{query} {{to:{watched} deliveredto:{watched}}}'
        params = {
            "q": query,
            "maxResults": 25 if query_mode == "recent_inbox" else 50,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GMAIL_API_BASE}/users/me/messages",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        return [m["id"] for m in data.get("messages", [])]

    async def _list_history_message_ids(
        self,
        headers: Dict,
        *,
        start_history_id: str,
        end_history_id: str | None = None,
    ) -> List[str]:
        """
        Return message IDs added to the watched mailbox since start_history_id.

        This keeps Gmail push event-driven: only messages introduced by the new
        history window are handed to the parser path, not an arbitrary recent
        slice of the mailbox.
        """
        message_ids: list[str] = []
        seen_ids: set[str] = set()
        page_token: str | None = None
        end_history_int = int(end_history_id) if str(end_history_id or "").isdigit() else None

        while True:
            params: Dict[str, str] = {
                "startHistoryId": str(start_history_id),
                "historyTypes": "messageAdded",
                "maxResults": "100",
            }
            if page_token:
                params["pageToken"] = page_token

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{GMAIL_API_BASE}/users/me/history",
                    headers=headers,
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()

            for record in data.get("history", []) or []:
                record_history_raw = str(record.get("id") or "").strip()
                record_history_int = int(record_history_raw) if record_history_raw.isdigit() else None
                if end_history_int is not None and record_history_int is not None and record_history_int > end_history_int:
                    continue

                for added in record.get("messagesAdded", []) or []:
                    message = added.get("message") or {}
                    msg_id = str(message.get("id") or "").strip()
                    if not msg_id or msg_id in seen_ids:
                        continue
                    label_ids = {str(label or "") for label in message.get("labelIds", []) or []}
                    if self.poll_label and label_ids and self.poll_label not in label_ids:
                        continue
                    seen_ids.add(msg_id)
                    message_ids.append(msg_id)

            page_token = str(data.get("nextPageToken") or "").strip() or None
            if not page_token:
                break

        return message_ids

    async def _get_full_message(
        self, msg_id: str, headers: Dict
    ) -> Optional[Dict[str, Any]]:
        """Fetch full message payload."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GMAIL_API_BASE}/users/me/messages/{msg_id}",
                headers=headers,
                params={"format": "full"},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def _process_one_message(
        self,
        msg_id: str,
        headers: Dict,
        result: GmailPollResult,
    ) -> None:
        """Fetch, parse, dedup-check, route, and mark one message."""

        # Dedup check — skip if already processed
        if await self._is_already_processed(msg_id):
            record = await self._get_processing_record(msg_id)
            status = str((record or {}).get("processing_status") or "").strip().lower()
            result.messages_skipped += 1
            if status == _PROCESSING_STATUS_QUARANTINED:
                result.quarantined_skips += 1
            else:
                result.already_processed_skips += 1
            return

        raw_message = await self._get_full_message(msg_id, headers)
        if not raw_message:
            result.messages_skipped += 1
            result.missing_message_skips += 1
            return

        if await self._is_before_inbox_go_live(raw_message):
            result.messages_skipped += 1
            result.pre_live_skips += 1
            await self._record_processing_state(
                gmail_message_id=msg_id,
                rfc_message_id="",
                status=_PROCESSING_STATUS_NON_GUEST,
                failure_reason="pre_live_cutoff",
                headers=headers,
            )
            return

        try:
            envelope = await self._intake_raw_message(raw_message, msg_id=msg_id, headers=headers)
        except LLMEmailExtractorParseFailure as exc:
            result.messages_skipped += 1
            result.parse_failure_skips += 1
            status, failure_count = await self._record_retryable_failure(
                gmail_message_id=msg_id,
                rfc_message_id="",
                reason=f"parse_failure:{exc.reason}",
                headers=headers,
            )
            if status == _PROCESSING_STATUS_QUARANTINED:
                result.quarantined_skips += 1
            logger.warning(
                "[EmailInboxPoller] parse failure source_message_id=%s reason=%s",
                msg_id,
                exc.reason,
            )
            return
        if envelope is None:
            # Not a guest message — skip without mutating Gmail read state.
            result.messages_skipped += 1
            result.non_guest_skips += 1
            await self._record_processing_state(
                gmail_message_id=msg_id,
                rfc_message_id="",
                status=_PROCESSING_STATUS_NON_GUEST,
                failure_reason=self._last_non_guest_reason or "non_guest_or_non_actionable",
                headers=headers,
            )
            return
        parsed = envelope.parsed

        # Route to correct pipeline
        try:
            routed = await self._route_message(parsed)
        except Exception as e:
            recovered = False
            if self._should_recover_pre_booking_route_failure(parsed):
                recovered = await self._save_fallback_pre_booking_inquiry(
                    parsed,
                    error_message=f"route_failure:{type(e).__name__}",
                )
                if recovered:
                    routed = "pre_booking_fallback"
                    logger.warning(
                        "[GmailPoller] recovered pre-booking route failure via fallback inquiry "
                        "save gmail_message_id=%s parser_source=%s exc_type=%s",
                        parsed.gmail_message_id,
                        parsed.parser_source,
                        type(e).__name__,
                        exc_info=True,
                    )
            if not recovered:
                # Stamp the normalization row before re-raising so the message
                # doesn't stay stranded at shadow_persisted permanently. The
                # outer loop catches the re-raise and records a retryable
                # failure in gmail_processing_state; on retry the dedup guard
                # fires so this path would run again — but the outcome row at
                # least becomes visible in the Filtered surface rather than
                # silently disappearing.
                try:
                    await update_normalization_outcome(
                        self.db,
                        self.company_id,
                        "email",
                        parsed.message_id or "",
                        route_outcome="route_exception",
                        fallback_reason=f"route_exception:{type(e).__name__}",
                    )
                except Exception:
                    logger.debug("[GmailPoller] route_exception outcome stamp failed", exc_info=True)
                raise

        if routed == "pre_booking":
            result.pre_booking_routed += 1
        elif routed == "in_stay":
            result.in_stay_routed += 1
        elif routed == "in_stay_pending_review":
            result.in_stay_routed += 1
        elif routed == "in_stay_ai_disabled":
            result.in_stay_routed += 1
        elif routed == "pre_booking_new":
            result.pre_booking_routed += 1
            result.new_pending_inquiries += 1
        elif routed == "pre_booking_duplicate":
            result.pre_booking_routed += 1
            result.duplicate_inquiry_skips += 1
        elif routed == "pre_booking_save_failed":
            result.pre_booking_routed += 1
            result.save_failed_inquiries += 1
        elif routed == "pre_booking_fallback":
            result.pre_booking_routed += 1
            result.new_pending_inquiries += 1
            result.fallback_inquiries_saved += 1
        elif routed == "pre_booking_gate_review":
            result.gate_review_routed += 1
            result.fallback_inquiries_saved += 1
        elif routed == "pre_booking_gate_skipped":
            # D1 fix: gate-skipped messages do NOT mutate Gmail read state.
            # The previous behavior unconditionally called _mark_read here,
            # which silently flipped UNREAD off the operator's primary inbox
            # view the moment the gate was enabled — a latent regression
            # against the file's overarching contract that read state is
            # operator-owned. Aligned with every other branch in this
            # dispatch: dedup is recorded below and Gmail's UNREAD is left
            # untouched.
            result.gate_skipped += 1
        elif routed == "pre_booking_gate_error":
            result.gate_errors += 1
            result.fallback_inquiries_saved += 1
        elif routed in {"guest_session_routed", "guest_session_existing", "pending_session_resolution"}:
            result.in_stay_routed += 1
        elif routed == "guest_session_route_failed":
            result.parse_failure_skips += 1
        elif routed == "dropped":
            result.non_guest_skips += 1

        result.messages_processed += 1

        # Mark as processed in the DB and add the operator-visible label
        # without mutating Gmail's unread/read state.
        await self._mark_processed(msg_id, parsed.message_id_header, headers)
        await self._ensure_processed_label(headers)
        await self._apply_label(msg_id, headers)

    async def _intake_message(
        self,
        msg_id: str,
        headers: Dict[str, str],
    ) -> Optional[GmailIntakeEnvelope]:
        """Fetch, parse, and enrich one inbound Gmail message before routing."""
        raw = await self._get_full_message(msg_id, headers)
        if not raw:
            return None

        return await self._intake_raw_message(raw, msg_id=msg_id, headers=headers)

    async def _intake_raw_message(
        self,
        raw: Dict[str, Any],
        *,
        msg_id: str,
        headers: Dict[str, str],
    ) -> Optional[GmailIntakeEnvelope]:
        """Parse and enrich one already-fetched inbound Gmail message before routing."""

        parsed = await self._parse_with_ota_fallback(raw)
        if not parsed:
            return None

        parsed = await self._prepare_parsed_message(parsed)
        return GmailIntakeEnvelope(
            parsed=parsed,
            source_message_id=parsed.message_id or msg_id,
            source_thread_id=parsed.thread_id or "",
        )

    async def _prepare_parsed_message(
        self,
        parsed: ParsedGmailMessage,
    ) -> ParsedGmailMessage:
        """Resolve canonical identity and enrich a parsed message for routing."""
        parsed.property_code = await self._resolve_property_code(parsed)
        parsed.property_match_type = ""
        if not parsed.property_code and self.db:
            from app.services.concierge.thread_property_inheritance import (
                inherit_property_from_thread_context,
            )

            inherited = await inherit_property_from_thread_context(
                self.db,
                tenant_id=self.company_id,
                source_thread_id=parsed.thread_id or "",
                current_message_id=parsed.message_id or "",
                in_reply_to=parsed.in_reply_to or "",
                references=parsed.references or [],
            )
            if inherited:
                parsed.property_code = inherited.property_code
                parsed.property_match_type = "thread_inheritance"
        parsed.identity = await resolve_guest_identity(
            db=self.db,
            tenant_id=self.company_id,
            guest_email=parsed.guest_email or "",
            guest_name=parsed.guest_name or "",
            reservation_id=parsed.reservation_id or "",
            property_code=parsed.property_code or "",
            requested_check_in=getattr(parsed, "requested_check_in", None),
            requested_check_out=getattr(parsed, "requested_check_out", None),
        )
        await self._auto_store_property_identity(parsed)
        await self._maybe_record_unmatched_platform_identifier(parsed)
        await self._enrich_with_link_context(parsed)
        await self._shadow_persist_canonical_message(parsed)
        return parsed

    async def _maybe_record_unmatched_platform_identifier(self, parsed: ParsedGmailMessage) -> None:
        if parsed.property_code:
            return
        if not (parsed.platform_listing_id or parsed.platform_unit_id):
            return
        if parsed.platform not in {"vrbo", "airbnb"}:
            return
        await self._record_property_binding_gap(parsed, reason="unmatched_platform_identifier")

    async def _auto_store_property_identity(self, parsed: ParsedGmailMessage) -> None:
        if not self.db or not parsed.property_code:
            return
        if not (
            parsed.platform_listing_id
            or parsed.platform_unit_id
            or parsed.raw_property_mention
            or parsed.property_name
        ):
            return
        try:
            property_data, _ = await self._load_property_context(parsed.property_code)
            assessment = await self._assess_property_identity_confidence(parsed)
            writer = get_canonical_property_write_service(self.db)
            common_metadata = {
                "gmail_thread_id": parsed.gmail_thread_id or "",
                "parser_source": parsed.parser_source or "",
                "message_id": parsed.gmail_message_id or "",
                "confidence": assessment["confidence"],
                "reason": assessment["reason"],
                "provider_property_id": parsed.provider_property_id or parsed.source_property_id or "",
                "provider_account_id": parsed.provider_account_id or parsed.source_account_id or "",
                "source_property_id": parsed.source_property_id or "",
                "source_account_id": parsed.source_account_id or "",
            }
            if assessment["auto_store"]:
                await writer.observe_resolved_identity(
                    self.company_id,
                    canonical_property_code=parsed.property_code,
                    platform=parsed.platform or "",
                    platform_listing_id=parsed.platform_listing_id or "",
                    platform_unit_id=parsed.platform_unit_id or "",
                    property_name=parsed.raw_property_mention or parsed.property_name or property_data.get("property_name") or "",
                    display_name=property_data.get("display_name") or property_data.get("property_name") or parsed.raw_property_mention or parsed.property_name or "",
                    address_line1=property_data.get("preferred_address") or property_data.get("address_street") or "",
                    source="gmail_auto_resolution",
                    metadata=common_metadata,
                )
            else:
                review_ref = parsed.raw_property_mention or parsed.property_name or parsed.platform_listing_id or parsed.platform_unit_id
                await writer.queue_property_link_review(
                    self.company_id,
                    canonical_property_code=parsed.property_code,
                    provider=parsed.platform or "internal",
                    ref_kind="alias" if (parsed.raw_property_mention or parsed.property_name) else ("external_id" if parsed.platform_listing_id else "unit_id"),
                    ref_value=review_ref,
                    platform_listing_id=parsed.platform_listing_id or "",
                    platform_unit_id=parsed.platform_unit_id or "",
                    property_name=parsed.raw_property_mention or parsed.property_name or property_data.get("property_name") or "",
                    display_name=property_data.get("display_name") or property_data.get("property_name") or parsed.raw_property_mention or parsed.property_name or "",
                    confidence=assessment["confidence"],
                    source="gmail_identity_review",
                    candidates=assessment.get("candidates") or [],
                    metadata=common_metadata,
                )
        except Exception as exc:
            await _safe_rollback(self.db)
            logger.debug("[GmailPoller] auto identity store skipped: %s", exc)

    async def _assess_property_identity_confidence(self, parsed: ParsedGmailMessage) -> Dict[str, Any]:
        svc = get_canonical_property_service(self.db)
        resolved_code = parsed.property_code or ""
        candidates: List[Dict[str, Any]] = []

        if parsed.platform_listing_id:
            listing_only = await svc.resolve_property_code(
                self.company_id,
                platform_listing_id=parsed.platform_listing_id or "",
                platform=parsed.platform or "",
            )
            if listing_only and listing_only == resolved_code:
                return {"auto_store": True, "confidence": 1.0, "reason": "trusted_listing_id", "candidates": []}

        if parsed.platform_unit_id:
            unit_only = await svc.resolve_property_code(
                self.company_id,
                platform_unit_id=parsed.platform_unit_id or "",
                platform=parsed.platform or "",
            )
            if unit_only and unit_only == resolved_code:
                return {"auto_store": True, "confidence": 1.0, "reason": "trusted_unit_id", "candidates": []}

        query_value = parsed.raw_property_mention or parsed.property_name or parsed.platform_listing_id or parsed.platform_unit_id or ""
        if query_value:
            candidates = await svc.suggest_property_matches(self.company_id, query_value, limit=5)
        if not candidates:
            return {"auto_store": False, "confidence": 0.0, "reason": "no_candidates", "candidates": []}

        top = candidates[0]
        second_score = float(candidates[1]["score"]) if len(candidates) > 1 else 0.0
        top_score = float(top["score"])
        score_gap = top_score - second_score
        if top.get("property_code") == resolved_code and top_score >= 0.95 and score_gap >= 0.15:
            return {
                "auto_store": True,
                "confidence": top_score,
                "reason": "strong_name_match",
                "candidates": candidates,
            }
        return {
            "auto_store": False,
            "confidence": top_score if top.get("property_code") == resolved_code else 0.0,
            "reason": "needs_operator_review",
            "candidates": candidates,
        }

    # ── Message routing ────────────────────────────────────────────────────────

    async def _route_message(self, parsed: ParsedGmailMessage) -> str:
        return await process_routed_email(
            parsed,
            services=EmailPipelineServices(
                find_active_session=self._find_active_session,
                evaluate_reservation_routing=self._evaluate_reservation_routing,
                dispatch_system_event=lambda parsed_message: dispatch_system_event(
                    services=self._email_dispatch_services(),
                    parsed=parsed_message,
                ),
                dispatch_in_stay=lambda parsed_message, session_row: dispatch_in_stay(
                    services=self._email_dispatch_services(),
                    parsed=parsed_message,
                    session_row=session_row,
                ),
                dispatch_confirmed_guest=lambda parsed_message, reservation_match: dispatch_confirmed_guest(
                    services=self._email_dispatch_services(),
                    parsed=parsed_message,
                    reservation_match=reservation_match,
                ),
                dispatch_pre_booking=lambda parsed_message: dispatch_pre_booking(
                    services=self._email_dispatch_services(),
                    parsed=parsed_message,
                ),
            ),
        )

    async def _evaluate_reservation_routing(self, parsed: ParsedGmailMessage):
        service = ReservationAwareRoutingService(company_id=self.company_id, db=self.db)
        return await service.evaluate(parsed)

    async def _parse_with_ota_fallback(
        self,
        gmail_message: Dict[str, Any],
        *,
        llm_extractor_factory=None,
    ) -> Optional[ParsedGmailMessage]:
        self._last_non_guest_reason = ""
        headers = {
            h["name"]: h["value"]
            for h in gmail_message.get("payload", {}).get("headers", [])
            if h.get("name") and h.get("value") is not None
        }
        subject = headers.get("Subject", headers.get("subject", ""))
        raw_body = self._parser._decode_gmail_payload(gmail_message.get("payload", {}))
        plain_body = self._parser.extract_plain_text_body(raw_body) if raw_body else ""
        raw_html = self._parser.extract_html_body(gmail_message)
        return await parse_structured_inbound_email(
            source_message_id=gmail_message.get("id", ""),
            subject=subject,
            plain_text=plain_body,
            raw_html=raw_html,
            headers=headers,
            parser=self._parser,
            adapt_llm_inquiry=lambda extracted: self._adapt_llm_inquiry(
                gmail_message,
                extracted,
                subject=subject,
                plain_body=plain_body,
                raw_body=raw_body,
            ),
            adapt_reservation_event=lambda parsed_event: self._adapt_ota_reservation_event(gmail_message, parsed_event),
            adapt_ota_inquiry=lambda parsed_ota: self._adapt_ota_inquiry(gmail_message, parsed_ota),
            adapt_direct_inquiry=lambda parsed_direct: self._adapt_direct_inquiry(gmail_message, parsed_direct),
            adapt_vendor_email=lambda parsed_vendor: self._adapt_vendor_email(gmail_message, parsed_vendor),
            fallback_parse=lambda: self._parser.parse(gmail_message),
            record_non_guest_drop=lambda reason: setattr(self, "_last_non_guest_reason", reason),
            llm_extractor_factory=(
                llm_extractor_factory
                or (lambda: LLMEmailExtractor(tenant_id=self.company_id))
            ),
            tenant_id=self.company_id,
            db=self.db,
        )

    def _adapt_llm_inquiry(
        self,
        gmail_message: Dict[str, Any],
        extracted: ExtractedEmailFields,
        *,
        subject: str,
        plain_body: str,
        raw_body: str,
    ) -> ParsedGmailMessage:
        headers = {
            h["name"].lower(): h["value"]
            for h in gmail_message.get("payload", {}).get("headers", [])
        }
        from_raw = headers.get("from", "")
        date_header = headers.get("date", "")
        msg_id_hdr = headers.get("message-id", "")
        in_reply_to, references = _extract_reply_headers(headers)
        extracted_links = self._parser.extract_links(raw_body or "")

        try:
            received_at = parsedate_to_datetime(date_header).replace(tzinfo=None)
        except Exception:
            received_at = datetime.utcnow()

        reply_target = extracted.sender_email or parseaddr(from_raw)[1].lower()
        if _is_platform_automation_email(reply_target):
            reply_target = ""

        platform = self._parser.detect_platform(reply_target or parseaddr(from_raw)[1].lower())
        property_identity_hint = extracted.external_id_hint or extracted.raw_property_mention
        asks = detect_message_asks(extracted.latest_guest_message or "")
        lifecycle_stage = infer_lifecycle_stage_from_message(
            current_stage="pre_booking",
            subject=subject,
            message=extracted.latest_guest_message or "",
            asks=asks,
        )
        return ParsedGmailMessage(
            source_provider="gmail",
            source_message_id=gmail_message["id"],
            source_thread_id=gmail_message["threadId"],
            gmail_message_id=gmail_message["id"],
            gmail_thread_id=gmail_message["threadId"],
            message_id_header=msg_id_hdr,
            in_reply_to=in_reply_to,
            references=references,
            guest_name=extracted.sender_name or "Guest",
            guest_email=reply_target,
            sender_role="guest",
            reply_channel_address=reply_target,
            subject=subject,
            body=extracted.latest_guest_message,
            latest_guest_message=extracted.latest_guest_message,
            latest_operator_message="",
            conversation_context="",
            full_body=plain_body or extracted.latest_guest_message,
            extracted_links=extracted_links,
            link_context_summary="",
            asks=asks,
            platform=platform,
            is_inquiry=True,
            lifecycle_stage=lifecycle_stage,
            parser_source=extracted.parser_source,
            property_name=property_identity_hint,
            property_mention_surface_audit=extracted.property_mention_surface_audit or {},
            raw_property_mention=property_identity_hint,
            property_code="",
            platform_listing_id=extracted.platform_listing_id,
            platform_unit_id=extracted.platform_unit_id,
            source_interaction_id="",
            source_property_id=extracted.source_property_id,
            source_account_id=extracted.provider_account_id,
            provider_property_id=extracted.provider_property_id,
            provider_account_id=extracted.provider_account_id,
            requested_check_in=extracted.requested_check_in,
            requested_check_out=extracted.requested_check_out,
            requested_guests=extracted.requested_guests,
            received_at=received_at,
            raw_from=from_raw,
        )

    def _adapt_ota_reservation_event(
        self,
        gmail_message: Dict[str, Any],
        parsed_event: ParsedOtaReservationEvent,
    ) -> Optional[ParsedGmailMessage]:
        headers = {
            h["name"].lower(): h["value"]
            for h in gmail_message.get("payload", {}).get("headers", [])
        }
        subject = headers.get("subject", "")
        from_raw = headers.get("from", "")
        date_header = headers.get("date", "")
        msg_id_hdr = headers.get("message-id", "")
        in_reply_to, references = _extract_reply_headers(headers)
        raw_body = self._parser._decode_gmail_payload(gmail_message.get("payload", {}))
        extracted_links = self._parser.extract_links(raw_body or "")

        try:
            received_at = parsedate_to_datetime(date_header).replace(tzinfo=None)
        except Exception:
            received_at = datetime.utcnow()

        requested_guests = None
        if parsed_event.guests_adults is not None or parsed_event.guests_children is not None:
            requested_guests = (parsed_event.guests_adults or 0) + (parsed_event.guests_children or 0)

        return ParsedGmailMessage(
            source_provider="gmail",
            source_message_id=gmail_message["id"],
            source_thread_id=gmail_message["threadId"],
            gmail_message_id=gmail_message["id"],
            gmail_thread_id=gmail_message["threadId"],
            message_id_header=msg_id_hdr,
            in_reply_to=in_reply_to,
            references=references,
            guest_name=parsed_event.guest_name or "Guest",
            guest_email=parsed_event.guest_email or "",
            sender_role="system",
            reply_channel_address=parsed_event.reply_channel_address or "",
            system_generated=True,
            system_event_type=parsed_event.system_event_type or "",
            system_event_payload={
                "review_rating": parsed_event.review_rating,
                "public_review_text": parsed_event.public_review_text or "",
                "private_note": parsed_event.private_note or "",
                "review_response_url": parsed_event.review_response_url or "",
            },
            subject=subject,
            body=parsed_event.summary_text or subject,
            latest_guest_message="",
            latest_operator_message="",
            conversation_context="",
            full_body=raw_body or parsed_event.summary_text or subject,
            extracted_links=extracted_links,
            link_context_summary="",
            asks=[],
            platform=parsed_event.platform,
            is_inquiry=False,
            lifecycle_stage=parsed_event.lifecycle_stage or "pre_arrival",
            parser_source=parsed_event.parser_source,
            property_name=parsed_event.property_name_hint or "",
            property_code="",
            platform_listing_id=parsed_event.platform_listing_id or "",
            platform_unit_id="",
            source_interaction_id=parsed_event.source_interaction_id or "",
            source_property_id="",
            reservation_id=parsed_event.reservation_id or "",
            requested_check_in=parsed_event.check_in,
            requested_check_out=parsed_event.check_out,
            requested_guests=requested_guests,
            received_at=received_at,
            raw_from=from_raw,
        )

    def _adapt_ota_inquiry(
        self,
        gmail_message: Dict[str, Any],
        parsed_ota: ParsedOtaInquiry,
    ) -> Optional[ParsedGmailMessage]:
        headers = {
            h["name"].lower(): h["value"]
            for h in gmail_message.get("payload", {}).get("headers", [])
        }
        subject = headers.get("subject", "")
        from_raw = headers.get("from", "")
        date_header = headers.get("date", "")
        msg_id_hdr = headers.get("message-id", "")
        in_reply_to, references = _extract_reply_headers(headers)
        raw_body = self._parser._decode_gmail_payload(gmail_message.get("payload", {}))
        extracted_links = self._parser.extract_links(raw_body or "")
        generic_property_name = self._parser.extract_property_name(subject, parsed_ota.message_body or "")

        try:
            received_at = parsedate_to_datetime(date_header).replace(tzinfo=None)
        except Exception:
            received_at = datetime.utcnow()

        requested_guests = None
        if parsed_ota.guests_adults is not None or parsed_ota.guests_children is not None:
            requested_guests = (parsed_ota.guests_adults or 0) + (parsed_ota.guests_children or 0)

        body = parsed_ota.latest_guest_turn or parsed_ota.message_body or parsed_ota.latest_operator_turn or ""
        if len(body.strip()) < 10:
            return None
        latest_guest_message = parsed_ota.latest_guest_turn or ""
        latest_operator_message = parsed_ota.latest_operator_turn or ""
        conversation_context = parsed_ota.prior_thread_context or ""
        if not latest_guest_message:
            latest_guest_message, fallback_context = self._parser.dissect_thread_content(body)
            conversation_context = conversation_context or fallback_context
        effective_body = latest_guest_message or body
        reply_target = parsed_ota.reply_channel_address or parsed_ota.guest_email or parseaddr(from_raw)[1].lower()
        if _is_platform_automation_email(reply_target):
            reply_target = ""

        return ParsedGmailMessage(
            source_provider="gmail",
            source_message_id=gmail_message["id"],
            source_thread_id=gmail_message["threadId"],
            gmail_message_id=gmail_message["id"],
            gmail_thread_id=gmail_message["threadId"],
            message_id_header=msg_id_hdr,
            in_reply_to=in_reply_to,
            references=references,
            guest_name=parsed_ota.guest_name or "Guest",
            guest_email=reply_target,
            sender_role=parsed_ota.sender_role or "guest",
            reply_channel_address=parsed_ota.reply_channel_address or "",
            subject=subject,
            body=effective_body,
            latest_guest_message=latest_guest_message or effective_body,
            latest_operator_message=latest_operator_message,
            conversation_context=conversation_context,
            full_body=body,
            extracted_links=extracted_links,
            link_context_summary="",
            asks=list(parsed_ota.asks or []),
            platform=parsed_ota.platform,
            is_inquiry=parsed_ota.lifecycle_stage == "pre_booking",
            lifecycle_stage=parsed_ota.lifecycle_stage or "unknown",
            parser_source=parsed_ota.parser_source,
            property_name=parsed_ota.property_name_hint or generic_property_name or "",
            property_code="",
            platform_listing_id=parsed_ota.platform_listing_id or "",
            platform_unit_id=parsed_ota.platform_unit_id or "",
            source_interaction_id=parsed_ota.source_interaction_id or "",
            source_property_id=parsed_ota.source_property_id or "",
            source_account_id=parsed_ota.source_account_id or "",
            provider_property_id=parsed_ota.provider_property_id or parsed_ota.source_property_id or "",
            provider_account_id=parsed_ota.provider_account_id or parsed_ota.source_account_id or "",
            requested_check_in=parsed_ota.check_in,
            requested_check_out=parsed_ota.check_out,
            requested_guests=requested_guests,
            received_at=received_at,
            raw_from=from_raw,
        )

    def _adapt_direct_inquiry(
        self,
        gmail_message: Dict[str, Any],
        parsed_direct: ParsedDirectInquiry,
    ) -> Optional[ParsedGmailMessage]:
        headers = {
            h["name"].lower(): h["value"]
            for h in gmail_message.get("payload", {}).get("headers", [])
        }
        subject = headers.get("subject", "")
        from_raw = headers.get("from", "")
        date_header = headers.get("date", "")
        msg_id_hdr = headers.get("message-id", "")
        in_reply_to, references = _extract_reply_headers(headers)
        raw_body = self._parser._decode_gmail_payload(gmail_message.get("payload", {}))
        extracted_links = self._parser.extract_links(raw_body or "")

        try:
            received_at = parsedate_to_datetime(date_header).replace(tzinfo=None)
        except Exception:
            received_at = datetime.utcnow()

        requested_guests = None
        if parsed_direct.guests_adults is not None or parsed_direct.guests_children is not None:
            requested_guests = (parsed_direct.guests_adults or 0) + (parsed_direct.guests_children or 0)

        body = parsed_direct.latest_guest_turn or parsed_direct.message_body or parsed_direct.latest_operator_turn or ""
        if len(body.strip()) < 10:
            return None
        lifecycle_stage = infer_lifecycle_stage_from_message(
            current_stage=parsed_direct.lifecycle_stage or "pre_booking",
            subject=subject,
            message=parsed_direct.latest_guest_turn or body,
            asks=parsed_direct.asks or [],
        )
        property_hint = (parsed_direct.property_name_hint or "").strip()
        page_path = (parsed_direct.page_path or "").strip()
        property_identity = property_hint or page_path

        return ParsedGmailMessage(
            source_provider="gmail",
            source_message_id=gmail_message["id"],
            source_thread_id=gmail_message["threadId"],
            gmail_message_id=gmail_message["id"],
            gmail_thread_id=gmail_message["threadId"],
            message_id_header=msg_id_hdr,
            in_reply_to=in_reply_to,
            references=references,
            guest_name=parsed_direct.guest_name or "Guest",
            guest_email=parsed_direct.guest_email or parseaddr(from_raw)[1].lower(),
            sender_role=parsed_direct.sender_role or "guest",
            reply_channel_address=parsed_direct.reply_channel_address or "",
            subject=subject,
            body=body,
            latest_guest_message=parsed_direct.latest_guest_turn or body,
            latest_operator_message=parsed_direct.latest_operator_turn or "",
            conversation_context=parsed_direct.prior_thread_context or "",
            full_body=body,
            extracted_links=extracted_links,
            link_context_summary="",
            asks=list(parsed_direct.asks or []),
            platform="direct",
            is_inquiry=True,
            lifecycle_stage=lifecycle_stage,
            parser_source=parsed_direct.parser_source,
            property_name=property_identity,
            property_code="",
            raw_property_mention=property_identity,
            platform_listing_id="",
            platform_unit_id="",
            source_interaction_id="",
            source_property_id=page_path,
            requested_check_in=parsed_direct.check_in,
            requested_check_out=parsed_direct.check_out,
            requested_guests=requested_guests,
            received_at=received_at,
            raw_from=from_raw,
        )

    def _adapt_vendor_email(
        self,
        gmail_message: Dict[str, Any],
        parsed_vendor,
    ) -> Optional[ParsedGmailMessage]:
        headers = {
            h["name"].lower(): h["value"]
            for h in gmail_message.get("payload", {}).get("headers", [])
        }
        subject = headers.get("subject", "")
        from_raw = headers.get("from", "")
        date_header = headers.get("date", "")
        msg_id_hdr = headers.get("message-id", "")
        in_reply_to, references = _extract_reply_headers(headers)
        raw_body = self._parser._decode_gmail_payload(gmail_message.get("payload", {}))
        extracted_links = self._parser.extract_links(raw_body or "")

        try:
            received_at = parsedate_to_datetime(date_header).replace(tzinfo=None)
        except Exception:
            received_at = datetime.utcnow()

        body = parsed_vendor.latest_vendor_turn or parsed_vendor.latest_operator_turn or subject
        return ParsedGmailMessage(
            source_provider="gmail",
            source_message_id=gmail_message["id"],
            source_thread_id=gmail_message["threadId"],
            gmail_message_id=gmail_message["id"],
            gmail_thread_id=gmail_message["threadId"],
            message_id_header=msg_id_hdr,
            in_reply_to=in_reply_to,
            references=references,
            guest_name=parsed_vendor.vendor_name or "Vendor",
            guest_email=parsed_vendor.vendor_email or parseaddr(from_raw)[1].lower(),
            sender_role=parsed_vendor.sender_role or "vendor",
            reply_channel_address="",
            system_generated=True,
            system_event_type=parsed_vendor.system_event_type or "vendor_ops_email",
            subject=subject,
            body=body,
            latest_guest_message="",
            latest_operator_message=parsed_vendor.latest_operator_turn or "",
            conversation_context="",
            full_body=raw_body or body,
            extracted_links=extracted_links,
            link_context_summary="",
            asks=[],
            platform="direct",
            is_inquiry=False,
            lifecycle_stage="ops_vendor",
            parser_source=parsed_vendor.parser_source,
            property_name=parsed_vendor.property_name_hint or "",
            property_code="",
            platform_listing_id="",
            platform_unit_id="",
            source_interaction_id="",
            source_property_id="",
            reservation_id="",
            requested_check_in=None,
            requested_check_out=None,
            requested_guests=None,
            received_at=received_at,
            raw_from=from_raw,
        )

    def _email_dispatch_services(self) -> EmailDispatchServices:
        return EmailDispatchServices(
            company_id=self.company_id,
            db=self.db,
            watched_email=self.watched_email,
            operator_name=self._get_operator_name(),
            infer_property_match_type=self._normalizer.infer_property_match_type,
            load_property_context=self._load_property_context,
            store_thread_context=self._store_gmail_thread_context,
            maybe_record_pre_booking_gap=self._maybe_record_pre_booking_gap,
            save_fallback_pre_booking_inquiry=self._save_fallback_pre_booking_inquiry,
            record_kb_gap=self._record_kb_gap,
            record_property_binding_gap=self._record_property_binding_gap,
            build_reply_sender=lambda: GmailReplySender(self.token_manager),
            generate_in_stay_reply=self._generate_in_stay_reply,
            load_review_event_policy=self._load_review_event_policy,
            find_session_by_reservation_context=self._find_session_by_reservation_context,
            create_provisional_session_from_system_event=self._create_provisional_session_from_system_event,
            persist_review_event=self._persist_review_event,
        )

    async def _generate_in_stay_reply(self, message: str, session_row) -> str:
        from app.api.v1.endpoints.sms import _generate_via_voice_pod
        from app.db.session import AsyncSessionLocal

        token = getattr(session_row, "token", None)
        async with AsyncSessionLocal() as db:
            return await _generate_via_voice_pod(message, token, session_row, db)

    async def _shadow_persist_canonical_message(self, parsed: ParsedGmailMessage) -> None:
        if not self.db:
            return
        try:
            normalized = self._normalizer.normalize_email_message(
                parsed,
                watched_email=self.watched_email,
            )
            await persist_canonical_inbound_message(self.db, self.company_id, normalized)
            await update_normalization_outcome(
                self.db,
                self.company_id,
                "email",
                parsed.message_id,
                selected_property_code=parsed.property_code or "",
                selected_property_match_type=self._normalizer.infer_property_match_type(
                    parsed, parsed.property_code or ""
                ),
                route_outcome="shadow_persisted",
            )
        except Exception as exc:
            await _safe_rollback(self.db)
            logger.error(
                "[GmailPoller] canonical shadow persist failed for tenant_id=%s "
                "gmail_message_id=%s source_message_id=%s parser_source=%s "
                "exc_type=%s exc_message=%s",
                self.company_id,
                parsed.gmail_message_id,
                parsed.message_id,
                parsed.parser_source,
                type(exc).__name__,
                str(exc),
                exc_info=True,
            )

    def _is_allowed_context_link(self, url: str) -> bool:
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            return False
        return any(host == d or host.endswith("." + d) for d in LINK_CONTEXT_ALLOWED_DOMAINS)

    async def _fetch_link_context_summary(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "OyvodaLinkContext/1.0"})
                resp.raise_for_status()
                ctype = (resp.headers.get("content-type") or "").lower()
                if "text/html" not in ctype and "text/plain" not in ctype:
                    return ""
                raw = resp.text[:20000]
        except Exception:
            return ""

        title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.I | re.S)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
        text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw)
        text = re.sub(r"(?i)<br\\s*/?>|</p>", "\n", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        snippet = text[:500]
        if not snippet:
            return ""
        return f"{title + ' — ' if title else ''}{snippet}".strip(" -")

    async def _enrich_with_link_context(self, parsed: ParsedGmailMessage) -> None:
        if not parsed.extracted_links:
            return
        links = [u for u in parsed.extracted_links if self._is_allowed_context_link(u)][:2]
        if not links:
            return
        summaries = []
        for url in links:
            summary = await self._fetch_link_context_summary(url)
            if summary:
                host = (urlparse(url).hostname or url).lower()
                summaries.append(f"{host}: {summary}")
        if not summaries:
            return
        parsed.link_context_summary = " | ".join(summaries)
        parsed.body = (
            parsed.body
            + "\n\nLinked page context (allowlisted domains):\n"
            + "\n".join(f"- {s}" for s in summaries)
        )[:4500]

    async def _load_kb_gap_threshold_pct(self) -> int:
        if self._kb_gap_threshold_pct is not None:
            return self._kb_gap_threshold_pct
        self._kb_gap_threshold_pct = 40
        if not self.db:
            return self._kb_gap_threshold_pct
        try:
            from sqlalchemy import text
            row = (await self.db.execute(text("""
                SELECT kb_gap_detection_threshold
                FROM operator_settings
                WHERE tenant_id = CAST(:tid AS uuid)
                LIMIT 1
            """), {"tid": str(self.company_id)})).fetchone()
            if row and row[0] is not None:
                self._kb_gap_threshold_pct = max(0, min(100, int(row[0])))
        except Exception as exc:
            await _safe_rollback(self.db)
            logger.debug("[GmailPoller] gap threshold lookup failed: %s", exc)
        return self._kb_gap_threshold_pct

    async def _load_review_event_policy(self) -> Dict[str, bool]:
        defaults = {
            "ingest_review_events": True,
            "apply_private_feedback_signals": False,
            "generate_review_response_drafts": False,
        }
        if not self.db:
            return defaults
        try:
            row = (
                await self.db.execute(
                    text(
                        """
                        SELECT extra
                        FROM operator_settings
                        WHERE tenant_id = CAST(:tid AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"tid": str(self.company_id)},
                )
            ).mappings().first()
            extra = row.get("extra") if row else {}
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except Exception:
                    extra = {}
            extra = extra if isinstance(extra, dict) else {}
            incoming = extra.get("review_event_policy") if isinstance(extra.get("review_event_policy"), dict) else {}
            if isinstance(incoming, dict):
                defaults.update(
                    {
                        "ingest_review_events": bool(incoming.get("ingest_review_events", defaults["ingest_review_events"])),
                        "apply_private_feedback_signals": bool(incoming.get("apply_private_feedback_signals", defaults["apply_private_feedback_signals"])),
                        "generate_review_response_drafts": bool(incoming.get("generate_review_response_drafts", defaults["generate_review_response_drafts"])),
                    }
                )
        except Exception as exc:
            await _safe_rollback(self.db)
            logger.debug("[GmailPoller] review event policy lookup failed: %s", exc)
        return defaults

    async def _record_kb_gap(
        self,
        parsed: ParsedGmailMessage,
        detected_intent: str,
        confidence_score: float,
        metadata: Dict[str, Any],
    ) -> None:
        if not self.db:
            return
        try:
            from app.services.messaging_brain.knowledge.gap_recorder import record_gap_async

            await record_gap_async(
                tenant_id=self.company_id,
                question=(parsed.body or parsed.subject or "").strip()[:4000],
                answer_attempt="",
                confidence_score=confidence_score,
                property_code=parsed.property_code or "",
                used_kb_chunks=False,
                was_deflected=False,
                detected_intent=detected_intent,
                stage="pre_booking",
                channel="email",
                source="gmail_poll",
                metadata=metadata,
            )
        except Exception as exc:
            await _safe_rollback(self.db)
            logger.debug("[GmailPoller] KB gap record failed: %s", exc)

    async def _maybe_record_pre_booking_gap(
        self,
        parsed: ParsedGmailMessage,
        result: Dict[str, Any],
    ) -> None:
        if not result.get("saved"):
            return
        confidence = float(result.get("confidence") or 0.0)
        threshold_pct = await self._load_kb_gap_threshold_pct()
        if confidence * 100.0 > threshold_pct:
            if not any(str(w).startswith("missing_property_knowledge:") for w in (result.get("policy_warnings") or [])):
                return
        missing_topics = []
        for warning in result.get("policy_warnings") or []:
            sw = str(warning)
            if sw.startswith("missing_property_knowledge:"):
                missing_topics = [p for p in sw.split(":", 1)[1].split(",") if p]
                break
        await self._record_kb_gap(
            parsed,
            detected_intent=(
                "gmail_prebooking_missing_knowledge"
                if missing_topics else
                "gmail_prebooking_low_confidence"
            ),
            confidence_score=confidence,
            metadata={
                "reason": "missing_property_knowledge" if missing_topics else "low_prebooking_confidence",
                "threshold_pct": threshold_pct,
                "actual_pct": round(confidence * 100.0, 1),
                "intent": result.get("intent"),
                "draft_id": result.get("draft_id"),
                "policy_warnings": result.get("policy_warnings") or [],
                "missing_topics": missing_topics,
                "link_context_summary": parsed.link_context_summary or "",
                "parser_source": parsed.parser_source,
                "asks": parsed.asks or [],
                "platform_listing_id": parsed.platform_listing_id or "",
                "platform_unit_id": parsed.platform_unit_id or "",
            },
        )

    async def _persist_review_event(
        self,
        session_row,
        parsed: ParsedGmailMessage,
        policy: Dict[str, bool],
    ) -> None:
        payload = dict(parsed.system_event_payload or {})
        rating = payload.get("review_rating")
        public_review_text = str(payload.get("public_review_text") or "").strip()
        private_note = str(payload.get("private_note") or "").strip()
        property_code = getattr(session_row, "property_code", None)
        property_data: Dict[str, Any] = {}
        if property_code:
            property_data, _ = await self._load_property_context(str(property_code))
        feedback_signals = extract_review_feedback_signals(
            private_note,
            property_data=property_data,
        )
        if feedback_signals:
            payload["feedback_signals"] = feedback_signals
            payload["feedback_signal_summary"] = summarize_feedback_signal_outcome(feedback_signals)

        if policy.get("generate_review_response_drafts"):
            payload["suggested_response"] = self._build_review_response_suggestion(
                guest_name=parsed.guest_name,
                rating=rating,
                public_review_text=public_review_text,
                private_note=private_note,
            )
            parsed.system_event_payload["suggested_response"] = payload["suggested_response"]

        await stay_event_service.record_event(
            self.db,
            str(self.company_id),
            session_id=str(getattr(session_row, "session_id", "")),
            session_token=getattr(session_row, "token", None),
            property_code=getattr(session_row, "property_code", None),
            event_type="guest_review_received",
            status="completed",
            source=parsed.platform,
            note=f"{parsed.guest_name} left a review",
            payload=payload,
            occurred_at=parsed.received_at.isoformat(),
            created_by="system",
        )

        if rating:
            await self.db.execute(
                text(
                    """
                    UPDATE concierge_guest_sessions
                    SET feedback_rating = COALESCE(feedback_rating, :rating),
                        feedback_text = COALESCE(NULLIF(feedback_text, ''), :feedback_text)
                    WHERE session_id = CAST(:sid AS uuid)
                    """
                ),
                {
                    "sid": str(getattr(session_row, "session_id", "")),
                    "rating": int(rating),
                    "feedback_text": private_note or public_review_text or None,
                },
            )

        if policy.get("apply_private_feedback_signals") and private_note:
            await stay_event_service.record_event(
                self.db,
                str(self.company_id),
                session_id=str(getattr(session_row, "session_id", "")),
                session_token=getattr(session_row, "token", None),
                property_code=getattr(session_row, "property_code", None),
                event_type="guest_review_signal",
                status="completed",
                source=parsed.platform,
                note="Private review note captured for operator follow-up",
                payload={
                    "feedback_signals": feedback_signals,
                    "feedback_signal_summary": summarize_feedback_signal_outcome(feedback_signals),
                    "private_note": private_note,
                    "review_rating": rating,
                    "guest_name": parsed.guest_name,
                },
                occurred_at=parsed.received_at.isoformat(),
                created_by="system",
            )

        await self.db.commit()

    def _build_review_response_suggestion(
        self,
        *,
        guest_name: str,
        rating: Any,
        public_review_text: str,
        private_note: str,
    ) -> str:
        first = (guest_name or "there").split()[0]
        if private_note and ("toilet paper" in private_note.lower() or "trash bag" in private_note.lower()):
            return (
                f"Thank you so much, {first}! We’re glad you had such a wonderful stay and really appreciate "
                "the kind words about the home and bikes. We also appreciate the note about supplies and will use "
                "that feedback to improve future stays."
            )
        if rating and int(rating) >= 5:
            return (
                f"Thank you so much, {first}! We’re thrilled you enjoyed your stay and truly appreciate "
                "you taking the time to share such kind feedback. We’d love to host you again anytime."
            )
        return (
            f"Thank you for the review, {first}. We appreciate the feedback and are glad to hear more about your stay."
        )

    # ── Property + session resolution ─────────────────────────────────────────

    async def _find_active_session(self, parsed: ParsedGmailMessage):
        """Look for an active concierge session matching this email."""
        if not self.db:
            return None
        guest_email = str(parsed.guest_email or "").strip()
        if not guest_email:
            return None
        try:
            from sqlalchemy import text
            result = await self.db.execute(
                text("""
                    SELECT * FROM concierge_guest_sessions
                    WHERE (guest_email = :email OR guest_email ILIKE :email_fuzzy)
                      AND status NOT IN ('expired', 'closed')
                      AND check_out >= CURRENT_DATE - INTERVAL '1 day'
                    ORDER BY created_at DESC LIMIT 1
                """),
                {
                    "email": guest_email,
                    "email_fuzzy": f"%{guest_email.split('@')[0]}%",
                },
            )
            return result.fetchone()
        except Exception as e:
            await _safe_rollback(self.db)
            logger.debug("[GmailPoller] Session lookup failed: %s", e)
            return None

    async def _find_session_by_reservation_context(self, parsed: ParsedGmailMessage):
        if not self.db:
            return None
        try:
            from sqlalchemy import text
            if parsed.reservation_id:
                result = await self.db.execute(
                    text("""
                        SELECT * FROM concierge_guest_sessions
                        WHERE tenant_id::text = :op
                          AND reservation_id = :reservation_id
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {"op": str(self.company_id), "reservation_id": parsed.reservation_id},
                )
                row = result.fetchone()
                if row:
                    return row

            if parsed.property_code and parsed.guest_name and parsed.requested_check_in and parsed.requested_check_out:
                result = await self.db.execute(
                    text("""
                        SELECT * FROM concierge_guest_sessions
                        WHERE tenant_id::text = :op
                          AND property_code = :property_code
                          AND LOWER(guest_name) = LOWER(:guest_name)
                          AND check_in = :check_in
                          AND check_out = :check_out
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {
                        "op": str(self.company_id),
                        "property_code": parsed.property_code,
                        "guest_name": parsed.guest_name,
                        "check_in": parsed.requested_check_in,
                        "check_out": parsed.requested_check_out,
                    },
                )
                return result.fetchone()
        except Exception as e:
            await _safe_rollback(self.db)
            logger.debug("[GmailPoller] Reservation context lookup failed: %s", e)
        return None

    async def _create_provisional_session_from_system_event(self, parsed: ParsedGmailMessage) -> bool:
        if not self.db or not parsed.property_code or not parsed.requested_check_in or not parsed.requested_check_out:
            return False
        try:
            from app.services.concierge.db_session_service import DatabaseSessionService

            property_meta = await self._property_table_meta()
            property_cols = property_meta["columns"]
            property_id = None
            property_name = parsed.property_name or parsed.property_code
            if property_meta["canonical_code_col"]:
                scope_parts = []
                if property_meta["tenant_col"]:
                    scope_parts.append(f"{property_meta['tenant_col']}::text = :op")
                if "deleted_at" in property_cols:
                    scope_parts.append("deleted_at IS NULL")
                if "is_deleted" in property_cols:
                    scope_parts.append("COALESCE(is_deleted, FALSE) = FALSE")
                scope_sql = " AND ".join(scope_parts) if scope_parts else "TRUE"
                select_cols = [property_meta["canonical_code_col"]]
                if property_meta["id_col"]:
                    select_cols.append(property_meta["id_col"])
                for col in property_meta["name_cols"]:
                    if col not in select_cols:
                        select_cols.append(col)
                row = (
                    await self.db.execute(
                        text(
                            f"""
                            SELECT {', '.join(select_cols)}
                            FROM properties
                            WHERE {scope_sql}
                              AND {property_meta['canonical_code_col']} = :code
                            LIMIT 1
                            """
                        ),
                        {"op": str(self.company_id), "code": parsed.property_code},
                    )
                ).mappings().first()
                if row:
                    if property_meta["id_col"]:
                        property_id = row.get(property_meta["id_col"])
                    property_name = next(
                        (row.get(col) for col in property_meta["name_cols"] if row.get(col)),
                        property_name,
                    )

            property_data, _ = await self._load_property_context(parsed.property_code)
            svc = DatabaseSessionService(self.company_id)
            await svc.create_session(
                db=self.db,
                property_id=property_id,
                property_code=parsed.property_code,
                property_name=property_name,
                guest_name=parsed.guest_name or "Guest",
                guest_phone=None,
                guest_email=parsed.guest_email or None,
                check_in=parsed.requested_check_in,
                check_out=parsed.requested_check_out,
                num_guests=parsed.requested_guests or 1,
                reservation_id=parsed.reservation_id or parsed.source_interaction_id or None,
                property_context={
                    **(property_data or {}),
                    "seeded_from": parsed.parser_source,
                    "system_event_type": parsed.system_event_type,
                    "booking_channel": parsed.platform,
                    "source_interaction_id": parsed.source_interaction_id,
                    "platform_listing_id": parsed.platform_listing_id,
                },
            )
            return True
        except Exception as e:
            await _safe_rollback(self.db)
            logger.debug("[GmailPoller] Provisional session create failed: %s", e)
            return False

    async def _record_property_binding_gap(self, parsed: ParsedGmailMessage, reason: str) -> None:
        await self._record_kb_gap(
            parsed,
            detected_intent="missing_property_binding",
            confidence_score=0.0,
            metadata={
                "reason": reason,
                "platform": parsed.platform,
                "platform_listing_id": parsed.platform_listing_id or "",
                "platform_unit_id": parsed.platform_unit_id or "",
                "source_interaction_id": parsed.source_interaction_id or "",
                "reservation_id": parsed.reservation_id or "",
                "property_name": parsed.property_name or "",
                "raw_property_mention": parsed.raw_property_mention or "",
                "source_property_id": parsed.source_property_id or "",
                "provider_property_id": parsed.provider_property_id or "",
                "provider_account_id": parsed.provider_account_id or "",
                "parser_source": parsed.parser_source,
                "system_generated": parsed.system_generated,
            },
        )

    async def _resolve_property_code(self, parsed: ParsedGmailMessage) -> str:
        """Resolve a property using OTA IDs first, then fall back to name matching."""
        if not self.db:
            return ""
        try:
            svc = get_canonical_property_service(self.db)
            return await svc.resolve_property_code(
                self.company_id,
                platform_listing_id=parsed.platform_listing_id or "",
                platform_unit_id=parsed.platform_unit_id or "",
                property_name=parsed.raw_property_mention or parsed.property_name or "",
                platform=parsed.platform or "",
            )
        except Exception as e:
            await _safe_rollback(self.db)
            logger.debug("[GmailPoller] Property resolution failed: %s", e)
            return ""

    async def _load_property_context(
        self, property_code: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Load property data and operator policies from DB."""
        property_data: Dict[str, Any] = {}
        operator_policies: Dict[str, Any] = {
            "min_nights": 3,
            "pet_policy": "not_allowed",
        }

        if not self.db or not property_code:
            return property_data, operator_policies

        try:
            svc = get_canonical_property_service(self.db)
            profile = await svc.build_profile(self.company_id, property_code=property_code)
            property_data = {k: v for k, v in profile.items() if k not in {"operator_policies", "concierge_knowledge", "source_provenance"}}
            operator_policies.update(profile.get("operator_policies") or {})
            property_data["concierge_knowledge"] = profile.get("concierge_knowledge") or {}
            property_data["source_provenance"] = profile.get("source_provenance") or {}
        except Exception as e:
            await _safe_rollback(self.db)
            logger.error(
                "[GmailPoller] property context load failed for tenant_id=%s "
                "property_code=%s exc_type=%s exc_message=%s",
                self.company_id,
                property_code,
                type(e).__name__,
                str(e),
                exc_info=True,
            )

        return property_data, operator_policies

    def _get_operator_name(self) -> str:
        return os.getenv("OPERATOR_NAME", "Your Host")

    async def _save_fallback_pre_booking_inquiry(
        self,
        parsed: ParsedGmailMessage,
        error_message: str,
    ) -> bool:
        """
        Persist a reviewable inquiry even if AI draft generation fails.

        This keeps inbound emails visible to operators instead of letting them
        disappear behind a swallowed exception in the draft pipeline.
        """
        if not self.db:
            return False
        draft_id = None
        try:
            from app.db.session import AsyncSessionLocal
            from app.services.concierge.post_booking_routing import (
                persist_inbound_from_inquiry,
            )
            from app.services.messaging_brain.persistence.prebooking_inquiry_store import (
                save_inquiry_from_canonical,
            )
            from app.services.messaging_brain.persistence.prebooking_inquiry_types import (
                InquirySaveContext,
            )

            draft_id = f"INQ-{uuid.uuid4().hex[:8].upper()}"
            property_ref = parsed.property_code or ""

            fallback_draft = (
                "We captured this guest email, but Oyvoda could not generate the AI draft automatically yet. "
                "Review the guest message and reply manually."
            )
            inbound = _build_canonical_from_parsed_gmail(parsed)
            save_context = InquirySaveContext(
                draft_id=draft_id,
                company_id=self.company_id,
                selected_property_code=property_ref,
                requested_check_in=parsed.requested_check_in,
                requested_check_out=parsed.requested_check_out,
                requested_guests=parsed.requested_guests,
                intent="general_inquiry",
                confidence=0.0,
                draft_text=fallback_draft,
                draft_source="gmail_fallback",
                policy_flags=[],
                policy_warnings=[f"gmail_fallback_saved:{error_message[:180]}"],
                decision="hold",
                guest_thread_id=None,
                autonomy_decision="routed_to_action_policy_review",
            )
            async with AsyncSessionLocal() as recovery_db:
                await save_inquiry_from_canonical(
                    db=recovery_db,
                    inbound=inbound,
                    context=save_context,
                    normalization_kwargs={
                        "route_outcome": "pre_booking_fallback",
                        "draft_source": "gmail_fallback",
                        "fallback_reason": f"gmail_fallback_saved:{error_message[:180]}",
                    },
                )
                await self._store_gmail_thread_context(parsed, draft_id, db_session=recovery_db)
            return True
        except Exception as fallback_error:
            await _safe_rollback(self.db)
            logger.error(
                "[GmailPoller] Fallback inquiry save failed for draft_id=%s gmail_thread_id=%s gmail_message_id=%s: %s",
                draft_id,
                parsed.gmail_thread_id,
                parsed.gmail_message_id,
                fallback_error,
                exc_info=True,
            )
            return False

    def _should_recover_pre_booking_route_failure(self, parsed: ParsedGmailMessage) -> bool:
        lifecycle = (getattr(parsed, "lifecycle_stage", "") or "").strip().lower()
        parser_source = (getattr(parsed, "parser_source", "") or "").strip().lower()
        if getattr(parsed, "is_inquiry", False):
            return True
        if lifecycle in {"pre_booking", "prebooking"}:
            return True
        return (
            parser_source.startswith("ota_parser_")
            or parser_source.startswith("pre_booking")
            or parser_source.startswith("gmail_prebooking")
        )

    # ── Deduplication + marking ───────────────────────────────────────────────

    async def _is_already_processed(self, gmail_message_id: str) -> bool:
        """Check if we've already processed this Gmail message ID."""
        if not self.db:
            return False
        try:
            result = await self.db.execute(
                text("""
                    SELECT processing_status, failure_count
                    FROM gmail_processed_messages
                    WHERE gmail_message_id = :mid AND operator_id = :op
                    LIMIT 1
                """),
                {"mid": gmail_message_id, "op": self.operator_id},
            )
            row = result.mappings().first()
            if not row:
                return False
            status = str(row.get("processing_status") or _PROCESSING_STATUS_PROCESSED).strip().lower()
            failure_count = int(row.get("failure_count") or 0)
            if status in {
                _PROCESSING_STATUS_PROCESSED,
                _PROCESSING_STATUS_NON_GUEST,
                _PROCESSING_STATUS_QUARANTINED,
            }:
                return True
            if status == _PROCESSING_STATUS_FAILED_RETRYABLE and failure_count >= _MAX_PARSE_FAILURE_ATTEMPTS:
                return True
            return False
        except Exception:
            await _safe_rollback(self.db)
            return False

    async def _get_processing_record(self, gmail_message_id: str) -> Optional[Dict[str, Any]]:
        if not self.db:
            return None
        try:
            result = await self.db.execute(
                text(
                    """
                    SELECT processing_status, failure_count, last_failure_reason, rfc_message_id
                    FROM gmail_processed_messages
                    WHERE gmail_message_id = :mid AND operator_id = :op
                    LIMIT 1
                    """
                ),
                {"mid": gmail_message_id, "op": self.operator_id},
            )
            row = result.mappings().first()
            return dict(row) if row else None
        except Exception:
            await _safe_rollback(self.db)
            return None

    async def _record_processing_state(
        self,
        *,
        gmail_message_id: str,
        rfc_message_id: str,
        status: str,
        failure_count: int = 0,
        failure_reason: str = "",
        headers: Optional[Dict[str, str]] = None,
        apply_label: bool = False,
    ) -> None:
        # Gmail-visible state is intentionally unchanged. Poller progress is
        # tracked in gmail_processed_messages only.
        _ = apply_label
        _ = headers

        if not self.db:
            return
        try:
            await self.db.execute(
                text(
                    """
                    INSERT INTO gmail_processed_messages (
                        gmail_message_id,
                        rfc_message_id,
                        operator_id,
                        processed_at,
                        processing_status,
                        failure_count,
                        last_failure_reason,
                        first_seen_at,
                        last_attempted_at
                    )
                    VALUES (
                        :mid,
                        :rfc,
                        :op,
                        NOW(),
                        :status,
                        :failure_count,
                        :failure_reason,
                        NOW(),
                        NOW()
                    )
                    ON CONFLICT (gmail_message_id) DO UPDATE
                    SET rfc_message_id = COALESCE(NULLIF(EXCLUDED.rfc_message_id, ''), gmail_processed_messages.rfc_message_id),
                        operator_id = EXCLUDED.operator_id,
                        processed_at = NOW(),
                        processing_status = EXCLUDED.processing_status,
                        failure_count = EXCLUDED.failure_count,
                        last_failure_reason = NULLIF(EXCLUDED.last_failure_reason, ''),
                        last_attempted_at = NOW()
                    """
                ),
                {
                    "mid": gmail_message_id,
                    "rfc": rfc_message_id,
                    "op": self.operator_id,
                    "status": status,
                    "failure_count": failure_count,
                    "failure_reason": failure_reason[:500],
                },
            )
            await self.db.commit()
        except Exception as e:
            await _safe_rollback(self.db)
            logger.debug("[GmailPoller] processing state record failed: %s", e)

    async def _record_retryable_failure(
        self,
        *,
        gmail_message_id: str,
        rfc_message_id: str,
        reason: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> tuple[str, int]:
        record = await self._get_processing_record(gmail_message_id)
        next_count = int((record or {}).get("failure_count") or 0) + 1
        status = (
            _PROCESSING_STATUS_QUARANTINED
            if next_count >= _MAX_PARSE_FAILURE_ATTEMPTS
            else _PROCESSING_STATUS_FAILED_RETRYABLE
        )
        await self._record_processing_state(
            gmail_message_id=gmail_message_id,
            rfc_message_id=rfc_message_id or str((record or {}).get("rfc_message_id") or ""),
            status=status,
            failure_count=next_count,
            failure_reason=reason,
            headers=headers,
        )
        if status == _PROCESSING_STATUS_QUARANTINED:
            logger.info(
                "[GmailPoller] quarantined gmail_message_id=%s operator_id=%s failure_count=%s reason=%s",
                gmail_message_id,
                self.operator_id,
                next_count,
                reason[:200],
            )
        return status, next_count

    async def _mark_processed(
        self,
        gmail_message_id: str,
        rfc_message_id: str,
        headers: Dict,
    ) -> None:
        """Record email as processed in the dedup table.

        Read state is intentionally left alone so Gmail reflects what the
        operator has actually reviewed, not what the poller has touched.
        """
        await self._record_processing_state(
            gmail_message_id=gmail_message_id,
            rfc_message_id=rfc_message_id,
            status=_PROCESSING_STATUS_PROCESSED,
            headers=headers,
        )

    async def _mark_read(self, msg_id: str, headers: Dict) -> None:
        """Remove UNREAD label from a Gmail message.

        Reserved for explicit caller-initiated read-state changes (e.g.
        send_approved_gmail_reply marking a thread read after a successful
        send). NOT called from the poll dispatch — see the D1 fix in
        _process_one_message for context.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{GMAIL_API_BASE}/users/me/messages/{msg_id}/modify",
                    headers=headers,
                    json={"removeLabelIds": ["UNREAD"]},
                )
        except Exception as e:
            logger.debug("[GmailPoller] mark_read failed: %s", e)

    async def _apply_label(self, msg_id: str, headers: Dict) -> None:
        """Apply the processed label while leaving Gmail read state unchanged."""
        if not self._processed_label_id:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{GMAIL_API_BASE}/users/me/messages/{msg_id}/modify",
                    headers=headers,
                    json={"addLabelIds": [self._processed_label_id]},
                )
        except Exception as e:
            logger.debug("[GmailPoller] apply_label failed: %s", e)

    async def _ensure_processed_label(self, headers: Dict) -> None:
        """Ensure the operator-visible processed label exists in Gmail."""
        if self._processed_label_id:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # List existing labels
                resp = await client.get(
                    f"{GMAIL_API_BASE}/users/me/labels",
                    headers=headers,
                )
                resp.raise_for_status()
                labels = resp.json().get("labels", [])

                # Check if our label exists
                for label in labels:
                    if label.get("name") == self.processed_label:
                        self._processed_label_id = label["id"]
                        return

                # Create it
                resp = await client.post(
                    f"{GMAIL_API_BASE}/users/me/labels",
                    headers=headers,
                    json={"name": self.processed_label, "labelListVisibility": "labelShow"},
                )
                resp.raise_for_status()
                self._processed_label_id = resp.json()["id"]
                logger.info("[GmailPoller] Created label: %s", self.processed_label)

        except Exception as e:
            logger.debug("[GmailPoller] Label setup failed: %s", e)

    async def _store_gmail_thread_context(
        self,
        parsed: ParsedGmailMessage,
        draft_id: Optional[str],
        db_session=None,
    ) -> None:
        """
        Store the Gmail thread ID alongside the pre-booking draft so that
        when the operator approves, we can reply via Gmail into the right thread.
        """
        db = db_session or self.db
        if not db or not draft_id:
            return
        try:
            from sqlalchemy import text
            from app.services.operator.prebooking_queue_service import get_prebooking_queue_service
            reply_target = parsed.reply_channel_address or parsed.guest_email or ""
            reply_enabled = bool(reply_target and parsed.gmail_thread_id)
            await db.execute(
                text("""
                    UPDATE pre_booking_inquiries
                    SET gmail_thread_id     = :tid,
                        gmail_message_id    = :mid,
                        guest_email         = :email,
                        reply_via_gmail     = :reply_enabled,
                        parser_source       = COALESCE(:parser_source, parser_source),
                        extracted_asks      = CASE
                            WHEN :asks_json = '' THEN extracted_asks
                            ELSE CAST(:asks_json AS jsonb)
                        END,
                        platform_listing_id = CASE
                            WHEN :listing_id = '' THEN platform_listing_id
                            ELSE :listing_id
                        END,
                        platform_unit_id    = CASE
                            WHEN :unit_id = '' THEN platform_unit_id
                            ELSE :unit_id
                        END
                    WHERE draft_id = :draft_id
                """),
                {
                    "tid":      parsed.gmail_thread_id,
                    "mid":      parsed.gmail_message_id,
                    "email":    reply_target,
                    "reply_enabled": reply_enabled,
                    "parser_source": parsed.parser_source or "",
                    "asks_json": json.dumps(parsed.asks or []),
                    "listing_id": parsed.platform_listing_id or "",
                    "unit_id": parsed.platform_unit_id or "",
                    "draft_id": draft_id,
                },
            )
            queue_service = get_prebooking_queue_service()
            if self.company_id:
                await queue_service.sync_draft(db, str(self.company_id), draft_id)
            await db.commit()
        except Exception as e:
            await _safe_rollback(db)
            logger.debug("[GmailPoller] Thread context store failed: %s", e)


class GmailInboxPoller(EmailInboxPollerBase):
    """Gmail-backed email inbox poller."""

    pass


# ─────────────────────────────────────────────────────────────────────────────
# Gmail Reply Sender — sends approved replies via Gmail API
# ─────────────────────────────────────────────────────────────────────────────

class GmailReplySender(EmailReplySenderBase):
    """
    Sends an email reply via Gmail API into the correct thread.
    Used both for pre-booking approvals and in-stay responses.
    """

    provider_name = "Gmail"

    def __init__(self, token_manager, sent_label: Optional[str] = None):
        super().__init__(token_manager)
        self.sent_label = (sent_label or os.getenv("GMAIL_SENT_LABEL", "Oyvoda/Sent")).strip() or "Oyvoda/Sent"
        self._sent_label_id: Optional[str] = None

    async def _mark_thread_read(self, thread_id: str, headers: Dict[str, str]) -> None:
        """Mark all messages in a Gmail thread as read."""
        if not thread_id:
            return
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{GMAIL_API_BASE}/users/me/threads/{thread_id}/modify",
                headers=headers,
                json={"removeLabelIds": ["UNREAD"]},
            )
            resp.raise_for_status()

    async def _ensure_sent_label(self, headers: Dict[str, str]) -> None:
        if self._sent_label_id:
            return
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{GMAIL_API_BASE}/users/me/labels",
                headers=headers,
            )
            resp.raise_for_status()
            labels = resp.json().get("labels", [])
            for label in labels:
                if label.get("name") == self.sent_label:
                    self._sent_label_id = label.get("id")
                    return

            resp = await client.post(
                f"{GMAIL_API_BASE}/users/me/labels",
                headers=headers,
                json={"name": self.sent_label, "labelListVisibility": "labelShow"},
            )
            resp.raise_for_status()
            self._sent_label_id = resp.json().get("id")
            logger.info("[GmailReply] Created thread label: %s", self.sent_label)

    async def _apply_thread_label(self, thread_id: str, headers: Dict[str, str]) -> None:
        if not thread_id:
            return
        await self._ensure_sent_label(headers)
        if not self._sent_label_id:
            return
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{GMAIL_API_BASE}/users/me/threads/{thread_id}/modify",
                headers=headers,
                json={"addLabelIds": [self._sent_label_id]},
            )
            resp.raise_for_status()

    async def reply(
        self,
        thread_id: str,
        in_reply_to: str,
        to_address: str,
        to_name: str,
        subject: str,
        body: str,
        operator_name: str,
        from_email: Optional[str] = None,
    ) -> bool:
        """
        Send a reply email in a Gmail thread.

        Args:
            thread_id:    Gmail thread ID to reply into
            in_reply_to:  RFC 2822 Message-ID of the message we're replying to
            to_address:   Guest email address
            to_name:      Guest display name
            subject:      Email subject (should start with "Re: ")
            body:         Plain text reply body
            operator_name: Operator display name for the From header
            from_email:   Override from address (defaults to watched_email)
        """
        try:
            token = await self.token_manager.get_access_token()
            auth_headers = self.token_manager.auth_header(token)

            # Build RFC 2822 email
            raw_message = self._build_rfc2822_email(
                to_address   = to_address,
                to_name      = to_name,
                subject      = subject,
                body         = body,
                in_reply_to  = in_reply_to,
                references   = in_reply_to,
                from_email   = from_email or "",
                from_name    = operator_name,
            )

            # Base64url encode for Gmail API
            encoded = base64.urlsafe_b64encode(raw_message.encode("utf-8")).decode("utf-8")

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{GMAIL_API_BASE}/users/me/messages/send",
                    headers=auth_headers,
                    json={
                        "raw":      encoded,
                        "threadId": thread_id,
                    },
                )
                resp.raise_for_status()

            try:
                await self._mark_thread_read(thread_id, auth_headers)
            except Exception as mark_exc:
                logger.warning(
                    "[GmailReply] Sent reply for thread %s but failed to mark thread read: %s",
                    thread_id,
                    mark_exc,
                )

            try:
                await self._apply_thread_label(thread_id, auth_headers)
            except Exception as label_exc:
                logger.warning(
                    "[GmailReply] Sent reply for thread %s but failed to apply sent label %s: %s",
                    thread_id,
                    self.sent_label,
                    label_exc,
                )

            self._log_send_success(to_address, thread_id)
            return True

        except Exception as e:
            self._log_send_failure(e)
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Approve + send a pre-booking draft via Gmail
# ─────────────────────────────────────────────────────────────────────────────

async def send_approved_gmail_reply(
    draft_id: str,
    final_text: str,
    db,
    token_manager: GmailTokenManager,
    operator_name: str = "Your Host",
) -> bool:
    """
    Called when an operator approves a pre-booking draft.
    Looks up the Gmail thread context and sends the reply via Gmail API.
    Also tries Escapia fallback if reply_via_gmail is False.
    """
    try:
        from sqlalchemy import text
        result = await db.execute(
            text("""
                SELECT gmail_thread_id, gmail_message_id, guest_email,
                       guest_name, reply_via_gmail, property_external_id
                FROM pre_booking_inquiries
                WHERE draft_id = :did
                LIMIT 1
            """),
            {"did": draft_id},
        )
        row = result.fetchone()
        if not row:
            logger.warning("[GmailReply] Draft %s not found", draft_id)
            return False

        if row.reply_via_gmail and row.gmail_thread_id:
            sender = GmailReplySender(token_manager)
            sent = await sender.reply(
                thread_id   = row.gmail_thread_id,
                in_reply_to = row.gmail_message_id or "",
                to_address  = row.guest_email or "",
                to_name     = row.guest_name or "Guest",
                subject     = f"Re: Your inquiry about {row.property_external_id}",
                body        = final_text,
                operator_name = operator_name,
            )
        else:
            logger.warning(
                "[GmailReply] Draft %s has no Gmail thread context (reply_via_gmail=%s, gmail_thread_id=%s); manual operator reply required",
                draft_id,
                row.reply_via_gmail,
                row.gmail_thread_id,
            )
            return False

        if sent:
            await db.execute(
                text("""
                    UPDATE pre_booking_inquiries
                    SET status = 'replied', final_reply = :reply, replied_at = NOW(), triggered_by = 'operator'
                    WHERE draft_id = :did
                """),
                {"reply": final_text, "did": draft_id},
            )
            from app.services.operator.prebooking_queue_service import get_prebooking_queue_service
            queue_service = get_prebooking_queue_service()
            company_row = await db.execute(
                text("""
                    SELECT company_id
                    FROM pre_booking_inquiries
                    WHERE draft_id = :did
                    LIMIT 1
                """),
                {"did": draft_id},
            )
            company = company_row.fetchone()
            if company and company[0]:
                await queue_service.sync_draft(db, str(company[0]), draft_id)
            await db.commit()

        return sent

    except Exception as e:
        logger.error("[GmailReply] send_approved_gmail_reply failed: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# DB migration
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Factory — builds a poller from environment variables
# ─────────────────────────────────────────────────────────────────────────────

def build_gmail_poller(
    operator_id: str,
    company_id: UUID,
    db=None,
    env_suffix: str = "",
) -> Optional[GmailInboxPoller]:
    """
    Build a GmailInboxPoller from environment variables.
    Returns None if credentials are not configured.

    env_suffix allows multiple operators:
      env_suffix=""   → GMAIL_REFRESH_TOKEN, GMAIL_WATCHED_EMAIL
      env_suffix="_BH" → GMAIL_REFRESH_TOKEN_BH, GMAIL_WATCHED_EMAIL_BH
    """
    client_id      = os.getenv("GMAIL_CLIENT_ID", "")
    client_secret  = os.getenv("GMAIL_CLIENT_SECRET", "")
    refresh_token  = os.getenv(f"GMAIL_REFRESH_TOKEN{env_suffix}", "")
    watched_email  = os.getenv(f"GMAIL_WATCHED_EMAIL{env_suffix}", "")

    if not all([client_id, client_secret, refresh_token, watched_email]):
        missing = [
            k for k, v in {
                "GMAIL_CLIENT_ID": client_id,
                "GMAIL_CLIENT_SECRET": client_secret,
                f"GMAIL_REFRESH_TOKEN{env_suffix}": refresh_token,
                f"GMAIL_WATCHED_EMAIL{env_suffix}": watched_email,
            }.items() if not v
        ]
        logger.info(
            "[GmailPoller] Not configured for %s — missing: %s",
            operator_id, missing,
        )
        return None

    token_manager = GmailTokenManager(
        client_id     = client_id,
        client_secret = client_secret,
        refresh_token = refresh_token,
    )

    return GmailInboxPoller(
        operator_id     = operator_id,
        company_id      = company_id,
        token_manager   = token_manager,
        watched_email   = watched_email,
        poll_label      = os.getenv(f"GMAIL_POLL_LABEL{env_suffix}", "INBOX"),
        processed_label = os.getenv(f"GMAIL_PROCESSED_LABEL{env_suffix}", "Oyvoda-Processed"),
        db              = db,
    )
