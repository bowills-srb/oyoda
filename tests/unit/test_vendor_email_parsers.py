from app.services.integrations.vendor_email_parsers import parse_vendor_coordination_email


def test_parse_vendor_outbound_coordination_email():
    plain_text = """
Hi Kristi,

Please see attached booking list for beach chairs for the month if May 2026 in Carillon Beach for 111 Village Way.

Thank you!
"""
    parsed = parse_vendor_coordination_email(
        headers={
            "From": "Info Info <info@beachhabitats30a.com>",
            "To": "kristi@ldvbeach.com",
        },
        subject="Beach Chair set up for May 2026 - 111 Village Way",
        plain_text=plain_text,
    )

    assert parsed is not None
    assert parsed.sender_role == "operator"
    assert parsed.service_type == "beach_chair_setup"
    assert parsed.service_period_hint == "May 2026"
    assert parsed.property_name_hint == "111 Village Way"
    assert "attached booking list" in (parsed.latest_operator_turn or "").lower()


def test_parse_vendor_inbound_acknowledgement_email():
    plain_text = """
Thank you for sending these over. Have a good weekend!

On Fri, Apr 24, 2026 at 12:12 PM Info Info <info@beachhabitats30a.com> wrote:
> Hi Kristi,
> Please see attached booking list for beach chairs for the month if May 2026 in Carillon Beach for 111 Village Way.
"""
    parsed = parse_vendor_coordination_email(
        headers={
            "From": "Kristi Meadows <kristi@destinbeachservice.com>",
            "To": "Info Info <info@beachhabitats30a.com>",
        },
        subject="Re: Beach Chair set up for May 2026 - 111 Village Way",
        plain_text=plain_text,
    )

    assert parsed is not None
    assert parsed.sender_role == "vendor"
    assert parsed.vendor_email == "kristi@destinbeachservice.com"
    assert parsed.property_name_hint == "111 Village Way"
    assert "thank you for sending these over" in (parsed.latest_vendor_turn or "").lower()
