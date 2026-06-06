"""
market_intelligence.py — Market Intelligence API

GET /api/v1/market/intelligence?company_id=...
GET /api/v1/market/events?market_id=30a_fl&days=30
GET /api/v1/market/signals?market_id=30a_fl

Powers the Market Intelligence section of the operator dashboard.
Shows operators WHY bookings are moving in their market — festivals,
events, demand compression, seasonal signals.

This is entirely read-only. All data is populated by the event scraper
(event_scraper.py) and signal emitters (bd_insight_service.py).
"""

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/market", tags=["Market Intelligence"])


@router.get("/scrape-status")
async def scrape_status(request: Request):
    """
    Diagnostic: shows exactly what the scraper sees at each resolution step.
    Helps debug why markets_scraped returns empty.
    """
    import os, json
    from app.core.database import get_db_session
    from sqlalchemy import text
    from tools.event_scraper import KNOWN_MARKETS, build_market_sources_config

    result = {}

    # 1. Auth check
    expected_key = os.getenv("OYVODA_MASTER_KEY", "").strip()
    x_master = request.headers.get("X-Master-Key", "").strip()
    result["auth_ok"] = (x_master == expected_key)
    if not result["auth_ok"]:
        return JSONResponse(result, status_code=401)

    # 2. market_registry contents
    try:
        async with get_db_session() as db:
            rows = (await db.execute(text(
                "SELECT market_id, scrape_enabled, last_scraped_at, "
                "sources_config FROM market_registry ORDER BY market_id"
            ))).fetchall()
        result["market_registry_count"] = len(rows)
        result["market_registry"] = [
            {"market_id": r[0], "scrape_enabled": r[1],
             "last_scraped_at": str(r[2]), "sources": r[3]}
            for r in rows
        ]
    except Exception as e:
        result["market_registry_error"] = str(e)

    # 3. Properties with address data
    try:
        async with get_db_session() as db:
            prop_rows = (await db.execute(text("""
                SELECT COUNT(*) as total,
                       COUNT(address_city) as with_city,
                       COUNT(address_zip) as with_zip,
                       MIN(address_zip) as sample_zip
                FROM properties
            """))).fetchone()
        result["properties"] = {
            "total": prop_rows[0],
            "with_city": prop_rows[1],
            "with_zip": prop_rows[2],
            "sample_zip": prop_rows[3],
        }
    except Exception as e:
        result["properties_error"] = str(e)

    # 4. KNOWN_MARKETS in code
    result["known_markets_in_code"] = list(KNOWN_MARKETS.keys())

    # 5. What _get_due_markets would return
    try:
        from tools.event_scraper import EventScrapeOrchestrator
        async with EventScrapeOrchestrator() as orc:
            due = await orc._get_due_markets()
        result["due_markets"] = due
    except Exception as e:
        result["due_markets_error"] = str(e)

    # 6. Quick probe: fetch visitsouthwalton.com and check what selectors exist
    try:
        import httpx as _httpx
        from bs4 import BeautifulSoup as _BS
        _r = await _httpx.AsyncClient().get(
            "https://www.visitsouthwalton.com/events",
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            timeout=15, follow_redirects=True
        )
        _soup = _BS(_r.text, "lxml")
        _jsonld = [s.string for s in _soup.find_all("script", type="application/ld+json") if s.string]
        _cards = _soup.select(".event-card, .views-row, article.event")
        _all_links = [a["href"] for a in _soup.find_all("a", href=True) if "/events/" in a.get("href", "")][:10]
        result["vsw_probe"] = {
            "status": _r.status_code,
            "jsonld_blocks": len(_jsonld),
            "jsonld_sample": _jsonld[0][:300] if _jsonld else None,
            "card_selectors_found": len(_cards),
            "event_links_found": len(_all_links),
            "event_links_sample": _all_links[:5],
            "page_size_bytes": len(_r.text),
        }
    except Exception as e:
        result["vsw_probe_error"] = str(e)

    return JSONResponse(result)


@router.get("/scrape-debug")
async def scrape_debug(request: Request):
    """Debug endpoint: shows key comparison details without exposing the key."""
    import os
    expected = os.getenv("OYVODA_MASTER_KEY", "").strip()
    auth = request.headers.get("Authorization", "")
    xmaster = request.headers.get("X-Master-Key", "").strip()
    provided = xmaster or auth.removeprefix("Bearer ").strip()
    return JSONResponse({
        "expected_len": len(expected),
        "expected_first4": expected[:4],
        "expected_last4": expected[-4:],
        "provided_len": len(provided),
        "provided_first4": provided[:4],
        "provided_last4": provided[-4:],
        "match": provided == expected,
        "headers_received": dict(request.headers),
    })


@router.post("/scrape")
async def trigger_market_scrape(
    request: Request,
    market_id: Optional[str] = Query(default=None),
    force: bool = Query(default=True,
        description="Force scrape even if market was recently scraped. Default true for manual triggers."),
):
    """
    Manually trigger the event scraper.
    Requires master key in Authorization header: 'Bearer <key>' or X-Master-Key header.

    Markets are derived from operator property geography via market_registry.
    If market_registry is empty, runs resolve_operator_market() against all
    properties in the DB to populate it before scraping.
    """
    import os
    expected_key = os.getenv("OYVODA_MASTER_KEY", "").strip()
    auth_header = request.headers.get("Authorization", "")
    x_master = request.headers.get("X-Master-Key", "").strip()
    provided_key = x_master or auth_header.removeprefix("Bearer ").strip()
    if not expected_key or provided_key != expected_key:
        logger.warning(
            f"[MarketScrape] Auth failed: expected='{expected_key[:4]}...{expected_key[-4:]}' "
            f"got='{provided_key[:4]}...{provided_key[-4:] if len(provided_key) >= 4 else provided_key}'"
        )
        return JSONResponse({"error": "Unauthorized — use X-Master-Key header"}, status_code=401)

    try:
        from tools.event_scraper import EventScrapeOrchestrator
        from app.core.database import get_db_session
        from sqlalchemy import text

        # If market_registry is empty, resolve markets from actual property addresses
        async with get_db_session() as db:
            count = (await db.execute(
                text("SELECT COUNT(*) FROM market_registry WHERE scrape_enabled = true")
            )).scalar() or 0

        if count == 0:
            logger.info("[MarketScrape] market_registry empty — resolving from property addresses")
            resolved = await _resolve_markets_from_properties()
            logger.info(f"[MarketScrape] Resolved {len(resolved)} markets from properties: {resolved}")

            # If property resolution failed (e.g. addresses not yet populated),
            # fall back to inserting the known markets directly from KNOWN_MARKETS.
            # This handles the common case of a PMS import that brought in property
            # codes only, before address data is available.
            if not resolved:
                logger.info("[MarketScrape] Property resolution yielded nothing — seeding from KNOWN_MARKETS")
                resolved = await _seed_from_known_markets()
                logger.info(f"[MarketScrape] Seeded {len(resolved)} markets from KNOWN_MARKETS")

            if not resolved:
                return JSONResponse({
                    "status": "warning",
                    "message": "No markets could be resolved. Check market_registry table.",
                    "markets_scraped": {},
                    "total_events": 0,
                    "scraped_at": date.today().isoformat(),
                })

        async with EventScrapeOrchestrator(days_ahead=90) as orc:
            if market_id:
                events = await orc.scrape_market(market_id)
                return JSONResponse({
                    "status": "ok",
                    "markets_scraped": {market_id: len(events)},
                    "total_events": len(events),
                    "scraped_at": date.today().isoformat(),
                })
            elif force:
                # Force: scrape all enabled markets regardless of last_scraped_at
                # Use psycopg2 sync to avoid pgbouncer session visibility issues
                import psycopg2 as _pg2, os as _os
                _db_url = _os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg", "postgresql")
                _conn = _pg2.connect(_db_url, sslmode="require")
                _cur = _conn.cursor()
                _cur.execute("SELECT market_id FROM market_registry WHERE scrape_enabled = true")
                mids = [r[0] for r in _cur.fetchall()]
                _cur.close()
                _conn.close()
                logger.info(f"[MarketScrape] Force scraping {len(mids)} markets: {mids}")
                results = {}
                source_detail = {}
                for mid in mids:
                    try:
                        events = await orc.scrape_market(mid)
                        results[mid] = len(events)
                        # Capture source counts from the last _mark_scraped call
                        # by re-reading sources_config health after the scrape
                        import psycopg2 as _pg3
                        _conn3 = _pg3.connect(_db_url, sslmode="require")
                        _cur3 = _conn3.cursor()
                        _cur3.execute("SELECT sources_config FROM market_registry WHERE market_id = %s", (mid,))
                        _row3 = _cur3.fetchone()
                        _cur3.close(); _conn3.close()
                        if _row3:
                            sc = _row3[0] or {}
                            source_detail[mid] = {
                                k: v.get("health", {}).get("last_event_count", "?")
                                for k, v in sc.items()
                                if isinstance(v, dict) and "health" in v
                            }
                    except Exception as _e:
                        logger.error(f"[MarketScrape] {mid} failed: {_e}")
                        results[mid] = -1
                return JSONResponse({
                    "status": "ok",
                    "markets_scraped": results,
                    "source_detail": source_detail,
                    "total_events": sum(v for v in results.values() if v >= 0),
                    "failed_markets": [k for k, v in results.items() if v < 0],
                    "scraped_at": date.today().isoformat(),
                })
            else:
                results = await orc.scrape_all_markets()
                return JSONResponse({
                    "status": "ok",
                    "markets_scraped": results,
                    "total_events": sum(v for v in results.values() if v >= 0),
                    "failed_markets": [k for k, v in results.items() if v < 0],
                    "scraped_at": date.today().isoformat(),
                })
    except Exception as e:
        logger.error(f"[MarketScrape] Trigger failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def _resolve_markets_from_properties() -> list[str]:
    """
    Derive markets from property addresses and write to market_registry.
    
    Uses a two-pass approach:
    1. Direct zip/state match against KNOWN_MARKETS zip clusters (no network call)
    2. Nominatim geocode fallback for addresses that don't match a known zip
    """
    from app.core.database import get_db_session
    from sqlalchemy import text
    from tools.event_scraper import resolve_operator_market, KNOWN_MARKETS, _persist_new_market

    # Zip code clusters for known markets — avoids geocoding for known areas
    ZIP_TO_MARKET = {
        # 30A / South Walton, FL
        "32459": "30a_fl", "32461": "30a_fl", "32550": "30a_fl",
        "32459": "30a_fl", "32413": "30a_fl",
        # Destin, FL
        "32541": "destin_fl", "32540": "destin_fl", "32542": "destin_fl",
        # Gulf Shores / Orange Beach, AL
        "36542": "gulf_shores_al", "36561": "gulf_shores_al",
        # Pensacola Beach, FL
        "32561": "pensacola_fl", "32563": "pensacola_fl",
        # Panama City Beach, FL
        "32407": "panama_city_beach_fl", "32408": "panama_city_beach_fl",
        # Myrtle Beach, SC
        "29572": "myrtle_beach_sc", "29577": "myrtle_beach_sc",
        # Outer Banks, NC
        "27959": "outer_banks_nc", "27954": "outer_banks_nc",
    }

    resolved = []
    market_tenant_map: dict[str, list[str]] = {}  # market_id -> [tenant_ids]

    try:
        async with get_db_session() as db:
            rows = (await db.execute(text("""
                SELECT DISTINCT ON (tenant_id)
                    tenant_id::text,
                    address_street, address_city, address_state, address_zip,
                    CAST(latitude AS float), CAST(longitude AS float)
                FROM properties
                WHERE address_city IS NOT NULL
                ORDER BY tenant_id, id
            """))).fetchall()

        for row in rows:
            tenant_id, street, city, state, zipcode, lat, lng = row
            market_id = None

            # Pass 1: direct zip match (fast, no network)
            if zipcode:
                market_id = ZIP_TO_MARKET.get(str(zipcode).strip()[:5])

            # Pass 2: lat/lng haversine match against KNOWN_MARKETS
            if not market_id and lat and lng:
                import math
                def hav(la1, lo1, la2, lo2):
                    R = 3959
                    d = math.radians
                    a = math.sin(d(la2-la1)/2)**2 + math.cos(d(la1))*math.cos(d(la2))*math.sin(d(lo2-lo1)/2)**2
                    return R * 2 * math.asin(math.sqrt(a))
                closest = min(KNOWN_MARKETS.items(), key=lambda kv: hav(lat, lng, kv[1]['lat'], kv[1]['lng']))
                if hav(lat, lng, closest[1]['lat'], closest[1]['lng']) <= 30:
                    market_id = closest[0]

            # Pass 3: Nominatim geocode fallback for truly unknown locations
            if not market_id:
                try:
                    market = await resolve_operator_market(
                        property_addresses=[f"{street}, {city}, {state} {zipcode}"],
                        operator_id=tenant_id,
                        operator_name=f"Operator ({city}, {state})",
                    )
                    if market:
                        market_id = market["id"]
                        resolved.append(market_id)
                        logger.info(f"[MarketScrape] Geocoded {city},{state} -> '{market_id}'")
                        continue
                except Exception as e:
                    logger.warning(f"[MarketScrape] Geocode failed for {city},{state}: {e}")

            if market_id:
                if market_id not in market_tenant_map:
                    market_tenant_map[market_id] = []
                market_tenant_map[market_id].append(tenant_id)

        # Write all resolved markets to market_registry at once
        for market_id, tenant_ids in market_tenant_map.items():
            m = KNOWN_MARKETS.get(market_id, {})
            if not m:
                continue
            market_dict = {
                **m,
                "id": market_id,
                "state": m.get("state_code", m.get("state", "FL")),
            }
            await _persist_new_market(market_dict, tenant_ids[0])
            resolved.append(market_id)
            logger.info(f"[MarketScrape] Registered market '{market_id}' for {len(tenant_ids)} tenant(s)")

        import asyncio
        await asyncio.sleep(0.5)  # Ensure commits are visible

    except Exception as e:
        logger.error(f"[MarketScrape] _resolve_markets_from_properties failed: {e}")

    return list(set(resolved))


async def _seed_from_known_markets() -> list[str]:
    """
    Direct insert of KNOWN_MARKETS into market_registry.
    Used as a fallback when property addresses aren't populated yet
    (e.g. PMS import brought in codes only).
    Once addresses are available, _resolve_markets_from_properties()
    will enrich the registry with tenant associations.
    """
    from app.core.database import get_db_session
    from sqlalchemy import text
    from tools.event_scraper import KNOWN_MARKETS
    import json

    inserted = []
    try:
        async with get_db_session() as db:
            for market_id, m in KNOWN_MARKETS.items():
                sources = build_market_sources_config(m.get("sources", {}))

                await db.execute(text("""
                    INSERT INTO market_registry (
                        market_id, market_name, state_code,
                        center_lat, center_lng, radius_miles, timezone,
                        scrape_enabled, scrape_interval_hours,
                        sources_config, operator_ids, last_scrape_event_count
                    ) VALUES (
                        :mid, :name, :state,
                        :lat, :lng, :radius, :tz,
                        true, 24,
                        CAST(:sources AS JSONB), '[]'::JSONB, 0
                    )
                    ON CONFLICT (market_id) DO NOTHING
                """), {
                    "mid":    market_id,
                    "name":   m["name"],
                    "state":  m.get("state", "FL"),
                    "lat":    m["lat"],
                    "lng":    m["lng"],
                    "radius": m.get("radius_miles", 15.0),
                    "tz":     m.get("timezone", "America/Chicago"),
                    "sources": json.dumps(sources),
                })
                inserted.append(market_id)
            await db.commit()
        logger.info(f"[MarketScrape] Seeded {len(inserted)} markets into market_registry")
    except Exception as e:
        logger.error(f"[MarketScrape] _seed_from_known_markets failed: {e}")
    return inserted


@router.get("/intelligence")
async def get_market_intelligence(
    company_id: Optional[str] = Query(default=None),
    market_id: Optional[str] = Query(default="30a_fl"),
    days: int = Query(default=30, ge=7, le=90),
):
    """
    Full market intelligence summary for an operator.
    Combines events, signals, and demand pressure into a single payload
    for the operator dashboard Market Intelligence view.
    """
    try:
        from app.core.database import get_db_session
        from sqlalchemy import text

        # Resolve market_id from company_id if provided
        resolved_market_id = market_id
        if company_id:
            try:
                async with get_db_session() as db:
                    result = await db.execute(
                        text("SELECT market_id FROM operator_market_links WHERE company_id = :cid LIMIT 1"),
                        {"cid": company_id}
                    )
                    row = result.fetchone()
                    if row:
                        resolved_market_id = row[0]
            except Exception:
                pass  # Fall back to default market_id

        today = date.today()
        window_end = today + timedelta(days=days)

        async with get_db_session() as db:

            # ── Upcoming events ────────────────────────────────────────────
            events_result = await db.execute(text("""
                SELECT
                    event_id, title, category, start_date, end_date,
                    venue_name, venue_address, description,
                    demand_impact_score, is_free, ticket_price_range,
                    ticket_url, is_multi_day, estimated_attendance
                FROM market_events
                WHERE market_id = :mid
                  AND start_date >= :today
                  AND start_date <= :end_date
                  AND is_active = true
                ORDER BY demand_impact_score DESC NULLS LAST, start_date ASC
                LIMIT 25
            """), {"mid": resolved_market_id, "today": today, "end_date": window_end})

            events = []
            for row in events_result.fetchall():
                impact = row[8] or 0
                impact_label = (
                    "High" if impact > 0.7 else
                    "Medium" if impact > 0.45 else
                    "Low"
                )
                events.append({
                    "id": str(row[0]),
                    "title": row[1],
                    "category": row[2] or "other",
                    "start_date": row[3].isoformat() if row[3] else None,
                    "end_date": row[4].isoformat() if row[4] else None,
                    "venue": row[5],
                    "venue_address": row[6],
                    "description": (row[7] or "")[:200],
                    "demand_impact": round(impact, 2),
                    "demand_impact_label": impact_label,
                    "is_free": row[9],
                    "ticket_price": row[10],
                    "ticket_url": row[11],
                    "is_multi_day": row[12],
                    "estimated_attendance": row[13],
                })

            # ── Category breakdown ─────────────────────────────────────────
            cat_result = await db.execute(text("""
                SELECT category, COUNT(*) as cnt,
                       AVG(demand_impact_score) as avg_impact
                FROM market_events
                WHERE market_id = :mid
                  AND start_date >= :today
                  AND start_date <= :end_date
                  AND is_active = true
                GROUP BY category
                ORDER BY cnt DESC
            """), {"mid": resolved_market_id, "today": today, "end_date": window_end})

            categories = [
                {
                    "category": row[0] or "other",
                    "count": row[1],
                    "avg_impact": round(row[2] or 0, 2)
                }
                for row in cat_result.fetchall()
            ]

            # ── Peak demand dates (days with most/highest impact events) ──
            peak_result = await db.execute(text("""
                SELECT
                    start_date,
                    COUNT(*) as event_count,
                    SUM(COALESCE(demand_impact_score, 0.3)) as total_impact,
                    string_agg(title, ', ' ORDER BY demand_impact_score DESC NULLS LAST) as event_titles
                FROM market_events
                WHERE market_id = :mid
                  AND start_date >= :today
                  AND start_date <= :end_date
                  AND is_active = true
                GROUP BY start_date
                HAVING COUNT(*) > 1 OR SUM(COALESCE(demand_impact_score, 0.3)) > 0.6
                ORDER BY total_impact DESC
                LIMIT 8
            """), {"mid": resolved_market_id, "today": today, "end_date": window_end})

            peak_dates = [
                {
                    "date": row[0].isoformat(),
                    "event_count": row[1],
                    "total_impact": round(row[2], 2),
                    "events": row[3][:80] + "..." if row[3] and len(row[3]) > 80 else row[3]
                }
                for row in peak_result.fetchall()
            ]

            # ── Recent demand pressure signals ─────────────────────────────
            signals_result = await db.execute(text("""
                SELECT signal_type, value, confidence,
                       detected_at, metadata, valid_from, valid_until
                FROM signals
                WHERE geo_id = :mid
                  AND signal_type = 'demand_pressure'
                  AND detected_at > NOW() - INTERVAL '30 days'
                ORDER BY detected_at DESC
                LIMIT 10
            """), {"mid": resolved_market_id})

            signals = []
            for row in signals_result.fetchall():
                meta = row[4] or {}
                signals.append({
                    "type": row[0],
                    "value": round(row[1], 3),
                    "confidence": round(row[2], 2),
                    "detected_at": row[3].isoformat() if row[3] else None,
                    "explanation": meta.get("explanation", ""),
                    "valid_from": row[5].isoformat() if row[5] else None,
                    "valid_until": row[6].isoformat() if row[6] else None,
                })

            # ── Market registry info ───────────────────────────────────────
            registry_result = await db.execute(text("""
                SELECT market_name, state_code, last_scraped_at,
                       last_scrape_event_count, scrape_interval_hours
                FROM market_registry
                WHERE market_id = :mid
            """), {"mid": resolved_market_id})
            registry_row = registry_result.fetchone()

            market_info = {}
            if registry_row:
                market_info = {
                    "name": registry_row[0],
                    "state": registry_row[1],
                    "last_scraped": registry_row[2].isoformat() if registry_row[2] else None,
                    "total_events_on_file": registry_row[3] or 0,
                    "scrape_interval_hours": registry_row[4],
                }

            # ── Overall demand summary ─────────────────────────────────────
            high_impact_count = sum(1 for e in events if e["demand_impact"] > 0.7)
            total_events = len(events)
            avg_impact = sum(e["demand_impact"] for e in events) / total_events if total_events else 0

            demand_level = (
                "High" if avg_impact > 0.6 or high_impact_count >= 3 else
                "Elevated" if avg_impact > 0.4 or high_impact_count >= 1 else
                "Normal"
            )

            return JSONResponse({
                "market_id": resolved_market_id,
                "market": market_info,
                "window_days": days,
                "as_of": today.isoformat(),
                "demand_summary": {
                    "level": demand_level,
                    "total_events": total_events,
                    "high_impact_events": high_impact_count,
                    "avg_impact_score": round(avg_impact, 2),
                    "peak_dates": peak_dates,
                },
                "events": events,
                "categories": categories,
                "signals": signals,
            })

    except Exception as e:
        logger.error(f"[MarketIntelligence] Failed: {e}")
        # Return empty structure — never crash the dashboard
        return JSONResponse({
            "market_id": market_id or "30a_fl",
            "market": {"name": "30A Beaches, FL"},
            "window_days": days,
            "as_of": date.today().isoformat(),
            "demand_summary": {
                "level": "Unknown",
                "total_events": 0,
                "high_impact_events": 0,
                "avg_impact_score": 0,
                "peak_dates": [],
            },
            "events": [],
            "categories": [],
            "signals": [],
            "note": "Market data not yet available. Run the event scraper to populate."
        })
