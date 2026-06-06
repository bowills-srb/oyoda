from app.services.integrations.email_type_classifier import EMAIL_TYPE_CLASSIFIER, MessageType
from app.services.integrations.inbound_source_router import InboundSourceRoute


def test_classifies_airbnb_booking_event_from_subject():
    classified = EMAIL_TYPE_CLASSIFIER.classify(
        headers={"From": "Airbnb <automated@airbnb.com>"},
        subject="Reservation confirmed - Amy McDonald arrives Jun 19",
        plain_text="NEW BOOKING CONFIRMED! AMY ARRIVES JUN 19.",
        source_route=InboundSourceRoute(family="ota", provider="airbnb", parser_hint="ota"),
    )

    assert classified.message_type == MessageType.AIRBNB_BOOKING_EVENT


def test_classifies_airbnb_guest_inquiry_from_reply_sender():
    classified = EMAIL_TYPE_CLASSIFIER.classify(
        headers={"From": "Airbnb Messages <reply@reply.airbnb.com>"},
        subject="Question about your place from Jamie",
        plain_text="Hi, is the pool heated and is parking included?",
        source_route=InboundSourceRoute(family="ota", provider="airbnb", parser_hint="ota"),
    )

    assert classified.message_type == MessageType.AIRBNB_GUEST_INQUIRY


def test_classifies_vrbo_guest_inquiry_from_headers():
    classified = EMAIL_TYPE_CLASSIFIER.classify(
        headers={
            "From": "Vrbo <sender@messages.homeaway.com>",
            "X-Mediated-Message-Type": "NEW_INQUIRY",
        },
        subject="Question",
        plain_text="Traveler Name: Jan Hevey",
        source_route=InboundSourceRoute(family="ota", provider="vrbo", parser_hint="ota"),
    )

    assert classified.message_type == MessageType.VRBO_GUEST_INQUIRY


def test_classifies_direct_website_form_inquiry():
    classified = EMAIL_TYPE_CLASSIFIER.classify(
        headers={"From": "Website Form <forms@example.com>", "X-Mailer": "Drupal Webform"},
        subject="116 W Summersweet Lane (Santa Rosa Beach, FL - 32459)",
        plain_text=(
            "Submitted values are:\n"
            "Arrival Date: Tue, 09/01/2026\n"
            "Departure Date: Sun, 09/06/2026\n"
            "Comments/Questions: Hi there\n"
            "Listing of Interest: 116 W Summersweet Lane\n"
        ),
        source_route=InboundSourceRoute(
            family="direct_website_form",
            provider="direct",
            parser_hint="direct_website_form",
        ),
    )

    assert classified.message_type == MessageType.DIRECT_WEBSITE_FORM_INQUIRY


def test_classifies_direct_website_form_other_newsletter():
    classified = EMAIL_TYPE_CLASSIFIER.classify(
        headers={"From": "Website Form <forms@example.com>", "X-Mailer": "Drupal Webform"},
        subject="Form submission from: Enewsletter Sign Up",
        plain_text="Name: Alex\nEmail: alex@example.com\nNewsletter: yes\nSign Up: yes",
        source_route=InboundSourceRoute(
            family="direct_website_form",
            provider="direct",
            parser_hint="direct_website_form",
        ),
    )

    assert classified.message_type == MessageType.NON_GUEST


def test_classifies_generic_guest_email():
    classified = EMAIL_TYPE_CLASSIFIER.classify(
        headers={"From": "Taylor <taylor@example.com>"},
        subject="Question about parking",
        plain_text="Hi, is parking included?",
        source_route=InboundSourceRoute(family="generic_email", provider="direct", parser_hint="generic"),
    )

    assert classified.message_type == MessageType.GENERIC_GUEST_EMAIL
