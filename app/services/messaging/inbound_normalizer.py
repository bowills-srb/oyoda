from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from email.utils import parseaddr
from typing import Any, Dict, List, Optional

from app.services.messaging.identity_resolver import GuestIdentityResolution


@dataclass
class PropertyBindingCandidate:
    candidate_type: str
    value: str
    confidence: float
    source: str


@dataclass
class CanonicalInboundMessage:
    source_channel: str
    source_provider: str
    source_thread_id: str
    source_message_id: str
    sender_role: str
    sender_display_name: str
    sender_address: str
    sent_at: datetime
    raw_subject: str
    latest_guest_turn: str
    prior_thread_context: str
    full_message_text: str
    structured_asks: List[str] = field(default_factory=list)
    prior_operator_commitments: List[str] = field(default_factory=list)
    property_binding_candidates: List[Dict[str, Any]] = field(default_factory=list)
    channel_constraints: Dict[str, Any] = field(default_factory=dict)
    parser_used: str = ""
    parser_version: str = "v1"
    parser_notes: List[str] = field(default_factory=list)
    latest_turn_confidence: float = 0.0
    latest_turn_extracted: bool = False
    guest_name: str = ""
    guest_email: str = ""
    identity: Optional[GuestIdentityResolution] = None


class InboundMessageNormalizer:
    """Channel-agnostic canonical model builder for inbound guest messages."""

    OPERATOR_COMMITMENT_PATTERNS = [
        re.compile(r"\b(i(?:'| a)?ll|we(?:'| wi)?ll)\b[^.?!]{0,120}", re.I),
        re.compile(r"\b(i|we)\s+can\b[^.?!]{0,120}", re.I),
        re.compile(r"\b(i|we)\s+are\s+checking\b[^.?!]{0,120}", re.I),
        re.compile(r"\b(confirm|confirmed|housekeeping|maintenance|check-?in)\b[^.?!]{0,120}", re.I),
    ]

    def normalize_email_message(
        self,
        parsed,
        watched_email: str = "",
    ) -> CanonicalInboundMessage:
        display_name, sender_address = parseaddr(parsed.raw_from or "")
        sender_address = (sender_address or parsed.guest_email or "").lower()

        latest_turn = (parsed.latest_guest_message or parsed.body or "").strip()
        full_body = (parsed.full_body or parsed.body or latest_turn).strip()
        prior_context = (parsed.conversation_context or "").strip()

        notes = []
        if parsed.parser_source:
            notes.append(f"parser:{parsed.parser_source}")
        if parsed.platform_listing_id:
            notes.append("listing_id_present")
        if parsed.platform_unit_id:
            notes.append("unit_id_present")
        if parsed.link_context_summary:
            notes.append("allowlisted_link_context")

        return CanonicalInboundMessage(
            source_channel="email",
            source_provider=self._infer_provider(parsed),
            source_thread_id=parsed.source_interaction_id or parsed.thread_id or "",
            source_message_id=parsed.message_id or "",
            sender_role=parsed.sender_role or "guest",
            sender_display_name=display_name or parsed.guest_name or "Guest",
            sender_address=sender_address,
            sent_at=parsed.received_at,
            raw_subject=parsed.subject or "",
            latest_guest_turn=latest_turn,
            prior_thread_context=prior_context,
            full_message_text=full_body,
            structured_asks=list(parsed.asks or []),
            prior_operator_commitments=self._extract_prior_operator_commitments(prior_context),
            property_binding_candidates=[
                asdict(c) for c in self._build_property_candidates(parsed)
            ],
            channel_constraints=self._build_channel_constraints(parsed, watched_email),
            parser_used=parsed.parser_source or "generic_email_parser",
            parser_version="v1",
            parser_notes=notes + ([f"lifecycle_stage:{getattr(parsed, 'lifecycle_stage', '')}"] if getattr(parsed, "lifecycle_stage", "") else []),
            latest_turn_confidence=self._estimate_latest_turn_confidence(parsed),
            latest_turn_extracted=bool(prior_context and latest_turn),
            guest_name=parsed.guest_name or "Guest",
            guest_email=parsed.guest_email or sender_address,
            identity=getattr(parsed, "identity", None),
        )

    def normalize_gmail_message(
        self,
        parsed,
        watched_email: str = "",
    ) -> CanonicalInboundMessage:
        """Compatibility wrapper while Gmail-specific callers are renamed."""
        return self.normalize_email_message(parsed, watched_email=watched_email)

    def infer_property_match_type(self, parsed, selected_property_code: str) -> str:
        if not selected_property_code:
            return ""
        explicit_match_type = (getattr(parsed, "property_match_type", "") or "").strip()
        if explicit_match_type:
            return explicit_match_type
        if parsed.platform_listing_id:
            return "platform_listing_id"
        if parsed.platform_unit_id:
            return "platform_unit_id"
        raw_property_mention = (getattr(parsed, "raw_property_mention", "") or parsed.property_name or "")
        if raw_property_mention.startswith("ExternalID:"):
            return "external_id_hint"
        if raw_property_mention:
            return "raw_property_mention"
        return "unknown"

    def _infer_provider(self, parsed) -> str:
        source_provider = (getattr(parsed, "source_provider", "") or "").strip().lower()
        if source_provider and source_provider != "email":
            return source_provider
        platform = (parsed.platform or "").strip().lower()
        host = (parseaddr(parsed.raw_from or "")[1] or "").split("@")[-1].lower()
        if host:
            return host
        if platform:
            return platform
        return "email"

    def _estimate_latest_turn_confidence(self, parsed) -> float:
        latest = (parsed.latest_guest_message or parsed.body or "").strip()
        full_body = (parsed.full_body or parsed.body or "").strip()
        if not latest:
            return 0.0
        if parsed.conversation_context and latest != full_body:
            return 0.92
        if latest == full_body:
            return 0.72
        return 0.85

    def _build_property_candidates(self, parsed) -> List[PropertyBindingCandidate]:
        candidates: List[PropertyBindingCandidate] = []
        seen = set()

        def add(candidate_type: str, value: str, confidence: float, source: str) -> None:
            v = (value or "").strip()
            key = (candidate_type, v.lower())
            if not v or key in seen:
                return
            seen.add(key)
            candidates.append(
                PropertyBindingCandidate(
                    candidate_type=candidate_type,
                    value=v,
                    confidence=confidence,
                    source=source,
                )
            )

        add("platform_listing_id", parsed.platform_listing_id or "", 0.98, "ota_html")
        add("platform_unit_id", parsed.platform_unit_id or "", 0.97, "ota_html")
        add("property_code", parsed.property_code or "", 0.95, "resolved_property")
        raw_property_mention = getattr(parsed, "raw_property_mention", "") or parsed.property_name or ""
        add("raw_property_mention", raw_property_mention, 0.55, "email_text")
        add("property_name", parsed.property_name or "", 0.45, "email_text")
        if raw_property_mention.startswith("ExternalID:"):
            add("external_id_hint", raw_property_mention.split(":", 1)[1], 0.93, "email_text")
        return candidates

    def _extract_prior_operator_commitments(self, context: str) -> List[str]:
        if not context:
            return []
        flattened = re.sub(r"\s+", " ", context)
        hits: List[str] = []
        seen = set()
        for pattern in self.OPERATOR_COMMITMENT_PATTERNS:
            for match in pattern.finditer(flattened):
                snippet = match.group(0).strip(" .,:;")
                if len(snippet) < 12:
                    continue
                key = snippet.lower()
                if key in seen:
                    continue
                seen.add(key)
                hits.append(snippet[:180])
        return hits[:6]

    def _build_channel_constraints(self, parsed, watched_email: str) -> Dict[str, Any]:
        return {
            "channel_type": "email",
            "reply_must_stay_in_thread": True,
            "source_thread_id": parsed.thread_id or "",
            "source_message_id": parsed.message_id or "",
            "gmail_thread_id": parsed.gmail_thread_id or "",
            "gmail_message_id": parsed.gmail_message_id or "",
            "source_interaction_id": getattr(parsed, "source_interaction_id", "") or "",
            "reply_channel_address": getattr(parsed, "reply_channel_address", "") or "",
            "message_id_header": getattr(parsed, "message_id_header", "") or "",
            "in_reply_to": getattr(parsed, "in_reply_to", "") or "",
            "references": list(getattr(parsed, "references", []) or []),
            "watched_email": watched_email or "",
            "platform": parsed.platform or "email",
        }
