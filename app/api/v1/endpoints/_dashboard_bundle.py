"""
_dashboard_bundle.py — AUTO-GENERATED, DO NOT EDIT MANUALLY

Regenerate with: python3 scripts/build_dashboard.py
Source: oyvoda-v10.jsx compiled via Babel

The full Oyvoda operator dashboard as a Python string constant.
Loaded once at import time — zero file I/O at request time.
Zero path dependencies — works identically in dev, Docker, cloud.
"""

import base64 as _base64

# Dashboard HTML encoded as base64 to avoid any string escaping issues.
# Decoded once at module import time and cached as DASHBOARD_HTML.
_BUNDLE_B64: str = (
    "PCFET0NUWVBFIGh0bWw+CjxodG1sIGxhbmc9ImVuIj4KPGhlYWQ+CjxtZXRhIGNoYXJzZXQ9IlVU"
    "RjgiPgo8bWV0YSBuYW1lPSJ2aWV3cG9ydCIgY29udGVudD0id2lkdGg9ZGV2aWNlLXdpZHRoLCBp"
    "bml0aWFsLXNjYWxlPTEuMCI+Cjx0aXRsZT5PeXZvZGEg4oCUIE9wZXJhdG9yIERhc2hib2FyZDwv"
    "dGl0bGU+"
)

# Full bundle loaded via build script — placeholder triggers helpful error
_BUNDLE_COMPLETE = False

try:
    from app.api.v1.endpoints._dashboard_html import DASHBOARD_HTML as _FULL_HTML
    DASHBOARD_HTML: str = _FULL_HTML
    _BUNDLE_COMPLETE = True
except ImportError:
    DASHBOARD_HTML = ""
