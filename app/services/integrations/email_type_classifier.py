from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.services.integrations.inbound_source_router import InboundSourceRoute
from app.services.integrations.message_source_detection import detect_platform
from app.services.integrations.non_guest_patterns import NON_GUEST_REGISTRY


class MessageType(str, Enum):
    AIRBNB_GUEST_INQUIRY = "airbnb_guest_inquiry"
    AIRBNB_BOOKING_EVENT = "airbnb_booking_event"
    AIRBNB_NOTIFICATION = "airbnb_notification"
    VRBO_GUEST_INQUIRY = "vrbo_guest_inquiry"
    VRBO_BOOKING_EVENT = "vrbo_booking_event"
    VRBO_NOTIFICATION = "vrbo_notification"
    DIRECT_WEBSITE_FORM_INQUIRY = "direct_website_form_inquiry"
    DIRECT_WEBSITE_FORM_OTHER = "direct_website_form_other"
    GENERIC_GUEST_EMAIL = "generic_guest_email"
    UNKNOWN = "unknown"
    NON_GUEST = "non_guest"


@dataclass(frozen=True)
class ClassifiedEmailType:
    message_type: MessageType
    reason: str


_BOOKING_EVENT_HEADER_TYPES = {
    "RESERVATION_CONFIRMED",
    "CANCELLED",
    "REMINDER",
}

_INQUIRY_HEADER_TYPES = {
    "NEW_INQUIRY",
    "NEW_BOOKING_REQUEST",
    "INQUIRY",
}

_AIRBNB_BOOKING_EVENT_SUBJECTS = (
    re.compile(r"\bnew booking\b", re.I),
    re.compile(r"\bbooking confirmed\b", re.I),
    re.compile(r"\breservation confirmed\b", re.I),
    re.compile(r"\breservation reminder\b", re.I),
    re.compile(r"\bbooking modified\b", re.I),
    re.compile(r"\btrip changed\b", re.I),
    re.compile(r"\bcanceled:\b", re.I),
    re.compile(r"\breservation canceled\b", re.I),
    re.compile(r"\byou requested money\b", re.I),
)

_AIRBNB_INQUIRY_SUBJECTS = (
    re.compile(r"\breservation request\b", re.I),
    re.compile(r"\binquiry for your (listing|place)\b", re.I),
    re.compile(r"\bquestion about your (listing|place)\b", re.I),
    re.compile(r"\bnew message from\b", re.I),
)

_VRBO_BOOKING_EVENT_SUBJECTS = (
    re.compile(r"\breservation confirmed\b", re.I),
    re.compile(r"\bbooking confirmed\b", re.I),
    re.compile(r"\bbooking modified\b", re.I),
    re.compile(r"\btrip changed\b", re.I),
    re.compile(r"\bcancelled\b", re.I),
    re.compile(r"\bcanceled\b", re.I),
    re.compile(r"\breservation reminder\b", re.I),
    re.compile(r"\bconfirmation code\b", re.I),
)

_VRBO_INQUIRY_SUBJECTS = (
    re.compile(r"\binquiry from .+ - vrbo\b", re.I),
    re.compile(r"\bnew inquiry\b", re.I),
    re.compile(r"\bnew booking request\b", re.I),
    re.compile(r"\bnew message\b", re.I),
)

_DIRECT_OTHER_SUBJECTS = (
    re.compile(r"\bnewsletter\b", re.I),
    re.compile(r"\bsign[\s-]?up\b", re.I),
    re.compile(r"\bsubscribe\b", re.I),
    re.compile(r"\bcontest\b", re.I),
)


class EmailTypeClassifier:
    def classify(
        self,
        *,
        headers: dict,
        subject: str,
        plain_text: str = "",
        raw_html: str = "",
        source_route: InboundSourceRoute,
    ) -> ClassifiedEmailType:
        from_header = (headers.get("From") or headers.get("from") or "").strip()
        header_map = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        ota_message_type = (header_map.get("x-mediated-message-type", "") or "").strip().upper()

        non_guest_match = NON_GUEST_REGISTRY.classify(
            from_header=from_header,
            subject=subject,
            plain_text=plain_text,
            raw_html=raw_html,
        )
        if non_guest_match:
            return ClassifiedEmailType(MessageType.NON_GUEST, non_guest_match.reason)

        if source_route.parser_hint == "direct_website_form":
            lowered_subject = subject or ""
            lowered_body = plain_text or ""
            if self._looks_like_direct_inquiry(plain_text):
                return ClassifiedEmailType(
                    MessageType.DIRECT_WEBSITE_FORM_INQUIRY,
                    "direct_form:inquiry_markers",
                )
            if any(pattern.search(lowered_subject) for pattern in _DIRECT_OTHER_SUBJECTS) or any(
                pattern.search(lowered_body) for pattern in _DIRECT_OTHER_SUBJECTS
            ):
                return ClassifiedEmailType(
                    MessageType.DIRECT_WEBSITE_FORM_OTHER,
                    "direct_form:marketing_or_signup_subject",
                )
            return ClassifiedEmailType(
                MessageType.DIRECT_WEBSITE_FORM_OTHER,
                "direct_form:non_inquiry_shape",
            )

        platform = detect_platform(
            headers,
            subject,
            plain_text=plain_text,
            raw_html=raw_html,
        )
        if platform == "airbnb":
            if ota_message_type in _BOOKING_EVENT_HEADER_TYPES:
                return ClassifiedEmailType(
                    MessageType.AIRBNB_BOOKING_EVENT,
                    f"airbnb:ota_message_type:{ota_message_type}",
                )
            if any(pattern.search(subject or "") for pattern in _AIRBNB_BOOKING_EVENT_SUBJECTS):
                return ClassifiedEmailType(
                    MessageType.AIRBNB_BOOKING_EVENT,
                    "airbnb:subject_booking_event",
                )
            if ota_message_type in _INQUIRY_HEADER_TYPES:
                return ClassifiedEmailType(
                    MessageType.AIRBNB_GUEST_INQUIRY,
                    f"airbnb:ota_message_type:{ota_message_type}",
                )
            if self._looks_like_airbnb_inquiry(from_header, subject):
                return ClassifiedEmailType(
                    MessageType.AIRBNB_GUEST_INQUIRY,
                    "airbnb:stable_inquiry_signal",
                )
            return ClassifiedEmailType(MessageType.UNKNOWN, "airbnb:unclassified")

        if platform == "vrbo":
            if ota_message_type in _BOOKING_EVENT_HEADER_TYPES:
                return ClassifiedEmailType(
                    MessageType.VRBO_BOOKING_EVENT,
                    f"vrbo:ota_message_type:{ota_message_type}",
                )
            if any(pattern.search(subject or "") for pattern in _VRBO_BOOKING_EVENT_SUBJECTS):
                return ClassifiedEmailType(
                    MessageType.VRBO_BOOKING_EVENT,
                    "vrbo:subject_booking_event",
                )
            if ota_message_type in _INQUIRY_HEADER_TYPES:
                return ClassifiedEmailType(
                    MessageType.VRBO_GUEST_INQUIRY,
                    f"vrbo:ota_message_type:{ota_message_type}",
                )
            if self._looks_like_vrbo_inquiry(subject, plain_text):
                return ClassifiedEmailType(
                    MessageType.VRBO_GUEST_INQUIRY,
                    "vrbo:stable_inquiry_signal",
                )
            return ClassifiedEmailType(MessageType.UNKNOWN, "vrbo:unclassified")

        if source_route.parser_hint == "generic":
            if subject.strip() or plain_text.strip():
                return ClassifiedEmailType(MessageType.GENERIC_GUEST_EMAIL, "generic:default_route")
            return ClassifiedEmailType(MessageType.UNKNOWN, "generic:empty_message")

        return ClassifiedEmailType(MessageType.UNKNOWN, f"{source_route.family}:unclassified")

    @staticmethod
    def _looks_like_direct_inquiry(plain_text: str) -> bool:
        lowered = (plain_text or "").lower()
        inquiry_markers = (
            "submitted values are:",
            "comments/questions:",
            "message/comments:",
            "arrival date:",
            "departure date:",
            "listing of interest:",
            "page path:",
            "email:",
        )
        return sum(1 for marker in inquiry_markers if marker in lowered) >= 3

    @staticmethod
    def _looks_like_airbnb_inquiry(from_header: str, subject: str) -> bool:
        lowered_from = (from_header or "").lower()
        return "@reply.airbnb.com" in lowered_from or any(
            pattern.search(subject or "") for pattern in _AIRBNB_INQUIRY_SUBJECTS
        )

    @staticmethod
    def _looks_like_vrbo_inquiry(subject: str, plain_text: str) -> bool:
        body = plain_text or ""
        if any(pattern.search(subject or "") for pattern in _VRBO_INQUIRY_SUBJECTS):
            return True
        lowered = body.lower()
        return any(
            marker in lowered
            for marker in (
                "has sent an additional inquiry",
                "respond to this inquiry",
                "traveler name",
                "message from ",
            )
        )


EMAIL_TYPE_CLASSIFIER = EmailTypeClassifier()
