from app.services.integrations.message_ask_taxonomy import detect_message_asks


def test_detect_pricing_change_and_billing_patterns():
    pricing_change = detect_message_asks(
        "The total for our dates was $7070 yesterday. Did something happen to make it increase within 24 hours?"
    )
    assert "pricing" in pricing_change
    assert "pricing_change" in pricing_change

    pricing_negotiation = detect_message_asks(
        "Hey! I'll give you 4900 for 7 nights. July 3-July 10!"
    )
    assert "pricing" in pricing_negotiation
    assert "pricing_negotiation" in pricing_negotiation

    billing = detect_message_asks(
        "Why has only the $477 fee posted to my credit card and not the first half charge?"
    )
    assert "pricing" in billing
    assert "billing_or_payment" in billing


def test_detect_timing_and_courtesy_hold_patterns():
    timing = detect_message_asks(
        "Are the check-in or check-out times flexible at all? We would love an early check-in and late checkout."
    )
    assert "check_in_process" in timing
    assert "early_check_in" in timing
    assert "late_checkout" in timing

    hold = detect_message_asks(
        "Please ignore my previous note. We would like to book and wanted to see if you could courtesy hold the property for 24 hours."
    )
    assert "courtesy_hold" in hold


def test_detect_booking_admin_and_reservation_ops_patterns():
    agreement = detect_message_asks(
        'We signed and submitted our rental agreement yesterday. Can you please send a receipt to confirm our first payment?'
    )
    assert "agreement_completion" in agreement
    assert "billing_or_payment" in agreement
    assert "payment_status" in agreement
    assert "receipt_request" in agreement
    assert "reservation_ops" in agreement

    cancellation = detect_message_asks(
        "Tonye Hutzelman is asking to cancel a booking for Jun 20, 2026. This cancellation will not be processed unless you approve it."
    )
    assert "cancellation_request" in cancellation
    assert "reservation_ops" in cancellation


def test_detect_in_stay_service_recovery_patterns():
    asks = detect_message_asks(
        "Good Morning! I wanted to let your team know we never got the internet back during our stay. "
        "This was very frustrating for the three people who had to work remote and our kiddos who couldn’t "
        "wind down the day with a show. We also had a few cock roaches on the kitchen counter. "
        "Please let me know if a small refund can be offered? Thank you!"
    )
    assert "amenities" in asks
    assert "wifi_issue" in asks
    assert "pest_issue" in asks
    assert "service_issue" in asks
    assert "refund_request" in asks
    assert "service_recovery" in asks


def test_detect_off_platform_booking_risk_patterns():
    asks = detect_message_asks(
        "Is there anyway to book directly through your company with VRBO? Just trying to avoid fees."
    )
    assert "off_platform_booking_risk" in asks


def test_detect_bring_your_own_beach_gear_policy_patterns():
    asks = detect_message_asks(
        "Are we allowed to bring our own to beach? We would prefer to bring our own umbrella and chairs."
    )
    assert "beach_access" in asks
    assert "beach_service" in asks
    assert "bring_your_own_gear_policy" in asks


def test_detect_recent_thread_shapes_added_after_audit():
    promo = detect_message_asks(
        "The promo code did not work and it is still the same price without the discount. Can you send the discounted total?"
    )
    assert "pricing" in promo
    assert "promo_code_issue" in promo

    eligibility = detect_message_asks(
        "I am 24 years old but would be booking with my parents who are over 25. Would I have to book with one of their names?"
    )
    assert "booking_eligibility" in eligibility

    entitlement = detect_message_asks(
        "Do the wristbands that are allotted with this stay include access to Camp WaterColor?"
    )
    assert "access_entitlement" in entitlement

    inclusion = detect_message_asks(
        "Does the LSV come with the booking or is there an additional fee?"
    )
    assert "pricing" in inclusion
    assert "amenity_inclusion" in inclusion

    vendor = detect_message_asks(
        "Just booked - any recs on how to rent / who for beach chairs / umbrellas?"
    )
    assert "beach_service" in vendor
    assert "local_vendor_recommendation" in vendor

    date_change = detect_message_asks(
        "Hi! Is there anyway we can modify our trip to Jun 15-20 instead of Jun 17-22?"
    )
    assert "reservation_change" in date_change
    assert "date_change_request" in date_change


def test_detect_service_animal_and_contract_dispute_patterns():
    service_animal = detect_message_asks(
        "We have a certified service dog and were told dogs are not allowed. This seems to violate ADA policy."
    )
    assert "pet_policy" in service_animal
    assert "service_animal_policy" in service_animal

    dispute = detect_message_asks(
        "I request deletion of the sale paragraph or a restatement providing the verbal assurance I was given. We won't sign unless the wording is modified."
    )
    assert "agreement_completion" not in dispute
    assert "agreement_dispute" in dispute

    refund_window = detect_message_asks(
        "Please note that after April 26th, we will be unable to refund you for this booking."
    )
    assert "refund_request" in refund_window
    assert "refund_deadline" in refund_window


def test_detect_later_checkout_and_bachelorette_patterns():
    asks = detect_message_asks(
        "Hi! I’m looking to book for my bachelorette and curious if there’s anyway to get a later checkout than 9 am on Sunday?"
    )
    assert "late_checkout" in asks
    assert "group_or_event" in asks
