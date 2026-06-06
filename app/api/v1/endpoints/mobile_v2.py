"""
Mobile Guest Concierge Interface - Multi-Operator Branded

Token-based mobile interface that pulls branding from the operator record:
- Logo, primary/secondary color, concierge name/emoji
- Falls back to Beach Habitats defaults if operator not found
- Voice and text input
- Quick action buttons
- Beach flag conditions (in-stay only)
- Session expiration handling
- Database persistence
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime, date, timezone
from typing import Optional
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_async_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Guest Mobile"])


# =============================================================================
# Request/Response Models
# =============================================================================

class ChatRequest(BaseModel):
    message: str
    channel: str = "mobile"


class ChatResponse(BaseModel):
    response: str
    session_token: str
    concierge_name: str
    timestamp: str
    should_request_feedback: bool = False


class FeedbackRequest(BaseModel):
    rating: int  # 1-5
    would_recommend: bool
    comments: Optional[str] = None


# =============================================================================
# Operator Branding Resolver
# =============================================================================

def _resolve_branding(operator_id: Optional[str]) -> dict:
    """
    Pull branding from the OperatorRegistry for a given operator_id.
    Falls back to Beach Habitats defaults if not found.
    """
    try:
        from app.models.operator import get_operator
        op = get_operator(operator_id)
        b = op.branding
        return {
            "company_name":      b.company_name,
            "logo_url":          b.logo_url,
            "primary":           b.primary_color,
            "secondary":         b.secondary_color,
            "grad_start":        b.header_gradient_start,
            "grad_end":          b.header_gradient_end,
            "concierge_name":    b.concierge_name,
            "concierge_emoji":   b.concierge_emoji,
            "support_phone":     b.support_phone or "(850) 733-7433",
            "bg":                "#f0f9ff",
        }
    except Exception:
        return {
            "company_name":    "Oyvoda",
            "logo_url":        "",
            "primary":         "#0ea5e9",
            "secondary":       "#0284c7",
            "grad_start":      "#0c4a6e",
            "grad_end":        "#0369a1",
            "concierge_name":  "Coral",
            "concierge_emoji": "🐚",
            "support_phone":   "",
            "bg":              "#f0f9ff",
        }


# =============================================================================
# HTML Template
# =============================================================================

def get_mobile_html(
    token: str,
    guest_name: str,
    property_name: str,
    branding: dict,
    is_in_stay: bool = False,
    beach_conditions: dict = None,
) -> str:
    """Generate operator-branded mobile guest interface."""

    p       = branding["primary"]
    s       = branding["secondary"]
    gs      = branding["grad_start"]
    ge      = branding["grad_end"]
    bg      = branding["bg"]
    logo    = branding["logo_url"]
    cname   = branding["concierge_name"]
    cemoji  = branding["concierge_emoji"]

    # Beach flag strip
    beach_flag_html = ""
    if is_in_stay and beach_conditions:
        flag = beach_conditions.get("flag", "yellow")
        flag_cfg = {
            "green":      {"color": "#22c55e", "emoji": "🟢", "label": "Safe Conditions",  "bg": "#dcfce7"},
            "yellow":     {"color": "#eab308", "emoji": "🟡", "label": "Moderate Surf",    "bg": "#fef9c3"},
            "red":        {"color": "#ef4444", "emoji": "🔴", "label": "High Hazard",       "bg": "#fee2e2"},
            "double_red": {"color": "#991b1b", "emoji": "🚩🚩","label": "Water Closed",    "bg": "#fecaca"},
        }
        cfg = flag_cfg.get(flag, flag_cfg["yellow"])
        beach_flag_html = f'''
        <div class="beach-flag" onclick="askQuestion('What are the current beach conditions?')"
             style="background:{cfg['bg']};border-left:4px solid {cfg['color']}">
            <span class="flag-emoji">{cfg['emoji']}</span>
            <div class="flag-info">
                <div class="flag-label" style="color:{cfg['color']}">{cfg['label']}</div>
                <div class="flag-hint">Tap for details</div>
            </div>
        </div>'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="{gs}">
<title>{branding["company_name"]} Concierge</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Poppins',-apple-system,sans-serif;background:linear-gradient(180deg,{bg} 0%,#e0f2fe 100%);min-height:100vh;min-height:100dvh;display:flex;flex-direction:column}}
.header{{background:linear-gradient(135deg,{gs} 0%,{ge} 100%);padding:20px;padding-top:calc(20px + env(safe-area-inset-top,0px))}}
.logo-row{{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}}
.logo{{height:38px;width:auto;filter:brightness(0) invert(1);object-fit:contain}}
.logo-fallback{{color:white;font-weight:700;font-size:17px}}
.concierge-badge{{background:rgba(255,255,255,.2);padding:5px 13px;border-radius:20px;color:white;font-size:13px;font-weight:500;white-space:nowrap}}
.welcome-text{{color:rgba(255,255,255,.85);font-size:13px;margin-bottom:3px}}
.property-name{{color:white;font-size:21px;font-weight:700;line-height:1.2}}
.beach-flag{{margin:14px 20px 0;padding:11px 15px;border-radius:12px;display:flex;align-items:center;gap:11px;cursor:pointer}}
.flag-emoji{{font-size:22px}}
.flag-info{{flex:1}}
.flag-label{{font-weight:600;font-size:14px}}
.flag-hint{{font-size:11px;color:#64748b}}
.messages{{flex:1;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:10px}}
.message{{max-width:85%;padding:13px 16px;border-radius:18px;font-size:14.5px;line-height:1.5;animation:slideUp .25s ease}}
@keyframes slideUp{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:translateY(0)}}}}
.message.assistant{{background:white;align-self:flex-start;border-bottom-left-radius:5px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.message.user{{background:linear-gradient(135deg,{p} 0%,{gs} 100%);color:white;align-self:flex-end;border-bottom-right-radius:5px}}
.typing{{display:flex;gap:5px;padding:14px 18px;background:white;border-radius:18px;align-self:flex-start;border-bottom-left-radius:5px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.typing span{{width:7px;height:7px;background:{p};border-radius:50%;animation:bounce 1.4s infinite}}
.typing span:nth-child(2){{animation-delay:.2s}}
.typing span:nth-child(3){{animation-delay:.4s}}
@keyframes bounce{{0%,60%,100%{{transform:translateY(0)}}30%{{transform:translateY(-7px)}}}}
.quick-actions{{padding:0 18px 10px;display:flex;gap:7px;overflow-x:auto;scrollbar-width:none}}
.quick-actions::-webkit-scrollbar{{display:none}}
.quick-btn{{flex-shrink:0;background:white;border:2px solid #e2e8f0;padding:9px 15px;border-radius:24px;font-size:13.5px;font-weight:500;color:#334155;cursor:pointer;font-family:inherit;transition:border-color .15s}}
.quick-btn:hover{{border-color:{p}}}
.input-area{{background:white;padding:14px 18px;padding-bottom:calc(14px + env(safe-area-inset-bottom,0px));border-top:1px solid #e2e8f0}}
.input-row{{display:flex;gap:10px;align-items:center}}
.voice-btn{{width:50px;height:50px;border-radius:50%;border:none;background:{bg};color:{gs};font-size:22px;cursor:pointer;flex-shrink:0;display:flex;align-items:center;justify-content:center}}
.voice-btn.recording{{background:#ef4444;color:white;animation:pulseRec 1.5s infinite}}
@keyframes pulseRec{{0%,100%{{box-shadow:0 0 0 0 rgba(239,68,68,.4)}}50%{{box-shadow:0 0 0 12px rgba(239,68,68,0)}}}}
.text-input{{flex:1;padding:13px 18px;border:2px solid #e2e8f0;border-radius:25px;font-size:16px;font-family:inherit;outline:none;background:{bg}}}
.text-input:focus{{border-color:{p};background:white}}
.send-btn{{width:50px;height:50px;border-radius:50%;border:none;background:linear-gradient(135deg,{p} 0%,{gs} 100%);color:white;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0}}
.send-btn svg{{width:20px;height:20px}}
</style>
</head>
<body>
<div class="header">
  <div class="logo-row">
    <img src="{logo}" alt="{branding['company_name']}" class="logo"
         onerror="this.outerHTML='<span class=\\'logo-fallback\\'>🏖️ {branding['company_name']}</span>'">
    <div class="concierge-badge">{cemoji} {cname}</div>
  </div>
  <div class="welcome-text">Hi {guest_name}! 👋</div>
  <div class="property-name">{property_name}</div>
</div>

{beach_flag_html}

<div class="messages" id="messages">
  <div class="message assistant">
    Hey {guest_name}! {cemoji} I'm {cname}, your personal concierge for <strong>{property_name}</strong>.<br><br>
    Ask me anything — WiFi, door code, restaurants, beach conditions, or whatever you need!
  </div>
</div>

<div class="quick-actions">
  <button class="quick-btn" onclick="askQuestion('What is the WiFi password?')">📶 WiFi</button>
  <button class="quick-btn" onclick="askQuestion('What is the door code?')">🔑 Door Code</button>
  <button class="quick-btn" onclick="askQuestion('Restaurant recommendations')">🍽️ Restaurants</button>
  <button class="quick-btn" onclick="askQuestion('Beach chair rentals')">🏖️ Beach Chairs</button>
  <button class="quick-btn" onclick="askQuestion('What time is checkout?')">⏰ Checkout</button>
</div>

<div class="input-area">
  <div class="input-row">
    <button class="voice-btn" id="voiceBtn" onclick="toggleVoice()">🎤</button>
    <input type="text" class="text-input" id="messageInput"
           placeholder="Ask me anything…"
           onkeypress="if(event.key==='Enter') sendMessage()">
    <button class="send-btn" onclick="sendMessage()">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <path d="M22 2L11 13M22 2L15 22L11 13L2 9L22 2Z"/>
      </svg>
    </button>
  </div>
</div>

<script>
const TOKEN = "{token}";
const msgs  = document.getElementById('messages');
const input = document.getElementById('messageInput');
const vBtn  = document.getElementById('voiceBtn');
let isRec = false, rec = null;

if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {{
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  rec = new SR();
  rec.continuous = false; rec.interimResults = true; rec.lang = 'en-US';
  rec.onresult = e => {{
    const t = Array.from(e.results).map(r=>r[0].transcript).join('');
    input.value = t;
    if (e.results[0].isFinal) {{ stopRec(); sendMessage(); }}
  }};
  rec.onerror = stopRec; rec.onend = stopRec;
}}

function toggleVoice() {{ isRec ? stopRec() : startRec(); }}
function startRec() {{
  if (!rec) return;
  isRec = true; vBtn.classList.add('recording'); vBtn.textContent = '⏹';
  input.placeholder = 'Listening…';
  try {{ rec.start(); }} catch(e) {{ stopRec(); }}
}}
function stopRec() {{
  isRec = false; vBtn.classList.remove('recording'); vBtn.textContent = '🎤';
  input.placeholder = 'Ask me anything…';
  try {{ rec?.stop(); }} catch(e) {{}}
}}
function askQuestion(q) {{ input.value = q; sendMessage(); }}
function addMsg(text, role) {{
  const d = document.createElement('div');
  d.className = 'message ' + role;
  d.innerHTML = text.replace(/\\*\\*(.+?)\\*\\*/g,'<strong>$1</strong>').replace(/\\n/g,'<br>');
  msgs.appendChild(d);
  msgs.scrollTop = msgs.scrollHeight;
}}
async function sendMessage() {{
  const text = input.value.trim(); if (!text) return;
  addMsg(text, 'user'); input.value = '';
  const typing = document.createElement('div');
  typing.className = 'typing';
  typing.innerHTML = '<span></span><span></span><span></span>';
  msgs.appendChild(typing); msgs.scrollTop = msgs.scrollHeight;
  try {{
    const res = await fetch(`/api/v1/mobile/${{TOKEN}}/chat`, {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{message:text, channel:'mobile'}})
    }});
    const data = await res.json();
    typing.remove(); addMsg(data.response, 'assistant');
  }} catch(e) {{
    typing.remove(); addMsg('Sorry, having trouble connecting. Please try again!', 'assistant');
  }}
}}
msgs.scrollTop = msgs.scrollHeight;
</script>
</body>
</html>'''


def get_expired_html(branding: dict = None) -> str:
    b = branding or {
        "company_name": "Oyvoda",
        "primary": "#0ea5e9",
        "grad_start": "#0c4a6e",
        "bg": "#f0f9ff",
    }
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Session Ended | {b["company_name"]}</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Poppins",sans-serif;background:linear-gradient(135deg,{b["bg"]} 0%,#e0f2fe 100%);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
.card{{background:white;border-radius:24px;padding:48px 32px;text-align:center;max-width:400px;box-shadow:0 20px 60px rgba(0,0,0,.1)}}
.emoji{{font-size:64px;margin-bottom:20px}}
h1{{color:{b["grad_start"]};font-size:24px;margin-bottom:10px}}
p{{color:#64748b;font-size:15px;line-height:1.6}}
</style>
</head>
<body>
<div class="card">
  <div class="emoji">🐚</div>
  <h1>Thanks for Staying!</h1>
  <p>Your concierge session has ended. We hope you had an amazing stay!</p>
</div>
</body>
</html>'''


# =============================================================================
# Shared VoicePod Runner
# =============================================================================

async def _run_voice_pod(message, db_session, db_row, session_tenant_id, token):
    from app.services.knowledge.voice_pod import VoicePodResponse
    from app.services.messaging_brain.session_channel_adapter import (
        run_session_channel_message,
    )

    try:
        result = await run_session_channel_message(
            message_text=message,
            db_session=db_session,
            db_row=db_row,
            session_tenant_id=session_tenant_id,
            token=token,
            channel="web_chat",
            source_provider="mobile_v2",
        )
        return VoicePodResponse(
            text=result.response_text,
            quick_answer_used=result.quick_answer_used,
            total_time_ms=0,
            estimated_cost_usd=0.0,
        )
    except Exception as exc:
        logger.error("Brain session-channel adapter unhandled error: %s", exc, exc_info=True)
        support = (db_row.property_context or {}).get("support_phone") or "your host"
        name = db_row.guest_name.split()[0] if db_row.guest_name else "Guest"
        return VoicePodResponse(
            text=(f"I'm so sorry, {name} — I'm having a technical issue right now. "
                  f"For immediate help please call **{support}**."),
            quick_answer_used=False, total_time_ms=0, estimated_cost_usd=0,
        )


# =============================================================================
# API Endpoints
# =============================================================================

@router.get("/c/{token}", response_class=HTMLResponse)
async def guest_concierge_page(token: str, db: AsyncSession = Depends(get_async_session)):
    from app.services.concierge.db_session_service import get_db_session_service, DEFAULT_TENANT_ID

    _bootstrap = get_db_session_service(DEFAULT_TENANT_ID)
    session = await _bootstrap.get_session_by_token(db, token, tenant_agnostic=True)

    if not session or session.status == "expired":
        branding = _resolve_branding(getattr(session, "operator_id", None) if session else None)
        return HTMLResponse(get_expired_html(branding))

    real_tenant_id = getattr(session, "tenant_id", None) or DEFAULT_TENANT_ID
    service = get_db_session_service(real_tenant_id)
    await service.update_session_phase(db, session.session_id)

    today = date.today()
    is_in_stay = session.check_in <= today <= session.check_out

    beach_conditions = None
    if is_in_stay:
        try:
            from app.services.knowledge.beach_flag_scraper import get_current_beach_flag
            beach_conditions = await get_current_beach_flag()
        except Exception as e:
            logger.warning(f"Beach conditions error: {e}")

    branding = _resolve_branding(getattr(session, "operator_id", None))
    first_name = session.guest_name.split()[0] if session.guest_name else "Guest"

    return HTMLResponse(get_mobile_html(
        token=token,
        guest_name=first_name,
        property_name=session.property_name,
        branding=branding,
        is_in_stay=is_in_stay,
        beach_conditions=beach_conditions,
    ))


@router.post("/api/v1/mobile/{token}/chat", response_model=ChatResponse)
async def chat_with_concierge(token: str, request: ChatRequest, db: AsyncSession = Depends(get_async_session)):
    from app.services.concierge.db_session_service import get_db_session_service, DEFAULT_TENANT_ID
    import time

    start_time = time.time()
    _bootstrap = get_db_session_service(DEFAULT_TENANT_ID)
    session = await _bootstrap.get_session_by_token(db, token, tenant_agnostic=True)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status == "expired":
        raise HTTPException(status_code=410, detail="Session expired")

    session_tenant_id = getattr(session, "tenant_id", None) or DEFAULT_TENANT_ID
    scoped_service = get_db_session_service(session_tenant_id)

    await scoped_service.add_message(db=db, session_id=session.session_id,
                                     direction="inbound", content=request.message)

    pod_response = await _run_voice_pod(
        message=request.message, db_session=db, db_row=session,
        session_tenant_id=session_tenant_id, token=token,
    )
    response_text = pod_response.text
    was_quick = pod_response.quick_answer_used
    response_time = int((time.time() - start_time) * 1000)

    await scoped_service.add_message(
        db=db, session_id=session.session_id, direction="outbound",
        content=response_text, was_quick_answer=was_quick, response_time_ms=response_time,
    )

    branding = _resolve_branding(getattr(session, "operator_id", None))
    return ChatResponse(
        response=response_text,
        session_token=token,
        concierge_name=branding["concierge_name"],
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/api/v1/mobile/{token}/feedback")
async def submit_feedback(token: str, request: FeedbackRequest, db: AsyncSession = Depends(get_async_session)):
    from app.services.concierge.db_session_service import get_db_session_service, DEFAULT_TENANT_ID

    _bootstrap = get_db_session_service(DEFAULT_TENANT_ID)
    session = await _bootstrap.get_session_by_token(db, token, tenant_agnostic=True)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session_tenant_id = getattr(session, "tenant_id", None) or DEFAULT_TENANT_ID
    scoped_service = get_db_session_service(session_tenant_id)
    await scoped_service.record_feedback(db=db, session_id=session.session_id,
                                         rating=request.rating, text=request.comments)
    return {"status": "ok", "message": "Thank you for your feedback!"}
