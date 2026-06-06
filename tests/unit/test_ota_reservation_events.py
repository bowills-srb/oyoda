from app.services.integrations.ota_reservation_events import parse_ota_reservation_event


def test_parse_airbnb_reservation_reminder_event():
    plain_text = """
ANDREW ARRIVES THURSDAY, APR 30.

If you haven’t already, reach out to Andrew to send directions and coordinate check-in time.

https://www.airbnb.com/hosting/reservations/details/HMW5ARXXDC?isPending=true   Andrew Wilson
Identity verified · 3 reviews

Send Andrew a Message
[https://www.airbnb.com/hosting/thread/2418002275?thread_type=home_booking]

https://www.airbnb.com/rooms/1517419297709659869

WATERCOLOR COTTAGE | 4 BD + 4 BIKES + RESORT

Check-in      Checkout
Thu, Apr 30   Sun, May 3

GUESTS
8 adults

CONFIRMATION CODE
HMW5ARXXDC
"""
    parsed = parse_ota_reservation_event(
        headers={"From": "Airbnb <automated@airbnb.com>"},
        subject="Reservation reminder: Andrew is coming soon!",
        plain_text=plain_text,
    )

    assert parsed is not None
    assert parsed.platform == "airbnb"
    assert parsed.system_event_type == "reservation_reminder"
    assert parsed.guest_name == "Andrew Wilson"
    assert parsed.platform_listing_id == "1517419297709659869"
    assert parsed.source_interaction_id == "2418002275"
    assert parsed.reservation_id == "HMW5ARXXDC"
    assert parsed.guests_adults == 8


def test_parse_airbnb_reservation_confirmed_event():
    plain_text = """
NEW BOOKING CONFIRMED! AMY ARRIVES JUN 19.

https://www.airbnb.com/hosting/reservations/details/HM8TTMFW9A?isPending=true   Amy McDonald
Identity verified · 3 reviews

Send Amy a Message
[https://www.airbnb.com/hosting/thread/2507239446?thread_type=home_booking]

https://www.airbnb.com/rooms/1571939770441752742

CASA BLANCO | ROSEMARY 8BD LUXURY + PRIVATE POOL

Check-in      Checkout
Fri, Jun 19   Mon, Jun 22

GUESTS
14 adults

CONFIRMATION CODE
HM8TTMFW9A
"""
    parsed = parse_ota_reservation_event(
        headers={"From": "Airbnb <automated@airbnb.com>"},
        subject="Reservation confirmed - Amy McDonald arrives Jun 19",
        plain_text=plain_text,
    )

    assert parsed is not None
    assert parsed.platform == "airbnb"
    assert parsed.system_event_type == "reservation_confirmed"
    assert parsed.guest_name == "Amy McDonald"
    assert parsed.platform_listing_id == "1571939770441752742"
    assert parsed.source_interaction_id == "2507239446"
    assert parsed.reservation_id == "HM8TTMFW9A"
    assert parsed.guests_adults == 14


def test_parse_vrbo_reservation_event_returns_none_for_guest_message_threads():
    plain_text = """
Vrbo: Pamela Herrmann has replied to your message

Unfortunately our youngest will be 5 that time.

https://www.vrbo.com/supply/interaction?interactionId=591254c8-d232-4906-a552-91b3f6207bb9&propertyId=61496307
"""
    parsed = parse_ota_reservation_event(
        headers={"From": "Pamela Herrmann <sender@messages.homeaway.com>"},
        subject="Inquiry from Pamela Herrmann: Mar 16 - Mar 23, 2027 - Vrbo #2146601",
        plain_text=plain_text,
    )

    assert parsed is None


def test_parse_airbnb_review_event():
    plain_text = """
MACY RATED THEIR STAY 5 STARS!

FEEDBACK FROM THEIR STAY

Mystic 30A | Near Town Center & Beach Club + Bikes

Apr 16 – 19, 2026

OVERALL RATING   5

This was a beautiful stay! The house is gorgeous and centrally located.

PRIVATE NOTE

Thank you so much for the beautiful stay! The only minor disappointment we had was the lack of basic items like toilet paper and trash bags!

SPECIAL THANKS
"""
    parsed = parse_ota_reservation_event(
        headers={"From": "Airbnb <automated@airbnb.com>"},
        subject="Macy left a 5-star review!",
        plain_text=plain_text,
    )

    assert parsed is not None
    assert parsed.platform == "airbnb"
    assert parsed.system_event_type == "review_received"
    assert parsed.lifecycle_stage == "post_stay"
    assert parsed.guest_name == "Macy"
    assert parsed.review_rating == 5
    assert parsed.property_name_hint == "Mystic 30A | Near Town Center & Beach Club + Bikes"
    assert "beautiful stay" in (parsed.public_review_text or "").lower()
    assert "toilet paper" in (parsed.private_note or "").lower()


def test_parse_vrbo_review_event_from_reviewed_their_stay_subject():
    plain_text = """
One of your guests has submitted a review

You can submit an owner response, which will be displayed with the review on your listing.

Write a response: http://www.vrbo.com/td/reviews/v2/response/reservation/01ede4f1-f432-46f8-8d1f-60210d0bdf60

WaterColor Camp District Retreat | 3 BR, Private Heated Pool & Golf Cart
Reservation ID #RES-08974

4 out of 5

Pool was difficult to keep clean with the nearby tree. Master bathroom shower clogged up and needed plunged each time it was used.

Date of arrival - March 29, 2026
"""
    parsed = parse_ota_reservation_event(
        headers={"From": "Vrbo <noreply@reviews.homeaway.com>"},
        subject="Alan reviewed their stay (March 29, 2026-April 2, 2026) at your property # 2813936",
        plain_text=plain_text,
    )

    assert parsed is not None
    assert parsed.platform == "vrbo"
    assert parsed.system_event_type == "review_received"
    assert parsed.lifecycle_stage == "post_stay"
    assert parsed.guest_name == "Alan"
    assert parsed.platform_listing_id == "2813936"
    assert parsed.reservation_id == "RES-08974"
    assert parsed.review_rating == 4
    assert parsed.property_name_hint == "WaterColor Camp District Retreat | 3 BR, Private Heated Pool & Golf Cart"
    assert "pool was difficult to keep clean" in (parsed.public_review_text or "").lower()
    assert parsed.review_response_url and "vrbo.com/td/reviews" in parsed.review_response_url


def test_parse_airbnb_money_request_event():
    plain_text = """
YOU REQUESTED $224 USD

Seth
Apr 13 – 18, 2026
WaterColor Retreat | 3 BR, Private Pool, 3 Bikes!

This is for payment for pool heating for Tuesday through Thursday of your stay.

Review request
[https://www.airbnb.com/resolutions/CLA-8ZFA44N9PD]
"""
    parsed = parse_ota_reservation_event(
        headers={"From": "Airbnb <automated@airbnb.com>"},
        subject="You requested money from Seth",
        plain_text=plain_text,
    )

    assert parsed is not None
    assert parsed.platform == "airbnb"
    assert parsed.system_event_type == "money_request_created"
    assert parsed.guest_name == "Seth"
    assert parsed.reservation_id == "CLA-8ZFA44N9PD"
    assert parsed.monetary_amount == 224.0
    assert parsed.property_name_hint == "WaterColor Retreat | 3 BR, Private Pool, 3 Bikes!"
    assert "pool heating" in (parsed.summary_text or "").lower()


def test_parse_airbnb_reservation_canceled_event():
    plain_text = """
RESERVATION CANCELED

https://www.airbnb.com/hosting/reservations/details/HMW8MZRSB5   Spooky Lane Gulf Front Condo | Walk to Restaurants

Listing #1517419124341363319

Aug 1 – 8, 6 guests

Unfortunately, your guest Rodolfo had to cancel reservation HMW8MZRSB5 for Aug 1 – 8.
Your calendar has been updated to show that these dates are now available.

According to your cancellation policy, a complete refund was given to the guest.
"""
    parsed = parse_ota_reservation_event(
        headers={"From": "Airbnb <automated@airbnb.com>"},
        subject="Canceled: Reservation HMW8MZRSB5 for Aug 1 – 8, 2026",
        plain_text=plain_text,
    )

    assert parsed is not None
    assert parsed.platform == "airbnb"
    assert parsed.system_event_type == "reservation_canceled"
    assert parsed.guest_name == "Rodolfo"
    assert parsed.reservation_id == "HMW8MZRSB5"
    assert parsed.platform_listing_id == "1517419124341363319"
    assert parsed.guests_adults == 6
    assert parsed.property_name_hint == "Spooky Lane Gulf Front Condo | Walk To Restaurants"
