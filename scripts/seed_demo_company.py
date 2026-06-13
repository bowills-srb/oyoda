#!/usr/bin/env python3
"""
seed_demo_company.py — fictitious company demo across Text (SMS) + Email
========================================================================
Seeds a self-contained demo operator — **Emerald Shores Stays** (a 30A Gulf
Coast vacation-rental manager) — with three properties and a spread of guest
conversations across BOTH communication channels:

  • Email  → pre-booking inquiries + a post-stay review request
  • Text   → in-stay SMS threads, a pre-arrival confirmation, an escalation

It powers the demo dashboard at GET /demo (see app/api/v1/endpoints/demo_dashboard.py).

Idempotent: re-running wipes and recreates only this demo tenant's data.

Usage:
  python scripts/seed_demo_company.py
  python scripts/seed_demo_company.py --wipe
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.core.database import get_db_session
from app.services.concierge.db_session_service import DatabaseSessionService
from db.models.concierge_escalations import ConciergeEscalationModel

# ── Fictitious company ───────────────────────────────────────────────────────
TENANT_ID = UUID("22222222-2222-2222-2222-222222222222")
COMPANY_NAME = "Emerald Shores Stays"
TODAY = date.today()

# property_code -> (id, name, city, bedrooms, bathrooms)
PROPERTIES = {
    "ES-SANDPIPER": (UUID("2a000000-0000-0000-0000-000000000001"), "The Sandpiper", "Rosemary Beach, FL", 3, 2.5),
    "ES-PELICAN":   (UUID("2a000000-0000-0000-0000-000000000002"), "Pelican Perch",  "WaterColor, FL",    5, 4.0),
    "ES-DUNEDRIFT": (UUID("2a000000-0000-0000-0000-000000000003"), "Dune Drift Bungalow", "Grayton Beach, FL", 2, 2.0),
}

# ── Email conversations → pre_booking_inquiries (platform='email') ───────────
EMAIL_INQUIRIES = [
    {
        "draft_id": "demo-email-0001", "code": "ES-SANDPIPER",
        "guest": "Priya Nair", "email": "priya.nair@example.com",
        "msg": ("Hello! We're interested in The Sandpiper for Aug 9–14 (2 adults, 2 kids). "
                "Is it available, and is it okay to bring a small, well-behaved dog?"),
        "draft": ("Hi Priya! The Sandpiper is available Aug 9–14 and is a great fit for a family of four. "
                  "We're happy to welcome one small dog with our $150 pet fee. Shall I send a booking link?"),
        "cin": 57, "cout": 62, "guests": 4, "status": "pending_review",
    },
    {
        "draft_id": "demo-email-0002", "code": "ES-PELICAN",
        "guest": "Greg & Tom Halvorsen", "email": "halvorsen.party@example.com",
        "msg": ("Looking at Pelican Perch for a group of 10 over Labor Day weekend. Do you offer any "
                "multi-night discount, and how does parking work for 3 cars?"),
        "draft": ("Hi Greg! Pelican Perch sleeps 12 and is perfect for a group of 10. For 4+ nights we can apply "
                  "a 10% stay discount, and the property has driveway space for 3 vehicles. Want me to hold the dates?"),
        "cin": 79, "cout": 83, "guests": 10, "status": "pending_review",
    },
]

# ── Email session → post-stay review request (channel='email') ───────────────
EMAIL_SESSIONS = [
    {
        "code": "ES-DUNEDRIFT", "guest": "Renee Castillo", "email": "renee.castillo@example.com",
        "phone": None, "channel": "email", "ci": -9, "co": -2, "guests": 2,
        "thread": [
            ("outbound", "Hi Renee — thank you for staying at Dune Drift Bungalow! We'd love a quick review of your "
                         "stay, and please let us know if you left anything behind.", "review_request"),
            ("inbound", "We had a wonderful time, thank you! One thing — I think we left a phone charger by the "
                        "nightstand. Could you check?", "lost_and_found"),
            ("outbound", "So glad you enjoyed it! Housekeeping found a white charger and we'll ship it to you today. "
                         "I'll text you the tracking number.", "lost_and_found"),
        ],
    },
]

# ── Text (SMS) sessions → concierge sessions (channel='sms') ─────────────────
SMS_SESSIONS = [
    {
        "code": "ES-PELICAN", "guest": "The Okafor Family", "email": "okafor@example.com",
        "phone": "+18505550110", "channel": "sms", "ci": 6, "co": 11, "guests": 8,
        "thread": [
            ("inbound", "Hi! We arrive Saturday — what time can we check in and how do we get the door code?", "check_in"),
            ("outbound", "Welcome! Check-in is 4 PM and your door code will text to you the morning of arrival. "
                         "Can't wait to host you at Pelican Perch!", "check_in"),
        ],
    },
    {
        "code": "ES-SANDPIPER", "guest": "Daniel Wu", "email": "daniel.wu@example.com",
        "phone": "+18505550133", "channel": "sms", "ci": -1, "co": 4, "guests": 4,
        "thread": [
            ("inbound", "The WiFi keeps dropping — can't get the kids' tablets online.", "wifi"),
            ("outbound", "Sorry about that! The router is in the hall closet — unplug it for 30 seconds, then plug back "
                         "in. The network is Sandpiper_Guest / SeaOats2024.", "wifi"),
            ("inbound", "That did it, thanks!", "wifi"),
        ],
    },
    {
        "code": "ES-PELICAN", "guest": "Marisol Vega", "email": "marisol.vega@example.com",
        "phone": "+18505550148", "channel": "sms", "ci": -2, "co": 5, "guests": 6,
        "thread": [
            ("inbound", "The pool doesn't seem to be heating — it's pretty cold for the kids.", "maintenance"),
            ("outbound", "Thanks for flagging — I see pool heat on your reservation. I'm having our tech confirm the "
                         "heater is firing; you should feel it warming within a couple of hours.", "maintenance"),
        ],
    },
]

# ── Escalation: AC out, upset guest (becomes a high-priority ticket) ─────────
ESCALATION_SESSION = {
    "code": "ES-DUNEDRIFT", "guest": "Brett Hollis", "email": "brett.hollis@example.com",
    "phone": "+18505550162", "channel": "sms", "ci": -1, "co": 3, "guests": 2,
    "thread": [
        ("inbound", "It's 86 degrees inside and the AC is blowing warm air. This is our anniversary trip and it's "
                    "miserable. We need this fixed NOW.", "complaint"),
        ("outbound", "I'm so sorry, Brett — that's not the anniversary we want for you. I'm escalating to our team "
                     "immediately and an HVAC tech will call you within 15 minutes.", "complaint"),
    ],
    "summary": "AC blowing warm air, 86°F indoors; anniversary trip, guest very upset. HVAC dispatch required.",
    "priority": "high",
}


async def wipe(db) -> None:
    codes = list(PROPERTIES.keys())
    params = {"t": str(TENANT_ID)}
    stmts = [
        text("DELETE FROM concierge_messages WHERE session_id IN (SELECT session_id FROM concierge_guest_sessions WHERE tenant_id=:t)"),
        text("DELETE FROM concierge_journey_activities WHERE journey_id IN (SELECT journey_id FROM concierge_guest_journeys WHERE session_id IN (SELECT session_id FROM concierge_guest_sessions WHERE tenant_id=:t))"),
        text("DELETE FROM concierge_guest_journeys WHERE session_id IN (SELECT session_id FROM concierge_guest_sessions WHERE tenant_id=:t)"),
        text("DELETE FROM concierge_escalations WHERE property_code = ANY(:codes)"),
        text("DELETE FROM concierge_guest_sessions WHERE tenant_id=:t"),
        text("DELETE FROM pre_booking_inquiries WHERE company_id=:t OR tenant_id=:t"),
        text("DELETE FROM concierge_scoped_knowledge WHERE tenant_id=:t"),
        text("DELETE FROM properties WHERE tenant_id=:t"),
    ]
    for s in stmts:
        await db.execute(s, {**params, "codes": codes})
    for s in (text("DELETE FROM guest_threads WHERE tenant_id=:t"),
              text("DELETE FROM companies WHERE name=:n"),
              text("DELETE FROM tenants WHERE id=:t")):
        try:
            await db.execute(s, {**params, "n": COMPANY_NAME})
        except Exception:
            pass
    await db.commit()


async def seed_company(db) -> None:
    await db.execute(
        text("INSERT INTO tenants (id, display_name) VALUES (:t, :n) ON CONFLICT (id) DO UPDATE SET display_name=EXCLUDED.display_name"),
        {"t": str(TENANT_ID), "n": COMPANY_NAME},
    )
    try:
        await db.execute(text("INSERT INTO companies (name) VALUES (:n)"), {"n": COMPANY_NAME})
    except Exception:
        pass
    await db.commit()


async def seed_properties(db) -> None:
    for code, (pid, name, city, br, ba) in PROPERTIES.items():
        await db.execute(
            text(
                """
                INSERT INTO properties (
                    id, tenant_id, property_code, address_street, address_city,
                    address_state, address_zip, bedrooms, bathrooms, sleeps, max_occupancy,
                    check_in_time, check_out_time, has_pool, pool_heated, has_beach_gear,
                    pets_allowed, smoking_allowed, events_allowed, general_notes, confidence_score
                ) VALUES (
                    :id, :t, :code, :addr, :city, 'FL', '32459', :br, :ba, :sleeps, :maxocc,
                    '4:00 PM', '10:00 AM', true, true, true, true, false, false, :notes, 0.95
                )
                """
            ),
            {
                "id": str(pid), "t": str(TENANT_ID), "code": code,
                "addr": f"{name}, {city}", "city": city.split(",")[0],
                "br": br, "ba": ba, "sleeps": br * 2, "maxocc": br * 2 + 2,
                "notes": f"{br}BR/{ba}BA {COMPANY_NAME} property in {city}.",
            },
        )
    await db.commit()


async def seed_email_inquiries(db) -> None:
    for q in EMAIL_INQUIRIES:
        _, name, *_ = PROPERTIES[q["code"]]
        await db.execute(
            text(
                """
                INSERT INTO pre_booking_inquiries (
                    draft_id, thread_id, company_id, tenant_id, platform,
                    guest_name, guest_email, message_text, draft_text,
                    property_external_id, intent, confidence, intent_confidence, draft_confidence,
                    status, send_decision, approval_mode, autonomy_decision, confidence_source,
                    requested_check_in, requested_check_out, requested_guests, triggered_by
                ) VALUES (
                    :draft_id, :thread_id, :t, :t, 'email',
                    :guest, :email, :msg, :draft,
                    :code, 'availability', 0.66, 0.84, 0.66,
                    :status, 'review', 'required', 'routed_to_action_below_threshold', 'model_composer',
                    :cin, :cout, :guests, 'inbound_email'
                )
                """
            ),
            {
                "draft_id": q["draft_id"], "thread_id": f"thr-{q['draft_id']}",
                "t": str(TENANT_ID), "guest": q["guest"], "email": q["email"],
                "msg": q["msg"], "draft": q["draft"], "code": q["code"],
                "status": q["status"],
                "cin": TODAY + timedelta(days=q["cin"]), "cout": TODAY + timedelta(days=q["cout"]),
                "guests": q["guests"],
            },
        )
    await db.commit()


async def seed_session(db, svc, spec) -> object:
    pid, name, *_ = PROPERTIES[spec["code"]]
    session = await svc.create_session(
        db,
        property_id=pid, property_code=spec["code"], property_name=name,
        guest_name=spec["guest"], guest_phone=spec.get("phone"), guest_email=spec.get("email"),
        check_in=TODAY + timedelta(days=spec["ci"]), check_out=TODAY + timedelta(days=spec["co"]),
        num_guests=spec.get("guests", 2),
        property_context={"channel": spec["channel"]},
    )
    for direction, content, intent in spec["thread"]:
        await svc.add_message(db, session.session_id, direction=direction, content=content, detected_intent=intent)
    return session


async def main(wipe_only: bool) -> None:
    async with get_db_session() as db:
        print(f"→ Wiping demo company data ({COMPANY_NAME}, tenant {TENANT_ID})…")
        await wipe(db)
        if wipe_only:
            print("✓ Wipe complete.")
            return

        await seed_company(db)
        await seed_properties(db)
        print(f"✓ Company + {len(PROPERTIES)} properties")

        await seed_email_inquiries(db)
        print(f"✓ {len(EMAIL_INQUIRIES)} email pre-booking inquiries")

        svc = DatabaseSessionService(TENANT_ID)
        for spec in EMAIL_SESSIONS:
            await seed_session(db, svc, spec)
        print(f"✓ {len(EMAIL_SESSIONS)} email session(s)")
        for spec in SMS_SESSIONS:
            await seed_session(db, svc, spec)
        print(f"✓ {len(SMS_SESSIONS)} text (SMS) sessions")

        esc_session = await seed_session(db, svc, ESCALATION_SESSION)
        db.add(ConciergeEscalationModel(
            ticket_id="ESC-EMERALD01",
            session_token=esc_session.token,
            guest_name=esc_session.guest_name, guest_phone=esc_session.guest_phone,
            guest_email=esc_session.guest_email,
            property_name=PROPERTIES[ESCALATION_SESSION["code"]][1],
            property_code=ESCALATION_SESSION["code"],
            reason="guest_complaint", priority=ESCALATION_SESSION["priority"], status="pending",
            summary=ESCALATION_SESSION["summary"], last_message=ESCALATION_SESSION["thread"][-1][1],
        ))
        await db.commit()
        print("✓ 1 escalation (text) — ticket ESC-EMERALD01 (priority=high)")

        print("\n" + "=" * 64)
        print(f"✅ Demo company seeded: {COMPANY_NAME}")
        print("=" * 64)
        print("View the dashboard at:  GET /demo")
        print(f"Tenant: {TENANT_ID}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Seed the Emerald Shores Stays demo company (text + email).")
    ap.add_argument("--wipe", action="store_true", help="Only remove this demo company's data.")
    args = ap.parse_args()
    asyncio.run(main(wipe_only=args.wipe))
