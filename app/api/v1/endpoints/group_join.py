"""
group_join.py — Web endpoint for the group share link.

Route: GET/POST /c/join/{join_token}

GET  → renders the join form (name + phone number)
POST → registers the guest and sends them a welcome SMS

This is a lightweight HTML form — no React, no frontend build.
Designed to open cleanly inside an RCS/SMS link tap on any device.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.services.concierge.group_session import (
    GroupSessionService,
    get_group_session_service,
    build_group_join_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Group Join"])

BASE_URL = os.getenv("BASE_URL", "https://oyvoda.com")


# ─────────────────────────────────────────────────────────────────────────────
# GET /c/join/{join_token} — show the join form
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/c/join/{join_token}", response_class=HTMLResponse)
async def show_join_form(
    join_token: str,
    db: AsyncSession = Depends(get_async_session),
):
    svc = get_group_session_service()
    session_row = await svc.get_session_by_join_token(db, join_token)

    if not session_row:
        return HTMLResponse(content=_expired_page(), status_code=410)

    property_name = session_row.property_name or "your vacation rental"
    concierge_name = getattr(session_row, "concierge_name", None) or "Oyvo"
    concierge_emoji = getattr(session_row, "concierge_emoji", None) or "🐚"
    lead_first = (session_row.guest_name or "your group").split()[0]
    primary_color = getattr(session_row, "operator_primary_color", None) or "#0ea5e9"

    return HTMLResponse(content=_join_form_page(
        join_token=join_token,
        property_name=property_name,
        concierge_name=concierge_name,
        concierge_emoji=concierge_emoji,
        lead_first=lead_first,
        primary_color=primary_color,
    ))


# ─────────────────────────────────────────────────────────────────────────────
# POST /c/join/{join_token} — submit the form
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/c/join/{join_token}", response_class=HTMLResponse)
async def submit_join_form(
    join_token: str,
    name: str = Form(...),
    phone: str = Form(...),
    db: AsyncSession = Depends(get_async_session),
):
    name = name.strip()[:50]
    phone = phone.strip()

    if not name or not phone:
        return HTMLResponse(
            content=_error_page("Please enter your name and phone number."),
            status_code=400,
        )

    svc = get_group_session_service()
    result = await svc.join_session(db, join_token, name, phone)

    if not result.success:
        return HTMLResponse(
            content=_error_page(result.error or "Something went wrong. Please try again."),
            status_code=400,
        )

    return HTMLResponse(content=_success_page(
        name=name,
        concierge_name=result.concierge_name or "Oyvo",
        concierge_emoji=result.concierge_emoji or "🐚",
        property_name=result.property_name or "the property",
        primary_color="#0ea5e9",
    ))


# ─────────────────────────────────────────────────────────────────────────────
# API endpoint for native apps / RCS webviews
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/v1/group/join/{join_token}")
async def api_join_session(
    join_token: str,
    name: str = Form(...),
    phone: str = Form(...),
    db: AsyncSession = Depends(get_async_session),
):
    """JSON API version for native integrations."""
    svc = get_group_session_service()
    result = await svc.join_session(db, join_token, name.strip(), phone.strip())

    if not result.success:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": result.error},
        )

    return JSONResponse(content={
        "success": True,
        "property_name": result.property_name,
        "concierge_name": result.concierge_name,
        "concierge_emoji": result.concierge_emoji,
        "welcome_message": result.welcome_message,
    })


# ─────────────────────────────────────────────────────────────────────────────
# HTML templates — clean mobile-first design
# ─────────────────────────────────────────────────────────────────────────────

def _join_form_page(
    join_token: str,
    property_name: str,
    concierge_name: str,
    concierge_emoji: str,
    lead_first: str,
    primary_color: str,
) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <title>{concierge_emoji} Join {concierge_name}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f8fafc;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px 16px;
    }}
    .card {{
      background: white;
      border-radius: 20px;
      padding: 36px 28px;
      max-width: 400px;
      width: 100%;
      box-shadow: 0 4px 24px rgba(0,0,0,0.08);
      text-align: center;
    }}
    .emoji {{ font-size: 52px; margin-bottom: 12px; }}
    h1 {{ font-size: 22px; font-weight: 700; color: #0f172a; margin-bottom: 8px; }}
    .subtitle {{ font-size: 15px; color: #64748b; margin-bottom: 28px; line-height: 1.5; }}
    .property-badge {{
      display: inline-block;
      background: #f1f5f9;
      color: #475569;
      font-size: 13px;
      font-weight: 600;
      padding: 6px 14px;
      border-radius: 100px;
      margin-bottom: 28px;
    }}
    label {{ display: block; text-align: left; font-size: 13px; font-weight: 600;
             color: #374151; margin-bottom: 6px; }}
    input {{
      width: 100%;
      padding: 14px 16px;
      border: 1.5px solid #e2e8f0;
      border-radius: 12px;
      font-size: 16px;
      color: #0f172a;
      margin-bottom: 16px;
      outline: none;
      transition: border-color 0.2s;
    }}
    input:focus {{ border-color: {primary_color}; }}
    button {{
      width: 100%;
      padding: 16px;
      background: {primary_color};
      color: white;
      border: none;
      border-radius: 12px;
      font-size: 16px;
      font-weight: 600;
      cursor: pointer;
      transition: opacity 0.2s;
    }}
    button:active {{ opacity: 0.85; }}
    .legal {{ font-size: 12px; color: #94a3b8; margin-top: 16px; line-height: 1.5; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="emoji">{concierge_emoji}</div>
    <h1>Meet {concierge_name}</h1>
    <p class="subtitle">
      {lead_first} invited you to their AI co-host.<br>
      Ask anything about the property, local spots, and more.
    </p>
    <div class="property-badge">🏠 {property_name}</div>
    <form method="POST" action="/c/join/{join_token}">
      <label for="name">Your first name</label>
      <input type="text" id="name" name="name" placeholder="Mike"
             autocomplete="given-name" required>
      <label for="phone">Your phone number</label>
      <input type="tel" id="phone" name="phone" placeholder="+1 (555) 000-0000"
             autocomplete="tel" required>
      <button type="submit">Connect to {concierge_name} →</button>
    </form>
    <p class="legal">
      By joining, you consent to receive SMS messages from {concierge_name}.
      Message and data rates may apply.
    </p>
  </div>
</body>
</html>"""


def _success_page(
    name: str,
    concierge_name: str,
    concierge_emoji: str,
    property_name: str,
    primary_color: str,
) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>You're connected!</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f8fafc;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px 16px;
    }}
    .card {{
      background: white;
      border-radius: 20px;
      padding: 40px 28px;
      max-width: 400px;
      width: 100%;
      box-shadow: 0 4px 24px rgba(0,0,0,0.08);
      text-align: center;
    }}
    .check {{ font-size: 56px; margin-bottom: 16px; }}
    h1 {{ font-size: 24px; font-weight: 700; color: #0f172a; margin-bottom: 10px; }}
    p {{ font-size: 16px; color: #475569; line-height: 1.6; }}
    .sms-hint {{
      margin-top: 24px;
      background: #f0fdf4;
      border: 1.5px solid #bbf7d0;
      border-radius: 12px;
      padding: 16px;
      font-size: 14px;
      color: #166534;
      line-height: 1.5;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="check">✅</div>
    <h1>You're connected, {name}!</h1>
    <p>
      {concierge_emoji} {concierge_name} just sent you a welcome text.
      Text back any time with questions about {property_name}.
    </p>
    <div class="sms-hint">
      📱 Check your messages — {concierge_name} is ready for your questions.
    </div>
  </div>
</body>
</html>"""


def _error_page(error_message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Something went wrong</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; background: #f8fafc;
            min-height: 100vh; display: flex; align-items: center;
            justify-content: center; padding: 24px; }}
    .card {{ background: white; border-radius: 20px; padding: 36px 28px;
             max-width: 400px; width: 100%; text-align: center;
             box-shadow: 0 4px 24px rgba(0,0,0,0.08); }}
    .icon {{ font-size: 48px; margin-bottom: 16px; }}
    h1 {{ font-size: 20px; font-weight: 700; color: #0f172a; margin-bottom: 10px; }}
    p {{ font-size: 15px; color: #64748b; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">⚠️</div>
    <h1>Something went wrong</h1>
    <p>{error_message}</p>
  </div>
</body>
</html>"""


def _expired_page() -> str:
    return _error_page(
        "This invite link has expired or is no longer valid. "
        "Please ask the lead guest to share the link again."
    )
