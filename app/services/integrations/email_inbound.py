from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from app.services.messaging.identity_resolver import GuestIdentityResolution


@dataclass(kw_only=True)
class ParsedEmailMessage:
    """Provider-agnostic parsed email message handed into routing."""
    source_message_id: str = ""
    source_thread_id: str = ""
    source_provider: str = "email"

    gmail_message_id: str
    gmail_thread_id: str
    message_id_header: str

    guest_name: str
    guest_email: str
    sender_role: str = "guest"
    reply_channel_address: str = ""
    system_generated: bool = False
    system_event_type: str = ""
    system_event_payload: Dict[str, Any] = field(default_factory=dict)

    subject: str
    body: str
    latest_guest_message: str = ""
    latest_operator_message: str = ""
    conversation_context: str = ""
    full_body: str = ""
    extracted_links: List[str] = field(default_factory=list)
    link_context_summary: str = ""
    asks: List[str] = field(default_factory=list)

    platform: str
    is_inquiry: bool
    lifecycle_stage: str = "pre_booking"
    parser_source: str = "generic_email_parser"

    property_name: str
    property_code: str
    property_match_type: str = ""
    raw_property_mention: str = ""
    property_mention_surface_audit: Dict[str, Any] = field(default_factory=dict)
    platform_listing_id: str = ""
    platform_unit_id: str = ""
    source_interaction_id: str = ""
    source_property_id: str = ""
    source_account_id: str = ""
    provider_property_id: str = ""
    provider_account_id: str = ""
    reservation_id: str = ""
    ota_site: str = ""
    conversation_id: str = ""
    message_type: str = ""
    recipient_type: str = ""
    intake_layer1_decision: str = ""
    intake_layer1_reason: str = ""

    requested_check_in: Optional[date] = None
    requested_check_out: Optional[date] = None
    requested_guests: Optional[int] = None

    received_at: datetime = field(default_factory=datetime.utcnow)
    raw_from: str = ""
    in_reply_to: str = ""
    references: List[str] = field(default_factory=list)
    identity: Optional[GuestIdentityResolution] = None

    def __post_init__(self) -> None:
        if not self.source_message_id:
            self.source_message_id = self.gmail_message_id or ""
        if not self.source_thread_id:
            self.source_thread_id = self.gmail_thread_id or ""
        if not self.raw_property_mention:
            self.raw_property_mention = self.property_name or ""

    @property
    def message_id(self) -> str:
        return self.source_message_id or self.gmail_message_id or ""

    @property
    def thread_id(self) -> str:
        return self.source_thread_id or self.gmail_thread_id or ""


@dataclass
class EmailIntakeEnvelope:
    """Normalized email intake payload handed from transport/parsing into routing."""
    parsed: ParsedEmailMessage
    source_message_id: str
    source_thread_id: str


# Compatibility aliases while Gmail-specific callers are still being renamed.
ParsedGmailMessage = ParsedEmailMessage
GmailIntakeEnvelope = EmailIntakeEnvelope
