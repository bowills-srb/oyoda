#!/usr/bin/env python3
"""
seed_local_dev.py — V1.0 local-development seed
================================================
Loads ONE realistic Gulf Coast (30A) vacation rental — "Beach Habitats" style —
with house rules, FAQs and check-in instructions, plus four realistic guest
conversations at different lifecycle stages:

  1. Pre-booking inquiry        → pre_booking_inquiries (AI-drafted, pending review)
  2. Booked / pre-arrival       → concierge session (phase=pre_arrival) + messages
  3. Active stay + maintenance  → concierge session (phase=in_stay) + messages
  4. Escalated complaint        → concierge session (phase=in_stay) + messages
                                  + concierge_escalations ticket (priority=high)

Everything is scoped to the default local tenant and a single property_code, so
the script is fully idempotent: re-running wipes and re-creates only this demo
property's data.

Prerequisites:
  - Local Postgres up, schema migrated to head (alembic -c alembic.ini upgrade head)
  - DATABASE_URL configured (read automatically from .env.local)

Usage:
  python scripts/seed_local_dev.py            # seed (idempotent)
  python scripts/seed_local_dev.py --wipe     # only remove this demo property's data

After seeding, the operator queue and activity feed will surface this data:
  GET /app/api/messages          (unified operator queue: inquiries + sessions + escalations)
  GET /app/api/v2/realtime       (activity feed — Server-Sent Events stream)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID

# Ensure repo root on path when run as `python scripts/seed_local_dev.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.core.database import get_db_session
from app.services.concierge.db_session_service import DatabaseSessionService
from db.models.concierge_escalations import ConciergeEscalationModel

# ─────────────────────────────────────────────────────────────────────────────
# Constants — single demo property, default local tenant
# ─────────────────────────────────────────────────────────────────────────────
TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")   # DEFAULT_TENANT_ID
PROPERTY_ID = UUID("11111111-1111-1111-1111-111111111111")  # stable demo property id
PROPERTY_CODE = "BH-SEAGLASS-30A"
PROPERTY_NAME = "Sea Glass Cottage"
OPERATOR_NAME = "Beach Habitats 30A"
ADDRESS = "178 Sea Glass Lane, Santa Rosa Beach, FL 32459"
COMMUNITY = "seagrove"
WIFI_NETWORK = "SeaGlass_Guest"
WIFI_PASSWORD = "GulfBreeze30A"

TODAY = date.today()


def qkey(s: str) -> str:
    """Normalize a question into a stable dedupe key."""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:200]


# ─────────────────────────────────────────────────────────────────────────────
# Property knowledge: house rules, FAQs, check-in instructions
# Stored in concierge_scoped_knowledge (scope_type='property').
# ─────────────────────────────────────────────────────────────────────────────
KNOWLEDGE: list[tuple[str, str, str]] = [
    # category, question, answer
    ("check_in",
     "What are the check-in and check-out times?",
     "Check-in is at 4:00 PM and check-out is at 10:00 AM. Early check-in or late "
     "check-out can sometimes be arranged the day before based on the cleaning schedule — "
     "just ask and we'll do our best."),
    ("check_in",
     "How do I get into the house? What is the door code?",
     "Sea Glass Cottage has a smart lock on the front door. Your unique 4-digit code is "
     "sent by text the morning of arrival and works from 4:00 PM on check-in day through "
     "10:00 AM on check-out day. There is no physical key to pick up — just drive straight to "
     "the house."),
    ("check_in",
     "Where do we park?",
     "The driveway fits two vehicles. Please do not park on the street or the grass — Seagrove "
     "HOA actively ticket-tows. Additional guest parking is available at the 30A public lot on "
     "Eastern Lake Road, about a 4-minute walk away."),
    ("wifi",
     "What is the WiFi network and password?",
     f"Network: {WIFI_NETWORK}  •  Password: {WIFI_PASSWORD}. The router is in the hall closet "
     "by the laundry; if WiFi drops, unplug it for 30 seconds and plug it back in."),
    ("house_rules",
     "Is smoking allowed?",
     "Sea Glass Cottage is strictly non-smoking and non-vaping indoors. Smoking is permitted "
     "outdoors only, and please dispose of butts in the metal can by the outdoor shower. A "
     "$350 cleaning fee applies to any indoor smoking."),
    ("house_rules",
     "Can we bring our dog? What's the pet policy?",
     "We love pets! Up to two dogs are welcome with the pre-paid pet fee. Please keep them off "
     "the white furniture, clean up in the yard, and never leave them unattended on the deck. "
     "Cats and other animals are not permitted."),
    ("house_rules",
     "What are the quiet hours and the party policy?",
     "Quiet hours are 10:00 PM to 8:00 AM out of respect for neighbors. Events, parties and "
     "gatherings beyond the booked guest count are not allowed — this is an HOA community with "
     "noise monitoring. Maximum occupancy is 10 guests."),
    ("beach",
     "How do we get to the beach? Is there beach gear?",
     "The Eastern Lake beach access is a 6-minute walk south on Sea Glass Lane. Your stay "
     "includes 2 beach chairs and an umbrella stored in the garage. From March–October, beach "
     "service (set-up chairs) is also available to book directly on the beach."),
    ("pool",
     "Is the pool heated? Can we heat it?",
     "The private plunge pool can be heated to 88°F for an additional nightly fee. Pool heat "
     "must be requested at least 24 hours before arrival so we can turn it on — message us and "
     "we'll add it."),
    ("faq",
     "When is trash pickup and where do the bins go?",
     "Trash is collected Monday and Thursday mornings. Roll the bins to the curb the night "
     "before and return them to the side gate after pickup. Recycling is the blue bin, collected "
     "Thursdays only."),
    ("faq",
     "Where is the nearest grocery store?",
     "Publix at Watercolor Crossings is about 8 minutes away (191 Watercolor Way). For a quick "
     "trip, the Seagrove Village Market Cafe is 3 minutes away and great for fresh seafood."),
]


# ─────────────────────────────────────────────────────────────────────────────
# Conversations
# ─────────────────────────────────────────────────────────────────────────────
# Each in-stay/pre-arrival conversation is a list of (direction, content, intent)
PRE_ARRIVAL_THREAD = [
    ("inbound", "Hi! We're so excited for our stay next week. What time can we check in, and "
                "will we get the door code automatically?", "check_in"),
    ("outbound", "Welcome! Check-in is 4:00 PM. Your personal 4-digit smart-lock code will text "
                 "to you the morning you arrive — no key pickup needed. Anything I can help you "
                 "plan before then?", "check_in"),
    ("inbound", "Perfect. Could we possibly heat the pool for the week?", "pool"),
    ("outbound", "Absolutely — I've noted a pool-heat request. I'll confirm the nightly add-on "
                 "and have it warm (88°F) by your 4 PM arrival. See you soon!", "pool"),
]

IN_STAY_MAINTENANCE_THREAD = [
    ("inbound", "Hey, the AC doesn't seem to be cooling the upstairs bedrooms — it's reading 79 "
                "even though we set it to 72.", "maintenance"),
    ("outbound", "Sorry about that! First, let's try the quick fix: the upstairs unit's filter "
                 "is behind the hallway return vent. Can you check it isn't clogged? Also make "
                 "sure both thermostats are set to COOL, not FAN.", "maintenance"),
    ("inbound", "Filter looks clean and it's set to cool, still not getting cold up here.", "maintenance"),
    ("outbound", "Thanks for checking. I'm dispatching our HVAC tech to take a look — they'll "
                 "reach out shortly to find a time today. In the meantime the downstairs unit is "
                 "running fine, so feel free to keep those doors open.", "maintenance"),
]

ESCALATION_THREAD = [
    ("inbound", "This is unacceptable. The hot water has been out since last night, I have three "
                "kids, and nobody has called me back. We are extremely unhappy.", "complaint"),
    ("outbound", "I am so sorry — cold showers with kids is exactly the kind of thing we never "
                 "want. I'm escalating this to our team right now and someone will call you within "
                 "15 minutes with a plan.", "complaint"),
]


async def wipe(db) -> None:
    """Remove this demo property's data so the seed is idempotent."""
    stmts = [
        # children of sessions first
        text("DELETE FROM concierge_messages WHERE session_id IN "
             "(SELECT session_id FROM concierge_guest_sessions WHERE tenant_id=:t AND property_code=:c)"),
        text("DELETE FROM concierge_journey_activities WHERE journey_id IN "
             "(SELECT journey_id FROM concierge_guest_journeys WHERE session_id IN "
             "(SELECT session_id FROM concierge_guest_sessions WHERE tenant_id=:t AND property_code=:c))"),
        text("DELETE FROM concierge_guest_journeys WHERE session_id IN "
             "(SELECT session_id FROM concierge_guest_sessions WHERE tenant_id=:t AND property_code=:c)"),
        text("DELETE FROM concierge_escalations WHERE property_code=:c"),
        text("DELETE FROM concierge_guest_sessions WHERE tenant_id=:t AND property_code=:c"),
        text("DELETE FROM pre_booking_inquiries WHERE property_external_id=:c"),
        text("DELETE FROM concierge_scoped_knowledge WHERE tenant_id=:t AND scope_target_id=:pid"),
        text("DELETE FROM properties WHERE tenant_id=:t AND property_code=:c"),
    ]
    # guest_threads cleanup is best-effort (column names vary across versions)
    optional = [
        text("DELETE FROM guest_threads WHERE tenant_id=:t AND property_code=:c"),
    ]
    params = {"t": str(TENANT_ID), "c": PROPERTY_CODE, "pid": str(PROPERTY_ID)}
    for s in stmts:
        await db.execute(s, params)
    for s in optional:
        try:
            await db.execute(s, params)
        except Exception:
            pass
    await db.commit()


async def seed_property(db) -> None:
    """Insert the demo property. Enum/jsonb columns not set here use their
    schema defaults (property_type, lock_type, data_source, amenities, etc.)."""
    await db.execute(
        text(
            """
            INSERT INTO properties (
                id, tenant_id, property_code,
                address_street, address_city, address_state, address_zip,
                bedrooms, bathrooms, sleeps, max_occupancy,
                wifi_network, wifi_password, wifi_router_location,
                check_in_time, check_out_time,
                check_in_instructions, parking_spaces, parking_instructions,
                has_pool, pool_heated, has_beach_gear, has_grill, has_washer_dryer,
                pets_allowed, smoking_allowed, events_allowed,
                quiet_hours_start, quiet_hours_end,
                rules, general_notes, confidence_score
            ) VALUES (
                :id, :t, :code,
                :addr, :city, :state, :zip,
                :bedrooms, :bathrooms, :sleeps, :maxocc,
                :wifi_net, :wifi_pw, :router_loc,
                :cin_time, :cout_time,
                :cin_instr, :parking_spaces, :parking_instr,
                true, true, true, true, true,
                true, false, false,
                :qh_start, :qh_end,
                CAST(:rules AS jsonb), :notes, 0.95
            )
            """
        ),
        {
            "id": str(PROPERTY_ID), "t": str(TENANT_ID), "code": PROPERTY_CODE,
            "addr": ADDRESS, "city": "Santa Rosa Beach", "state": "FL", "zip": "32459",
            "bedrooms": 4, "bathrooms": 3.5, "sleeps": 10, "maxocc": 10,
            "wifi_net": WIFI_NETWORK, "wifi_pw": WIFI_PASSWORD,
            "router_loc": "Hall closet by the laundry",
            "cin_time": "4:00 PM", "cout_time": "10:00 AM",
            "cin_instr": ("Smart lock on the front door. A unique 4-digit code is texted the "
                          "morning of arrival and is active from 4:00 PM check-in day through "
                          "10:00 AM check-out day."),
            "parking_spaces": 2,
            "parking_instr": ("Driveway fits two vehicles. No street or grass parking (Seagrove "
                              "HOA tows). Overflow at the 30A public lot on Eastern Lake Road."),
            "qh_start": "22:00", "qh_end": "08:00",
            "rules": json.dumps([
                "No smoking or vaping indoors ($350 fee).",
                "Up to two dogs welcome with pet fee; no other animals.",
                "Quiet hours 10:00 PM - 8:00 AM.",
                "No parties or events; maximum occupancy 10 guests.",
            ]),
            "notes": "4BR/3.5BA Gulf-front cottage on 30A with a private heated plunge pool.",
        },
    )
    await db.commit()


async def seed_knowledge(db) -> int:
    for category, question, answer in KNOWLEDGE:
        await db.execute(
            text(
                """
                INSERT INTO concierge_scoped_knowledge (
                    tenant_id, scope_type, scope_target_id, topic_id,
                    question_text, question_key, answer_text, tags, source, metadata
                ) VALUES (
                    :t, 'property', :pid, NULL,
                    :q, :qk, :a,
                    CAST(:tags AS jsonb), 'guidebook_import', CAST(:meta AS jsonb)
                )
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "t": str(TENANT_ID), "pid": str(PROPERTY_ID),
                "q": question, "qk": qkey(question), "a": answer,
                "tags": f'["{category}"]',
                "meta": f'{{"category": "{category}", "seed_source": "seed_local_dev"}}',
            },
        )
    await db.commit()
    return len(KNOWLEDGE)


async def seed_pre_booking_inquiry(db) -> None:
    """Stage 1: a pre-booking inquiry with an AI draft awaiting operator review."""
    await db.execute(
        text(
            """
            INSERT INTO pre_booking_inquiries (
                draft_id, thread_id, company_id, tenant_id, platform,
                guest_name, guest_email, message_text, draft_text,
                property_external_id, intent, confidence, intent_confidence, draft_confidence,
                status, send_decision, approval_mode,
                autonomy_decision, confidence_source,
                requested_check_in, requested_check_out, requested_guests, triggered_by
            ) VALUES (
                :draft_id, :thread_id, :t, :t, 'vrbo',
                :guest, :email, :msg, :draft,
                :code, 'availability', 0.62, 0.81, 0.62,
                'pending_review', 'review', 'required',
                'routed_to_action_below_threshold', 'model_composer',
                :cin, :cout, 6, 'inbound_inquiry'
            )
            """
        ),
        {
            "draft_id": "seed-prebooking-0001",
            "thread_id": "seed-thread-prebooking-0001",
            "t": str(TENANT_ID),
            "guest": "Jessica Martin",
            "email": "jessica.martin@example.com",
            "msg": ("Hi! Is Sea Glass Cottage available July 12–18 for 6 guests? We'd have two "
                    "small dogs — is that okay, and what's the pet fee? Also is the pool heated?"),
            "draft": ("Hi Jessica! Yes, Sea Glass Cottage is available July 12–18 and comfortably "
                      "sleeps your group. We're happy to welcome up to two dogs with our pet fee, "
                      "and the private plunge pool can be heated to 88°F for a nightly add-on. "
                      "Would you like me to send a booking link?"),
            "code": PROPERTY_CODE,
            "cin": TODAY + timedelta(days=29),
            "cout": TODAY + timedelta(days=35),
        },
    )
    await db.commit()


async def seed_session(db, svc, *, guest_name, guest_email, guest_phone,
                       check_in, check_out, thread) -> object:
    """Create a concierge session and replay its message thread."""
    session = await svc.create_session(
        db,
        property_id=PROPERTY_ID,
        property_code=PROPERTY_CODE,
        property_name=PROPERTY_NAME,
        guest_name=guest_name,
        guest_phone=guest_phone,
        guest_email=guest_email,
        check_in=check_in,
        check_out=check_out,
        num_guests=4,
    )
    for direction, content, intent in thread:
        await svc.add_message(
            db, session.session_id, direction=direction, content=content,
            detected_intent=intent,
        )
    return session


async def seed_escalation(db, session, *, summary, last_message) -> str:
    ticket_id = "ESC-SEAGLASS01"
    db.add(
        ConciergeEscalationModel(
            ticket_id=ticket_id,
            session_token=session.token,
            guest_name=session.guest_name,
            guest_phone=session.guest_phone,
            guest_email=session.guest_email,
            property_name=PROPERTY_NAME,
            property_code=PROPERTY_CODE,
            reason="guest_complaint",
            priority="high",
            status="pending",
            summary=summary,
            last_message=last_message,
        )
    )
    await db.commit()
    return ticket_id


async def main(wipe_only: bool) -> None:
    async with get_db_session() as db:
        print(f"→ Wiping existing demo data for {PROPERTY_CODE} (tenant {TENANT_ID})…")
        await wipe(db)
        if wipe_only:
            print("✓ Wipe complete (--wipe). Nothing seeded.")
            return

        print(f"→ Seeding property: {PROPERTY_NAME} [{PROPERTY_CODE}]")
        await seed_property(db)

        n_kb = await seed_knowledge(db)
        print(f"✓ Seeded {n_kb} knowledge entries (house rules, FAQs, check-in)")

        await seed_pre_booking_inquiry(db)
        print("✓ Seeded 1 pre-booking inquiry (pending_review)")

        svc = DatabaseSessionService(TENANT_ID)

        # Stage 2 — booked / pre-arrival
        await seed_session(
            db, svc,
            guest_name="The Whitfield Family", guest_email="whitfield@example.com",
            guest_phone="+18505550142",
            check_in=TODAY + timedelta(days=10), check_out=TODAY + timedelta(days=15),
            thread=PRE_ARRIVAL_THREAD,
        )
        print("✓ Seeded session: pre-arrival (booked, upcoming)")

        # Stage 3 — active stay with a maintenance issue
        await seed_session(
            db, svc,
            guest_name="Marcus Bell", guest_email="marcus.bell@example.com",
            guest_phone="+18505550178",
            check_in=TODAY - timedelta(days=2), check_out=TODAY + timedelta(days=3),
            thread=IN_STAY_MAINTENANCE_THREAD,
        )
        print("✓ Seeded session: in-stay + maintenance issue (AC)")

        # Stage 4 — escalated complaint
        esc_session = await seed_session(
            db, svc,
            guest_name="Dana Reyes", guest_email="dana.reyes@example.com",
            guest_phone="+18505550199",
            check_in=TODAY - timedelta(days=1), check_out=TODAY + timedelta(days=4),
            thread=ESCALATION_THREAD,
        )
        ticket = await seed_escalation(
            db, esc_session,
            summary="No hot water since last night; guest with three children, very upset. "
                    "Plumber dispatch required.",
            last_message=ESCALATION_THREAD[-1][1],
        )
        print(f"✓ Seeded session: escalated complaint + escalation ticket {ticket} (priority=high)")

        print()
        print("=" * 70)
        print("✅ Local seed complete.")
        print("=" * 70)
        print("Operator queue : GET /app/api/messages   (inquiries + sessions + escalations)")
        print("Activity feed  : GET /app/api/v2/realtime (Server-Sent Events stream)")
        print(f"Tenant         : {TENANT_ID}")
        print(f"Property       : {PROPERTY_NAME} [{PROPERTY_CODE}]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Seed one Gulf Coast property + 4 conversations for local dev.")
    ap.add_argument("--wipe", action="store_true", help="Only remove this demo property's data; do not seed.")
    args = ap.parse_args()
    asyncio.run(main(wipe_only=args.wipe))
