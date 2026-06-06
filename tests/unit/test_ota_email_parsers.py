from app.services.integrations.ota_email_parsers import parse_ota_inquiry
from app.services.integrations.message_source_detection import detect_platform


def test_parse_vrbo_plain_text_reply_thread_fallback_extracts_latest_guest_message():
    subject = "Re: Inquiry from Jan Hevey: Nov 18 - Dec 2, 2025 - Vrbo #1673198"
    plain_text = """
Hi Jan,

The laundry is on the main floor.

On Tue, Sep 30, 2025 at 11:24 AM Jan Hevey <sender@messages.homeaway.com> wrote:

> Vrbo: Jan Hevey has replied to your message
>
> Jan Hevey has sent an additional inquiry
>
> Property
> External ID 2403-165151
> #1673198
>
> Unit
> unit_2234599
>
> Dates
> Nov 18 - Dec 2, 2025, 14 nights
>
> Guests
> 2 adults, 0 children
>
> Traveler Name
> Jan Hevey
>
> Inquiry from
> Vrbo
>
> Message from Jan Hevey
>
> Many old reviews. Have you updated and when? Is parking still a problem?
>
> Respond to this Inquiry
"""
    parsed = parse_ota_inquiry(
        raw_html="",
        headers={"From": "Info Info <info@beachhabitats30a.com>"},
        subject=subject,
        plain_text=plain_text,
    )

    assert parsed is not None
    assert parsed.parser_source == "ota_parser_vrbo_plain"
    assert parsed.guest_name == "Jan Hevey"
    assert parsed.platform_listing_id == "1673198"
    assert parsed.platform_unit_id == "unit_2234599"
    assert parsed.source_account_id == "2403"
    assert parsed.source_property_id == "165151"
    assert parsed.provider_account_id == "2403"
    assert parsed.provider_property_id == "165151"
    assert parsed.message_body == "Many old reviews. Have you updated and when? Is parking still a problem?"


def test_parse_ota_inquiry_uses_market_extensions_for_asks():
    subject = "Inquiry from Zachary Eckels: Apr 5 - Apr 12, 2026 - Vrbo #3836644"
    plain_text = """
Property
External ID 2403-259874
#3836644

Unit
unit_4410789

Dates
Apr 5 - Apr 12, 2026, 7 nights

Guests
10 adults, 0 children

Traveler Name
Zachary Eckels

Message from Zachary Eckels

Hello! Are we allowed to bring our own beach chairs and umbrella or do we need to rent them?
"""
    parsed = parse_ota_inquiry(
        raw_html="",
        headers={"From": "Zachary Eckels <sender@messages.homeaway.com>"},
        subject=subject,
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert "beach_service" in parsed.asks


def test_parse_vrbo_guest_reply_notification_extracts_latest_turn_and_interaction_id():
    subject = "Inquiry from Pamela Herrmann: Mar 16 - Mar 23, 2027 - Vrbo #2146601"
    plain_text = """
Vrbo: Pamela Herrmann has replied to your message

Unfortunately our youngest will be 5 that time. Do the owners of this home have an extra few bands?
I'm just so confused why this house accommodates 16 but can't supply 16 bands.

Respond to this Inquiry
https://www.vrbo.com/supply/interaction?interactionId=591254c8-d232-4906-a552-91b3f6207bb9&propertyId=61496307
"""
    parsed = parse_ota_inquiry(
        raw_html="",
        headers={"From": "Pamela Herrmann <sender@messages.homeaway.com>"},
        subject=subject,
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.sender_role == "guest"
    assert parsed.thread_event_type == "guest_reply"
    assert parsed.guest_name == "Pamela Herrmann"
    assert parsed.source_interaction_id == "591254c8-d232-4906-a552-91b3f6207bb9"
    assert parsed.source_property_id == "61496307"
    assert "extra few bands" in (parsed.latest_guest_turn or "")


def test_parse_vrbo_operator_reply_extracts_operator_turn_and_original_guest_turn():
    subject = "Re: Inquiry from Pamela Herrmann: Mar 16 - Mar 23, 2027 - Vrbo #2146601"
    plain_text = """
Hi Pamela,
We are unable to request additional bands based on Watercolors HOA policy. However, guests 5 and under do not require a wristband.
Best,
Beach Habitats 30A

> On Apr 24, 2026, at 9:30 AM, Pamela Herrmann <sender@messages.homeaway.com> wrote:
>
> Message from Pamela Herrmann
>
> I would love to book your beautiful home. I would have a party of 16. Is it possible to get 2 extra wristbands so we can all go to the beach and pools together? Thank you
>
> Respond to this Inquiry
> https://www.vrbo.com/supply/interaction?interactionId=591254c8-d232-4906-a552-91b3f6207bb9&propertyId=61496307
"""
    parsed = parse_ota_inquiry(
        raw_html="",
        headers={
            "From": "Info Info <info@beachhabitats30a.com>",
            "To": "Pamela Herrmann <37bb05ca-f5d5-4f91-b1af-4fefb66d3cc7@messages.homeaway.com>",
        },
        subject=subject,
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.sender_role == "operator"
    assert parsed.thread_event_type == "operator_reply"
    assert "unable to request additional bands" in (parsed.latest_operator_turn or "").lower()
    assert "party of 16" in (parsed.latest_guest_turn or "").lower()
    assert parsed.reply_channel_address == "37bb05ca-f5d5-4f91-b1af-4fefb66d3cc7@messages.homeaway.com"


def test_parse_adrienne_inquiry_detects_event_and_policy_asks():
    subject = "Inquiry from Adrienne Wallace: Jul 30 - Aug 2, 2026 - Vrbo #2174163"
    plain_text = """
Property
External ID 2403-207686
#2174163

Unit
unit_2738699

Dates
Jul 30 - Aug 2, 2026, 3 nights

Guests
14 adults, 2 children

Traveler Name
Adrienne Wallace

Message from Adrienne Wallace

Hello, my family is local to Lynn Haven/ Panama City area and we are looking for a place to end the summer and celebrate our daughter's recent engagement. Is this allowed at your place?
"""
    parsed = parse_ota_inquiry(
        raw_html="",
        headers={"From": "Adrienne Wallace <sender@messages.homeaway.com>"},
        subject=subject,
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert "group_or_event" in parsed.asks
    assert "event_policy" in parsed.asks
    assert "house_rules" in parsed.asks


def test_parse_reservation_reply_detects_pre_arrival_stage_and_multiple_intents():
    subject = "Reservation from Deborah Korte: Apr 27 - May 1, 2026 - Vrbo #1416282"
    plain_text = """
Vrbo: Deborah Korte has replied to your message

Have some questions about checking in and the pool

https://www.vrbo.com/supply/interaction?interactionId=f24444e0-49ca-4cf9-ac2f-3cf25832a6c6&propertyId=29622096
"""
    parsed = parse_ota_inquiry(
        raw_html="",
        headers={"From": "Deborah Korte <sender@messages.homeaway.com>"},
        subject=subject,
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.lifecycle_stage == "pre_arrival"
    assert parsed.thread_event_type == "guest_reply"
    assert "check_in_process" in parsed.asks
    assert "pool_access" in parsed.asks


def test_parse_vrbo_initial_inquiry_plain_text_uses_further_info_and_reply_to():
    subject = "Inquiry from Misty Kettinger: Vrbo #3350889"
    plain_text = """
Hello, Misty Kettinger is interested in your property.


Property:
        External ID 2403-250642
        #3350889
Unit:
        unit_3924014
Guests:
        2 adults, 0 children
Traveler Name:
        Misty Kettinger
Traveler Phone:
        Available when booked
Inquiry from:
        Vrbo
        https://www.vrbo.com


Further info

Hi, we are checking in on May 16. I was wondering if early check in is a possibility. We will be driving all night and will likely arrive earlier in the day. Thank you

Respond to this Inquiry

https://www.vrbo.com/supply/interaction?interactionId=920c8885-8c1c-49ba-802f-d48b8a1e6b0e&propertyId=92850506
"""
    parsed = parse_ota_inquiry(
        raw_html="",
        headers={
            "From": "Misty Kettinger <sender@messages.homeaway.com>",
            "To": "Beach Habitats 30A <info@beachhabitats30a.com>",
            "Reply-To": "Misty Kettinger <ae0c9666-0b0b-4dcc-b602-0ab410680720@messages.homeaway.com>",
        },
        subject=subject,
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.parser_source == "ota_parser_vrbo_plain"
    assert parsed.guest_name == "Misty Kettinger"
    assert parsed.platform_listing_id == "3350889"
    assert parsed.platform_unit_id == "unit_3924014"
    assert parsed.reply_channel_address == "ae0c9666-0b0b-4dcc-b602-0ab410680720@messages.homeaway.com"
    assert parsed.guest_email == "ae0c9666-0b0b-4dcc-b602-0ab410680720@messages.homeaway.com"
    assert parsed.message_body.startswith("Hi, we are checking in on May 16.")
    assert "early_check_in" in parsed.asks


def test_parse_airbnb_reservation_message_extracts_canonical_ota_fields():
    subject = "RE: Reservation for Upscale Seacrest Condo| Deeded Beach + Lagoon Pool, Apr 22 – 27"
    plain_text = """
RESERVATION FOR UPSCALE SEACREST CONDO| DEEDED BEACH + LAGOON POOL, APR 22 – 27

For your protection and safety, always communicate through Airbnb.

   JANET

   Booker

   Hi! What is the house number and address? Trying to fill out
   paperwork for parking and pool passes

Reply
[https://www.airbnb.com/hosting/thread/2397644153?thread_type=home_booking&inbox_type=host]

You can also respond by replying directly to this email.

https://www.airbnb.com/rooms/1517430821577472766

UPSCALE SEACREST CONDO| DEEDED BEACH + LAGOON POOL

Check-in         Checkout
April 22, 2026   April 27, 2026

GUESTS
2 adults, 2 children
"""
    parsed = parse_ota_inquiry(
        raw_html="",
        headers={
            "From": "Airbnb <express@airbnb.com>",
            "Reply-To": "4jc2cyol1ggu2mxr73zajj07tr7k80b9yerw@reply.airbnb.com",
        },
        subject=subject,
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.platform == "airbnb"
    assert parsed.lifecycle_stage == "pre_arrival"
    assert parsed.reply_channel_address == "4jc2cyol1ggu2mxr73zajj07tr7k80b9yerw@reply.airbnb.com"


def test_parse_airbnb_initial_inquiry_template_extracts_guest_message_and_dates():
    subject = "Inquiry for Incredible Updated 4 Bedroom Park District Home | for Jul 3 – 11, 2026"
    plain_text = """
RESPOND TO JULIE'S INQUIRY

Julie

Identity verified · 9 reviews

Dallas, TX

Hi! I was trying to figure out where the bunk beds are? I didn’t see them in the pictures

Pre-approve / DeclinePre-approve / Decline
[https://www.airbnb.com/hosting/thread/2494359957?thread_type=home_booking]

https://www.airbnb.com/rooms/1608144533104721279

INCREDIBLE UPDATED 4 BEDROOM PARK DISTRICT HOME |

Check-in     Checkout

Fri, Jul 3   Sat, Jul 11

GUESTS

1 adult, 3 children
"""
    parsed = parse_ota_inquiry(
        raw_html="",
        headers={"From": "Airbnb <automated@airbnb.com>"},
        subject=subject,
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.platform == "airbnb"
    assert parsed.parser_source == "ota_parser_airbnb_plain"
    assert parsed.lifecycle_stage == "pre_booking"
    assert parsed.guest_name == "Julie"
    assert parsed.platform_listing_id == "1608144533104721279"
    assert parsed.source_interaction_id == "2494359957"
    assert parsed.property_name_hint == "Incredible Updated 4 Bedroom Park District Home"
    assert parsed.check_in is not None
    assert parsed.check_in.month == 7
    assert parsed.check_in.day == 3
    assert parsed.check_out is not None
    assert parsed.check_out.month == 7
    assert parsed.check_out.day == 11
    assert parsed.guests_adults == 1
    assert parsed.guests_children == 3
    assert "bunk beds" in (parsed.message_body or "").lower()


def test_parse_airbnb_initial_inquiry_subject_variant_extracts_property_and_checkout_intent():
    subject = "Inquiry for Sun Kissed | Pool, Bikes, Prime Seagrove Location for Aug 20 – 23, 2026"
    plain_text = """
RESPOND TO KRISTI'S INQUIRY

Kristi

Identity verified · 5 reviews

Denver, CO

Hi! I’m looking to book for my bachelorette and curious if there’s anyway to get a later checkout than 9 am on Sunday?
It would be hard for us to all make that work with our flights

Pre-approve / DeclinePre-approve / Decline
[https://www.airbnb.com/hosting/thread/2493941464?thread_type=home_booking]

https://www.airbnb.com/rooms/1517439658215941054

SUN KISSED | POOL, BIKES, PRIME SEAGROVE LOCATION

Check-in      Checkout

Thu, Aug 20   Sun, Aug 23

GUESTS

1 adult
"""
    parsed = parse_ota_inquiry(
        raw_html="",
        headers={"From": "Airbnb <automated@airbnb.com>"},
        subject=subject,
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.property_name_hint == "Sun Kissed | Pool, Bikes, Prime Seagrove Location"
    assert parsed.guest_name == "Kristi"
    assert parsed.platform_listing_id == "1517439658215941054"
    assert parsed.source_interaction_id == "2493941464"
    assert "later checkout" in (parsed.message_body or "").lower()
    assert "late_checkout" in parsed.asks
    assert "group_or_event" in parsed.asks


def test_parse_vrbo_guest_declared_booked_upgrades_lifecycle():
    subject = "Inquiry from Ryan Ballheimer: Jul 11 - Jul 16, 2026 - Vrbo #4934657"
    plain_text = """
Vrbo: Ryan Ballheimer has replied to your message

just booked - any recs on how to rent / who for beach chairs / umbrellas?
"""
    parsed = parse_ota_inquiry(
        raw_html="",
        headers={"From": "Ryan Ballheimer <sender@messages.homeaway.com>"},
        subject=subject,
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.lifecycle_stage == "pre_arrival"
    assert "lifecycle:guest_declared_booked" in parsed.extraction_notes
    assert parsed.platform_listing_id == "4934657"
    assert parsed.guest_name == "Ryan Ballheimer"
    assert "just booked" in (parsed.latest_guest_turn or "").lower()


def test_detect_platform_uses_vrbo_body_markers_when_headers_are_generic():
    plain_text = """
Ginny Stehling has sent an additional inquiry

Property
External ID 2403-228842
#2541521

Unit
unit_3111576

Further info

Good morning this is Property comes with the golf cart?

We're here to help. Visit our Help Centre for useful info and FAQs.
"""
    detected = detect_platform(
        headers={"From": "forwarder@example.com"},
        subject="Guest inquiry",
        plain_text=plain_text,
    )

    assert detected == "vrbo"


def test_parse_vrbo_additional_inquiry_works_even_when_headers_are_generic():
    plain_text = """
Ginny Stehling has sent an additional inquiry
Property
External ID 2403-228842
#2541521
Unit
unit_3111576
Dates
Jun 24 - Jun 29, 2026, 5 nights
Guests
5 adults, 5 children
Traveler Name
ginny Stehling
Inquiry from
Vrbo
https://www.vrbo.com

Further info

Good morning this is Property comes with the golf cart?
-------
We're here to help. Visit our Help Centre for useful info and FAQs.
"""
    parsed = parse_ota_inquiry(
        raw_html="",
        headers={"From": "forwarder@example.com"},
        subject="Guest inquiry",
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.platform == "vrbo"
    assert parsed.parser_source == "ota_parser_vrbo_plain"
    assert parsed.platform_listing_id == "2541521"
    assert parsed.platform_unit_id == "unit_3111576"
    assert "golf cart" in (parsed.latest_guest_turn or "").lower()
