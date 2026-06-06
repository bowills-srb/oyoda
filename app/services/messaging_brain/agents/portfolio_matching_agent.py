"""
portfolio_matching_agent.py — Portfolio retrieval executor.

Architecture (decider / answerer split):
  INTAKE CLASSIFIER (LLMIntakeAgent) normalizes the guest message and
    extracts structured constraints into classification.extracted_constraints
    with a portfolio_search block (anchor_property, compare_on, date_window).
  RETRIEVAL EXECUTOR (this file — deterministic SQL) runs ONE set-based
    anti-join against canonical pms_listings / pms_bookings tables and
    returns structured candidate facts.
  LLM COMPOSER (LLMComposerAgent) drafts the guest-facing reply from those
    facts. It judges "similar," hedges unverified fields, and produces prose.

The executor:
  - Runs the query the classifier produced. Does NOT compose prose.
  - Does NOT detect portfolio intent from message text (intake did that).
  - Does NOT interpret "similar" (composer does that with facts).
  - Does NOT filter on schema-unsupported constraints (party_size, golf_cart,
    exact community, price point). Those are returned as "unverified" so the
    composer can hedge.

Tables (canonical — written by pms_ingest_worker):
  pms_listings : company_id, external_id, property_name, city, state,
                 latitude, longitude, bedrooms, bathrooms, has_pool,
                 pool_heated, has_waterfront, beach_access, pet_friendly,
                 is_active, listing_status, last_synced_at
  pms_bookings : company_id, listing_id (→ pms_listings.id), check_in,
                 check_out, status

A1 BUG (FIXED): legacy code queried FROM properties / FROM bookings.
  Canonical tables are pms_listings / pms_bookings.  Wrong tables meant
  wrong column names (tenant_id → company_id), wrong date columns
  (start_date/end_date → check_in/check_out).

SCALE (FIXED): legacy code issued one COUNT(*) per candidate property.
  At 1,000 units = 1,000 queries/message.  Replaced with a single
  anti-join NOT EXISTS that scales to arbitrarily large portfolios.

Fail-safe behavior (CRITICAL — Beach Habitats has NO PMS data yet):
  pms_listings / pms_bookings are EMPTY for operators who have not connected
  their PMS.  The retrieval distinguishes three empty cases:
    no_portfolio_data  pms_listings has NO rows for this company (never synced)
    no_candidates      listings exist but none match / are available
    stale_hold         newest last_synced_at is older than FRESHNESS_THRESHOLD_HOURS

  "Nothing available" is only correct for no_candidates.
  The other two must produce "let me confirm / follow up" language.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    GuestContextBundle,
    InboundGuestMessage,
    MessageClassification,
    RecommendedAction,
)

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

#: Hard cap on candidate set delivered to the LLM composer.
RESULT_LIMIT: int = 8

#: Stale-sync threshold.  Availability off a stale cache can be wrong.
#: Hold beats false assurance.
FRESHNESS_THRESHOLD_HOURS: int = 24

# Retrieval status sentinels (used in answer_summary and missing_info)
_STATUS_OK               = "ok"
_STATUS_NO_PORTFOLIO_DATA = "no_portfolio_data"
_STATUS_STALE_HOLD        = "stale_hold"
_STATUS_NO_CANDIDATES     = "no_candidates"
_STATUS_NO_DATES          = "no_dates"

#: Constraints the intake classifier may extract that pms_listings does NOT
#: carry.  These are surfaced as "unverified" so the composer can hedge.
_UNVERIFIABLE_CONSTRAINTS = frozenset([
    "party_size",
    "golf_cart",
    "exact_community",
    "price_point",
    "budget",
])


# ── Main agent ────────────────────────────────────────────────────────────────


class PortfolioMatchingAgent:
    """Canonical portfolio retrieval executor.

    Registered in DEFAULT_TOPIC_TO_AGENTS for 'booking_inquiry' alongside
    BookingInquiryAgent.  Returns a zero-cost passthrough (no DB call) when
    portfolio_search is not in classification.sub_intents, so every standard
    booking inquiry pays only a dict-lookup to skip this agent.
    """

    name = "PortfolioMatchingAgent"
    # Empty: no primary-topic ownership.  The routing table puts this agent
    # on 'booking_inquiry' as a secondary executor; handles_topics stays
    # empty to avoid the one-topic-one-agent collision check.
    handles_topics: Tuple[str, ...] = ()

    def eligible_for_identity(self, identity_state: str) -> bool:
        # Portfolio search is pre-booking; identity not required.
        return True

    async def run(
        self,
        *,
        message: InboundGuestMessage,
        classification: MessageClassification,
        context: GuestContextBundle,
        db_session: Any = None,
    ) -> AgentDecision:
        """Execute portfolio retrieval or return zero-cost passthrough.

        The intake classifier signals portfolio intent via sub_intents.
        If "portfolio_search" is absent, this agent returns immediately
        without touching the DB.
        """
        # ── Passthrough: not a portfolio search ───────────────────────────
        if "portfolio_search" not in (classification.sub_intents or []):
            return _passthrough_decision(self.name)

        # ── Extract query parameters from classifier's extracted_constraints ─
        constraints = classification.extracted_constraints or {}
        ps = constraints.get("portfolio_search") or {}

        # Date window: prefer portfolio_search.date_window, fall back to
        # top-level dates block.  LLM may put dates either place depending
        # on message phrasing ("similar to xyz, July 4 week").
        date_window = ps.get("date_window") or constraints.get("dates") or {}
        check_in, check_out = _parse_dates(date_window)

        # Constraints the canonical schema supports
        min_bedrooms: Optional[int] = None
        raw_beds = constraints.get("bedroom_count") or ps.get("bedroom_count")
        if raw_beds is not None:
            try:
                min_bedrooms = int(raw_beds)
            except (TypeError, ValueError):
                pass

        amenity_asks_lower = [
            str(a).lower() for a in (constraints.get("amenity_asks") or [])
        ]
        require_pool = any("pool" in a for a in amenity_asks_lower)
        require_pet  = bool(constraints.get("pet_friendly")) or any(
            "pet" in a or "dog" in a for a in amenity_asks_lower
        )

        # Constraints pms_listings does NOT carry → unverified
        unverified: List[str] = []
        if constraints.get("party_size"):
            unverified.append("party_size")
        if any("golf" in a for a in amenity_asks_lower):
            unverified.append("golf_cart")
        if constraints.get("community"):
            # We'll use city as a proxy but it's not the same
            unverified.append("exact_community")
        if constraints.get("budget"):
            unverified.append("price_point")

        # company_id from context
        company_id: Optional[UUID] = None
        if context.tenant_id:
            try:
                company_id = UUID(context.tenant_id)
            except (ValueError, TypeError):
                pass

        # ── Fail-safe: no dates → hold ─────────────────────────────────
        # Availability without dates is meaningless.  Composer should ask
        # the guest for their travel window.
        if not (check_in and check_out):
            return _hold_decision(
                agent_name=self.name,
                status=_STATUS_NO_DATES,
                reason=(
                    "portfolio_search detected but no date_window extracted — "
                    "intake did not find travel dates in the message"
                ),
                unverified=unverified,
            )

        # ── Fail-safe: no DB or company ──────────────────────────────────
        if not db_session or not company_id:
            return _hold_decision(
                agent_name=self.name,
                status=_STATUS_NO_PORTFOLIO_DATA,
                reason="db_session or company_id unavailable",
                unverified=unverified,
            )

        # ── Execute canonical retrieval ───────────────────────────────────
        try:
            status, candidates, freshness = await _query_canonical(
                db=db_session,
                company_id=company_id,
                check_in=check_in,
                check_out=check_out,
                min_bedrooms=min_bedrooms,
                require_pool=require_pool,
                require_pet=require_pet,
                anchor_property=ps.get("anchor_property"),
                result_limit=int(ps.get("result_limit_hint") or RESULT_LIMIT),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PortfolioMatchingAgent] retrieval failed: %s", exc)
            return _hold_decision(
                agent_name=self.name,
                status="retrieval_error",
                reason=f"{type(exc).__name__}: {exc}",
                unverified=unverified,
            )

        # ── Fail-safe: stale sync ─────────────────────────────────────────
        if status == _STATUS_STALE_HOLD:
            return _hold_decision(
                agent_name=self.name,
                status=_STATUS_STALE_HOLD,
                reason=(
                    f"PMS sync is stale (last_synced_at="
                    f"{freshness.get('last_synced_at')}) — "
                    f"availability cannot be asserted beyond {FRESHNESS_THRESHOLD_HOURS}h old data"
                ),
                unverified=unverified,
            )

        # ── Fail-safe: PMS never synced ───────────────────────────────────
        if status == _STATUS_NO_PORTFOLIO_DATA:
            return _hold_decision(
                agent_name=self.name,
                status=_STATUS_NO_PORTFOLIO_DATA,
                reason=(
                    "pms_listings is empty for this company — "
                    "PMS not yet connected; portfolio feature is dormant until data exists"
                ),
                unverified=unverified,
            )

        # ── No listings match / available ─────────────────────────────────
        if status == _STATUS_NO_CANDIDATES or not candidates:
            return AgentDecision(
                agent_name=self.name,
                intent_topic="booking_inquiry",
                confidence=0.75,
                answer_summary=(
                    f"Portfolio search: no listings available for "
                    f"{check_in.isoformat()} – {check_out.isoformat()} "
                    f"matching the requested criteria. "
                    f"Listings exist in pms_listings for this company but none "
                    f"passed the availability + attribute filters."
                ),
                evidence_used=["pms_listings", "pms_bookings"],
                missing_info=unverified,
                risk_flags=[],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text="",
                module_events=[],
            )

        # ── Candidates found — return structured facts to composer ─────────
        # The composer reads answer_summary and writes the guest-facing prose.
        # draft_text is intentionally empty: this agent does NOT compose prose.
        answer_summary = _format_candidates_for_composer(
            candidates=candidates,
            check_in=check_in,
            check_out=check_out,
            freshness=freshness,
            unverified=unverified,
        )
        return AgentDecision(
            agent_name=self.name,
            intent_topic="booking_inquiry",
            confidence=0.85,
            answer_summary=answer_summary,
            evidence_used=["pms_listings", "pms_bookings"],
            missing_info=unverified,
            risk_flags=[],
            recommended_action=RecommendedAction.DRAFT_ONLY,
            draft_text="",   # LLM composer writes this from answer_summary facts
            module_events=[],
        )


# ── Module-level helpers ──────────────────────────────────────────────────────


def _passthrough_decision(agent_name: str) -> AgentDecision:
    """Zero-cost no-op returned when portfolio_search not in sub_intents."""
    return AgentDecision(
        agent_name=agent_name,
        intent_topic="booking_inquiry",
        confidence=0.0,
        answer_summary="not a portfolio search — passthrough",
        evidence_used=[],
        missing_info=[],
        risk_flags=[],
        recommended_action=RecommendedAction.DRAFT_ONLY,
        draft_text="",
        module_events=[],
    )


def _hold_decision(
    *,
    agent_name: str,
    status: str,
    reason: str,
    unverified: List[str],
) -> AgentDecision:
    """Return a DRAFT_ONLY decision signalling the composer to hold / follow up."""
    return AgentDecision(
        agent_name=agent_name,
        intent_topic="booking_inquiry",
        confidence=0.40,
        answer_summary=f"Portfolio retrieval hold [{status}]: {reason}",
        evidence_used=[],
        missing_info=[status] + unverified,
        risk_flags=[],
        recommended_action=RecommendedAction.DRAFT_ONLY,
        draft_text="",
        module_events=[],
    )


def _parse_dates(
    date_window: Dict[str, Any],
) -> Tuple[Optional[date], Optional[date]]:
    """Parse (check_in, check_out) from an extracted date_window dict.

    Accepts ISO strings ("YYYY-MM-DD") or date objects.  Returns None for
    any field that can't be parsed rather than raising — the caller decides
    whether missing dates gate the retrieval.
    """
    result: List[Optional[date]] = [None, None]
    for idx, key in enumerate(("check_in", "check_out")):
        raw = date_window.get(key)
        if raw is None:
            continue
        if isinstance(raw, datetime):
            result[idx] = raw.date()
        elif isinstance(raw, date):
            result[idx] = raw
        elif isinstance(raw, str):
            try:
                result[idx] = date.fromisoformat(raw[:10])
            except (ValueError, TypeError):
                pass
    return result[0], result[1]


async def _query_canonical(
    *,
    db: Any,
    company_id: UUID,
    check_in: date,
    check_out: date,
    min_bedrooms: Optional[int],
    require_pool: bool,
    require_pet: bool,
    anchor_property: Optional[str],
    result_limit: int,
) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """Run the canonical portfolio availability query.

    Returns (status, candidates, freshness_info).

    ONE query (the anti-join) replaces the legacy per-property availability
    loop.  scales to arbitrarily large portfolios.

    freshness_info: {"last_synced_at": str|None, "is_stale": bool}
    """
    from sqlalchemy import text

    cid = str(company_id)
    limit = max(1, min(int(result_limit), RESULT_LIMIT))

    # ── Step 1: portfolio presence + freshness ────────────────────────────
    sync_row = (await db.execute(
        text("""
            SELECT COUNT(*)                AS cnt,
                   MAX(last_synced_at)     AS latest_sync
            FROM pms_listings
            WHERE company_id = :cid
              AND is_active = true
        """),
        {"cid": cid},
    )).mappings().first()

    total_listings = int((sync_row or {}).get("cnt") or 0)
    latest_sync: Optional[datetime] = (sync_row or {}).get("latest_sync")

    freshness_info: Dict[str, Any] = {
        "last_synced_at": (
            latest_sync.isoformat() if latest_sync else None
        ),
        "is_stale": False,
    }

    if total_listings == 0:
        return _STATUS_NO_PORTFOLIO_DATA, [], freshness_info

    if latest_sync is not None:
        # Normalise to UTC-aware for comparison
        if latest_sync.tzinfo is None:
            latest_sync_utc = latest_sync.replace(tzinfo=timezone.utc)
        else:
            latest_sync_utc = latest_sync.astimezone(timezone.utc)
        threshold = datetime.now(timezone.utc) - timedelta(
            hours=FRESHNESS_THRESHOLD_HOURS
        )
        if latest_sync_utc < threshold:
            freshness_info["is_stale"] = True
            return _STATUS_STALE_HOLD, [], freshness_info

    # ── Step 2: single set-based anti-join ───────────────────────────────
    # NOT EXISTS replaces the legacy per-property COUNT(*) loop.
    # O(candidates × index lookups) at the DB level, not N round trips.
    rows = (await db.execute(
        text("""
            SELECT l.id,
                   l.external_id,
                   l.property_name,
                   l.city,
                   l.state,
                   l.bedrooms,
                   l.bathrooms,
                   l.has_pool,
                   l.pet_friendly,
                   l.has_waterfront,
                   l.beach_access,
                   l.latitude,
                   l.longitude,
                   l.last_synced_at
            FROM pms_listings l
            WHERE l.company_id   = :cid
              AND l.is_active    = true
              AND l.listing_status = 'active'
              AND (:min_bedrooms IS NULL OR l.bedrooms >= :min_bedrooms)
              AND (:require_pool = false  OR l.has_pool    = true)
              AND (:require_pet  = false  OR l.pet_friendly = true)
              AND NOT EXISTS (
                  SELECT 1
                  FROM pms_bookings b
                  WHERE b.listing_id   = l.id
                    AND b.company_id   = l.company_id
                    AND b.status       IN ('confirmed', 'pending')
                    AND b.check_in     < :check_out
                    AND b.check_out    > :check_in
              )
            ORDER BY l.property_name
            LIMIT :result_limit
        """),
        {
            "cid":          cid,
            "min_bedrooms": min_bedrooms,
            "require_pool": require_pool,
            "require_pet":  require_pet,
            "check_in":     check_in.isoformat(),
            "check_out":    check_out.isoformat(),
            "result_limit": limit,
        },
    )).mappings().all()

    candidates = [dict(r) for r in rows]

    # ── Step 3 (optional): anchor-proximity re-rank ───────────────────────
    # Post-ranks the already-capped candidate set (~≤8 rows) by similarity
    # to an anchor property when one was identified by the intake classifier.
    # Price-proximity is omitted: pms_listings has no forward rate card.
    if anchor_property and candidates:
        try:
            anchor_row = (await db.execute(
                text("""
                    SELECT latitude, longitude, bedrooms
                    FROM pms_listings
                    WHERE company_id = :cid
                      AND (LOWER(property_name) = LOWER(:anchor)
                           OR external_id        = :anchor)
                    LIMIT 1
                """),
                {"cid": cid, "anchor": str(anchor_property)},
            )).mappings().first()
            if anchor_row:
                candidates = _rank_by_proximity(candidates, dict(anchor_row))
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "[PortfolioMatchingAgent] anchor-proximity rank failed "
                "(non-fatal): %s", exc,
            )

    if not candidates:
        return _STATUS_NO_CANDIDATES, [], freshness_info

    return _STATUS_OK, candidates, freshness_info


def _rank_by_proximity(
    candidates: List[Dict[str, Any]],
    anchor: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Re-rank candidates by attribute proximity to an anchor listing.

    Sort key (ascending):
      1. |bedrooms − anchor_bedrooms|
      2. haversine distance from anchor lat/lon (if coords available)
      3. property_name (tie-break)

    Annotates each candidate dict with `distance_km` for the composer.
    Price-proximity is intentionally omitted: no forward rate card in
    pms_listings.
    """
    anchor_lat  = float(anchor.get("latitude")  or 0)
    anchor_lon  = float(anchor.get("longitude") or 0)
    anchor_beds = int(anchor.get("bedrooms")    or 0)
    has_coords  = bool(anchor_lat and anchor_lon)

    def _key(c: Dict[str, Any]) -> Tuple:
        bed_diff = abs(int(c.get("bedrooms") or 0) - anchor_beds)
        if has_coords and c.get("latitude") and c.get("longitude"):
            lat = float(c["latitude"])
            lon = float(c["longitude"])
            dlat = math.radians(lat - anchor_lat)
            dlon = math.radians(lon - anchor_lon)
            a = (
                math.sin(dlat / 2) ** 2
                + math.cos(math.radians(anchor_lat))
                * math.cos(math.radians(lat))
                * math.sin(dlon / 2) ** 2
            )
            dist = 6371.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            c["distance_km"] = round(dist, 1)
        else:
            dist = 999.0
            c["distance_km"] = None
        return (bed_diff, dist, str(c.get("property_name") or ""))

    return sorted(candidates, key=_key)


def _format_candidates_for_composer(
    *,
    candidates: List[Dict[str, Any]],
    check_in: date,
    check_out: date,
    freshness: Dict[str, Any],
    unverified: List[str],
) -> str:
    """Produce a structured-text summary the LLM composer reads to draft
    the guest-facing reply.

    This is NOT a guest-facing string.  It is factual structured data
    for the composer LLM.  The composer writes the prose.
    """
    nights = (check_out - check_in).days
    lines = [
        f"Portfolio availability: {check_in.isoformat()} – {check_out.isoformat()} "
        f"({nights} night{'s' if nights != 1 else ''})",
        f"Candidates ({len(candidates)}, hard cap {RESULT_LIMIT}):",
    ]
    for i, c in enumerate(candidates, 1):
        beds  = c.get("bedrooms")  if c.get("bedrooms")  is not None else "?"
        baths = c.get("bathrooms") if c.get("bathrooms") is not None else "?"
        attrs = [
            f"pool: {'yes' if c.get('has_pool')      else 'no'}",
            f"pets: {'yes' if c.get('pet_friendly')  else 'no'}",
            f"beach: {'yes' if c.get('beach_access') else 'no'}",
        ]
        city  = c.get("city")  or ""
        state = c.get("state") or ""
        loc   = f"{city}, {state}".strip(", ") or "unknown location"
        dist  = (
            f" ({c['distance_km']} km from ref)"
            if c.get("distance_km") is not None
            else ""
        )
        name = c.get("property_name") or c.get("external_id") or f"listing_{i}"
        lines.append(
            f"{i}. {name}{dist} — {beds} BR / {baths} BA — "
            + ", ".join(attrs)
            + f" — {loc}"
        )
    if unverified:
        lines.append(
            "Constraints NOT in canonical schema "
            f"(hedge in reply, do not assert): {', '.join(unverified)}"
        )
    sync_ts = freshness.get("last_synced_at") or "unknown"
    lines.append(f"PMS sync: last_synced_at={sync_ts} (confirmed fresh)")
    return "\n".join(lines)
