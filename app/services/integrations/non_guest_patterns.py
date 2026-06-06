from __future__ import annotations

from dataclasses import dataclass
from email.utils import parseaddr
import re
from typing import Callable, Optional, Pattern


@dataclass(frozen=True)
class NonGuestEmail:
    from_header: str
    subject: str
    plain_text: str
    raw_html: str = ""

    @property
    def sender_email(self) -> str:
        _, addr = parseaddr(self.from_header or "")
        return (addr or self.from_header or "").strip().lower()

    @property
    def sender_domain(self) -> str:
        sender = self.sender_email
        if "@" not in sender:
            return ""
        return sender.rsplit("@", 1)[1].lower()

    @property
    def body_text(self) -> str:
        return (self.plain_text or self.raw_html or "").strip()

    @property
    def lowered_body_text(self) -> str:
        return self.body_text.lower()


@dataclass(frozen=True)
class ClassificationResult:
    name: str
    reason: str


Matcher = Callable[[NonGuestEmail], bool]


def _compile_many(patterns: tuple[str, ...]) -> tuple[Pattern[str], ...]:
    return tuple(re.compile(pattern, re.I) for pattern in patterns)


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    lowered = (value or "").lower()
    return any(needle.lower() in lowered for needle in needles)


def _matches_any(value: str, patterns: tuple[Pattern[str], ...]) -> bool:
    return any(pattern.search(value or "") for pattern in patterns)


def _sender_domain_any(*domains: str) -> Matcher:
    normalized = tuple(domain.lower() for domain in domains)

    def _match(email: NonGuestEmail) -> bool:
        sender_domain = email.sender_domain
        return any(
            sender_domain == domain or sender_domain.endswith(f".{domain}")
            for domain in normalized
        )

    return _match


def _sender_email_any(*values: str) -> Matcher:
    normalized = tuple(value.lower() for value in values)
    return lambda email: _contains_any(email.sender_email, normalized)


def _sender_any(*matchers: Matcher) -> Matcher:
    return lambda email: any(matcher(email) for matcher in matchers)


def _subject_contains_any(*needles: str) -> Matcher:
    normalized = tuple(needle.lower() for needle in needles)
    return lambda email: _contains_any(email.subject, normalized)


def _subject_matches_any(*patterns: str) -> Matcher:
    compiled = _compile_many(patterns)
    return lambda email: _matches_any(email.subject, compiled)


def _body_contains_any(*needles: str) -> Matcher:
    normalized = tuple(needle.lower() for needle in needles)
    return lambda email: _contains_any(email.lowered_body_text, normalized)


def _body_matches_any(*patterns: str) -> Matcher:
    compiled = _compile_many(patterns)
    return lambda email: _matches_any(email.body_text, compiled)


def _all(*matchers: Matcher) -> Matcher:
    return lambda email: all(matcher(email) for matcher in matchers)


def _not(matcher: Matcher) -> Matcher:
    return lambda email: not matcher(email)


_HAS_GUEST_THREAD_MARKER = _body_matches_any(
    r"\bmessage from [A-Z][a-z]+",
    r"\bguest\b",
    r"\btraveler\b",
    r"\breservation code\b",
    r"\bcheck[- ]in\b",
    r"\bcheck[- ]out\b",
)

_ORDER_NOTIFICATION_SUBJECT = _subject_matches_any(
    r"\border notification\s*#?[A-Z0-9-]+\b",
    r"\border confirmation\s*#?[A-Z0-9-]+\b",
)


@dataclass(frozen=True)
class NonGuestPattern:
    name: str
    matcher: Matcher
    reason: str

    def classify(self, email: NonGuestEmail) -> Optional[ClassificationResult]:
        if not self.matcher(email):
            return None
        return ClassificationResult(name=self.name, reason=self.reason)


class NonGuestRegistry:
    def __init__(self, patterns: tuple[NonGuestPattern, ...]):
        self.patterns = patterns

    def classify(
        self,
        *,
        from_header: str,
        subject: str,
        plain_text: str,
        raw_html: str = "",
    ) -> Optional[ClassificationResult]:
        email = NonGuestEmail(
            from_header=from_header,
            subject=subject,
            plain_text=plain_text,
            raw_html=raw_html,
        )
        for pattern in self.patterns:
            matched = pattern.classify(email)
            if matched:
                return matched
        return None


NON_GUEST_REGISTRY = NonGuestRegistry(
    patterns=(
        NonGuestPattern(
            name="airbnb_review_notification",
            matcher=_all(
                _sender_domain_any("airbnb.com"),
                _subject_contains_any("wrote you a review", "left you a review"),
            ),
            reason="pattern:airbnb_review_notification",
        ),
        NonGuestPattern(
            name="airbnb_review_reminder",
            matcher=_all(
                _sender_domain_any("airbnb.com"),
                _subject_contains_any("write a review for", "days left to write a review"),
            ),
            reason="pattern:airbnb_review_reminder",
        ),
        NonGuestPattern(
            name="airbnb_payout_notice",
            matcher=_all(
                _sender_domain_any("airbnb.com"),
                _subject_contains_any("we sent a payout", "your payout", "payout of"),
            ),
            reason="pattern:airbnb_payout_notice",
        ),
        NonGuestPattern(
            name="airbnb_host_promo",
            matcher=_all(
                _sender_domain_any("airbnb.com"),
                _subject_contains_any(
                    "connect with nearby hosts",
                    "host club",
                    "host meetup",
                    "superhost",
                ),
            ),
            reason="pattern:airbnb_host_promo",
        ),
        NonGuestPattern(
            name="airbnb_support_survey",
            matcher=_all(
                _sender_any(
                    _sender_domain_any("airbnb.com"),
                    _sender_email_any("supportmessaging.airbnb.com"),
                ),
                _subject_contains_any("we'd love your feedback", "survey", "rate your support"),
            ),
            reason="pattern:airbnb_support_survey",
        ),
        NonGuestPattern(
            name="airbnb_support_thread",
            matcher=_all(
                _sender_any(
                    _sender_email_any("supportmessaging.airbnb.com", "resolutions@airbnb.com"),
                    _sender_domain_any("airbnb.com"),
                ),
                _subject_contains_any("airbnb support"),
                _not(_HAS_GUEST_THREAD_MARKER),
            ),
            reason="pattern:airbnb_support_thread",
        ),
        NonGuestPattern(
            name="airbnb_marketing",
            matcher=_all(
                _sender_any(
                    _sender_email_any("automated@airbnb.com", "community@airbnb.com"),
                    _sender_domain_any("mail.airbnb.com"),
                ),
                _subject_contains_any("host tips", "hosting update", "community", "airbnb update"),
            ),
            reason="pattern:airbnb_marketing",
        ),
        NonGuestPattern(
            name="airbnb_co_host_invite",
            matcher=_all(
                _sender_domain_any("airbnb.com"),
                _subject_contains_any("co-host", "cohost"),
            ),
            reason="pattern:airbnb_co_host_invite",
        ),
        NonGuestPattern(
            name="vrbo_marketing",
            matcher=_all(
                _sender_any(
                    _sender_domain_any("vrbo.com", "homeaway.com"),
                    _sender_email_any("no-reply", "noreply"),
                ),
                _subject_contains_any(
                    "discover",
                    "plan your next trip",
                    "vacation inspiration",
                    "traveler newsletter",
                ),
            ),
            reason="pattern:vrbo_marketing",
        ),
        NonGuestPattern(
            name="vrbo_milestone",
            matcher=_all(
                _sender_domain_any("vrbo.com", "homeaway.com"),
                _subject_contains_any("congratulations", "milestone", "achievement", "you did it"),
            ),
            reason="pattern:vrbo_milestone",
        ),
        NonGuestPattern(
            name="vrbo_review_notification",
            matcher=_all(
                _sender_domain_any("vrbo.com", "homeaway.com"),
                _subject_contains_any("review", "traveler rated", "guest rated"),
            ),
            reason="pattern:vrbo_review_notification",
        ),
        NonGuestPattern(
            name="vrbo_payout_notice",
            matcher=_all(
                _sender_domain_any("vrbo.com", "homeaway.com"),
                _subject_contains_any("payout", "payment sent", "payment on the way"),
            ),
            reason="pattern:vrbo_payout_notice",
        ),
        NonGuestPattern(
            name="vrbo_account_update",
            matcher=_all(
                _sender_domain_any("vrbo.com", "homeaway.com"),
                _subject_contains_any("account update", "password reset", "verify your email", "security alert"),
            ),
            reason="pattern:vrbo_account_update",
        ),
        NonGuestPattern(
            name="vrbo_support_thread",
            matcher=_all(
                _sender_email_any("support_vrbo@vrbo.com", "support@vrbo.com"),
                _subject_matches_any(r"^vrbo\s+\d+", r"\[ ref:"),
                _not(_HAS_GUEST_THREAD_MARKER),
            ),
            reason="pattern:vrbo_support_thread",
        ),
        NonGuestPattern(
            name="instagram_notification",
            matcher=_sender_domain_any("instagram.com", "mail.instagram.com"),
            reason="pattern:instagram_notification",
        ),
        NonGuestPattern(
            name="facebook_notification",
            matcher=_sender_domain_any("facebookmail.com", "facebook.com"),
            reason="pattern:facebook_notification",
        ),
        NonGuestPattern(
            name="linkedin_notification",
            matcher=_sender_domain_any("linkedin.com"),
            reason="pattern:linkedin_notification",
        ),
        NonGuestPattern(
            name="twitter_notification",
            matcher=_sender_domain_any("twitter.com", "x.com"),
            reason="pattern:twitter_notification",
        ),
        NonGuestPattern(
            name="newsletter_signup_form",
            matcher=_all(
                _subject_matches_any(r"\bform submission\b", r"\bnewsletter\b", r"\bsign[ -]?up\b"),
                _body_contains_any("newsletter", "sign up", "subscribe"),
            ),
            reason="pattern:newsletter_signup_form",
        ),
        NonGuestPattern(
            name="contest_entry",
            matcher=_all(
                _subject_contains_any("contest", "sweepstakes", "giveaway"),
                _body_contains_any("entry", "subscribe", "winner"),
            ),
            reason="pattern:contest_entry",
        ),
        NonGuestPattern(
            name="generic_contact_form",
            matcher=_all(
                _subject_contains_any("contact form", "form submission"),
                _body_matches_any(r"\bphone\b", r"\bemail\b"),
                _not(_body_matches_any(r"\bcheck[- ]?in\b", r"\bcheck[- ]?out\b", r"\bguests?\b", r"\bmessage\b")),
            ),
            reason="pattern:generic_contact_form",
        ),
        NonGuestPattern(
            name="noreply_marketing",
            matcher=_all(
                _sender_email_any("no-reply", "noreply", "do-not-reply", "donotreply"),
                _subject_contains_any("newsletter", "sale", "promo", "offer", "unsubscribe"),
            ),
            reason="pattern:noreply_marketing",
        ),
        NonGuestPattern(
            name="transactional_only",
            matcher=_all(
                _sender_email_any("no-reply", "noreply", "do-not-reply", "donotreply"),
                _subject_contains_any("password reset", "verify your email", "account verification", "security code"),
            ),
            reason="pattern:transactional_only",
        ),
        NonGuestPattern(
            name="transactional_order_notification",
            matcher=_all(
                _ORDER_NOTIFICATION_SUBJECT,
                _sender_any(
                    _sender_email_any("beachhabitats30a.com", "shopify", "order", "receipt", "notifications"),
                    _sender_domain_any("shopify.com"),
                ),
                _not(_HAS_GUEST_THREAD_MARKER),
            ),
            reason="pattern:transactional_order_notification",
        ),
    )
)
