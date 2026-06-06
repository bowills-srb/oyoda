"""
PMS Ingest Worker — Escapia → Oyvoda DB

Pulls listings and bookings from a connected PMS (starting with Escapia)
and writes them into the canonical tables used by the concierge pipeline.

Triggered by:
  - Celery beat (hourly via sync_pms_sessions task)
  - Manual API call (POST /api/v1/operators/{company_id}/sync-pms)
  - Post-onboarding (first sync after credentials stored)

Flow:
  1. Load operator's Escapia credentials from IntegrationCredentialStore
  2. Instantiate EscapiaConnectorV2
  3. Test connection — bail with error if fails
  4. fetch_listings() → upsert into pms_listings table
  5. fetch_bookings(today, today+180) → upsert into pms_bookings table
  6. Trigger concierge session creation for active check-ins
  7. Log sync result to operator_sync_log
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.connectors.integration_gateway import (
    IntegrationCredentialStore,
    IntegrationProvider,
    get_integration_credential_store,
)
from app.services.connectors.escapia_connector import EscapiaConnectorV2
from app.services.connectors.pms_connectors import CanonicalListing, CanonicalBooking
from app.services.property_canonical_write_service import get_canonical_property_write_service

logger = logging.getLogger(__name__)


# =============================================================================
# MAIN INGEST ENTRY POINT
# =============================================================================

async def run_pms_ingest(
    company_id: UUID,
    db: AsyncSession,
    days_forward: int = 180,
    force: bool = False,
) -> dict:
    """
    Full PMS ingest for one operator.

    Returns a result dict:
    {
        "success": bool,
        "listings_synced": int,
        "bookings_synced": int,
        "active_stays": int,
        "error": str | None,
        "synced_at": str,
    }
    """
    result = {
        "success": False,
        "company_id": str(company_id),
        "listings_synced": 0,
        "bookings_synced": 0,
        "active_stays": 0,
        "error": None,
        "synced_at": datetime.utcnow().isoformat(),
    }

    try:
        # ── 1. Load credentials ───────────────────────────────────────────
        store = get_integration_credential_store()
        try:
            credentials = store.get_credentials(company_id, IntegrationProvider.ESCAPIA)
        except ValueError:
            result["error"] = "No Escapia credentials configured for this operator."
            logger.warning(f"[PMSIngest] No Escapia credentials for company {company_id}")
            await _log_sync(db, company_id, result)
            return result

        # ── 2. Instantiate connector ──────────────────────────────────────
        connector = EscapiaConnectorV2(
            company_id=company_id,
            credentials=credentials,
        )

        # ── 3. Test connection ────────────────────────────────────────────
        ok, msg = await connector.test_connection()
        if not ok:
            result["error"] = f"Escapia connection failed: {msg}"
            logger.error(f"[PMSIngest] Connection test failed for {company_id}: {msg}")
            await _log_sync(db, company_id, result)
            return result

        logger.info(f"[PMSIngest] Connected to Escapia for company {company_id}")

        # ── 4. Fetch + upsert listings ────────────────────────────────────
        listings = await connector.fetch_listings()
        listing_id_map = {}  # external_id → internal UUID

        for listing in listings:
            internal_id = await _upsert_listing(db, listing)
            listing_id_map[listing.external_id] = internal_id
            await get_canonical_property_write_service(db).register_property_record(
                company_id,
                canonical_property_code=(
                    str(listing.provider_unit_id or "").strip()
                    or str(listing.provider_property_id or "").strip()
                    or str(listing.external_id or "").strip()
                ),
                display_name=str(listing.property_name or "").strip() or None,
                property_name=str(listing.property_name or "").strip() or None,
                address_line1=str(listing.address_line1 or "").strip() or None,
                external_ids={str(listing.pms_provider): str(listing.external_id or "").strip()},
                aliases=[
                    str(listing.property_name or "").strip(),
                    str(listing.address_line1 or "").strip(),
                    str(listing.provider_unit_id or "").strip(),
                ],
                ref_pairs=[
                    {
                        "provider": str(listing.pms_provider),
                        "ref_kind": "provider_account_id",
                        "ref_value": str(listing.provider_account_id or "").strip(),
                        "confidence": 0.98,
                        "metadata": {"source": "pms_ingest", "provider_base_url": str(listing.provider_base_url or "")},
                    },
                    {
                        "provider": str(listing.pms_provider),
                        "ref_kind": "property_id",
                        "ref_value": str(listing.provider_property_id or "").strip(),
                        "confidence": 0.99,
                        "metadata": {"source": "pms_ingest", "provider_base_url": str(listing.provider_base_url or "")},
                    },
                    {
                        "provider": str(listing.pms_provider),
                        "ref_kind": "unit_id",
                        "ref_value": str(listing.provider_unit_id or "").strip(),
                        "confidence": 0.99,
                        "metadata": {"source": "pms_ingest", "provider_base_url": str(listing.provider_base_url or "")},
                    },
                    {
                        "provider": str(listing.pms_provider),
                        "ref_kind": "listing_id",
                        "ref_value": str(listing.provider_listing_id or "").strip(),
                        "confidence": 0.99,
                        "metadata": {"source": "pms_ingest", "provider_base_url": str(listing.provider_base_url or "")},
                    },
                ],
                source="pms_ingest",
            )

        result["listings_synced"] = len(listings)
        logger.info(f"[PMSIngest] Upserted {len(listings)} listings for {company_id}")

        # Trigger historical message import if this is a first sync
        # (detected by checking if escapia_message_history is empty for this operator)
        try:
            from sqlalchemy import text as _text
            existing_count = await db.execute(
                _text("SELECT COUNT(*) FROM escapia_message_history WHERE company_id = :cid::uuid LIMIT 1"),
                {"cid": str(company_id)},
            )
            count = (existing_count.fetchone() or [0])[0]
            if count == 0 and listings:
                from app.workers.tasks import import_historical_messages_for_operator
                import_historical_messages_for_operator.apply_async(
                    args=[str(company_id)],
                    countdown=60,  # Wait 60s for listings to fully commit
                )
                logger.info(f"[PMSIngest] First sync detected — queued historical message import for {company_id}")
        except Exception as _he:
            logger.debug(f"[PMSIngest] Historical import trigger skipped: {_he}")

        # Initialize rollout phase tracking for any new listings
        try:
            from app.services.staged_rollout import get_rollout_service
            rollout = get_rollout_service(db)
            for listing in listings:
                await rollout.initialize_property(str(company_id), listing.external_id)
        except Exception as e:
            logger.debug(f"[PMSIngest] Rollout init skipped (non-fatal): {e}")

        # ── 5. Fetch + upsert bookings ────────────────────────────────────
        today = date.today()
        end_date = today + timedelta(days=days_forward)

        bookings = await connector.fetch_bookings(
            start_date=today - timedelta(days=7),  # Include recent check-ins
            end_date=end_date,
        )

        active_stays = 0
        for booking in bookings:
            # Map external listing ID to internal UUID
            ext_listing_id = getattr(booking, "_external_listing_id", None)
            if ext_listing_id and ext_listing_id in listing_id_map:
                booking.listing_id = listing_id_map[ext_listing_id]

            await _upsert_booking(db, booking, company_id)

            # Count active stays (checked in today or within window)
            if booking.check_in <= today <= booking.check_out:
                active_stays += 1

        result["bookings_synced"] = len(bookings)
        result["active_stays"] = active_stays
        result["success"] = True

        logger.info(
            f"[PMSIngest] Complete for {company_id}: "
            f"{len(listings)} listings, {len(bookings)} bookings, "
            f"{active_stays} active stays"
        )

        # ── 6. Create rich concierge sessions for confirmed bookings ────────
        # For each booking, attempt to build a full BookingSessionContext
        # that includes guest identity, property details, and market data
        await _create_rich_concierge_sessions(
            db=db,
            company_id=company_id,
            bookings=bookings,
            listing_map={l.external_id: l for l in listings},
            today=today,
        )

    except Exception as e:
        result["error"] = str(e)
        logger.exception(f"[PMSIngest] Unexpected error for {company_id}: {e}")

    finally:
        await _log_sync(db, company_id, result)

    return result


# =============================================================================
# DB UPSERT HELPERS
# =============================================================================

async def _upsert_listing(
    db: AsyncSession,
    listing: CanonicalListing,
) -> UUID:
    """
    Upsert a canonical listing into the pms_listings table.
    Returns the internal UUID.
    """
    row = await db.execute(
        text("""
            INSERT INTO pms_listings (
                company_id, external_id, pms_provider,
                property_name, address_line1, address_line2,
                city, state, postal_code, country,
                latitude, longitude,
                bedrooms, bathrooms, square_footage, property_type,
                has_pool, pool_heated, has_hot_tub, has_waterfront,
                waterfront_type, beach_access, pet_friendly,
                has_garage, has_ev_charger, has_game_room, has_home_theater,
                is_active, listing_status, last_synced_at,
                created_at, updated_at
            ) VALUES (
                :company_id, :external_id, :pms_provider,
                :property_name, :address_line1, :address_line2,
                :city, :state, :postal_code, :country,
                :latitude, :longitude,
                :bedrooms, :bathrooms, :square_footage, :property_type,
                :has_pool, :pool_heated, :has_hot_tub, :has_waterfront,
                :waterfront_type, :beach_access, :pet_friendly,
                :has_garage, :has_ev_charger, :has_game_room, :has_home_theater,
                :is_active, :listing_status, NOW(),
                NOW(), NOW()
            )
            ON CONFLICT (company_id, external_id, pms_provider)
            DO UPDATE SET
                property_name   = EXCLUDED.property_name,
                address_line1   = EXCLUDED.address_line1,
                city            = EXCLUDED.city,
                state           = EXCLUDED.state,
                bedrooms        = EXCLUDED.bedrooms,
                bathrooms       = EXCLUDED.bathrooms,
                has_pool        = EXCLUDED.has_pool,
                has_waterfront  = EXCLUDED.has_waterfront,
                pet_friendly    = EXCLUDED.pet_friendly,
                is_active       = EXCLUDED.is_active,
                listing_status  = EXCLUDED.listing_status,
                last_synced_at  = NOW(),
                updated_at      = NOW()
            RETURNING id
        """),
        {
            "company_id":     str(listing.company_id),
            "external_id":    listing.external_id,
            "pms_provider":   listing.pms_provider.value,
            "property_name":  listing.property_name,
            "address_line1":  listing.address_line1,
            "address_line2":  listing.address_line2 or "",
            "city":           listing.city,
            "state":          listing.state,
            "postal_code":    listing.postal_code,
            "country":        listing.country,
            "latitude":       listing.latitude,
            "longitude":      listing.longitude,
            "bedrooms":       listing.bedrooms,
            "bathrooms":      listing.bathrooms,
            "square_footage": listing.square_footage,
            "property_type":  listing.property_type,
            "has_pool":       listing.has_pool,
            "pool_heated":    listing.pool_heated,
            "has_hot_tub":    listing.has_hot_tub,
            "has_waterfront": listing.has_waterfront,
            "waterfront_type":listing.waterfront_type,
            "beach_access":   listing.beach_access,
            "pet_friendly":   listing.pet_friendly,
            "has_garage":     listing.has_garage,
            "has_ev_charger": listing.has_ev_charger,
            "has_game_room":  listing.has_game_room,
            "has_home_theater": listing.has_home_theater,
            "is_active":      listing.is_active,
            "listing_status": listing.listing_status,
        },
    )
    row_data = row.fetchone()
    await db.commit()
    return row_data.id if row_data else None


async def _upsert_booking(
    db: AsyncSession,
    booking: CanonicalBooking,
    company_id: UUID,
) -> None:
    """Upsert a canonical booking into pms_bookings."""
    await db.execute(
        text("""
            INSERT INTO pms_bookings (
                company_id, listing_id, external_id,
                check_in, check_out, nights,
                total_amount, nightly_rate, cleaning_fee, taxes,
                guest_count, guest_first_name, guest_last_name, guest_email, guest_phone,
                booking_channel, status,
                booked_at, created_at, updated_at
            ) VALUES (
                :company_id, :listing_id, :external_id,
                :check_in, :check_out, :nights,
                :total_amount, :nightly_rate, :cleaning_fee, :taxes,
                :guest_count, :guest_first_name, :guest_last_name, :guest_email, :guest_phone,
                :booking_channel, :status,
                :booked_at, NOW(), NOW()
            )
            ON CONFLICT (company_id, external_id)
            DO UPDATE SET
                check_in         = EXCLUDED.check_in,
                check_out        = EXCLUDED.check_out,
                nights           = EXCLUDED.nights,
                total_amount     = EXCLUDED.total_amount,
                guest_count      = EXCLUDED.guest_count,
                guest_first_name = EXCLUDED.guest_first_name,
                guest_last_name  = EXCLUDED.guest_last_name,
                guest_email      = EXCLUDED.guest_email,
                guest_phone      = EXCLUDED.guest_phone,
                booking_channel  = EXCLUDED.booking_channel,
                status           = EXCLUDED.status,
                updated_at       = NOW()
        """),
        {
            "company_id":      str(company_id),
            "listing_id":      str(booking.listing_id) if booking.listing_id else None,
            "external_id":     booking.external_id,
            "check_in":        booking.check_in,
            "check_out":       booking.check_out,
            "nights":          booking.nights,
            "total_amount":    booking.total_amount,
            "nightly_rate":    booking.nightly_rate,
            "cleaning_fee":    booking.cleaning_fee,
            "taxes":           booking.taxes,
            "guest_count":     booking.guest_count,
            "guest_first_name": booking.guest_first_name,
            "guest_last_name": booking.guest_last_name,
            "guest_email":     booking.guest_email,
            "guest_phone":     booking.guest_phone,
            "booking_channel": booking.booking_channel,
            "status":          booking.status,
            "booked_at":       booking.booked_at,
        },
    )
    await db.commit()


async def _create_rich_concierge_sessions(
    db,
    company_id: UUID,
    bookings: list,
    listing_map: dict,
    today,
) -> None:
    """
    For each confirmed booking:
    - Skip if session already exists
    - Build a full BookingSessionContext (guest info, property, market)
    - Create a concierge session with the rich context
    - Only for upcoming/active stays (not historical)
    """
    try:
        from app.services.concierge.escapia_unified import get_escapia_unified_handler
        from app.services.concierge.integration_gateway import (
            get_integration_credential_store, IntegrationProvider
        )
        from sqlalchemy import text

        # Load operator context for session creation
        op_row = await db.execute(
            text("SELECT name, concierge_name, support_phone FROM companies WHERE id = :cid LIMIT 1"),
            {"cid": str(company_id)},
        )
        op = op_row.fetchone()
        company_context = {
            "name": op.name if op else "Your Host",
            "concierge_name": op.concierge_name if op else "Coral",
            "support_phone": op.support_phone if op else None,
        }

        handler = get_escapia_unified_handler(company_id)

        created = 0
        for booking in bookings:
            try:
                # Only process upcoming or active stays
                if booking.check_out < today:
                    continue
                if booking.status not in ("confirmed", "pending"):
                    continue

                # Check if session already exists
                existing = await db.execute(
                    text("""
                        SELECT token FROM concierge_guest_sessions
                        WHERE property_code = :prop
                          AND check_in = :check_in
                          AND check_out = :check_out
                        LIMIT 1
                    """),
                    {
                        "prop": booking._external_listing_id or "",
                        "check_in": booking.check_in,
                        "check_out": booking.check_out,
                    },
                )
                if existing.fetchone():
                    continue  # Already have a session for this booking

                # Get the listing for this booking
                ext_listing_id = getattr(booking, "_external_listing_id", "")
                listing = listing_map.get(ext_listing_id)
                if not listing:
                    continue

                token = await handler.create_session_from_confirmed_booking(
                    booking=booking,
                    listing=listing,
                    company_context=company_context,
                    db=db,
                )
                if token:
                    created += 1

            except Exception as e:
                logger.warning(f"[PMSIngest] Session creation failed for booking {getattr(booking, 'external_id', '?')}: {e}")

        if created:
            logger.info(f"[PMSIngest] Created {created} rich concierge sessions")

    except Exception as e:
        logger.warning(f"[PMSIngest] Rich session creation failed (non-fatal): {e}")
        # Fall back to simple session creation
        await _trigger_concierge_sessions(db, company_id, today)


async def _trigger_concierge_sessions(
    db: AsyncSession,
    company_id: UUID,
    today: date,
) -> None:
    """
    For bookings where check_in = today and no concierge session exists yet,
    create a session so the guest journey pipeline can fire the welcome message.
    """
    try:
        await db.execute(
            text("""
                INSERT INTO concierge_sessions (
                    company_id, booking_id, listing_id,
                    status, created_at, updated_at
                )
                SELECT
                    b.company_id,
                    b.id,
                    b.listing_id,
                    'active',
                    NOW(),
                    NOW()
                FROM pms_bookings b
                LEFT JOIN concierge_sessions cs
                    ON cs.booking_id = b.id
                WHERE b.company_id = :company_id
                  AND b.check_in = :today
                  AND b.status = 'confirmed'
                  AND cs.id IS NULL
            """),
            {"company_id": str(company_id), "today": today},
        )
        await db.commit()
        logger.info(f"[PMSIngest] Concierge sessions created for check-ins on {today}")
    except Exception as e:
        logger.warning(f"[PMSIngest] Could not create concierge sessions: {e}")


async def _log_sync(
    db: AsyncSession,
    company_id: UUID,
    result: dict,
) -> None:
    """Write sync result to operator_sync_log."""
    try:
        import json
        await db.execute(
            text("""
                INSERT INTO operator_sync_log (
                    company_id, provider, success,
                    listings_synced, bookings_synced,
                    error_message, synced_at
                ) VALUES (
                    :company_id, 'escapia', :success,
                    :listings_synced, :bookings_synced,
                    :error_message, NOW()
                )
            """),
            {
                "company_id":      str(company_id),
                "success":         result["success"],
                "listings_synced": result["listings_synced"],
                "bookings_synced": result["bookings_synced"],
                "error_message":   result.get("error"),
            },
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"[PMSIngest] Could not write sync log: {e}")


# =============================================================================
# DB MIGRATION — run once
# =============================================================================

MIGRATION_SQL = """
-- PMS Listings (canonical, source-of-truth for all properties)
CREATE TABLE IF NOT EXISTS pms_listings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL,
    external_id     TEXT NOT NULL,
    pms_provider    TEXT NOT NULL DEFAULT 'escapia',

    -- Location
    property_name   TEXT,
    address_line1   TEXT,
    address_line2   TEXT,
    city            TEXT,
    state           TEXT,
    postal_code     TEXT,
    country         TEXT DEFAULT 'US',
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,

    -- Property details
    bedrooms        INTEGER DEFAULT 0,
    bathrooms       NUMERIC(4,1) DEFAULT 0,
    square_footage  INTEGER,
    property_type   TEXT DEFAULT 'single_family',

    -- Amenities
    has_pool        BOOLEAN DEFAULT FALSE,
    pool_heated     BOOLEAN DEFAULT FALSE,
    has_hot_tub     BOOLEAN DEFAULT FALSE,
    has_waterfront  BOOLEAN DEFAULT FALSE,
    waterfront_type TEXT,
    beach_access    TEXT,
    pet_friendly    BOOLEAN DEFAULT FALSE,
    has_garage      BOOLEAN DEFAULT FALSE,
    has_ev_charger  BOOLEAN DEFAULT FALSE,
    has_game_room   BOOLEAN DEFAULT FALSE,
    has_home_theater BOOLEAN DEFAULT FALSE,

    -- Status
    is_active       BOOLEAN DEFAULT TRUE,
    listing_status  TEXT DEFAULT 'active',
    last_synced_at  TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (company_id, external_id, pms_provider)
);

-- PMS Bookings
CREATE TABLE IF NOT EXISTS pms_bookings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL,
    listing_id      UUID REFERENCES pms_listings(id),
    external_id     TEXT NOT NULL,

    check_in        DATE NOT NULL,
    check_out       DATE NOT NULL,
    nights          INTEGER NOT NULL DEFAULT 1,

    total_amount    NUMERIC(10,2),
    nightly_rate    NUMERIC(10,2),
    cleaning_fee    NUMERIC(10,2),
    taxes           NUMERIC(10,2),

    guest_count     INTEGER DEFAULT 1,
    guest_first_name TEXT,
    guest_last_name  TEXT,
    guest_email      TEXT,
    guest_phone      TEXT,
    booking_channel TEXT DEFAULT 'direct',
    status          TEXT DEFAULT 'confirmed',
    booked_at       TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (company_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_bookings_checkin
    ON pms_bookings (company_id, check_in)
    WHERE status = 'confirmed';

-- Sync log
CREATE TABLE IF NOT EXISTS operator_sync_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL,
    provider        TEXT NOT NULL,
    success         BOOLEAN NOT NULL,
    listings_synced INTEGER DEFAULT 0,
    bookings_synced INTEGER DEFAULT 0,
    error_message   TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""
