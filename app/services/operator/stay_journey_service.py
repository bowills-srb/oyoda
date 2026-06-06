from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.concierge.db_session_service import DatabaseSessionService
from app.services.operator.stay_action_agent import StayActionAgent, get_stay_action_agent
from app.services.operator.stay_workflow_service import get_stay_workflow_service


BEACH_CHAIR_PROVIDERS = [
    {
        "name": "La Dolce Vita Beach Services",
        "phone": "(850) 267-1444",
        "website": "https://www.ldvbeach.com",
        "desc": "Premium beach setups - chairs, umbrellas, cabanas. Most popular on 30A. Book early for peak season!",
        "booking_lead_days": 60,
    },
    {
        "name": "Beach Chair Guys",
        "phone": "(850) 419-4862",
        "website": "https://www.beachchairguys.com",
        "desc": "Reliable beach chair and umbrella rentals. Good availability.",
        "booking_lead_days": 30,
    },
    {
        "name": "Rent Gear Here",
        "phone": "(850) 837-4992",
        "website": "https://www.rentgearhere.com",
        "desc": "Beach chairs, umbrellas, kayaks, paddleboards, and more.",
        "booking_lead_days": 14,
    },
]

FISHING_CHARTERS = [
    {
        "name": "Destin Charter Fishing",
        "phone": "(850) 837-2320",
        "website": "https://www.destincharterfishing.com",
        "desc": "Deep sea fishing out of Destin Harbor. Half-day and full-day trips. Great for families.",
        "booking_lead_days": 14,
    },
    {
        "name": "Charter Boat Backlash",
        "phone": "(850) 585-4747",
        "website": "https://www.charterboatbacklash.com",
        "desc": "Inshore and offshore fishing. Captain has 30+ years experience.",
        "booking_lead_days": 7,
    },
    {
        "name": "YOLO Board & Kayak Fishing",
        "phone": "(850) 534-0059",
        "website": None,
        "desc": "Kayak fishing trips on Western Lake and the Gulf. Unique experience!",
        "booking_lead_days": 3,
    },
]

GOLF_COURSES = [
    {
        "name": "Camp Creek Golf Club",
        "phone": "(850) 231-7600",
        "website": "https://www.campcreekgolfclub.com",
        "desc": "Tom Fazio designed. Premier course on 30A. Book tee times well in advance.",
        "booking_lead_days": 30,
    },
    {
        "name": "Santa Rosa Golf & Beach Club",
        "phone": "(850) 267-2229",
        "website": "https://www.santarosagolfbeachclub.com",
        "desc": "Beautiful course with Gulf views. More accessible tee times.",
        "booking_lead_days": 7,
    },
    {
        "name": "Emerald Bay Golf Club",
        "phone": "(850) 837-5197",
        "website": "https://www.emeraldbaygolfclub.com",
        "desc": "In Destin, about 25 min drive. Good value, well-maintained.",
        "booking_lead_days": 3,
    },
]

BIKE_RENTALS = [
    {
        "name": "YOLO Board & Bike",
        "phone": "(850) 534-0059",
        "website": None,
        "desc": "Located in WaterColor Town Center. Beach cruisers, kids bikes, trailers. They deliver!",
        "booking_lead_days": 3,
    },
    {
        "name": "30A Bike Rentals",
        "phone": "(850) 231-0606",
        "website": "https://www.30abikerentals.com",
        "desc": "Free delivery to your rental. Beach cruisers, tandems, kids bikes.",
        "booking_lead_days": 3,
    },
    {
        "name": "Big Daddy's Bike Shop",
        "phone": "(850) 622-1766",
        "website": None,
        "desc": "Local shop in Seagrove. Repairs and rentals.",
        "booking_lead_days": 1,
    },
]

PONTOON_BOAT_RENTALS = [
    {
        "name": "Paradise Boat Rentals",
        "phone": "(850) 837-1997",
        "website": "https://www.paradiseboatrentals.com",
        "desc": "Pontoon boats out of Destin Harbor. Half-day and full-day. No license needed!",
        "booking_lead_days": 7,
    },
    {
        "name": "Crab Island Cruises",
        "phone": "(850) 269-5836",
        "website": None,
        "desc": "Pontoon trips to famous Crab Island sandbar. Fun for families!",
        "booking_lead_days": 3,
    },
]

DOLPHIN_TOURS = [
    {
        "name": "Southern Star Dolphin Cruise",
        "phone": "(850) 837-7741",
        "website": "https://www.southernstardolphincruise.com",
        "desc": "Glass-bottom boat dolphin tours from Destin Harbor. Great for kids!",
        "booking_lead_days": 1,
    },
    {
        "name": "Destin Dolphin Watch",
        "phone": "(850) 654-4400",
        "website": None,
        "desc": "Dolphin cruises with high sighting success rate.",
        "booking_lead_days": 1,
    },
]

SPA_SERVICES = [
    {
        "name": "WaterColor Inn Spa",
        "phone": "(850) 534-5050",
        "website": None,
        "desc": "Full-service spa at WaterColor. Massages, facials, body treatments.",
        "booking_lead_days": 7,
    },
    {
        "name": "Alys Spa",
        "phone": "(850) 213-5700",
        "website": None,
        "desc": "Luxury spa at Alys Beach. Couples treatments available.",
        "booking_lead_days": 7,
    },
]

GROCERY_DELIVERY = [
    {
        "name": "Publix Delivery (via Instacart)",
        "phone": None,
        "website": "https://www.instacart.com",
        "desc": "Order from Publix, delivered same-day. Use your property address.",
        "booking_lead_days": 0,
    },
    {
        "name": "30A Concierge Services",
        "phone": "(850) 231-3030",
        "website": None,
        "desc": "Personal grocery shopping and stocking. They'll have everything ready when you arrive!",
        "booking_lead_days": 3,
    },
]

ACTIVITY_PROVIDERS = {
    "beach_chairs": BEACH_CHAIR_PROVIDERS,
    "fishing": FISHING_CHARTERS,
    "golf": GOLF_COURSES,
    "bikes": BIKE_RENTALS,
    "pontoon": PONTOON_BOAT_RENTALS,
    "dolphin": DOLPHIN_TOURS,
    "spa": SPA_SERVICES,
    "groceries": GROCERY_DELIVERY,
}


def _first_name(name: str) -> str:
    parts = [part for part in str(name or "").strip().split() if part]
    return parts[0] if parts else "there"


def _activity_payload(activity: Any) -> dict[str, Any]:
    return {
        "activity_type": getattr(activity, "activity_type", None),
        "status": getattr(activity, "status", None),
        "discussed_at": getattr(activity, "discussed_at", None).isoformat()
        if getattr(activity, "discussed_at", None)
        else None,
        "notes": getattr(activity, "notes", None),
    }


def get_season_demand(check_in: date) -> str:
    month = check_in.month
    day = check_in.day
    if month in [6, 7]:
        return "peak"
    if month == 3 and day >= 10:
        return "peak"
    if month == 12 and day >= 20:
        return "high"
    if month == 11 and 20 <= day <= 30:
        return "high"
    if month in [4, 5, 8, 9, 10]:
        return "moderate"
    return "low"


def get_activity_info_text(activity_type: str, check_in: date) -> str:
    providers = ACTIVITY_PROVIDERS.get(activity_type, [])
    if not providers:
        return "I don't have specific providers for that, but I'm happy to help you search!"

    days_until = (check_in - date.today()).days
    season = get_season_demand(check_in)
    intros = {
        "beach_chairs": "Beach chair and umbrella setups are the way to go on 30A! Here are the local providers I recommend:",
        "fishing": "Fishing out of Destin is incredible! Here are some great local charter options:",
        "golf": "30A has some beautiful courses! Here are my recommendations:",
        "bikes": "Biking the 30A path is one of the best ways to explore! These local shops deliver right to your door:",
        "pontoon": "Pontoon boats are so fun - cruise to Crab Island or explore the harbor! Here are local rental options:",
        "dolphin": "Dolphin tours are a family favorite! Here are the local options:",
        "spa": "A spa day sounds perfect! Here are the best options nearby:",
        "groceries": "Great idea to have groceries waiting when you arrive! Here's how:",
    }
    intro = intros.get(activity_type, "Here are some options:")
    lines = [intro, ""]
    for i, provider in enumerate(providers, 1):
        lines.append(f"**{i}. {provider['name']}**")
        lines.append(f"   {provider['desc']}")
        if provider.get("phone"):
            lines.append(f"   📞 {provider['phone']}")
        if provider.get("website"):
            lines.append(f"   🌐 {provider['website']}")
        lines.append("")
    if season in ["peak", "high"] and providers[0].get("booking_lead_days", 0) > 0:
        lead_days = providers[0]["booking_lead_days"]
        if days_until <= lead_days:
            lines.append(f"⚠️ **Heads up:** During {check_in.strftime('%B')}, these book up fast! I'd recommend reaching out soon.")
        elif days_until <= lead_days + 14:
            lines.append(f"💡 **Tip:** For {check_in.strftime('%B')} visits, booking {lead_days}+ days ahead is a good idea.")
    return "\n".join(lines)


def get_welcome_message_text(guest_name: str, property_name: str, check_in: date, check_out: date) -> str:
    days_until = (check_in - date.today()).days
    season = get_season_demand(check_in)
    date_str = check_in.strftime("%B %d")
    if check_in.year != date.today().year:
        date_str = check_in.strftime("%B %d, %Y")

    msg = f"""Hi {guest_name}! 🏖️

Welcome to **{property_name}**! I'm Coral, your Beach Habitats concierge.

I'm here to help make your stay as enjoyable as possible - from booking beach chairs to finding the best local restaurants."""

    if season in ["peak", "high"] and days_until >= 14:
        msg += f"""

📅 Quick tip for your {check_in.strftime('%B')} trip: A few things book up fast during this time - especially beach chair setups, fishing charters, and popular restaurants. Happy to help you get those sorted whenever you're ready!"""

    msg += """

Is there anything specific you'd like help with before your arrival? Golf tee times, fishing excursions, beach rentals, restaurant recommendations - just let me know!"""
    return msg


def get_extend_stay_offer_text(guest_name: str, property_name: str, check_out: date) -> str:
    extra_night_date = check_out.strftime("%A, %B %d")
    return f"""Hi {guest_name}! 🌟

Not ready to leave {property_name} just yet? Good news - we don't have anyone arriving tomorrow, so you're welcome to extend your stay!

🎁 **Special offer: 10% off** if you'd like to add {extra_night_date}.

Just let me know if you're interested and I'll take care of the details. No pressure either way - hope you've had an amazing trip!"""


def get_pool_heat_info_text() -> str:
    return """Your property has a **heated pool** option! 🏊‍♂️

Pool heating is **$50/day** and needs to be requested at least 48 hours before you want it turned on. It makes a big difference in the cooler months!

Would you like me to add pool heat to your stay?"""


async def _load_session_by_token(
    db: AsyncSession,
    token: str,
):
    bootstrap = DatabaseSessionService(UUID("00000000-0000-0000-0000-000000000001"))
    session_row = await bootstrap.get_session_by_token(db, token, tenant_agnostic=True)
    if not session_row:
        return None, None
    scoped = DatabaseSessionService(session_row.tenant_id)
    return session_row, scoped


async def get_journey_summary_by_token(
    db: AsyncSession,
    token: str,
) -> Optional[dict[str, Any]]:
    session_row, scoped = await _load_session_by_token(db, token)
    if not session_row or not scoped:
        return None

    journey = await scoped.get_journey(db, session_row.session_id)
    if not journey:
        return None

    not_discussed: list[str] = []
    info_provided: list[str] = []
    booked_or_handled: list[str] = []
    declined: list[str] = []
    activities = getattr(journey, "activities", None) or []
    for activity in activities:
        status = str(getattr(activity, "status", "") or "").lower()
        activity_type = str(getattr(activity, "activity_type", "") or "")
        if not activity_type:
            continue
        if status == "not_discussed":
            not_discussed.append(activity_type)
        elif status == "info_provided":
            info_provided.append(activity_type)
        elif status in {"booked", "handled"}:
            booked_or_handled.append(activity_type)
        elif status == "not_interested":
            declined.append(activity_type)

    days_until_checkin = (session_row.check_in - date.today()).days if session_row.check_in else None
    return {
        "session_token": token,
        "guest_name": session_row.guest_name,
        "property_name": session_row.property_name,
        "check_in": session_row.check_in.isoformat() if session_row.check_in else None,
        "days_until_checkin": days_until_checkin,
        "welcome_sent": bool(getattr(journey, "welcome_sent", False)),
        "discussed": info_provided,
        "booked_or_handled": booked_or_handled,
        "declined": declined,
        "not_discussed": not_discussed,
    }


async def update_activity_status_by_token(
    db: AsyncSession,
    token: str,
    *,
    activity_type: str,
    status: str,
    notes: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    session_row, scoped = await _load_session_by_token(db, token)
    if not session_row or not scoped:
        return None

    journey = await scoped.get_journey(db, session_row.session_id)
    if not journey:
        return None

    updated = await scoped.update_activity_status(
        db,
        journey.journey_id,
        activity_type,
        status,
        notes=notes,
    )
    if not updated:
        return None

    refreshed = await scoped.get_journey(db, session_row.session_id)
    activities = getattr(refreshed, "activities", None) or []
    match = next(
        (activity for activity in activities if str(getattr(activity, "activity_type", "") or "") == activity_type),
        None,
    )
    return _activity_payload(match) if match else None


async def get_canonical_proactive_preview_by_token(
    db: AsyncSession,
    token: str,
    *,
    allowed_touch_types: Iterable[str],
) -> Optional[dict[str, Any]]:
    session_row, _scoped = await _load_session_by_token(db, token)
    if not session_row:
        return None

    tenant_id = str(session_row.tenant_id)
    session_id = str(session_row.session_id)
    await get_stay_workflow_service().sync_session(db, tenant_id, session_id)
    action_map = await get_stay_action_agent().list_actions(db, tenant_id, [session_id])
    actions = action_map.get(session_id) or []
    allowed = {str(item).strip().lower() for item in allowed_touch_types if str(item).strip()}
    proactive = next(
        (
            item
            for item in actions
            if str(item.get("action_type") or "") == StayActionAgent.ACTION_PROACTIVE
            and str(((item.get("payload") or {}).get("touch_type") or "")).strip().lower() in allowed
        ),
        None,
    )
    if not proactive:
        return None

    payload = proactive.get("payload") if isinstance(proactive.get("payload"), dict) else {}
    message_text = str(payload.get("message_text") or "").strip()
    if not message_text:
        return None
    return {
        "message": message_text,
        "touch_type": str(payload.get("touch_type") or ""),
        "status": str(proactive.get("status") or ""),
        "guest_name": _first_name(session_row.guest_name),
        "property_name": session_row.property_name,
    }


async def get_activity_info_by_token(
    db: AsyncSession,
    token: str,
    *,
    activity_type: str,
) -> Optional[str]:
    session_row, scoped = await _load_session_by_token(db, token)
    if not session_row or not scoped:
        return None

    info = get_activity_info_text(activity_type, session_row.check_in)

    journey = await scoped.get_journey(db, session_row.session_id)
    if journey:
        await scoped.update_activity_status(
            db,
            journey.journey_id,
            activity_type,
            "info_provided",
        )
    return info
