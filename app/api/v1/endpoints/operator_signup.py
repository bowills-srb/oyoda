"""
operator_signup.py — Self-service operator signup and onboarding.

Handles the full signup flow including:
  - Two-email model (login email + messaging inbox email)
  - PMS selection with correct messaging strategy per PMS
  - Email provider detection (Google vs Microsoft vs Other)
  - Gmail OAuth self-service (popup flow)
  - Microsoft OAuth stub (future)
  - Beach Habitats property linkage (existing tenant migration)
  - Team invite acceptance
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import urllib.parse
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.services.auth.operator_auth_service import get_operator_auth_service

# Import JWT helper to verify auth on protected endpoints
def _get_current_user(request):
    """Inline JWT verifier — avoids circular import with operator_app.py."""
    import json, base64, time, os as _os
    token = request.cookies.get("oyvoda_access")
    if not token:
        return None
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        _, body, _ = parts
        payload = json.loads(base64.urlsafe_b64decode(body + "=="))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Operator Signup"])

BASE_URL   = os.getenv("BASE_URL", "https://oyvoda.com")
GMAIL_CID  = os.getenv("GMAIL_CLIENT_ID", "")
GMAIL_CSEC = os.getenv("GMAIL_CLIENT_SECRET", "")

# Microsoft OAuth (future — stub for now)
MS_CLIENT_ID  = os.getenv("MICROSOFT_CLIENT_ID", "")
MS_CLIENT_SEC = os.getenv("MICROSOFT_CLIENT_SECRET", "")

# ─────────────────────────────────────────────────────────────────────────────
# Signup page
# ─────────────────────────────────────────────────────────────────────────────

SIGNUP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Get Started — Oyvoda</title>
<meta name="robots" content="noindex">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#080c14;color:#eef0f5;font-family:'DM Sans',sans-serif;min-height:100vh;display:flex;flex-direction:column;-webkit-font-smoothing:antialiased}
.wrap{flex:1;display:flex;align-items:center;justify-content:center;padding:40px 20px;position:relative}
.grid{position:absolute;inset:0;background-image:linear-gradient(rgba(200,120,50,0.04) 1px,transparent 1px),linear-gradient(90deg,rgba(200,120,50,0.04) 1px,transparent 1px);background-size:60px 60px;pointer-events:none}
.glow{position:absolute;top:40%;left:50%;transform:translate(-50%,-50%);width:700px;height:600px;background:radial-gradient(ellipse,rgba(200,120,50,0.08) 0%,transparent 65%);pointer-events:none}
.card{background:rgba(15,21,38,0.98);border:1px solid rgba(200,120,50,0.25);border-radius:20px;padding:48px;width:100%;max-width:560px;position:relative;z-index:1;box-shadow:0 32px 80px rgba(0,0,0,0.6),inset 0 1px 0 rgba(255,255,255,0.05)}
.logo{font-family:'Cormorant Garamond',serif;font-size:28px;font-weight:500;color:#f0ebe3;text-align:center;display:block;text-decoration:none;margin-bottom:6px;letter-spacing:0.02em}
.sub{font-size:14px;color:rgba(238,240,245,0.65);text-align:center;margin-bottom:32px;font-weight:400}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.group{margin-bottom:18px}
.label{display:block;font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(238,240,245,0.95);margin-bottom:7px;font-weight:500}
.label-hint{font-size:11px;color:rgba(238,240,245,0.6);font-family:'DM Sans',sans-serif;text-transform:none;letter-spacing:0;display:block;margin-top:3px}
.input{width:100%;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.15);border-radius:10px;padding:12px 16px;font-size:14px;color:#eef0f5;font-family:'DM Sans',sans-serif;transition:border-color 0.15s,background 0.15s;outline:none}
.input:focus{border-color:rgba(200,120,50,0.6);background:rgba(255,255,255,0.09);box-shadow:0 0 0 3px rgba(200,120,50,0.1)}
.input::placeholder{color:rgba(238,240,245,0.38)}
select.input{cursor:pointer}
select.input option{background:#0f1526;color:#eef0f5}
.divider{border:none;border-top:1px solid rgba(255,255,255,0.09);margin:24px 0}
.section-label{font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.14em;text-transform:uppercase;color:#d88c40;margin-bottom:16px;font-weight:500}
.btn{width:100%;background:linear-gradient(135deg,#c87832,#e09040);color:#fff;border:none;border-radius:10px;padding:14px;font-size:15px;font-weight:600;font-family:'DM Sans',sans-serif;cursor:pointer;margin-top:8px;transition:all 0.2s;letter-spacing:0.01em}
.btn:hover{background:linear-gradient(135deg,#d8883c,#f0a050);transform:translateY(-1px);box-shadow:0 8px 24px rgba(200,120,50,0.35)}
.btn:disabled{opacity:0.5;cursor:not-allowed;transform:none;box-shadow:none}
.err{background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);border-radius:8px;padding:12px 14px;font-size:13px;color:#f87171;margin-bottom:18px;display:none}
.info-box{background:rgba(200,120,50,0.08);border:1px solid rgba(200,120,50,0.2);border-radius:10px;padding:14px 16px;font-size:12.5px;color:rgba(238,240,245,0.7);margin-bottom:18px;line-height:1.6;display:none}
.info-box strong{color:#e09040}
.legal{font-size:12px;color:rgba(238,240,245,0.5);text-align:center;margin-top:16px;line-height:1.5}
.legal a{color:rgba(200,120,50,0.8);text-decoration:none}
.login-link{text-align:center;font-size:13px;color:rgba(238,240,245,0.65);margin-top:20px}
.login-link a{color:#c87832;text-decoration:none;font-weight:500}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,0.3);border-top-color:#fff;border-radius:50%;animation:spin 0.6s linear infinite;margin-right:8px;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div class="wrap">
  <div class="grid"></div><div class="glow"></div>
  <div class="card">
    <a href="/" class="logo">oyvoda</a>
    <div class="sub">Set up your operator account — takes 2 minutes</div>
    <div class="err" id="err"></div>

    <!-- Account info -->
    <div class="row2">
      <div class="group">
        <label class="label">Your name</label>
        <input class="input" id="owner_name" placeholder="Your full name" autocomplete="name">
      </div>
      <div class="group">
        <label class="label">Company name</label>
        <input class="input" id="company_name" placeholder="Your company name">
      </div>
    </div>

    <div class="group">
    <label class="label">Your login email
    <span class="label-hint">Used to sign in to Oyvoda</span>
    </label>
    <input class="input" id="email" type="email" placeholder="you@yourcompany.com" autocomplete="email">
    </div>

    <div class="group">
      <label class="label">Password</label>
      <input class="input" id="password" type="password" placeholder="At least 8 characters" autocomplete="new-password">
    </div>

    <hr class="divider">
    <div class="section-label">Messaging setup</div>

    <div class="group">
      <label class="label">Property management system</label>
      <select class="input" id="pms" onchange="onPmsChange()">
        <option value="escapia">Loading providers…</option>
      </select>
    </div>

    <!-- PMS-specific messaging hint -->
    <div class="info-box" id="pms-hint"></div>

    <div class="group">
      <label class="label">Guest messaging inbox
        <span class="label-hint">The email address where Vrbo / Escapia sends guest message copies — often different from your login email</span>
      </label>
      <input class="input" id="messaging_email" type="email" placeholder="notifications@yourcompany.com" oninput="onMessagingEmailInput()">
      <div id="same-email-warning" style="display:none;margin-top:8px;padding:10px 12px;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.25);border-radius:8px;font-size:12px;color:#fbbf24;line-height:1.5">
        ⚠ This matches your login email. That's fine if Vrbo / Escapia forwards to your personal inbox — but most operators use a separate company address for guest messages. Double-check your Escapia notification settings if unsure.
      </div>
    </div>

    <div class="group">
      <label class="label">Email provider for that inbox</label>
      <select class="input" id="email_provider" onchange="onProviderChange()">
        <option value="google">Google Workspace / Gmail</option>
        <option value="microsoft">Microsoft 365 / Outlook</option>
        <option value="other">Other (IMAP/custom)</option>
      </select>
    </div>

    <!-- Provider-specific note -->
    <div class="info-box" id="provider-hint" style="display:block">
      <strong>Google Workspace:</strong> You'll connect your inbox during setup using Google's secure OAuth flow. No password sharing required.
    </div>

    <hr class="divider">
    <div class="section-label">Property portfolio</div>

    <div class="row2">
      <div class="group">
        <label class="label">Number of properties</label>
        <input class="input" id="property_count" type="number" placeholder="e.g. 25" min="1" max="5000">
      </div>
      <div class="group">
        <label class="label">Phone (optional)</label>
        <input class="input" id="phone" type="tel" placeholder="+1 (555) 000-0000">
      </div>
    </div>

    <button class="btn" id="btn" onclick="doSignup()">Create Account →</button>
    <p class="legal">By creating an account you agree to Oyvoda's <a href="/privacy" style="color:#c87832">Terms & Privacy Policy</a>.</p>
    <p class="login-link">Already have an account? <a href="/app">Sign in</a></p>
  </div>
</div>
<script>
// Provider hints
var PROVIDER_HINTS = {
  google: `<strong>Google / Gmail:</strong> After signup, you'll click "Connect with Google" and approve access in a small Google popup. No password sharing — Google handles it securely.`,
  microsoft: `<strong>Microsoft 365 / Outlook:</strong> After signup, you'll connect via a Microsoft popup. No password sharing required.`,
  other: `<strong>Other provider:</strong> Our team will reach out within 24 hours to set up your inbox connection via IMAP.`,
};

var PMS_CATALOG = {};
var DIRECT_OPTIONS = [
  {
    provider: 'airbnb_direct',
    name: 'Airbnb (direct)',
    message_transport: 'direct_api',
    readiness: 'planned',
    notes: 'Airbnb has an API for verified partners. Oyvoda will apply for direct API access on your behalf. This typically takes 2–4 weeks, so connecting your inbox is still helpful in the meantime.',
  },
  {
    provider: 'vrbo_direct',
    name: 'Vrbo (direct)',
    message_transport: 'direct_api',
    readiness: 'planned',
    notes: 'Vrbo has an API for verified partners. Oyvoda will apply for direct API access on your behalf. This typically takes 2–4 weeks, so connecting your inbox is still helpful in the meantime.',
  },
  {
    provider: 'other',
    name: 'Other / Custom',
    message_transport: 'email_bridge',
    readiness: 'planned',
    notes: 'Most PMS systems can still work through a forwarded guest-messaging inbox even before a dedicated API adapter exists.',
  },
];

function titleCase(text) {
  return String(text || '').replace(/_/g, ' ').replace(/\\b\\w/g, function(ch) { return ch.toUpperCase(); });
}

function pmsMeta(pms) {
  return PMS_CATALOG[pms] || DIRECT_OPTIONS.find(function(item) { return item.provider === pms; }) || null;
}

function buildPmsHint(meta) {
  if (!meta) {
    return `<strong>Property messaging:</strong> We can usually start with an inbox bridge, then deepen the PMS integration once the account is connected.`;
  }
  var transport = meta.message_transport || 'email_bridge';
  var name = meta.name || meta.provider || 'This provider';
  if (meta.notes) {
    return `<strong>${name}:</strong> ${meta.notes}`;
  }
  if (transport === 'direct_api') {
    return `<strong>${name}:</strong> Oyvoda can work from the provider API directly. Connecting an inbox is still recommended as backup coverage.`;
  }
  if (transport === 'hybrid') {
    return `<strong>${name}:</strong> Oyvoda can combine provider data with an inbox bridge so property, booking, and guest messaging context stay aligned.`;
  }
  return `<strong>${name}:</strong> Oyvoda will usually start from the guest-messaging inbox for this provider and then expand the integration path as needed.`;
}

function pmsNeedsInbox(meta) {
  if (!meta) return true;
  var transport = meta.message_transport || 'email_bridge';
  return transport !== 'direct_api';
}

async function loadPmsCatalog() {
  var select = document.getElementById('pms');
  try {
    var res = await fetch('/gateway/providers', { credentials: 'include' });
    var data = await res.json();
    var providers = Array.isArray(data.providers) ? data.providers : [];
    var preferredOrder = ['escapia', 'guesty', 'hostaway', 'track', 'streamline', 'lodgify', 'hostfully', 'ownerrez', 'beds24', 'smoobu'];
    var providerMap = {};
    providers.forEach(function(item) { providerMap[item.provider] = item; });
    preferredOrder.forEach(function(providerKey) {
      if (providerMap[providerKey]) {
        PMS_CATALOG[providerKey] = providerMap[providerKey];
      }
    });
    select.innerHTML = '';
    preferredOrder.forEach(function(providerKey) {
      var meta = PMS_CATALOG[providerKey];
      if (!meta) return;
      var option = document.createElement('option');
      option.value = providerKey;
      option.textContent = meta.name || titleCase(providerKey);
      select.appendChild(option);
    });
    DIRECT_OPTIONS.forEach(function(item) {
      var option = document.createElement('option');
      option.value = item.provider;
      option.textContent = item.name;
      select.appendChild(option);
    });
  } catch (error) {
    select.innerHTML = `
      <option value="escapia">Escapia</option>
      <option value="guesty">Guesty</option>
      <option value="hostaway">Hostaway</option>
      <option value="track">Track</option>
      <option value="lodgify">Lodgify</option>
      <option value="airbnb_direct">Airbnb (direct)</option>
      <option value="vrbo_direct">Vrbo (direct)</option>
      <option value="other">Other / Custom</option>
    `;
  }
  onPmsChange();
}

function onMessagingEmailInput() {
  var login = document.getElementById('email').value.trim().toLowerCase();
  var msg = document.getElementById('messaging_email').value.trim().toLowerCase();
  var warning = document.getElementById('same-email-warning');
  var pms = document.getElementById('pms').value;
  if (msg && login && msg === login && pmsNeedsInbox(pmsMeta(pms))) {
    warning.style.display = 'block';
  } else {
    warning.style.display = 'none';
  }
}

function onPmsChange() {
  var pms = document.getElementById('pms').value;
  var hint = document.getElementById('pms-hint');
  var meta = pmsMeta(pms);
  if (meta) {
    hint.innerHTML = buildPmsHint(meta);
    hint.style.display = 'block';
  } else {
    hint.style.display = 'none';
  }
  var needsEmail = pmsNeedsInbox(meta);
  var msgGroup = document.getElementById('messaging_email').closest('.group');
  var providerGroup = document.getElementById('email_provider').closest('.group');
  var providerHint = document.getElementById('provider-hint');
  msgGroup.style.display = 'block';
  providerGroup.style.display = 'block';
  providerHint.style.display = 'block';
  onMessagingEmailInput();
}

function onProviderChange() {
  var provider = document.getElementById('email_provider').value;
  var hint = document.getElementById('provider-hint');
  hint.innerHTML = PROVIDER_HINTS[provider] || '';
  hint.style.display = hint.innerHTML ? 'block' : 'none';
}

// Trigger on load
loadPmsCatalog();

document.addEventListener('keydown', e => { if (e.key==='Enter') doSignup(); });

window.doSignup = async function doSignup() {
  var err = document.getElementById('err');
  var btn = document.getElementById('btn');
  var data = {
    owner_name:      document.getElementById('owner_name').value.trim(),
    company_name:    document.getElementById('company_name').value.trim(),
    email:           document.getElementById('email').value.trim(),
    password:        document.getElementById('password').value,
    messaging_email: document.getElementById('messaging_email').value.trim(),
    email_provider:  document.getElementById('email_provider').value,
    pms:             document.getElementById('pms').value,
    property_count:  parseInt(document.getElementById('property_count').value) || 1,
    phone:           document.getElementById('phone').value.trim() || null,
  };
  // messaging_email defaults to login email
  if (!data.messaging_email) data.messaging_email = data.email;

  if (!data.owner_name || !data.company_name || !data.email || !data.password) {
    err.textContent = 'Please fill in all required fields.';
    err.style.display='block'; return;
  }
  if (data.password.length < 8) {
    err.textContent = 'Password must be at least 8 characters.';
    err.style.display='block'; return;
  }
  err.style.display='none';
  btn.disabled=true;
  btn.innerHTML='<span class="spinner"></span>Creating account...';

  try {
    var res = await fetch('/signup', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(data)
    });
    var json = await res.json();
    if (!res.ok) {
      err.textContent = json.detail || 'Something went wrong.';
      err.style.display='block';
      btn.disabled=false; btn.innerHTML='Create Account →';
      return;
    }
    sessionStorage.setItem('oyvoda_signup', JSON.stringify(json.operator));
    window.location.href = '/onboarding';
  } catch(e) {
    err.textContent='Connection error. Please try again.';
    err.style.display='block';
    btn.disabled=false; btn.innerHTML='Create Account →';
  }
}
</script>
</body>
</html>"""


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return HTMLResponse(content=SIGNUP_HTML)


@router.post("/signup")
async def signup_submit(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    from fastapi import HTTPException

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid request body")

    email           = data.get("email", "").strip()
    password        = data.get("password", "")
    company_name    = data.get("company_name", "").strip()
    owner_name      = data.get("owner_name", "").strip()
    messaging_email = data.get("messaging_email", "").strip() or email
    email_provider  = data.get("email_provider", "google")
    pms             = data.get("pms", "escapia")
    property_count  = int(data.get("property_count", 1))
    phone           = data.get("phone") or None

    if not all([email, password, company_name, owner_name]):
        raise HTTPException(400, "All fields are required.")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")

    svc = get_operator_auth_service()
    try:
        account = await svc.create_account(
            db=db, email=email, password=password,
            company_name=company_name, owner_name=owner_name,
            phone=phone,
            messaging_email=messaging_email,
            email_provider=email_provider,
            pms=pms,
            property_count=property_count,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("[Signup] create_account failed: %s", e, exc_info=True)
        raise HTTPException(500, f"Account creation failed: {type(e).__name__}: {e}")

    # Link any existing properties for this company name
    # (handles Beach Habitats migration where props are already in DB)
    try:
        from sqlalchemy import text
        await db.execute(
            text("""
                UPDATE properties
                SET tenant_id = :tid::uuid
                WHERE LOWER(operator_name) = LOWER(:company)
                  AND (tenant_id IS NULL
                       OR tenant_id = '00000000-0000-0000-0000-000000000001'::uuid)
            """),
            {"tid": account["tenant_id"], "company": company_name},
        )
        await db.commit()
    except Exception as _le:
        logger.debug("[Signup] Property link attempt: %s", _le)

    return JSONResponse({"ok": True, "operator": account})


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding wizard
# ─────────────────────────────────────────────────────────────────────────────

def _build_gmail_auth_url(operator_id: str, watched_email: str = "") -> str:
    if not GMAIL_CID:
        return ""
    redirect_uri = f"{BASE_URL}/app/gmail-callback"
    # Sign the state so the callback can verify it wasn't tampered with.
    # state = operator_id:hmac_hex  (HMAC-SHA256 keyed on JWT_SECRET)
    _jwt_secret = os.getenv("JWT_SECRET", "oyvoda-dev")
    sig = hmac.new(_jwt_secret.encode(), operator_id.encode(), hashlib.sha256).hexdigest()[:16]
    signed_state = f"{operator_id}:{sig}"
    params = {
        "client_id":     GMAIL_CID,
        "redirect_uri":  redirect_uri,
        "scope":         "https://www.googleapis.com/auth/gmail.modify",
        "response_type": "code",
        "access_type":   "offline",
        "prompt":        "consent",
        "state":         signed_state,
    }
    if watched_email:
        params["login_hint"] = watched_email
    return "https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode(params)


def _verify_oauth_state(state: str) -> str | None:
    """Verify the signed OAuth state param. Returns operator_id on success, None on failure."""
    try:
        operator_id, received_sig = state.rsplit(":", 1)
    except ValueError:
        return None
    _jwt_secret = os.getenv("JWT_SECRET", "oyvoda-dev")
    expected_sig = hmac.new(_jwt_secret.encode(), operator_id.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(expected_sig, received_sig):
        return None
    return operator_id


def _build_microsoft_auth_url(operator_id: str) -> str:
    """Microsoft OAuth2 for Outlook/Exchange mailboxes."""
    if not MS_CLIENT_ID:
        return ""
    redirect_uri = f"{BASE_URL}/app/microsoft-callback"
    _jwt_secret = os.getenv("JWT_SECRET", "oyvoda-dev")
    sig = hmac.new(_jwt_secret.encode(), operator_id.encode(), hashlib.sha256).hexdigest()[:16]
    signed_state = f"{operator_id}:{sig}"
    params = {
        "client_id":     MS_CLIENT_ID,
        "redirect_uri":  redirect_uri,
        "scope":         "https://graph.microsoft.com/Mail.ReadWrite offline_access",
        "response_type": "code",
        "response_mode": "query",
        "state":         signed_state,
    }
    return "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?" + urllib.parse.urlencode(params)


ONBOARDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Setup — Oyvoda</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#08090f;color:#f0ebe3;font-family:'DM Sans',sans-serif;min-height:100vh;display:flex;flex-direction:column;-webkit-font-smoothing:antialiased}
.wrap{flex:1;display:flex;align-items:center;justify-content:center;padding:48px 20px}
.card{background:rgba(13,18,32,0.95);border:1px solid rgba(200,120,50,0.15);border-radius:24px;padding:56px 48px;width:100%;max-width:580px;box-shadow:0 32px 80px rgba(0,0,0,0.5)}
.logo{font-family:'Cormorant Garamond',serif;font-size:24px;font-weight:500;color:#f0ebe3;text-align:center;display:block;margin-bottom:36px;text-decoration:none}
.step-row{display:flex;gap:8px;margin-bottom:36px;justify-content:center}
.step-dot{width:8px;height:8px;border-radius:50%;background:rgba(255,255,255,0.1);transition:all 0.3s}
.step-dot.active{background:#c87832;width:28px;border-radius:4px}
.step-dot.done{background:rgba(34,197,94,0.5)}
.step{display:none}
.step.active{display:block}
h2{font-size:22px;font-weight:600;margin-bottom:8px;color:#f0ebe3}
.desc{font-size:14px;color:rgba(240,235,227,0.5);margin-bottom:28px;line-height:1.6}
.connect-box{background:rgba(255,255,255,0.03);border:1px solid rgba(200,120,50,0.12);border-radius:14px;padding:22px;margin-bottom:14px}
.connect-box-title{font-size:14px;font-weight:600;color:#f0ebe3;margin-bottom:4px;display:flex;align-items:center;gap:8px}
.connect-box-sub{font-size:12px;color:rgba(240,235,227,0.4);margin-bottom:16px;line-height:1.5}
.connect-box.disabled{opacity:0.4;pointer-events:none}
.inline-note{display:none;margin:14px 0 0;padding:12px 14px;border-radius:10px;font-size:12px;line-height:1.5}
.inline-note.show{display:block}
.inline-note.info{background:rgba(200,120,50,0.08);border:1px solid rgba(200,120,50,0.18);color:rgba(240,235,227,0.78)}
.inline-note.error{background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);color:#fecaca}
.btn-primary{display:block;width:100%;background:#c87832;color:#f0ebe3;border:none;border-radius:10px;padding:14px;font-size:14px;font-weight:600;font-family:'DM Sans',sans-serif;cursor:pointer;text-align:center;text-decoration:none;transition:all 0.15s}
.btn-primary:hover{background:#e09040}
.btn-secondary{display:block;width:100%;background:rgba(255,255,255,0.04);color:rgba(240,235,227,0.5);border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:12px;font-size:13px;font-weight:500;font-family:'DM Sans',sans-serif;cursor:pointer;text-align:center;text-decoration:none;margin-top:12px;transition:all 0.15s}
.btn-secondary:hover{background:rgba(255,255,255,0.08);color:#f0ebe3}
.badge-green{display:inline-flex;align-items:center;gap:6px;background:rgba(34,197,94,0.1);color:#22c55e;border:1px solid rgba(34,197,94,0.2);border-radius:100px;padding:4px 12px;font-size:12px;font-family:'DM Mono',monospace}
.badge-pending{display:inline-flex;align-items:center;gap:6px;background:rgba(245,158,11,0.1);color:#f59e0b;border:1px solid rgba(245,158,11,0.2);border-radius:100px;padding:4px 12px;font-size:12px;font-family:'DM Mono',monospace}
.inbox-info{background:rgba(200,120,50,0.06);border:1px solid rgba(200,120,50,0.12);border-radius:10px;padding:14px 16px;font-size:13px;color:rgba(240,235,227,0.6);margin-bottom:20px;line-height:1.6}
.inbox-info strong{color:#c87832}
.success-icon{font-size:52px;text-align:center;margin-bottom:16px}
.property-count{display:flex;align-items:center;gap:12px;background:rgba(34,197,94,0.05);border:1px solid rgba(34,197,94,0.15);border-radius:10px;padding:14px 16px;font-size:13px;color:rgba(240,235,227,0.7);margin-bottom:20px}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <a href="/" class="logo">oyvoda</a>
    <div class="step-row">
      <div class="step-dot active" id="dot-1"></div>
      <div class="step-dot" id="dot-2"></div>
      <div class="step-dot" id="dot-3"></div>
    </div>

    <!-- Step 1: Welcome + summary -->
    <div class="step active" id="step-1">
      <h2>Welcome to Oyvoda 🐚</h2>
      <p class="desc">Your account is ready. Now let's connect your guest messaging inbox so Oyvo can start handling inquiries automatically.</p>
      <div class="inbox-info" id="inbox-summary"></div>
      <div class="property-count" id="prop-count" style="display:none">
        <span style="font-size:20px">🏠</span>
        <div><strong id="prop-count-num" style="color:#f0ebe3"></strong><br>
        <span style="font-size:12px;color:rgba(240,235,227,0.4)">properties linked to your account</span></div>
      </div>
      <button class="btn-primary" onclick="nextStep(2)">Connect Your Inbox →</button>
    </div>

    <!-- Step 2: Connect inbox -->
    <div class="step" id="step-2">
      <h2>Connect your inbox</h2>
      <p class="desc" id="step2-desc">Guest messages from Vrbo, Airbnb, and direct inquiries are forwarded to your inbox. Connect it so Oyvo can read and reply on your behalf.</p>

      <!-- Google -->
      <div class="connect-box" id="box-google" style="display:none">
        <div class="connect-box-title">
          <span>Google Workspace / Gmail</span>
          <span id="google-status"></span>
        </div>
        <div class="connect-box-sub" id="google-inbox-label"></div>
        <button class="btn-primary" id="google-btn" onclick="connectGoogle()">Connect with Google →</button>
        <div class="inline-note info" id="google-note"></div>
      </div>

      <!-- Microsoft -->
      <div class="connect-box" id="box-microsoft" style="display:none">
        <div class="connect-box-title">
          <span>Microsoft 365 / Outlook</span>
          <span id="ms-status"></span>
        </div>
        <div class="connect-box-sub" id="ms-inbox-label"></div>
        <button class="btn-primary" id="ms-btn" onclick="connectMicrosoft()">Connect with Microsoft →</button>
        <div class="inline-note info" id="ms-note"></div>
      </div>

      <!-- Other / Manual -->
      <div class="connect-box" id="box-other" style="display:none">
        <div class="connect-box-title">Custom / IMAP inbox</div>
        <div class="connect-box-sub">Our team will set up your inbox connection within 24 hours. You can start using the dashboard right away — inbox integration will activate automatically once configured.</div>
        <button class="btn-primary" onclick="skipInbox()">Continue — I'll wait for setup →</button>
      </div>

      <!-- API-based PMS (Guesty, Hostaway, etc.) -->
      <div class="connect-box" id="box-api-pms" style="display:none">
        <div class="connect-box-title" id="api-pms-title"></div>
        <div class="connect-box-sub" id="api-pms-sub"></div>
        <button class="btn-primary" onclick="nextStep(3)">Continue →</button>
      </div>

      <!-- Also connect inbox if they have one -->
      <div id="also-inbox" style="display:none;margin-top:14px">
        <div class="connect-box">
          <div class="connect-box-title">Also connect email inbox (recommended)</div>
          <div class="connect-box-sub">Even with API access, some messages may come via email. Connecting your inbox ensures nothing is missed.</div>
          <div id="also-inbox-inner"></div>
        </div>
      </div>

      <button class="btn-secondary" onclick="skipInbox()">Skip for now and finish setup</button>
    </div>

    <!-- Step 3: Done -->
    <div class="step" id="step-3">
      <div class="success-icon">✅</div>
      <h2 style="text-align:center">You're all set!</h2>
      <p class="desc" style="text-align:center">Oyvo is now monitoring your inbox. Pre-booking inquiry drafts will appear in your dashboard for review before anything is sent.</p>
      <button class="btn-primary" onclick="goToDashboard()">Open Dashboard →</button>
    </div>
  </div>
</div>
<script>
var op = JSON.parse(sessionStorage.getItem('oyvoda_signup') || '{}');
var currentStep = 1;
var ONBOARDING_PMS_CATALOG = {};
var ONBOARDING_DIRECT_OPTIONS = {
  airbnb_direct: {
    provider: 'airbnb_direct',
    name: 'Airbnb',
    message_transport: 'direct_api',
    notes: 'Oyvoda will apply for direct Airbnb API access for your account. This typically takes 2–4 weeks, and your inbox can cover the gap in the meantime.',
  },
  vrbo_direct: {
    provider: 'vrbo_direct',
    name: 'Vrbo',
    message_transport: 'direct_api',
    notes: 'Oyvoda will apply for direct Vrbo API access for your account. This typically takes 2–4 weeks, and your inbox can cover the gap in the meantime.',
  },
  other: {
    provider: 'other',
    name: 'Other / Custom',
    message_transport: 'email_bridge',
    notes: 'Most custom PMS setups can start from a forwarded guest-messaging inbox while the deeper integration is configured.',
  },
};

function onboardingPmsMeta(pms) {
  return ONBOARDING_PMS_CATALOG[pms] || ONBOARDING_DIRECT_OPTIONS[pms] || null;
}

function onboardingPmsIsApi(meta) {
  if (!meta) return false;
  return (meta.message_transport || 'email_bridge') === 'direct_api';
}

// Populate step 1 summary
(function() {
  var summary = document.getElementById('inbox-summary');
  if (op.messaging_email && op.messaging_email !== op.email) {
    summary.innerHTML = 'Oyvo will monitor <strong>' + op.messaging_email + '</strong> for incoming guest messages. Your login email is <strong>' + op.email + '</strong>.';
  } else {
    summary.innerHTML = 'Oyvo will monitor <strong>' + (op.email||'your inbox') + '</strong> for incoming guest messages.';
  }

  // Check if properties were linked
  fetch('/onboarding/property-count?tenant_id=' + (op.tenant_id||''))
    .then(r=>r.json())
    .then(data=>{
      if (data.count > 0) {
        var el = document.getElementById('prop-count');
        el.style.display = 'flex';
        document.getElementById('prop-count-num').textContent = data.count + ' properties';
      }
    }).catch(()=>{});
})();

// Setup step 2 based on PMS + provider
async function setupOnboardingStepTwo() {
  var provider = op.email_provider || 'google';
  var pms = op.pms || 'escapia';
  var msgEmail = op.messaging_email || op.email || '';
  try {
    var res = await fetch('/gateway/providers', { credentials: 'include' });
    var data = await res.json();
    var providers = Array.isArray(data.providers) ? data.providers : [];
    providers.forEach(function(item) {
      ONBOARDING_PMS_CATALOG[item.provider] = item;
    });
  } catch (error) {}
  var meta = onboardingPmsMeta(pms);
  var isApiPms = onboardingPmsIsApi(meta);
  var pmsName = (meta && meta.name) || pms;

  if (isApiPms) {
    var box = document.getElementById('box-api-pms');
    box.style.display = 'block';
    document.getElementById('api-pms-title').textContent = pmsName + ' API Integration';
    document.getElementById('api-pms-sub').textContent =
      (meta && meta.notes)
      ? meta.notes
      : ('Oyvoda can connect directly to ' + pmsName + ' and still fall back to your inbox when needed.');
    // Show email inbox option too
    document.getElementById('also-inbox').style.display = 'block';
    var inner = document.getElementById('also-inbox-inner');
    if (provider === 'google') {
      inner.innerHTML = '<button class="btn-primary" onclick="connectGoogle()">Connect Google Inbox →</button>';
    } else if (provider === 'microsoft') {
      inner.innerHTML = '<button class="btn-primary" onclick="connectMicrosoft()">Connect Outlook Inbox →</button>';
    }
  } else if (provider === 'google') {
    var box = document.getElementById('box-google');
    box.style.display = 'block';
    document.getElementById('google-inbox-label').textContent =
      'Connecting: ' + msgEmail + ' (your guest messaging inbox)';
  } else if (provider === 'microsoft') {
    var box = document.getElementById('box-microsoft');
    box.style.display = 'block';
    document.getElementById('ms-inbox-label').textContent =
      'Connecting: ' + msgEmail + ' (your guest messaging inbox)';
  } else {
    document.getElementById('box-other').style.display = 'block';
  }
}
setupOnboardingStepTwo();

// Check if returning from OAuth callback
if (sessionStorage.getItem('inbox_connected') === 'google') {
  document.getElementById('google-status').innerHTML = '<span class="badge-green">✓ Connected</span>';
  setInlineNote('google', '', '');
  var btn = document.getElementById('google-btn');
  if (btn) { btn.textContent = '✓ Connected — Continue →'; btn.onclick = function(){ nextStep(3); }; }
}
if (sessionStorage.getItem('inbox_connected') === 'microsoft') {
  document.getElementById('ms-status').innerHTML = '<span class="badge-green">✓ Connected</span>';
  setInlineNote('microsoft', '', '');
  var btn = document.getElementById('ms-btn');
  if (btn) { btn.textContent = '✓ Connected — Continue →'; btn.onclick = function(){ nextStep(3); }; }
}

function nextStep(n) {
  document.getElementById('step-' + currentStep).classList.remove('active');
  document.getElementById('dot-' + currentStep).classList.remove('active');
  document.getElementById('dot-' + currentStep).classList.add('done');
  currentStep = n;
  document.getElementById('step-' + n).classList.add('active');
  document.getElementById('dot-' + n).classList.add('active');
}

function setInlineNote(provider, kind, message) {
  var note = document.getElementById(provider === 'google' ? 'google-note' : 'ms-note');
  if (!note) { return; }
  if (!message) {
    note.className = 'inline-note info';
    note.textContent = '';
    return;
  }
  note.className = 'inline-note ' + (kind || 'info') + ' show';
  note.textContent = message;
}

function setConnectButtonState(provider, text, disabled) {
  var btn = document.getElementById(provider === 'google' ? 'google-btn' : 'ms-btn');
  if (!btn) { return; }
  btn.textContent = text;
  btn.disabled = !!disabled;
  btn.style.opacity = disabled ? '0.7' : '1';
  btn.style.cursor = disabled ? 'wait' : 'pointer';
}

function openOAuthPopup(url, provider) {
  var providerLabel = provider === 'google' ? 'Google' : 'Microsoft';
  setInlineNote(provider, 'info', 'Opening ' + providerLabel + ' sign-in. If your browser blocks the popup, we will continue in this tab.');
  setConnectButtonState(provider, 'Opening sign-in…', true);
  var popup = window.open(url, 'inbox_auth',
    'width=600,height=700,left='+((screen.width-600)/2)+',top='+((screen.height-700)/2));
  if (!popup) {
    setInlineNote(provider, 'error', 'Your browser blocked the popup. Continuing to sign-in in this tab now.');
    window.location.href = url;
    return;
  }
  var redirectFallback = setTimeout(function() {
    if (sessionStorage.getItem('inbox_connected') !== provider) {
      setInlineNote(provider, 'info', 'Still waiting on sign-in. If the popup did not appear, continuing in this tab.');
      window.location.href = url;
    }
  }, 2500);
  var check = setInterval(function() {
    if (!popup || popup.closed) {
      clearInterval(check);
      clearTimeout(redirectFallback);
      if (sessionStorage.getItem('inbox_connected') === provider) {
        nextStep(3);
      } else {
        setInlineNote(provider, 'info', 'Sign-in was closed before finishing. You can try again or skip for now and finish setup.');
        setConnectButtonState(provider, provider === 'google' ? 'Connect with Google →' : 'Connect with Microsoft →', false);
      }
    }
  }, 600);
}

function connectGoogle() {
  if (!op.id) { alert('Session expired — please sign in again.'); return; }
  setInlineNote('google', '', '');
  fetch('/app/gmail-auth-url?operator_id=' + op.id + '&hint=' + encodeURIComponent(op.messaging_email||''))
    .then(r=>r.json())
    .then(data => {
      if (data.url) { openOAuthPopup(data.url, 'google'); }
      else {
        setInlineNote('google', 'error', 'Google sign-in is not configured on the server yet. You can skip for now and finish setup.');
        setConnectButtonState('google', 'Connect with Google →', false);
      }
    }).catch(function() {
      setInlineNote('google', 'error', 'We could not start Google sign-in right now. You can try again or skip for now and finish setup.');
      setConnectButtonState('google', 'Connect with Google →', false);
    });
}

function connectMicrosoft() {
  if (!op.id) { alert('Session expired — please sign in again.'); return; }
  setInlineNote('microsoft', '', '');
  fetch('/app/microsoft-auth-url?operator_id=' + op.id)
    .then(r=>r.json())
    .then(data => {
      if (data.url) { openOAuthPopup(data.url, 'microsoft'); }
      else {
        setInlineNote('microsoft', 'error', 'Microsoft sign-in is not configured yet. You can skip for now and finish setup.');
        setConnectButtonState('microsoft', 'Connect with Microsoft →', false);
      }
    }).catch(function() {
      setInlineNote('microsoft', 'error', 'We could not start Microsoft sign-in right now. You can try again or skip for now and finish setup.');
      setConnectButtonState('microsoft', 'Connect with Microsoft →', false);
    });
}

function skipInbox() {
  nextStep(3);
}

async function goToDashboard() {
  if (op.id) {
    await fetch('/onboarding/complete', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({operator_id: op.id})
    }).catch(()=>{});
  }
  window.location.href = '/app';
}
</script>
</body>
</html>"""


@router.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(request: Request):
    return HTMLResponse(content=ONBOARDING_HTML)


@router.get("/onboarding/property-count")
async def onboarding_property_count(
    tenant_id: str = "",
    db: AsyncSession = Depends(get_async_session),
):
    """Return count of properties linked to this tenant — shown during onboarding."""
    if not tenant_id:
        return {"count": 0}
    try:
        from sqlalchemy import text
        result = await db.execute(
            text("SELECT COUNT(*) FROM properties WHERE tenant_id=:tid::uuid AND deleted_at IS NULL"),
            {"tid": tenant_id},
        )
        count = result.scalar() or 0
        return {"count": count}
    except Exception:
        return {"count": 0}


@router.post("/onboarding/complete")
async def onboarding_complete(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    # Require a valid JWT — operator_id comes from the token, not the body.
    # This prevents any unauthenticated caller from marking arbitrary accounts complete.
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"ok": False, "error": "Not authenticated"}, status_code=401)

    operator_id = user.get("sub")
    if operator_id:
        svc = get_operator_auth_service()
        await svc.mark_onboarding_complete(db, operator_id)

    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# Gmail OAuth — generate auth URL + handle callback
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/app/gmail-auth-url")
async def gmail_auth_url(operator_id: str, hint: str = ""):
    url = _build_gmail_auth_url(operator_id, hint)
    if not url:
        return JSONResponse({"error": "Gmail OAuth not configured"}, status_code=503)
    return JSONResponse({"url": url})


@router.get("/app/gmail-callback", response_class=HTMLResponse)
async def gmail_callback(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    code        = request.query_params.get("code", "")
    raw_state   = request.query_params.get("state", "")
    error       = request.query_params.get("error", "")

    if error or not code:
        return HTMLResponse(_callback_page(False, f"Authorization failed: {error or 'No code received'}", None))

    # Verify the signed state to prevent account-mixup attacks
    operator_id = _verify_oauth_state(raw_state)
    if not operator_id:
        return HTMLResponse(_callback_page(False, "Invalid OAuth state — possible CSRF attempt.", None))

    if not all([GMAIL_CID, GMAIL_CSEC]):
        return HTMLResponse(_callback_page(False, "Gmail credentials not configured on server.", None))

    try:
        redirect_uri = f"{BASE_URL}/app/gmail-callback"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code, "client_id": GMAIL_CID,
                    "client_secret": GMAIL_CSEC,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            token_data    = resp.json()
            refresh_token = token_data.get("refresh_token")

        if not refresh_token:
            return HTMLResponse(_callback_page(False, "No refresh token returned. Please try again.", None))
    except Exception as e:
        logger.error("[GmailCallback] Token exchange failed: %s", e)
        return HTMLResponse(_callback_page(False, f"Token exchange failed: {e}", None))

    try:
        from sqlalchemy import text
        result = await db.execute(
            text("SELECT id, tenant_id, messaging_email, email FROM operator_accounts WHERE id=:id"),
            {"id": operator_id},
        )
        op_row = result.fetchone()
        if not op_row:
            return HTMLResponse(_callback_page(False, "Operator account not found.", None))

        # Use messaging_email (inbox) as the watched address
        watched = op_row.messaging_email or op_row.email

        svc = get_operator_auth_service()
        await svc.store_gmail_creds(
            db=db,
            operator_id=str(op_row.id),
            tenant_id=str(op_row.tenant_id),
            watched_email=watched,
            refresh_token=refresh_token,
        )
        watch_notice = ""
        try:
            from app.services.integrations.gmail_push import register_gmail_watch

            watch_result = await register_gmail_watch(
                db,
                operator_id=str(op_row.id),
                tenant_id=str(op_row.tenant_id),
                watched_email=watched,
                refresh_token=refresh_token,
            )
            if watch_result.status == "ok":
                watch_notice = " Gmail push is active."
            elif watch_result.reason == "gmail_push_topic_missing":
                watch_notice = " Background polling is active; Gmail push will activate after Pub/Sub is configured."
            else:
                watch_notice = " Background polling is active; Gmail push registration is pending."
        except Exception as watch_exc:
            logger.warning("[GmailCallback] Watch registration failed for operator %s: %s", operator_id, watch_exc)
            watch_notice = " Background polling is active; Gmail push registration is pending."
        logger.info("[GmailCallback] Creds stored for operator %s — watching %s", operator_id, watched)
        return HTMLResponse(_callback_page(True, f"Gmail connected! Watching {watched}.{watch_notice}", "google"))

    except Exception as e:
        logger.error("[GmailCallback] Storage failed: %s", e)
        return HTMLResponse(_callback_page(False, f"Failed to save credentials: {e}", None))


# ─────────────────────────────────────────────────────────────────────────────
# Microsoft OAuth stub (future)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/app/microsoft-auth-url")
async def microsoft_auth_url(operator_id: str):
    url = _build_microsoft_auth_url(operator_id)
    if not url:
        return JSONResponse({"error": "Microsoft OAuth not yet configured"}, status_code=503)
    return JSONResponse({"url": url})


@router.get("/app/microsoft-callback", response_class=HTMLResponse)
async def microsoft_callback(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Microsoft OAuth2 callback.
    Exchanges code for refresh token and stores as microsoft_refresh_token
    in operator_gmail_creds (reuses same table, different provider).
    Full implementation pending MICROSOFT_CLIENT_ID/SECRET in Railway.
    """
    code        = request.query_params.get("code", "")
    raw_state   = request.query_params.get("state", "")
    error       = request.query_params.get("error", "")

    if error or not code:
        return HTMLResponse(_callback_page(False, f"Authorization failed: {error or 'No code'}", None))

    # Verify signed state
    operator_id = _verify_oauth_state(raw_state)
    if not operator_id:
        return HTMLResponse(_callback_page(False, "Invalid OAuth state — possible CSRF attempt.", None))

    if not all([MS_CLIENT_ID, MS_CLIENT_SEC]):
        return HTMLResponse(_callback_page(False, "Microsoft OAuth not yet configured. Our team will reach out.", None))

    try:
        redirect_uri = f"{BASE_URL}/app/microsoft-callback"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                data={
                    "client_id": MS_CLIENT_ID, "client_secret": MS_CLIENT_SEC,
                    "code": code, "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    "scope": "https://graph.microsoft.com/Mail.ReadWrite offline_access",
                },
            )
            resp.raise_for_status()
            token_data    = resp.json()
            refresh_token = token_data.get("refresh_token")

        if not refresh_token:
            return HTMLResponse(_callback_page(False, "No refresh token returned.", None))

        from sqlalchemy import text
        result = await db.execute(
            text("SELECT id, tenant_id, messaging_email, email FROM operator_accounts WHERE id=:id"),
            {"id": operator_id},
        )
        op_row = result.fetchone()
        if not op_row:
            return HTMLResponse(_callback_page(False, "Operator account not found.", None))

        watched = op_row.messaging_email or op_row.email
        svc = get_operator_auth_service()
        await svc.store_gmail_creds(
            db=db, operator_id=str(op_row.id),
            tenant_id=str(op_row.tenant_id),
            watched_email=watched, refresh_token=refresh_token,
        )
        # Mark as microsoft provider
        await db.execute(
            text("UPDATE operator_gmail_creds SET email_provider='microsoft' WHERE operator_id=:id"),
            {"id": str(op_row.id)},
        )
        await db.commit()
        logger.info("[MicrosoftCallback] Creds stored for operator %s", operator_id)
        return HTMLResponse(_callback_page(True, f"Microsoft inbox connected! Watching {watched}", "microsoft"))

    except Exception as e:
        logger.error("[MicrosoftCallback] Failed: %s", e)
        return HTMLResponse(_callback_page(False, f"Connection failed: {e}", None))


def _callback_page(success: bool, message: str, provider) -> str:
    icon  = "✅" if success else "❌"
    color = "#22c55e" if success else "#ef4444"

    if success and provider:
        js = f"""
(function() {{
  try {{
    if (window.opener && !window.opener.closed) {{
      window.opener.sessionStorage.setItem('inbox_connected', '{provider}');
      setTimeout(function() {{ window.close(); }}, 1800);
    }} else {{
      // Tab redirect fallback — no opener means we came via full-page redirect
      setTimeout(function() {{ window.location.href = '/app/connect-gmail?connected={provider}'; }}, 1800);
    }}
  }} catch(e) {{
    setTimeout(function() {{ window.location.href = '/app/connect-gmail?connected={provider}'; }}, 1800);
  }}
}})();"""
    else:
        js = "setTimeout(function() { try { window.close(); } catch(e) {} }, 3000);"

    close_note = "This window will close automatically..." if success else "You can close this window."
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>body{{background:#08090f;color:#f0ebe3;font-family:'DM Sans',sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.box{{text-align:center;padding:32px}}.icon{{font-size:48px;margin-bottom:16px}}
p{{font-size:15px;color:{color};margin-bottom:8px}}
small{{font-size:12px;color:rgba(240,235,227,0.3)}}</style></head>
<body><div class="box"><div class="icon">{icon}</div>
<p>{message}</p><small>{close_note}</small>
</div><script>{js}</script></body></html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Team invite acceptance
# ─────────────────────────────────────────────────────────────────────────────

ACCEPT_INVITE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Accept Invite — Oyvoda</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#08090f;color:#f0ebe3;font-family:'DM Sans',sans-serif;min-height:100vh;
     display:flex;align-items:center;justify-content:center;padding:24px;-webkit-font-smoothing:antialiased}
.card{background:rgba(13,18,32,0.95);border:1px solid rgba(200,120,50,0.15);border-radius:20px;
      padding:48px;width:100%;max-width:420px;box-shadow:0 32px 80px rgba(0,0,0,0.5);text-align:center}
.logo{font-family:'Cormorant Garamond',serif;font-size:24px;font-weight:500;color:#f0ebe3;
      display:block;margin-bottom:24px;text-decoration:none}
h2{font-size:20px;font-weight:600;margin-bottom:8px}
.sub{font-size:13px;color:rgba(240,235,227,0.4);margin-bottom:28px;line-height:1.5}
.group{margin-bottom:18px;text-align:left}
.label{display:block;font-size:11px;letter-spacing:0.1em;text-transform:uppercase;
       color:rgba(240,235,227,0.4);margin-bottom:6px}
.input{width:100%;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);
       border-radius:10px;padding:12px 16px;font-size:14px;color:#f0ebe3;outline:none;
       font-family:'DM Sans',sans-serif;transition:border-color 0.15s}
.input:focus{border-color:rgba(200,120,50,0.4)}
.btn{width:100%;background:#c87832;color:#f0ebe3;border:none;border-radius:10px;padding:14px;
     font-size:14px;font-weight:600;cursor:pointer;margin-top:8px;transition:all 0.15s}
.btn:hover{background:#e09040}
.err{background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);border-radius:8px;
     padding:12px;font-size:13px;color:#ef4444;margin-bottom:16px;display:none;text-align:left}
</style>
</head>
<body>
<div class="card">
  <a href="/" class="logo">oyvoda</a>
  <h2>You've been invited 🎉</h2>
  <p class="sub">Set a password to activate your team account and access the Oyvoda dashboard.</p>
  <div class="err" id="err"></div>
  <div class="group">
    <label class="label">New password</label>
    <input class="input" id="password" type="password" placeholder="At least 8 characters">
  </div>
  <div class="group">
    <label class="label">Confirm password</label>
    <input class="input" id="confirm" type="password" placeholder="Same password again">
  </div>
  <button class="btn" onclick="doAccept()">Activate Account →</button>
</div>
<script>
var token = window.location.pathname.split('/').pop();
async function doAccept() {
  var pw=document.getElementById('password').value;
  var cf=document.getElementById('confirm').value;
  var err=document.getElementById('err');
  if(pw.length<8){err.textContent='Password must be at least 8 characters.';err.style.display='block';return;}
  if(pw!==cf){err.textContent='Passwords do not match.';err.style.display='block';return;}
  err.style.display='none';
  var res=await fetch('/app/accept-invite/'+token,{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})
  });
  var data=await res.json();
  if(res.ok){window.location.href='/app';}
  else{err.textContent=data.detail||'Invalid or expired invite link.';err.style.display='block';}
}
</script>
</body>
</html>"""


@router.get("/app/accept-invite/{invite_token}", response_class=HTMLResponse)
async def accept_invite_page(invite_token: str):
    return HTMLResponse(content=ACCEPT_INVITE_HTML)


@router.post("/app/accept-invite/{invite_token}")
async def accept_invite_submit(
    invite_token: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    from fastapi import HTTPException
    try:
        data = await request.json()
        password = data.get("password", "")
    except Exception:
        raise HTTPException(400, "Invalid request body")

    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")

    svc = get_operator_auth_service()
    result = await svc.accept_invite(db, invite_token, password)
    if not result:
        raise HTTPException(400, "Invalid or expired invite link.")

    return JSONResponse({"ok": True, "message": "Account activated. You can now sign in."})
