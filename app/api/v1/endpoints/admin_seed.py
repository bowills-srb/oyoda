"""
admin_seed.py — Super-admin-only endpoint to seed Beach Habitats data.

POST /app/api/admin/seed-beach-habitats
POST /app/api/admin/relink-tenant
GET  /app/api/admin/seed-status

Protected by OYVODA_MASTER_KEY header.
Uses psycopg2 (sync) in a thread to avoid asyncpg/pgbouncer prepared statement conflicts.

Scoped knowledge is now the only supported KB write target for this seed
path. Legacy concierge_knowledge writes were retired in Phase 1.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Admin Seed"])

OPERATOR_NAME  = "Beach Habitats 30A"
OPERATOR_ID    = "op_beach_habitats"
DEFAULT_TENANT = "00000000-0000-0000-0000-000000000001"

BASE_DIR        = Path(__file__).parent.parent.parent.parent.parent
UNIT_INFO_JSON  = BASE_DIR / "scripts" / "output" / "unit_info_import" / "properties_normalized.json"
KNOWLEDGE_JSONL = BASE_DIR / "scripts" / "output" / "concierge_knowledge" / "concierge_knowledge_bulk.jsonl"

COMMUNITIES = {
    "watercolor": "watercolor", "water color": "watercolor",
    "rosemary beach": "rosemary_beach", "rosemary": "rosemary_beach",
    "alys beach": "alys_beach", "alys": "alys_beach",
    "seaside": "seaside",
    "grayton beach": "grayton_beach", "grayton": "grayton_beach",
    "blue mountain beach": "blue_mountain", "blue mountain": "blue_mountain",
    "seagrove beach": "seagrove", "seagrove": "seagrove",
    "watersound": "watersound", "water sound": "watersound",
    "seacrest beach": "seacrest", "seacrest": "seacrest",
    "inlet beach": "inlet_beach", "inlet": "inlet_beach",
}

SECTION_QUESTIONS = {
    "parking":   "Where do we park and what are the parking instructions?",
    "door_lock": "How do we access the property and what are the door codes?",
    "pool":      "What are the pool and amenity rules?",
    "beach":     "What beach gear and access information should we know?",
    "bikes":     "Are there bikes available and where are they?",
    "shipping":  "Can we ship packages to the property?",
    "transport": "What transportation options are available?",
    "check_in":  "What are the full check-in instructions?",
    "check_out": "What are the full check-out instructions?",
    "wifi":      "What is the full WiFi information?",
    "hvac":      "How do we use the AC and heating?",
    "appliance": "How do we use the appliances?",
}


def _normalize_message(text: str) -> set[str]:
    stopwords = {
        "the", "and", "for", "with", "that", "this", "from", "your", "you", "are",
        "can", "could", "would", "should", "what", "when", "where", "which", "who",
        "how", "why", "does", "did", "have", "has", "had", "our", "about", "into",
        "them", "they", "will", "just", "need", "any", "all", "get", "let", "know",
    }
    import re
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in stopwords}


def _question_key(text: str) -> str:
    return " ".join(sorted(_normalize_message(text)))


def _norm_community(v) -> str:
    return COMMUNITIES.get(str(v or "").lower().strip(), "other")


def _safe(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.lower() not in ("nan", "none", "") else None


def _check_key(provided: str) -> None:
    key      = os.getenv("OYVODA_MASTER_KEY", "").strip()
    seed_key = os.getenv("OYVODA_SEED_KEY", "").strip()
    if not key and not seed_key:
        raise HTTPException(500, "OYVODA_MASTER_KEY not configured on server")
    provided = provided.strip()
    if not provided:
        raise HTTPException(403, "X-Master-Key header required")
    if not ((key and provided == key) or (seed_key and provided == seed_key)):
        raise HTTPException(403, "Invalid master key")


def _get_sync_conn():
    """psycopg2 connection — bypasses asyncpg/pgbouncer prepared statement issues."""
    import psycopg2
    from app.core.config import get_settings
    raw = get_settings().database_url
    url = raw.replace("postgresql+asyncpg://", "postgresql://")
    sep = "&" if "?" in url else "?"
    url += f"{sep}sslmode=require"
    return psycopg2.connect(url)


# ─────────────────────────────────────────────────────────────────────────────

@router.get("/app/api/admin/seed-status")
async def seed_status():
    """Public diagnostic — shows file availability, key config, and live table columns."""
    table_cols = {}
    try:
        conn = _get_sync_conn()
        cur = conn.cursor()
        for tbl in ["concierge_scoped_knowledge", "properties", "knowledge_embeddings"]:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name=%s ORDER BY ordinal_position",
                (tbl,)
            )
            table_cols[tbl] = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
    except Exception as e:
        table_cols["error"] = str(e)
    return {
        "master_key_configured": bool(os.getenv("OYVODA_MASTER_KEY", "").strip()),
        "unit_info_json_exists": UNIT_INFO_JSON.exists(),
        "knowledge_jsonl_exists": KNOWLEDGE_JSONL.exists(),
        "unit_info_path": str(UNIT_INFO_JSON),
        "knowledge_path": str(KNOWLEDGE_JSONL),
        "base_dir": str(BASE_DIR),
        "table_columns": table_cols,
    }


@router.post("/app/api/admin/seed-beach-habitats")
async def seed_beach_habitats(
    request: Request,
    tenant_id: str = DEFAULT_TENANT,
    dry_run: bool = False,
    x_master_key: str = Header(default=""),
):
    _check_key(x_master_key)
    import asyncio
    result = await asyncio.get_event_loop().run_in_executor(
        None, _run_seed_sync, tenant_id, dry_run
    )
    return JSONResponse(result)


def _run_seed_sync(tenant_id: str, dry_run: bool) -> dict:
    """Synchronous seed using psycopg2 — no asyncpg, no prepared statement issues."""
    results: dict = {
        "tenant_id": tenant_id,
        "dry_run": dry_run,
        "properties":          {"inserted": 0, "updated": 0, "errors": []},
        "concierge_scoped_knowledge": {"upserted": 0, "errors": []},
        "files_found": {
            "unit_info":       UNIT_INFO_JSON.exists(),
            "knowledge_jsonl": KNOWLEDGE_JSONL.exists(),
        },
    }

    try:
        conn = _get_sync_conn()
        conn.autocommit = False
    except Exception as e:
        results["connection_error"] = str(e)
        return results

    cur = conn.cursor()

    try:
        # ── Step 1: properties ────────────────────────────────────────────────
        code_to_id: dict = {}
        if UNIT_INFO_JSON.exists():
            records = json.loads(UNIT_INFO_JSON.read_text("utf-8"))
            cur.execute(
                "SELECT property_code, id::text FROM properties WHERE tenant_id=%s",
                (tenant_id,)
            )
            existing = {r[0]: r[1] for r in cur.fetchall()}
            code_to_id = dict(existing)

            for rec in records:
                code = _safe(rec.get("unit_code") or rec.get("property_code"))
                if not code:
                    continue
                addr      = _safe(rec.get("address") or rec.get("address_street")) or "Unknown"
                community = _norm_community(rec.get("community"))
                bedrooms  = int(float(rec.get("bedrooms") or 0))
                bathrooms = float(rec.get("bathrooms") or 0)
                wifi_net  = _safe(rec.get("wifi_network") or rec.get("wifi_name"))
                wifi_pw   = _safe(rec.get("wifi_password"))
                guide_url = _safe(rec.get("guidebook_url") or rec.get("property_guide_url")
                                  or rec.get("property_guide"))
                notes     = _safe(rec.get("notes") or rec.get("general_notes"))

                try:
                    if code in existing:
                        if not dry_run:
                            cur.execute("""
                                UPDATE properties SET
                                    address_street=%s, community=%s,
                                    bedrooms=%s, bathrooms=%s,
                                    wifi_network=%s, wifi_password=%s,
                                    property_guide_url=%s, general_notes=%s,
                                    updated_at=NOW()
                                WHERE tenant_id=%s AND property_code=%s
                            """, (addr, community, bedrooms, bathrooms,
                                  wifi_net, wifi_pw, guide_url, notes,
                                  tenant_id, code))
                        results["properties"]["updated"] += 1
                    else:
                        new_id = str(uuid4())
                        if not dry_run:
                            cur.execute("""
                                INSERT INTO properties
                                    (id, tenant_id, property_code, address_street, community,
                                     bedrooms, bathrooms, wifi_network, wifi_password,
                                     property_guide_url, general_notes,
                                     data_source, confidence_score)
                                VALUES
                                    (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'import',0.85)
                            """, (new_id, tenant_id, code, addr, community,
                                  bedrooms, bathrooms, wifi_net, wifi_pw,
                                  guide_url, notes))
                        code_to_id[code] = new_id
                        results["properties"]["inserted"] += 1
                except Exception as e:
                    results["properties"]["errors"].append(f"{code}: {str(e)[:120]}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass

            if not dry_run:
                conn.commit()

        # ── Step 2: concierge_scoped_knowledge ────────────────────────────────
        if KNOWLEDGE_JSONL.exists():
            lines = [
                l.strip()
                for l in KNOWLEDGE_JSONL.read_text("utf-8").split("\n")
                if l.strip()
            ]
            for line in lines:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                code = rec.get("unit_code", "")
                if not code:
                    continue
                property_id = code_to_id.get(code)
                if not property_id:
                    results["concierge_scoped_knowledge"]["errors"].append(
                        f"{code}: missing property_id for scoped seed"
                    )
                    continue

                facts    = rec.get("facts", {})
                faq      = rec.get("faq", [])
                sections = rec.get("sections", {})

                # Build Q&A rows from all knowledge sources
                rows = []  # (question, answer, category, confidence)

                # Key facts
                if facts.get("wifi"):
                    rows.append(("What is the WiFi password?",
                                 f"WiFi password: {facts['wifi']}", "facts", 1.0))
                if facts.get("check_in"):
                    rows.append(("What time is check-in?",
                                 str(facts["check_in"])[:500], "facts", 1.0))
                if facts.get("check_out"):
                    rows.append(("What time is check-out?",
                                 str(facts["check_out"])[:200], "facts", 1.0))

                # FAQ entries from guidebook
                for item in faq:
                    q = item.get("question", "").strip()
                    a = item.get("answer", "").strip()
                    if q and a:
                        rows.append((q, a[:2000], "faq", 0.9))

                # Section content
                for sec_key, sec_q in SECTION_QUESTIONS.items():
                    sec_text = sections.get(sec_key, "").strip()
                    if sec_text:
                        rows.append((sec_q, sec_text[:2000], "guidebook", 0.85))

                for (question, answer, category, confidence) in rows:
                    try:
                        if not dry_run:
                            cur.execute("""
                                INSERT INTO concierge_scoped_knowledge
                                    (knowledge_entry_id, tenant_id, scope_type, scope_target_id,
                                     topic_id, question_text, question_key, answer_text,
                                     tags, source, metadata, created_by_user_id, is_active, version)
                                VALUES (
                                    gen_random_uuid(), %s, 'property', %s::uuid,
                                    NULL, %s, %s, %s,
                                    '[]'::jsonb, 'guidebook_import',
                                    %s::jsonb, NULL, true, 1
                                )
                                ON CONFLICT (tenant_id, scope_type, scope_target_id, question_key)
                                WHERE topic_id IS NULL
                                DO UPDATE SET
                                    answer_text = EXCLUDED.answer_text,
                                    source = EXCLUDED.source,
                                    metadata = EXCLUDED.metadata,
                                    updated_at = NOW(),
                                    is_active = TRUE
                            """, (
                                tenant_id,
                                property_id,
                                question,
                                _question_key(question) or "general",
                                answer,
                                json.dumps(
                                    {
                                        "category": category,
                                        "confidence": confidence,
                                        "legacy_property_external_id": code,
                                        "seed_source": "admin_seed",
                                    }
                                ),
                            ))
                        results["concierge_scoped_knowledge"]["upserted"] += 1
                    except Exception as e:
                        results["concierge_scoped_knowledge"]["errors"].append(
                            f"{code}/{category}: {str(e)[:80]}"
                        )
                        try:
                            conn.rollback()
                        except Exception:
                            pass

            if not dry_run:
                conn.commit()

    except Exception as e:
        logger.error("[AdminSeed] Fatal: %s", e)
        results["fatal_error"] = str(e)
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        cur.close()
        conn.close()

    results["summary"] = (
        f"Properties: {results['properties']['inserted']} inserted, "
        f"{results['properties']['updated']} updated | "
        f"concierge_scoped_knowledge: {results['concierge_scoped_knowledge']['upserted']} upserted"
    )
    logger.info("[AdminSeed] %s", results["summary"])
    return results


@router.post("/app/api/admin/relink-tenant")
async def relink_tenant(
    request: Request,
    new_tenant_id: str,
    x_master_key: str = Header(default=""),
):
    """Re-link all Beach Habitats rows to Lanier's real tenant UUID after signup."""
    _check_key(x_master_key)

    import asyncio

    def _relink():
        conn = _get_sync_conn()
        cur  = conn.cursor()
        try:
            cur.execute(
                "UPDATE properties SET tenant_id=%s, updated_at=NOW() WHERE tenant_id=%s",
                (new_tenant_id, DEFAULT_TENANT)
            )
            props = cur.rowcount
            cur.execute(
                "UPDATE concierge_scoped_knowledge SET tenant_id=%s, updated_at=NOW() WHERE tenant_id=%s",
                (new_tenant_id, DEFAULT_TENANT)
            )
            ck = cur.rowcount
            cur.execute(
                "UPDATE concierge_scoped_knowledge_history SET tenant_id=%s WHERE tenant_id=%s",
                (new_tenant_id, DEFAULT_TENANT)
            )
            conn.commit()
            return {"properties_relinked": props, "knowledge_relinked": ck}
        finally:
            cur.close()
            conn.close()

    result = await asyncio.get_event_loop().run_in_executor(None, _relink)
    logger.info("[AdminSeed] Relink → %s: %s", new_tenant_id, result)
    return JSONResponse({"ok": True, "new_tenant_id": new_tenant_id, **result})


@router.get("/app/api/admin", include_in_schema=False)
async def admin_panel(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Master-key protected admin panel — lists all operators, tenant IDs, property counts, Gmail status."""
    from fastapi.responses import HTMLResponse
    master_key = request.query_params.get("key", "")
    if not master_key or master_key != os.getenv("OYVODA_MASTER_KEY", ""):
        return HTMLResponse("""
        <html><body style='background:#08090f;color:#f0ebe3;font-family:sans-serif;
        display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>
        <form method='get'>
          <div style='text-align:center'>
            <p style='font-size:18px;margin-bottom:12px'>Oyvoda Admin</p>
            <input name='key' type='password' placeholder='Master key'
              style='background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.2);
              border-radius:8px;padding:10px 14px;color:#f0ebe3;font-size:14px;margin-right:8px'>
            <button type='submit'
              style='background:#c87832;color:#fff;border:none;border-radius:8px;
              padding:10px 20px;font-size:14px;cursor:pointer'>Enter</button>
          </div>
        </form></body></html>
        """, status_code=401)

    # Fetch all operators
    try:
        from sqlalchemy import text
        ops_result = await db.execute(text("""
            SELECT
                a.id,
                a.tenant_id,
                a.email,
                a.owner_name,
                a.company_name,
                a.plan,
                a.onboarding_complete,
                a.created_at,
                COUNT(DISTINCT p.id) as property_count,
                MAX(g.watched_email) as gmail_inbox,
                MAX(g.created_at) as gmail_connected_at
            FROM operator_accounts a
            LEFT JOIN properties p ON p.tenant_id = a.tenant_id AND p.deleted_at IS NULL
            LEFT JOIN operator_gmail_creds g ON g.operator_id = a.id
            GROUP BY a.id, a.tenant_id, a.email, a.owner_name, a.company_name,
                     a.plan, a.onboarding_complete, a.created_at
            ORDER BY a.created_at DESC
        """))
        operators = [dict(r._mapping) for r in ops_result.fetchall()]
    except Exception as e:
        operators = []
        logger.error("Admin panel query failed: %s", e)

    rows_html = ""
    for op in operators:
        tid = str(op.get('tenant_id', ''))
        oid = str(op.get('id', ''))
        gmail = op.get('gmail_inbox') or '<span style="color:#f59e0b">Not connected</span>'
        prop_count = op.get('property_count', 0)
        onboarded = '✅' if op.get('onboarding_complete') else '⏳'
        created = str(op.get('created_at', ''))[:10]
        rows_html += f"""
        <tr>
          <td style='padding:12px 16px'>
            <div style='font-weight:600'>{op.get('owner_name','')}</div>
            <div style='font-size:12px;color:rgba(240,235,227,0.4)'>{op.get('company_name','')}</div>
          </td>
          <td style='padding:12px 16px;font-size:12px;color:rgba(240,235,227,0.5)'>{op.get('email','')}</td>
          <td style='padding:12px 16px'>
            <code style='font-size:11px;background:rgba(255,255,255,0.05);padding:2px 6px;
              border-radius:4px;color:#c87832'>{tid}</code><br>
            <button onclick="navigator.clipboard.writeText('{tid}')"
              style='margin-top:4px;font-size:10px;background:rgba(200,120,50,0.15);
              border:1px solid rgba(200,120,50,0.3);color:#c87832;border-radius:4px;
              padding:2px 8px;cursor:pointer'>Copy</button>
          </td>
          <td style='padding:12px 16px;text-align:center'>
            <span style='font-size:18px'>{prop_count}</span>
            <br><button onclick="relinkTenant('{tid}', this)"
              style='margin-top:4px;font-size:10px;background:rgba(34,197,94,0.1);
              border:1px solid rgba(34,197,94,0.3);color:#22c55e;border-radius:4px;
              padding:2px 8px;cursor:pointer'>Relink</button>
          </td>
          <td style='padding:12px 16px;font-size:12px'>{gmail}</td>
          <td style='padding:12px 16px;text-align:center'>{onboarded}</td>
          <td style='padding:12px 16px;font-size:12px;color:rgba(240,235,227,0.4)'>{created}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset='UTF-8'>
<title>Oyvoda Admin</title>
<link href='https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500&family=DM+Sans:wght@400;600&family=DM+Mono:wght@400&display=swap' rel='stylesheet'>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#08090f;color:#f0ebe3;font-family:'DM Sans',sans-serif;padding:32px}}
.header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:28px}}
.logo{{font-family:'Cormorant Garamond',serif;font-size:22px;color:#f0ebe3}}
.badge{{background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);
  color:#f87171;border-radius:100px;padding:3px 10px;font-size:11px;font-family:'DM Mono',monospace}}
table{{width:100%;border-collapse:collapse;background:rgba(13,18,32,0.8);
  border:1px solid rgba(255,255,255,0.07);border-radius:12px;overflow:hidden}}
th{{padding:12px 16px;text-align:left;font-size:10px;letter-spacing:0.1em;text-transform:uppercase;
  color:rgba(240,235,227,0.4);font-family:'DM Mono',monospace;background:rgba(255,255,255,0.03);
  border-bottom:1px solid rgba(255,255,255,0.07)}}
tr:not(:last-child){{border-bottom:1px solid rgba(255,255,255,0.05)}}
tr:hover{{background:rgba(255,255,255,0.02)}}
.stat{{background:rgba(13,18,32,0.8);border:1px solid rgba(255,255,255,0.07);
  border-radius:12px;padding:20px 24px;display:inline-block;margin-right:12px;margin-bottom:20px}}
.stat-val{{font-size:28px;font-weight:600;color:#c87832}}
.stat-label{{font-size:12px;color:rgba(240,235,227,0.4);margin-top:2px}}
#toast{{position:fixed;bottom:24px;right:24px;background:#22c55e;color:#fff;
  border-radius:8px;padding:10px 18px;font-size:13px;display:none;z-index:999}}
</style></head><body>
<div class='header'>
  <div class='logo'>oyvoda <span style='font-family:"DM Mono";font-size:12px;color:rgba(240,235,227,0.3)'>/ admin</span></div>
  <span class='badge'>MASTER ACCESS</span>
</div>

<div>
  <div class='stat'><div class='stat-val'>{len(operators)}</div><div class='stat-label'>Total Operators</div></div>
  <div class='stat'><div class='stat-val'>{sum(op.get('property_count',0) for op in operators)}</div><div class='stat-label'>Total Properties</div></div>
  <div class='stat'><div class='stat-val'>{sum(1 for op in operators if op.get('gmail_inbox'))}</div><div class='stat-label'>Gmail Connected</div></div>
  <div class='stat'><div class='stat-val'>{sum(1 for op in operators if op.get('onboarding_complete'))}</div><div class='stat-label'>Onboarding Complete</div></div>
</div>

<table>
  <thead><tr>
    <th>Operator</th><th>Login Email</th><th>Tenant ID</th>
    <th style='text-align:center'>Properties</th><th>Gmail Inbox</th>
    <th style='text-align:center'>Onboarded</th><th>Signed Up</th>
  </tr></thead>
  <tbody>{rows_html}</tbody>
</table>

<div id='toast'></div>
<script>
const MASTER_KEY = new URLSearchParams(location.search).get('key');
async function relinkTenant(tenantId, btn) {{
  btn.textContent = '...';
  try {{
    const r = await fetch('/app/api/admin/relink-tenant?new_tenant_id=' + tenantId, {{
      method: 'POST', headers: {{'X-Master-Key': MASTER_KEY}}
    }});
    const d = await r.json();
    const t = document.getElementById('toast');
    t.textContent = 'Relinked: ' + (d.updated_count || 0) + ' properties';
    t.style.display = 'block';
    setTimeout(() => {{ t.style.display = 'none'; location.reload(); }}, 2000);
  }} catch(e) {{ btn.textContent = 'Error'; }}
}}
</script>
</body></html>"""
    return HTMLResponse(content=html)


@router.post("/app/api/admin/seed-markets")
async def seed_markets_endpoint(request: Request):
    """Seed or refresh market_registry from KNOWN_MARKETS using the richer source config."""
    master_key = request.headers.get("X-Master-Key", "")
    if not master_key or master_key != os.getenv("OYVODA_MASTER_KEY", ""):
        raise HTTPException(status_code=403, detail="Invalid master key")

    import json as _json
    from tools.event_scraper import KNOWN_MARKETS, build_market_sources_config

    inserted, updated = [], []
    try:
        # Use psycopg2 sync (same pattern as rest of admin_seed.py)
        import psycopg2, ssl as _ssl
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        conn = psycopg2.connect(
            os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg", "postgresql"),
            sslmode="require"
        )
        conn.autocommit = False
        cur = conn.cursor()

        for market_id, m in KNOWN_MARKETS.items():
            sources = build_market_sources_config(m.get("sources", {}))
            cur.execute("SELECT 1 FROM market_registry WHERE market_id = %s", (market_id,))
            existed = cur.fetchone() is not None

            cur.execute("""
                INSERT INTO market_registry (
                    market_id, market_name, state_code,
                    center_lat, center_lng, radius_miles, timezone,
                    scrape_enabled, scrape_interval_hours,
                    sources_config, operator_ids, last_scrape_event_count
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,true,24,%s::jsonb,'[]'::jsonb,0)
                ON CONFLICT (market_id) DO UPDATE SET
                    market_name = EXCLUDED.market_name,
                    state_code = EXCLUDED.state_code,
                    center_lat = EXCLUDED.center_lat,
                    center_lng = EXCLUDED.center_lng,
                    radius_miles = EXCLUDED.radius_miles,
                    timezone = EXCLUDED.timezone,
                    scrape_enabled = EXCLUDED.scrape_enabled,
                    scrape_interval_hours = EXCLUDED.scrape_interval_hours,
                    sources_config = EXCLUDED.sources_config
            """, (
                market_id, m["name"], m.get("state", "FL"),
                m["lat"], m["lng"], m.get("radius_miles", 15.0),
                m.get("timezone", "America/Chicago"),
                _json.dumps(sources),
            ))
            if existed:
                updated.append(market_id)
            else:
                inserted.append(market_id)

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error("[AdminSeed] seed-markets failed: %s", e)
        raise HTTPException(500, f"Seed failed: {e}")

    return JSONResponse({
        "ok": True,
        "inserted": inserted,
        "updated": updated,
        "total": len(inserted) + len(updated),
    })


@router.post("/app/api/admin/run-auth-migration")
async def run_auth_migration_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Run the operator auth migration to create operator_accounts, team_members, gmail_creds tables."""
    master_key = request.headers.get("X-Master-Key", "")
    if not master_key or master_key != os.getenv("OYVODA_MASTER_KEY", ""):
        raise HTTPException(status_code=403, detail="Invalid master key")
    try:
        from app.services.auth.operator_auth_service import run_auth_migration
        await run_auth_migration(db)
        return JSONResponse({"ok": True, "message": "Auth migration complete — operator_accounts, operator_team_members, operator_gmail_creds tables created"})
    except Exception as e:
        logger.error("[AdminSeed] Auth migration failed: %s", e, exc_info=True)
        raise HTTPException(500, f"Migration failed: {e}")
