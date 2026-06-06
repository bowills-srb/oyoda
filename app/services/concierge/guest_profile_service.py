"""
PRESERVATION STATUS (post-Phase-1, 2026-05-23):
This module is preserved for future product surface (pre-arrival,
in-stay, multi-guest, returning-guest personalization, BD-aware
messaging, etc.). It is not currently part of the active brain
runtime path. Do not delete in subsequent phases unless explicitly
retired by product decision.

When the relevant product surface is wired into the brain, this
module relocates to the appropriate messaging_brain/ subdirectory
and stops being marked as preserved.

Guest Profile Service

Manages the lifecycle of GuestProfileModel records:

  1. lookup(tenant_id, phone, email) → profile or None
  2. get_or_create(...)              → always returns a profile
  3. close_stay(session)             → called on checkout / feedback submission
                                       updates history, CSAT arc, preference signals
  4. build_concierge_context(...)    → returns dict injected into AI concierge

The service is intentionally stateless — no singleton — so it can be called
from any async context (FastAPI endpoints, background tasks, Celery workers).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.guest_profiles import GuestProfileModel, MAX_STAY_HISTORY

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def lookup_guest_profile(
    db: AsyncSession,
    tenant_id: str,
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> Optional[GuestProfileModel]:
    """
    Find an existing guest profile by phone (preferred) or email.
    Returns None if this is a first-time guest.
    """
    if not phone and not email:
        return None

    # Normalise: strip spaces / dashes from phone
    norm_phone = _normalise_phone(phone) if phone else None

    if norm_phone:
        row = (await db.execute(
            select(GuestProfileModel).where(
                GuestProfileModel.tenant_id == tenant_id,
                GuestProfileModel.phone     == norm_phone,
            )
        )).scalar_one_or_none()
        if row:
            return row

    if email:
        row = (await db.execute(
            select(GuestProfileModel).where(
                GuestProfileModel.tenant_id == tenant_id,
                GuestProfileModel.email     == email.lower().strip(),
            )
        )).scalar_one_or_none()
        if row:
            return row

    return None


async def get_or_create_profile(
    db: AsyncSession,
    tenant_id: str,
    phone: Optional[str],
    email: Optional[str],
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> tuple[GuestProfileModel, bool]:
    """
    Returns (profile, created).
    created=True  → brand new profile (first-time guest)
    created=False → existing profile (returning guest)
    """
    existing = await lookup_guest_profile(db, tenant_id, phone, email)
    if existing:
        return existing, False

    profile = GuestProfileModel(
        tenant_id   = tenant_id,
        phone       = _normalise_phone(phone) if phone else None,
        email       = email.lower().strip() if email else None,
        first_name  = first_name,
        last_name   = last_name,
        total_stays = 0,
        total_nights= 0,
        stay_history= [],
    )
    db.add(profile)
    await db.flush()   # get profile_id without committing
    logger.info(f"[GuestProfile] Created new profile for {first_name} ({tenant_id})")
    return profile, True


async def close_stay(
    db: AsyncSession,
    tenant_id: str,
    session_token: str,
    phone: Optional[str],
    email: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    property_code: str,
    property_name: str,
    reservation_id: str,
    check_in_str: str,           # ISO date string
    check_out_str: str,          # ISO date string
    nights: int,
    num_guests: int,
    csat: Optional[int],
    would_recommend: Optional[bool],
    feedback_text: Optional[str],
    upsells_booked: Optional[list] = None,
    escalation_reasons: Optional[list] = None,
) -> GuestProfileModel:
    """
    Called on checkout or feedback submission.
    Upserts the guest profile and appends this stay to the history.
    Also updates rolling CSAT average, preference signals, upsell history.
    """
    profile, _ = await get_or_create_profile(
        db, tenant_id, phone, email, first_name, last_name
    )

    now = datetime.now(tz=timezone.utc)

    # ── Build stay record ─────────────────────────────────────────────────────
    stay_record: dict = {
        "session_token":   session_token,
        "reservation_id":  reservation_id,
        "property_code":   property_code,
        "property_name":   property_name,
        "check_in":        check_in_str,
        "check_out":       check_out_str,
        "nights":          nights,
        "num_guests":      num_guests,
        "csat":            csat,
        "would_recommend": would_recommend,
        "feedback_text":   feedback_text,
        "upsells_booked":  upsells_booked or [],
        "escalations":     escalation_reasons or [],
        "closed_at":       now.isoformat(),
    }

    # ── Prepend and cap history ───────────────────────────────────────────────
    history: list = list(profile.stay_history or [])
    history.insert(0, stay_record)
    if len(history) > MAX_STAY_HISTORY:
        history = history[:MAX_STAY_HISTORY]
    profile.stay_history = history

    # ── Update counters ───────────────────────────────────────────────────────
    profile.total_stays  = (profile.total_stays or 0) + 1
    profile.total_nights = (profile.total_nights or 0) + nights

    # Rolling party-size average
    n = profile.total_stays
    prev_avg = profile.avg_party_size or num_guests
    profile.avg_party_size = round(prev_avg + (num_guests - prev_avg) / n, 1)

    # ── CSAT arc ──────────────────────────────────────────────────────────────
    if csat is not None:
        prev_csat = profile.avg_csat or csat
        profile.avg_csat  = round(prev_csat + (csat - prev_csat) / n, 2)
        profile.last_csat = csat
        # Trend: compare this stay to rolling average before this stay
        if csat > prev_csat + 0.3:
            profile.csat_trend = "up"
        elif csat < prev_csat - 0.3:
            profile.csat_trend = "down"
        else:
            profile.csat_trend = "flat"

    # Recommend rate
    if would_recommend is not None:
        prev_rate = profile.recommend_rate
        if prev_rate is None:
            profile.recommend_rate = 1.0 if would_recommend else 0.0
        else:
            profile.recommend_rate = round(
                prev_rate + (int(would_recommend) - prev_rate) / n, 2
            )

    # ── Preference signals from upsells ──────────────────────────────────────
    if upsells_booked:
        ever = set(profile.upsells_ever_booked or [])
        ever.update(upsells_booked)
        profile.upsells_ever_booked = sorted(ever)
        profile.upsell_count = (profile.upsell_count or 0) + len(upsells_booked)

        # Mirror to preferences.upsells for concierge context
        prefs: dict = dict(profile.preferences or {})
        prefs["upsells"] = profile.upsells_ever_booked
        profile.preferences = prefs

    # ── Escalation signals ────────────────────────────────────────────────────
    if escalation_reasons:
        profile.escalation_count = (profile.escalation_count or 0) + len(escalation_reasons)
        profile.last_escalation_reason = escalation_reasons[-1]

    # ── Timestamps ───────────────────────────────────────────────────────────
    if profile.first_stay_at is None:
        profile.first_stay_at = now
    profile.last_stay_at = now

    await db.flush()
    logger.info(
        f"[GuestProfile] Updated profile {profile.profile_id} — "
        f"stay #{profile.total_stays}, CSAT={csat}, upsells={upsells_booked}"
    )
    return profile


async def build_concierge_context(
    db: AsyncSession,
    tenant_id: str,
    phone: Optional[str],
    email: Optional[str],
) -> dict:
    """
    Called at session-creation time.
    Returns a dict that gets merged into GuestSession.property_context
    (or injected directly into the concierge system prompt).
    Returns empty dict for first-time guests — zero overhead.
    """
    profile = await lookup_guest_profile(db, tenant_id, phone, email)
    if not profile or profile.total_stays == 0:
        return {}

    ctx = profile.to_concierge_context()
    ctx["prompt_snippet"] = profile.to_prompt_snippet()
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard / operator endpoints
# ─────────────────────────────────────────────────────────────────────────────

async def list_guest_profiles(
    db: AsyncSession,
    tenant_id: str,
    min_stays: int = 2,
    limit: int = 100,
    offset: int = 0,
) -> list[GuestProfileModel]:
    """
    List repeat guests for the operator dashboard.
    Default: only guests with 2+ stays (the interesting segment).
    """
    rows = (await db.execute(
        select(GuestProfileModel)
        .where(
            GuestProfileModel.tenant_id   == tenant_id,
            GuestProfileModel.total_stays >= min_stays,
        )
        .order_by(GuestProfileModel.last_stay_at.desc())
        .limit(limit)
        .offset(offset)
    )).scalars().all()
    return list(rows)


async def update_guest_preferences(
    db: AsyncSession,
    tenant_id: str,
    profile_id: str,
    preference_patch: dict,
) -> Optional[GuestProfileModel]:
    """
    Merge operator-supplied preference notes into a guest profile.
    The operator can add custom_notes, dietary info, travel type, etc.
    """
    import uuid
    profile = (await db.execute(
        select(GuestProfileModel).where(
            GuestProfileModel.tenant_id  == tenant_id,
            GuestProfileModel.profile_id == uuid.UUID(profile_id),
        )
    )).scalar_one_or_none()

    if not profile:
        return None

    merged = dict(profile.preferences or {})
    merged.update(preference_patch)
    profile.preferences = merged
    await db.flush()
    return profile


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_phone(phone: str) -> str:
    """Strip everything except digits, then store E.164-ish (+1XXXXXXXXXX)."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        digits = "1" + digits
    return "+" + digits if digits else phone.strip()
