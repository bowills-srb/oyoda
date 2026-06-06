from app.services.integrations.direct_email_parsers import parse_direct_inquiry
from app.services.integrations.inbound_source_router import detect_inbound_source_route


def test_detect_direct_website_form_route():
    route = detect_inbound_source_route(
        headers={"X-Mailer": "Drupal Webform"},
        subject="116 W Summersweet Lane (Santa Rosa Beach, FL - 32459)",
        plain_text="Submitted values are:\nListing of Interest: 116 W Summersweet Lane\nComments/Questions: Hi there",
    )
    assert route.family == "direct_website_form"
    assert route.parser_hint == "direct_website_form"


def test_vendor_ops_detection_does_not_catch_guest_amenity_question():
    route = detect_inbound_source_route(
        headers={"From": "Carri Bevil <carri.bevil@yahoo.com>"},
        subject="Questions",
        plain_text=(
            "Hi there, I had a few questions about 517 Eastern Lake Road. "
            "Do you provide beach chairs, towels, and what kind of coffee maker is there?"
        ),
    )

    assert route.family == "generic_email"
    assert route.parser_hint == "generic"


def test_vendor_ops_detection_still_catches_beach_chair_coordination():
    route = detect_inbound_source_route(
        headers={
            "From": "Info Info <info@beachhabitats30a.com>",
            "To": "kristi@ldvbeach.com",
        },
        subject="Beach Chair set up for May 2026 - 111 Village Way",
        plain_text=(
            "Hi Kristi,\n\nPlease see attached booking list for beach chairs for the month of May 2026.\n"
        ),
    )

    assert route.family == "vendor_ops_email"
    assert route.parser_hint == "vendor_ops_email"


def test_parse_direct_website_form_inquiry():
    plain_text = """
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
"""
    parsed = parse_direct_inquiry(
        headers={
            "From": '"morgan_childress@yahoo.com via Beach Habitats 30A" <lanier@beachhabitats30a.com>',
            "Reply-To": "morgan_childress@yahoo.com",
            "X-Mailer": "Drupal Webform",
        },
        subject="116 W Summersweet Lane (Santa Rosa Beach, FL - 32459)",
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.sender_role == "guest"
    assert parsed.thread_event_type == "inquiry"
    assert parsed.guest_email == "morgan_childress@yahoo.com"
    assert parsed.property_name_hint == "116 W Summersweet Lane"
    assert parsed.guests_adults == 6
    assert parsed.guests_children == 10
    assert "extra wrist bands" in (parsed.latest_guest_turn or "").lower()
    assert "occupancy_policy" in parsed.asks or "house_rules" in parsed.asks


def test_parse_direct_website_form_operator_reply():
    plain_text = """
Hi Morgan. This home sleeps 12 and only allows for 12 guests. This is also the max number of wristbands allowed by the HOA. How many people are coming? We may be able to find you a home better suited to your needs.

On Thu, Apr 23, 2026 at 8:14 AM morgan_childress@yahoo.com via Beach Habitats 30A <lanier@beachhabitats30a.com> wrote:
> Submitted on Thursday, April 23, 2026 - 08:14
> Submitted values are:
> Email: morgan_childress@yahoo.com
> Arrival Date: Tue, 09/01/2026
> Departure Date: Sun, 09/06/2026
> Adults: 6
> Children: 10
> Comments/Questions: Hi we have a large group potentially coming! Are you allowed to purchase extra wrist bands?
> Listing of Interest: 116 W Summersweet Lane
"""
    parsed = parse_direct_inquiry(
        headers={
            "From": "Info Info <info@beachhabitats30a.com>",
            "To": "morgan_childress@yahoo.com",
        },
        subject="Re: 116 W Summersweet Lane (Santa Rosa Beach, FL - 32459)",
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.sender_role == "operator"
    assert parsed.thread_event_type == "operator_reply"
    assert parsed.guest_name == "morgan_childress@yahoo.com"
    assert "only allows for 12 guests" in (parsed.latest_operator_turn or "").lower()
    assert "extra wrist bands" in (parsed.latest_guest_turn or "").lower()


def test_parse_direct_website_form_wrapped_pricing_change_inquiry():
    plain_text = """
Submitted on Tuesday, April 21, 2026 - 20:22
Submitted values are:

FIrst Name: Cassie
Last Name: Warren
Email: cassiekolls@gmail.com
Arrival Date: Sun, 08/23/2026
Departure Date: Sat, 08/29/2026
Adults: 5
Children: 3
Comments/Questions: Hello! I just looked at this property yesterday to book
and the total for our dates was $7070. Did something happen to make it
increase within 24 hours?
Listing of Interest: 517 Eastern Lake Rd
Page Path: /30a-vacation-rentals/517-eastern-lake-rd
"""
    parsed = parse_direct_inquiry(
        headers={
            "From": '"Cassie via Beach Habitats 30A" <lanier@beachhabitats30a.com>',
            "Reply-To": "Cassie <cassiekolls@gmail.com>",
            "X-Mailer": "Drupal Webform",
        },
        subject="517 Eastern Lake Rd (Santa Rosa Beach, FL - 32459)",
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.guest_name == "Cassie Warren"
    assert parsed.property_name_hint == "517 Eastern Lake Rd"
    assert "increase within 24 hours" in (parsed.latest_guest_turn or "").lower()
    assert "pricing" in parsed.asks
    assert "pricing_change" in parsed.asks


def test_parse_direct_guest_reply_detects_follow_up_and_pet_policy():
    plain_text = """
Question about our stay at 90 Mystic Cobalt, are we able to bring a small dog?

On Tue, Apr 14, 2026 at 2:28 PM Info Info <info@beachhabitats30a.com> wrote:
> Yes Ma’am. Both rooms with bunk beds have a door.
>
> > Submitted on Tuesday, April 14, 2026 - 13:56
> > Comments/Questions:
> > Is there a door to the room with the bunk beds?
> > Listing of Interest: 90 Mystic Cobalt St
"""
    parsed = parse_direct_inquiry(
        headers={
            "From": "Gina Taverna <taverna1313@gmail.com>",
            "To": "Info Info <info@beachhabitats30a.com>",
        },
        subject="Re: 90 Mystic Cobalt St (Santa Rosa Beach, FL - 32459)",
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.sender_role == "guest"
    assert parsed.thread_event_type == "guest_reply"
    assert "small dog" in (parsed.latest_guest_turn or "").lower()
    assert "pet_policy" in parsed.asks


def test_parse_direct_website_form_thread_preserves_guest_inquiry_context():
    inquiry_text = """
Submitted on Monday, April 6, 2026 - 21:07
Submitted by anonymous user: 69.245.203.55
Submitted values are:

FIrst Name: Gwyn
Last Name: Pashawitz
Email: gpashawitz@comcast.net
Phone Number: 6309451168
Arrival Date: Sun, 08/02/2026
Departure Date: Fri, 08/07/2026
Adults: 6
Children: 3
Comments/Questions: Hi there!  I’d love additional information on this
beach house.  Hoping for a family vacation near the watercolor area & this
looks like it fits the bill!  Can you please tell me the cost, proximity to
the beach & if the amenities include activities @ Watercolor resort.  Thank
you!
Listing of Interest: Here Comes the Sun
Page Path: /30a-vacation-rentals/here-comes-sun
City: Santa Rosa Beach
State Province Code: FL
Postal Code: 32459
Country Code: US
"""
    parsed = parse_direct_inquiry(
        headers={
            "From": '"Gwyn via Beach Habitats 30A" <lanier@beachhabitats30a.com>',
            "Reply-To": '"Gwyn" <gpashawitz@comcast.net>',
            "X-Mailer": "Drupal Webform",
        },
        subject="Here Comes the Sun (Santa Rosa Beach, FL - 32459)",
        plain_text=inquiry_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.sender_role == "guest"
    assert parsed.thread_event_type == "inquiry"
    assert parsed.guest_name == "Gwyn Pashawitz"
    assert parsed.guest_email == "gpashawitz@comcast.net"
    assert parsed.property_name_hint == "Here Comes the Sun"
    assert parsed.page_path == "/30a-vacation-rentals/here-comes-sun"
    assert parsed.check_in is not None
    assert parsed.check_in.month == 8
    assert parsed.check_in.day == 2
    assert parsed.check_out is not None
    assert parsed.check_out.month == 8
    assert parsed.check_out.day == 7
    assert "watercolor area" in (parsed.latest_guest_turn or "").lower()
    assert "pricing" in parsed.asks
    assert "amenities" in parsed.asks


def test_parse_direct_operator_reply_thread_keeps_latest_operator_and_guest_turns():
    reply_text = """
Hi Gwen.

You have great taste!! This home is 2 miles to the beach club, it comes with a 6 seater golf cart and 5 bikes to make that an easy journey. It has access to all Watercolor amenities. Below is a link to what is included for guests. For the nights listed, the cost including all taxes and fees would be $8019.77

https://www.mywatercolorcommunity.com/280/Amenity-Information-for-Visitors

Let us know if we can answer any further questions!

-BH30A

On Mon, Apr 6, 2026 at 9:07 PM Gwyn via Beach Habitats 30A <lanier@beachhabitats30a.com> wrote:

> Submitted on Monday, April 6, 2026 - 21:07
> Submitted by anonymous user: 69.245.203.55
> Submitted values are:
>
> FIrst Name: Gwyn
> Last Name: Pashawitz
> Email: gpashawitz@comcast.net
> Phone Number: 6309451168
> Arrival Date: Sun, 08/02/2026
> Departure Date: Fri, 08/07/2026
> Adults: 6
> Children: 3
> Comments/Questions: Hi there!  I’d love additional information on this
> beach house.  Hoping for a family vacation near the watercolor area & this
> looks like it fits the bill!  Can you please tell me the cost, proximity to
> the beach & if the amenities include activities @ Watercolor resort.  Thank
> you!
> Listing of Interest: Here Comes the Sun
> Page Path: /30a-vacation-rentals/here-comes-sun
"""
    parsed = parse_direct_inquiry(
        headers={
            "From": "Info Info <info@beachhabitats30a.com>",
            "To": "Gwyn <gpashawitz@comcast.net>",
        },
        subject="Re: Here Comes the Sun (Santa Rosa Beach, FL - 32459)",
        plain_text=reply_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.sender_role == "operator"
    assert parsed.thread_event_type == "operator_reply"
    assert parsed.guest_name == "Gwyn Pashawitz"
    assert parsed.guest_email == "gpashawitz@comcast.net"
    assert "2 miles to the beach club" in (parsed.latest_operator_turn or "").lower()
    assert "watercolor resort" in (parsed.latest_guest_turn or "").lower()
    assert parsed.prior_thread_context is not None
    assert "submitted values are" in parsed.prior_thread_context.lower()


def test_parse_direct_inquiry_strict_form_only_rejects_reply_thread_shape():
    plain_text = """
Question about our stay at 90 Mystic Cobalt, are we able to bring a small dog?

On Tue, Apr 14, 2026 at 2:28 PM Info Info <info@beachhabitats30a.com> wrote:
> Yes Ma’am. Both rooms with bunk beds have a door.
>
> > Submitted on Tuesday, April 14, 2026 - 13:56
> > Comments/Questions:
> > Is there a door to the room with the bunk beds?
> > Listing of Interest: 90 Mystic Cobalt St
"""
    parsed = parse_direct_inquiry(
        headers={
            "From": "Gina Taverna <taverna1313@gmail.com>",
            "To": "Info Info <info@beachhabitats30a.com>",
        },
        subject="Re: 90 Mystic Cobalt St (Santa Rosa Beach, FL - 32459)",
        plain_text=plain_text,
        market_id="30a_fl",
        strict_form_only=True,
    )

    assert parsed is None


def test_parse_direct_website_form_message_comments_variant_without_listing_subject():
    plain_text = """
Submitted on Sunday, April 5, 2026 - 22:30
Submitted by anonymous user: 162.193.66.142
Submitted values are:

First Name: Sabina
Last Name: Karkin
Email: sabina.karkin@gmail.com
Phone Number:
Message/Comments:
Hello,
We are a family of four, and we came across your Rosemary beach condo
listing on your site. We would love to stay here this thur-mon, apr 9-13,
however, the price is outside our budget (which is half of that).
Would you be willing to offer a discount for us? We've stayed in Rosemary
before and also have reviews on airbnb as guests, where you can see that we
are extremely clean and quiet with kids' bedtime by 8 pm.
Thank you for considering and I hope we get to enjoy your
property. Warmly,Sabina
Page Path: /node/2
"""
    parsed = parse_direct_inquiry(
        headers={
            "From": '"Sabina via Beach Habitats 30A" <lanier@beachhabitats30a.com>',
            "Reply-To": '"Sabina" <sabina.karkin@gmail.com>',
            "X-Mailer": "Drupal Webform",
        },
        subject="Sabina",
        plain_text=plain_text,
        market_id="30a_fl",
    )

    assert parsed is not None
    assert parsed.sender_role == "guest"
    assert parsed.thread_event_type == "inquiry"
    assert parsed.guest_name == "Sabina Karkin"
    assert parsed.guest_email == "sabina.karkin@gmail.com"
    assert parsed.property_name_hint == ""
    assert parsed.page_path == "/node/2"
    assert "outside our budget" in (parsed.latest_guest_turn or "").lower()
    assert "pricing" in parsed.asks
    assert "pricing_negotiation" in parsed.asks
