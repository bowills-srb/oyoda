from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.services.integrations.email_parser_router as router_module
from app.services.integrations.email_parser_router import parse_structured_inbound_email
from app.services.integrations.llm_email_extractor import LLMEmailExtractor


class _ScalarOneOrNoneResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.mark.asyncio
async def test_router_routes_airbnb_booking_event_without_llm(monkeypatch):
    async def _unexpected_llm(*args, **kwargs):
        raise AssertionError("LLM should not run for booking events")

    monkeypatch.setattr(LLMEmailExtractor, "extract", _unexpected_llm)

    parsed = await parse_structured_inbound_email(
        source_message_id="msg-booking",
        subject="Reservation confirmed - Amy McDonald arrives Jun 19",
        plain_text="""
NEW BOOKING CONFIRMED! AMY ARRIVES JUN 19.

https://www.airbnb.com/hosting/reservations/details/HM8TTMFW9A?isPending=true   Amy McDonald

Send Amy a Message
[https://www.airbnb.com/hosting/thread/2507239446?thread_type=home_booking]

https://www.airbnb.com/rooms/1571939770441752742

CASA BLANCO | ROSEMARY 8BD LUXURY + PRIVATE POOL

CONFIRMATION CODE
HM8TTMFW9A
""",
        raw_html="",
        headers={"From": "Airbnb <automated@airbnb.com>"},
        parser=SimpleNamespace(is_non_guest_email=lambda subject, body: False),
        adapt_llm_inquiry=lambda extracted: None,
        adapt_reservation_event=lambda event: SimpleNamespace(
            body=event.summary_text or "",
            source="reservation_event",
            system_event_type=event.system_event_type,
        ),
        adapt_ota_inquiry=lambda ota: None,
        adapt_direct_inquiry=lambda direct: None,
        adapt_vendor_email=lambda vendor: None,
        fallback_parse=lambda: (_ for _ in ()).throw(AssertionError("fallback should not run")),
    )

    assert parsed is not None
    assert parsed.source == "reservation_event"
    assert parsed.system_event_type == "reservation_confirmed"


@pytest.mark.asyncio
async def test_router_prefers_llm_for_direct_form_inquiry(monkeypatch):
    async def _fake_llm(self, **kwargs):
        return SimpleNamespace(
            latest_guest_message="Hi we have a large group potentially coming! Are you allowed to purchase extra wrist bands?",
            parser_source="llm_email_extractor_groq",
        )

    monkeypatch.setattr(LLMEmailExtractor, "extract", _fake_llm)

    parsed = await parse_structured_inbound_email(
        source_message_id="msg-direct",
        subject="116 W Summersweet Lane (Santa Rosa Beach, FL - 32459)",
        plain_text="""
Submitted on Thursday, April 23, 2026 - 08:14
Submitted values are:

Email: morgan_childress@yahoo.com
Arrival Date: Tue, 09/01/2026
Departure Date: Sun, 09/06/2026
Adults: 6
Children: 10
Comments/Questions: Hi we have a large group potentially coming! Are you allowed to purchase extra wrist bands?
Listing of Interest: 116 W Summersweet Lane
Page Path: /30a-vacation-rentals/116-w-summersweet-lane
""",
        raw_html="",
        headers={
            "From": '"morgan_childress@yahoo.com via Beach Habitats 30A" <lanier@beachhabitats30a.com>',
            "Reply-To": "morgan_childress@yahoo.com",
            "X-Mailer": "Drupal Webform",
        },
        parser=SimpleNamespace(is_non_guest_email=lambda subject, body: False),
        adapt_llm_inquiry=lambda extracted: SimpleNamespace(
            body=extracted.latest_guest_message,
            source=extracted.parser_source,
        ),
        adapt_reservation_event=lambda event: None,
        adapt_ota_inquiry=lambda ota: None,
        adapt_direct_inquiry=lambda direct: (_ for _ in ()).throw(
            AssertionError("deterministic direct parser should not run before the LLM")
        ),
        adapt_vendor_email=lambda vendor: None,
        fallback_parse=lambda: (_ for _ in ()).throw(AssertionError("fallback should not run")),
    )

    assert parsed is not None
    assert parsed.source == "llm_email_extractor_groq"


@pytest.mark.asyncio
async def test_router_routes_generic_guest_email_to_llm(monkeypatch):
    async def _fake_llm(self, **kwargs):
        return SimpleNamespace(latest_guest_message="Hi, is parking included?", parser_source="llm_email_extractor_groq")

    monkeypatch.setattr(LLMEmailExtractor, "extract", _fake_llm)

    parsed = await parse_structured_inbound_email(
        source_message_id="msg-generic",
        subject="Question about parking",
        plain_text="Hi, is parking included?",
        raw_html="",
        headers={"From": "Taylor <taylor@example.com>"},
        parser=SimpleNamespace(is_non_guest_email=lambda subject, body: False),
        adapt_llm_inquiry=lambda extracted: SimpleNamespace(
            body=extracted.latest_guest_message,
            source=extracted.parser_source,
        ),
        adapt_reservation_event=lambda event: None,
        adapt_ota_inquiry=lambda ota: None,
        adapt_direct_inquiry=lambda direct: None,
        adapt_vendor_email=lambda vendor: None,
        fallback_parse=lambda: None,
    )

    assert parsed is not None
    assert parsed.source == "llm_email_extractor_groq"


@pytest.mark.asyncio
async def test_router_hands_direct_reply_thread_to_llm_instead_of_deterministic_parser(monkeypatch):
    async def _fake_llm(self, **kwargs):
        return SimpleNamespace(
            latest_guest_message="Question about our stay at 90 Mystic Cobalt, are we able to bring a small dog?",
            parser_source="llm_email_extractor_groq",
        )

    monkeypatch.setattr(LLMEmailExtractor, "extract", _fake_llm)

    parsed = await parse_structured_inbound_email(
        source_message_id="msg-direct-thread",
        subject="Re: 90 Mystic Cobalt St (Santa Rosa Beach, FL - 32459)",
        plain_text="""
Question about our stay at 90 Mystic Cobalt, are we able to bring a small dog?

On Tue, Apr 14, 2026 at 2:28 PM Info Info <info@beachhabitats30a.com> wrote:
> Yes Ma’am. Both rooms with bunk beds have a door.
>
> > Submitted on Tuesday, April 14, 2026 - 13:56
> > Comments/Questions:
> > Is there a door to the room with the bunk beds?
> > Listing of Interest: 90 Mystic Cobalt St
""",
        raw_html="",
        headers={
            "From": "Gina Taverna <taverna1313@gmail.com>",
            "To": "Info Info <info@beachhabitats30a.com>",
        },
        parser=SimpleNamespace(is_non_guest_email=lambda subject, body: False),
        adapt_llm_inquiry=lambda extracted: SimpleNamespace(
            body=extracted.latest_guest_message,
            source=extracted.parser_source,
        ),
        adapt_reservation_event=lambda event: None,
        adapt_ota_inquiry=lambda ota: None,
        adapt_direct_inquiry=lambda direct: (_ for _ in ()).throw(
            AssertionError("deterministic direct parser should not claim reply-thread shapes")
        ),
        adapt_vendor_email=lambda vendor: None,
        fallback_parse=lambda: None,
    )

    assert parsed is not None
    assert parsed.source == "llm_email_extractor_groq"


@pytest.mark.asyncio
async def test_router_skips_legacy_airbnb_parser_and_uses_llm(monkeypatch):
    async def _fake_llm(self, **kwargs):
        return SimpleNamespace(
            latest_guest_message="Curious if there is an option for a later check out on Monday",
            parser_source="llm_email_extractor_groq",
        )

    def _unexpected_ota_parser(*args, **kwargs):
        raise AssertionError("legacy Airbnb parser should not run")

    monkeypatch.setattr(LLMEmailExtractor, "extract", _fake_llm)
    monkeypatch.setattr(router_module, "parse_ota_inquiry", _unexpected_ota_parser)

    parsed = await parse_structured_inbound_email(
        source_message_id="msg-airbnb-llm",
        subject="RE: Reservation for Watercolor Cottage | 4 Bd + 4 bikes + Resort, Sep 4 - 7",
        plain_text="Curious if there is an option for a later check out on Monday",
        raw_html="<html><body><p>Curious if there is an option for a later check out on Monday</p></body></html>",
        headers={"From": "Airbnb <express@airbnb.com>"},
        parser=SimpleNamespace(is_non_guest_email=lambda subject, body: False),
        adapt_llm_inquiry=lambda extracted: SimpleNamespace(
            body=extracted.latest_guest_message,
            source=extracted.parser_source,
        ),
        adapt_reservation_event=lambda event: None,
        adapt_ota_inquiry=lambda ota: None,
        adapt_direct_inquiry=lambda direct: None,
        adapt_vendor_email=lambda vendor: None,
        fallback_parse=lambda: None,
    )

    assert parsed is not None
    assert parsed.source == "llm_email_extractor_groq"


@pytest.mark.asyncio
async def test_router_prefers_llm_for_vrbo_guest_inquiry(monkeypatch):
    async def _fake_llm(self, **kwargs):
        return SimpleNamespace(
            latest_guest_message="Hello! Can you please explain the layout of the condo? One of the reviews says it’s on the third floor and one of the bathrooms are on the bottom floor near a game room?",
            parser_source="llm_email_extractor_groq",
        )

    monkeypatch.setattr(LLMEmailExtractor, "extract", _fake_llm)

    plain_text = """
Property
External ID 2403-268707 #4300735
Unit
unit_4874905
Dates
Jun 9 - Jun 14, 2026, 5 nights
Guests
2 adults

Further info
Hello! Can you please explain the layout of the condo? One of the reviews says it’s on the third floor and one of the bathrooms are on the bottom floor near a game room?
Respond to this Inquiry
"""

    parsed = await parse_structured_inbound_email(
        source_message_id="msg-vrbo-melanie",
        subject="Inquiry from Melanie Tarbush: Jun 9 - Jun 14, 2026 - Vrbo #4300735",
        plain_text=plain_text,
        raw_html="",
        headers={
            "From": "Vrbo <messaging@messages.vrbo.com>",
            "Reply-To": "inquiry@messages.homeaway.com",
            "X-Mediated-Site": "vrbo",
            "X-Mediated-Message-Type": "INQUIRY",
        },
        parser=SimpleNamespace(is_non_guest_email=lambda subject, body: False),
        adapt_llm_inquiry=lambda extracted: SimpleNamespace(
            body=extracted.latest_guest_message,
            source=extracted.parser_source,
        ),
        adapt_reservation_event=lambda event: None,
        adapt_ota_inquiry=lambda ota: (_ for _ in ()).throw(
            AssertionError("deterministic OTA parser should not run before the LLM")
        ),
        adapt_direct_inquiry=lambda direct: None,
        adapt_vendor_email=lambda vendor: None,
        fallback_parse=lambda: (_ for _ in ()).throw(AssertionError("fallback should not run")),
    )

    assert parsed is not None
    assert parsed.source == "llm_email_extractor_groq"


@pytest.mark.asyncio
async def test_router_falls_back_to_direct_parser_when_llm_chain_declines(monkeypatch):
    from app.services.integrations.llm_email_extractor import LLMEmailExtractorFallback

    async def _llm_declines(self, **kwargs):
        raise LLMEmailExtractorFallback("no_keys_configured")

    monkeypatch.setattr(LLMEmailExtractor, "extract", _llm_declines)

    parsed = await parse_structured_inbound_email(
        source_message_id="msg-direct-fallback",
        subject="116 W Summersweet Lane (Santa Rosa Beach, FL - 32459)",
        plain_text="""
Submitted on Thursday, April 23, 2026 - 08:14
Submitted values are:

Email: morgan_childress@yahoo.com
Arrival Date: Tue, 09/01/2026
Departure Date: Sun, 09/06/2026
Adults: 6
Children: 10
Comments/Questions: Hi we have a large group potentially coming! Are you allowed to purchase extra wrist bands?
Listing of Interest: 116 W Summersweet Lane
Page Path: /30a-vacation-rentals/116-w-summersweet-lane
""",
        raw_html="",
        headers={
            "From": '"morgan_childress@yahoo.com via Beach Habitats 30A" <lanier@beachhabitats30a.com>',
            "Reply-To": "morgan_childress@yahoo.com",
            "X-Mailer": "Drupal Webform",
        },
        parser=SimpleNamespace(is_non_guest_email=lambda subject, body: False),
        adapt_llm_inquiry=lambda extracted: None,
        adapt_reservation_event=lambda event: None,
        adapt_ota_inquiry=lambda ota: None,
        adapt_direct_inquiry=lambda direct: SimpleNamespace(
            body=direct.message_body or "",
            source="direct_parser",
            guest_email=direct.guest_email,
        ),
        adapt_vendor_email=lambda vendor: None,
        fallback_parse=lambda: (_ for _ in ()).throw(AssertionError("fallback should not run")),
    )

    assert parsed is not None
    assert parsed.source == "direct_parser"
    assert parsed.guest_email == "morgan_childress@yahoo.com"


@pytest.mark.asyncio
async def test_router_uses_injected_llm_extractor_factory(monkeypatch):
    async def _unexpected_llm(*args, **kwargs):
        raise AssertionError("default LLM extractor should not run in dry-run replay")

    class _DryRunExtractor:
        async def extract(self, **kwargs):
            return SimpleNamespace(
                latest_guest_message="Dry-run route preview",
                parser_source="dryrun_llm_route_only_groq",
            )

    monkeypatch.setattr(LLMEmailExtractor, "extract", _unexpected_llm)

    parsed = await parse_structured_inbound_email(
        source_message_id="msg-dryrun",
        subject="Question about check-in",
        plain_text="Could we check in a little early?",
        raw_html="",
        headers={"From": "Jamie <jamie@example.com>"},
        parser=SimpleNamespace(is_non_guest_email=lambda subject, body: False),
        adapt_llm_inquiry=lambda extracted: SimpleNamespace(
            body=extracted.latest_guest_message,
            source=extracted.parser_source,
        ),
        adapt_reservation_event=lambda event: None,
        adapt_ota_inquiry=lambda ota: None,
        adapt_direct_inquiry=lambda direct: None,
        adapt_vendor_email=lambda vendor: None,
        fallback_parse=lambda: None,
        llm_extractor_factory=_DryRunExtractor,
    )

    assert parsed is not None
    assert parsed.source == "dryrun_llm_route_only_groq"


@pytest.mark.asyncio
async def test_router_drops_dynamic_prefilter_override_before_llm(monkeypatch):
    async def _unexpected_llm(*args, **kwargs):
        raise AssertionError("LLM should not run for dynamic drop override")

    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=_ScalarOneOrNoneResult(
                {
                    "inbound_prefilter_drop_overrides": [
                        {
                            "name": "billing_payout",
                            "sender_domain": "example.com",
                            "subject_contains": "payout",
                        }
                    ]
                }
            )
        )
    )
    drops: list[str] = []
    monkeypatch.setattr(LLMEmailExtractor, "extract", _unexpected_llm)

    parsed = await parse_structured_inbound_email(
        source_message_id="msg-billing",
        subject="Monthly payout summary for your account",
        plain_text="Thanks for your payment.",
        raw_html="",
        headers={"From": "ops@billing.example.com"},
        parser=SimpleNamespace(is_non_guest_email=lambda subject, body: False),
        adapt_llm_inquiry=lambda extracted: None,
        adapt_reservation_event=lambda event: None,
        adapt_ota_inquiry=lambda ota: None,
        adapt_direct_inquiry=lambda direct: None,
        adapt_vendor_email=lambda vendor: None,
        fallback_parse=lambda: (_ for _ in ()).throw(AssertionError("fallback should not run")),
        tenant_id="11111111-1111-1111-1111-111111111111",
        db=db,
        record_non_guest_drop=drops.append,
    )

    assert parsed is None
    assert drops == ["override:billing_payout"]
