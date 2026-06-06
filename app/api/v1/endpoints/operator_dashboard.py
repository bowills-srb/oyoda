"""
operator_dashboard.py — Oyvoda React Dashboard

Serves the operator dashboard. The dashboard HTML is generated at container
build time by scripts/build_dashboard.py and stored in _dashboard_html.py.

For production: run `python3 scripts/build_dashboard.py` before building
the Docker image. The HTML is then baked into the Python module and requires
no file I/O at request time.

For local dev: the dashboard reads from app/static/dashboard/oyvoda-dashboard.js
which is volume-mounted from the host. Restart the API after JS changes.
"""

import os
import base64
import logging
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Operator Dashboard"])

# ── Dashboard HTML loading strategy ──────────────────────────────────────────
# 1. Try the pre-built Python module (production — baked in at build time)
# 2. Fall back to reading the compiled JS from disk (dev — volume-mounted)
# 3. Fall back to a helpful error page

_CACHED_HTML: str | None = None


def _load_from_module() -> str | None:
    """Load dashboard HTML from the pre-built Python module."""
    try:
        from app.api.v1.endpoints._dashboard_html import DASHBOARD_HTML
        if DASHBOARD_HTML:
            return DASHBOARD_HTML
    except ImportError:
        pass
    return None


def _load_from_disk() -> str | None:
    """Load dashboard JS from disk and assemble HTML (dev fallback)."""
    # The compiled JS lives at app/static/dashboard/oyvoda-dashboard.js
    # Inside container: /app/app/static/dashboard/oyvoda-dashboard.js
    candidates = [
        Path(__file__).parent.parent.parent / "static" / "dashboard" / "oyvoda-dashboard.js",
        Path("/app/app/static/dashboard/oyvoda-dashboard.js"),
    ]
    for p in candidates:
        if p.exists():
            try:
                js = p.read_text(encoding="utf-8")
                logger.info(f"Dashboard: loaded JS from {p} ({len(js):,} bytes)")
                return _build_html(js)
            except Exception as e:
                logger.warning(f"Dashboard: failed to read {p}: {e}")
    return None


def _build_html(js: str) -> str:
    """Assemble the full dashboard HTML with the given JS content."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Oyvoda — AI Guest Experience for Private Stays</title>
<meta name="description" content="AI-powered, RCS-first guest experience platform for STR operators and boutique hotels. White-labeled to your brand, synced to any PMS.">
<meta name="theme-color" content="#08090f">
<!-- Open Graph -->
<meta property="og:type" content="website">
<meta property="og:url" content="https://oyvoda.com/">
<meta property="og:title" content="Oyvoda \u2014 Professional Hospitality for the Private Stay">
<meta property="og:description" content="AI-powered guest experience for STR operators. RCS-first, white-labeled, synced to any PMS. 89% of guest questions resolved automatically.">
<meta property="og:image" content="https://oyvoda-production.up.railway.app/static/og-image.svg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:site_name" content="Oyvoda">
<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Oyvoda \u2014 Professional Hospitality for the Private Stay">
<meta name="twitter:description" content="AI-powered guest experience for STR operators. RCS-first, white-labeled.">
<meta name="twitter:image" content="https://oyvoda-production.up.railway.app/static/og-image.svg">
<!-- Favicon -->
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%2308090f'/%3E%3Ctext x='16' y='23' font-family='Georgia,serif' font-size='21' font-weight='500' fill='%23f0ebe3' text-anchor='middle'%3Eo%3C/text%3E%3Cpath d='M20 7 Q24 4 27 8' stroke='%23c87832' stroke-width='2' fill='none' stroke-linecap='round'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body, #root {{ height: 100%; background: #08090f; color: #f4f6fa; font-family: 'DM Sans', sans-serif; }}
  #loading {{ display: flex; flex-direction: column; align-items: center; justify-content: center;
    height: 100vh; gap: 18px; background: #08090f; color: #5a7090; }}
  .logo {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 38px; font-weight: 500;
    color: #f0ebe3; letter-spacing: -0.02em; }}
  .dots {{ display: flex; gap: 6px; }}
  .dot {{ width: 7px; height: 7px; border-radius: 50%; background: #c87832; animation: pulse 1.4s ease-in-out infinite; }}
  .dot:nth-child(2) {{ animation-delay: .2s; }}
  .dot:nth-child(3) {{ animation-delay: .4s; }}
  .loading-label {{ font-size: 11px; letter-spacing: .08em; text-transform: uppercase; opacity: .5; }}
  @keyframes pulse {{ 0%,60%,100%{{opacity:.25}} 30%{{opacity:1}} }}
</style>
</head>
<body>
<div id="loading">
  <div class="logo">oyvoda</div>
  <div class="dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
  <div class="loading-label">Loading dashboard</div>
</div>
<div id="root"></div>
<script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js"></script>
<script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js"></script>
<script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/prop-types/15.8.1/prop-types.min.js"></script>
<script>
  window.React=React;window.ReactDOM=ReactDOM;window.PropTypes=PropTypes;
  // Expose React hooks as globals so compiled JSX can call them directly
  var useState=React.useState,useEffect=React.useEffect,useRef=React.useRef,
      useCallback=React.useCallback,useMemo=React.useMemo,useContext=React.useContext,
      useReducer=React.useReducer,useLayoutEffect=React.useLayoutEffect;
</script>
<script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/recharts/2.5.0/Recharts.min.js"></script>
<script>
  var _r=Recharts;
  var LineChart=_r.LineChart,Line=_r.Line,BarChart=_r.BarChart,Bar=_r.Bar,
      XAxis=_r.XAxis,YAxis=_r.YAxis,CartesianGrid=_r.CartesianGrid,
      Tooltip=_r.Tooltip,Legend=_r.Legend,ResponsiveContainer=_r.ResponsiveContainer,
      PieChart=_r.PieChart,Pie=_r.Pie,Cell=_r.Cell,AreaChart=_r.AreaChart,
      Area=_r.Area,RadarChart=_r.RadarChart,Radar=_r.Radar,PolarGrid=_r.PolarGrid,
      PolarAngleAxis=_r.PolarAngleAxis,ComposedChart=_r.ComposedChart;
</script>
<script>
{js}
</script>
</body>
</html>"""


def _error_page(msg: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Oyvoda</title>
<style>body{{background:#08090f;color:#f4f6fa;font-family:'DM Sans',sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}}
.wrap{{text-align:center;max-width:600px;padding:40px;}}
.logo{{font-family:Georgia,serif;font-size:36px;color:#f0ebe3;margin-bottom:20px;}}
.err{{color:#ef4444;font-family:monospace;font-size:13px;background:#1a0a0a;
padding:16px;border-radius:8px;text-align:left;margin-top:12px;}}
.hint{{color:#5a7090;font-size:12px;margin-top:12px;line-height:1.6;}}</style>
</head><body><div class="wrap">
<div class="logo">oyvoda</div>
<div class="err">{msg}</div>
<div class="hint">
  Fix: run <code>python3 scripts/build_dashboard.py</code> then restart the API.<br>
  Or copy the compiled JS: <code>cp /tmp/oyvoda-dashboard.js app/static/dashboard/</code>
</div>
</div></body></html>"""


def get_dashboard_html() -> str:
    """Get dashboard HTML — cached after first successful load."""
    global _CACHED_HTML

    # Return cached version if available
    if _CACHED_HTML:
        return _CACHED_HTML

    # Try pre-built Python module first (production)
    html = _load_from_module()
    if html:
        _CACHED_HTML = html
        logger.info("Dashboard: loaded from Python module (production mode)")
        return html

    # Fall back to disk (dev / volume-mounted)
    html = _load_from_disk()
    if html:
        # Don't cache in dev mode so changes are picked up on restart
        logger.info("Dashboard: loaded from disk (dev mode)")
        return html

    # Nothing found
    return _error_page(
        "Dashboard JS not found.\n"
        "Expected: app/static/dashboard/oyvoda-dashboard.js\n"
        "Run: python3 scripts/build_dashboard.py"
    )


@router.get("/operator-dashboard", response_class=HTMLResponse, include_in_schema=False)
async def serve_operator_dashboard(request: Request):
    import base64
    settings = get_settings()
    ops_key = settings.ops_api_key or os.getenv("OPS_API_KEY") or ""
    if ops_key:
        auth_header = request.headers.get("Authorization", "")
        authenticated = False
        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                _, password = decoded.split(":", 1)
                authenticated = (password == ops_key)
            except Exception:
                pass
        if not authenticated:
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Oyvoda Ops"'},
                content="Access restricted.",
                media_type="text/plain",
            )
    return HTMLResponse(content=get_dashboard_html())
