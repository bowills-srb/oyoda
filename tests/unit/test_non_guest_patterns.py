from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.services.integrations.email_parser_router import parse_structured_inbound_email
from app.services.integrations.non_guest_patterns import NON_GUEST_REGISTRY


def test_registry_classifies_airbnb_review_notification():
    result = NON_GUEST_REGISTRY.classify(
        from_header="Airbnb <automated@airbnb.com>",
        subject="Kimberly wrote you a review",
        plain_text="Open Airbnb to read the review.",
    )

    assert result is not None
    assert result.name == "airbnb_review_notification"
    assert result.reason == "pattern:airbnb_review_notification"


def test_registry_classifies_airbnb_payout_notice():
    result = NON_GUEST_REGISTRY.classify(
        from_header="Airbnb <automated@airbnb.com>",
        subject="We sent a payout of $2,619.40 USD",
        plain_text="Your payout has been sent.",
    )

    assert result is not None
    assert result.name == "airbnb_payout_notice"


def test_registry_classifies_airbnb_support_survey():
    result = NON_GUEST_REGISTRY.classify(
        from_header="Airbnb Support <no-reply@supportmessaging.airbnb.com>",
        subject="We'd love your feedback!",
        plain_text="Please take our survey about your recent support experience.",
    )

    assert result is not None
    assert result.name == "airbnb_support_survey"


def test_registry_classifies_instagram_notification():
    result = NON_GUEST_REGISTRY.classify(
        from_header="Instagram <security@mail.instagram.com>",
        subject="See who followed you",
        plain_text="You have new activity on Instagram.",
    )

    assert result is not None
    assert result.name == "instagram_notification"


def test_registry_classifies_newsletter_signup_form():
    result = NON_GUEST_REGISTRY.classify(
        from_header="Website Form <forms@example.com>",
        subject="Form submission from: Enewsletter Sign Up",
        plain_text="Name: Alex\nEmail: alex@example.com\nNewsletter: yes\nSign Up: yes",
    )

    assert result is not None
    assert result.name == "newsletter_signup_form"


def test_registry_classifies_transactional_order_notification():
    result = NON_GUEST_REGISTRY.classify(
        from_header="lanier@beachhabitats30a.com",
        subject="Order Notification #6GX0C",
        plain_text="A new order notification was generated for your storefront.",
    )

    assert result is not None
    assert result.name == "transactional_order_notification"


def test_registry_classifies_vrbo_support_thread():
    result = NON_GUEST_REGISTRY.classify(
        from_header="Vrbo Support <support_vrbo@vrbo.com>",
        subject="Vrbo 152112740    [ ref:!00DC00PxQg.!500PE0gyQXN:ref ]",
        plain_text="This is a support follow-up from Vrbo regarding your prior ticket.",
    )

    assert result is not None
    assert result.name == "vrbo_support_thread"


def test_registry_does_not_classify_real_airbnb_guest_inquiry():
    result = NON_GUEST_REGISTRY.classify(
        from_header="Airbnb Messages <reply@reply.airbnb.com>",
        subject="Question about your place from Jamie",
        plain_text="Hi, is the pool heated and is parking included for two cars?",
    )

    assert result is None


def test_registry_does_not_classify_real_vrbo_guest_inquiry():
    result = NON_GUEST_REGISTRY.classify(
        from_header="Vrbo <sender@messages.homeaway.com>",
        subject="Inquiry from Jan Hevey: Nov 18 - Dec 2, 2025 - Vrbo #1673198",
        plain_text="Many old reviews. Have you updated and when? Is parking still a problem?",
    )

    assert result is None


def test_registry_does_not_classify_real_vrbo_guest_inquiry_from_message_sender():
    result = NON_GUEST_REGISTRY.classify(
        from_header="Kevin Heskett <sender@messages.homeaway.com>",
        subject="Inquiry from Kevin Heskett: Apr 22 - Apr 26, 2026 - Vrbo #5089865",
        plain_text="We're interested in booking and wanted to confirm parking and beach access.",
    )

    assert result is None


def test_router_drops_registry_match_before_llm_or_fallback():
    captured: list[str] = []

    async def _run():
        return await parse_structured_inbound_email(
            source_message_id="msg-1",
            subject="See who followed you",
            plain_text="You have new activity on Instagram.",
            raw_html="",
            headers={"From": "Instagram <security@mail.instagram.com>"},
            parser=SimpleNamespace(is_non_guest_email=lambda subject, body: False),
            adapt_llm_inquiry=lambda extracted: None,
            adapt_reservation_event=lambda event: None,
            adapt_ota_inquiry=lambda ota: None,
            adapt_direct_inquiry=lambda direct: None,
            adapt_vendor_email=lambda vendor: None,
            fallback_parse=lambda: (_ for _ in ()).throw(AssertionError("fallback should not run")),
            record_non_guest_drop=captured.append,
        )

    parsed = asyncio.run(_run())

    assert parsed is None
    assert captured == ["pattern:instagram_notification"]
