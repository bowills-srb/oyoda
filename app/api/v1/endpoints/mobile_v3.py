"""
Beach Habitats — Guest Mobile Concierge Interface v3

Professional mobile-first chat UI featuring:
- Operator logo in header (with upload prompt if not set)
- Palm tree (🌴) voice activation button in input bar
- Clean iMessage-style chat bubbles
- Quick action pills (WiFi, Door Code, Check-Out, Restaurants, Beach, Pool)
- Operator branding: logo, primary color, concierge name/emoji
- Real-time session persistence
- Voice input via Web Speech API
- Session expiry handling
- No app required — token-gated PWA

Design: Ultra-clean mobile UI. Branded header. No unnecessary chrome.
Served at GET /c/{token}
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_async_session

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Guest Mobile v3"])


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
    rating: int
    would_recommend: bool
    comments: Optional[str] = None


def _resolve_branding(operator_id: Optional[str]) -> dict:
    try:
        from app.models.operator import get_operator
        op = get_operator(operator_id)
        b = op.branding
        return {
            "company_name": b.company_name,
            "logo_url": b.logo_url or "",
            "logo_dark_url": b.logo_dark_url or b.logo_url or "",
            "primary": b.primary_color or "#0b5a87",
            "secondary": b.secondary_color or "#1279b5",
            "grad_start": b.header_gradient_start or "#0b5a87",
            "grad_end": b.header_gradient_end or "#1279b5",
            "concierge_name": b.concierge_name or "Coral",
            "concierge_emoji": b.concierge_emoji or "🐚",
            "support_phone": b.support_phone or "(850) 733-7433",
            "tagline": b.tagline or "Your personal vacation concierge",
        }
    except Exception:
        return {
            "company_name": "Beach Habitats",
            "logo_url": "https://www.beachhabitats30a.com/sites/nbhb/files/styles/ngt_logo/public/nbhb/ngt_logo/Transparent%20%28edited%29.png",
            "logo_dark_url": "",
            "primary": "#0b5a87",
            "secondary": "#1279b5",
            "grad_start": "#0b5a87",
            "grad_end": "#1279b5",
            "concierge_name": "Coral",
            "concierge_emoji": "🐚",
            "support_phone": "(850) 733-7433",
            "tagline": "Your 30A vacation concierge",
        }


def _build_mobile_html(
    token: str,
    branding: dict,
    property_name: str = "Your Property",
    property_address: str = "",
    is_in_stay: bool = True,
    show_beach_conditions: bool = True,
) -> str:
    logo_url = branding["logo_url"]
    logo_html = ""
    if logo_url:
        logo_html = f'<img src="{logo_url}" alt="{branding["company_name"]}" class="header-logo" onerror="this.style.display=\'none\'">'
    else:
        logo_html = f'<div class="header-logo-text">{branding["company_name"]}</div>'

    quick_actions = [
        ("📶", "WiFi Password", "What's the WiFi network and password?"),
        ("🔑", "Door Code", "What's the door code?"),
        ("🕙", "Check-Out", "What time is check-out?"),
        ("🍽️", "Restaurants", "Can you recommend nearby restaurants?"),
    ]
    if show_beach_conditions and is_in_stay:
        quick_actions.append(("🏖️", "Beach Flags", "What are the current beach flag conditions?"))
        quick_actions.append(("🅿️", "Parking", "Where do I park?"))
    else:
        quick_actions.append(("🅿️", "Parking", "Where do I park?"))
        quick_actions.append(("🏊", "Pool", "What are the pool hours?"))

    qa_html = "".join(
        f'<button class="qa-pill" onclick="sendQuick(`{q[2]}`)">{q[0]} {q[1]}</button>'
        for q in quick_actions
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>{branding["company_name"]} · {branding["concierge_name"]}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --primary:{branding["primary"]};
  --grad-start:{branding["grad_start"]};
  --grad-end:{branding["grad_end"]};
  --bg:#f0f4f8;
  --surface:#fff;
  --border:#e2e8f0;
  --text:#1a202c;
  --text-muted:#718096;
  --text-faint:#a0aec0;
  --bot-bubble:#fff;
  --user-bubble:var(--primary);
  --input-bg:#f7fafc;
  --font:'Inter',-apple-system,'Segoe UI',sans-serif;
  --safe-bottom:env(safe-area-inset-bottom,0px);
  --safe-top:env(safe-area-inset-top,0px);
}}
html{{height:100%;-webkit-text-size-adjust:100%}}
body{{
  font-family:var(--font);color:var(--text);background:var(--bg);
  height:100%;display:flex;flex-direction:column;overflow:hidden;
  -webkit-font-smoothing:antialiased
}}
.app{{
  display:flex;flex-direction:column;height:100vh;height:calc(var(--vh,1vh)*100);
  max-width:480px;margin:0 auto;width:100%;background:var(--surface);
  position:relative;box-shadow:0 0 40px rgba(0,0,0,.08)
}}

/* HEADER */
.header{{
  background:linear-gradient(135deg,var(--grad-start),var(--grad-end));
  padding:calc(var(--safe-top) + 12px) 16px 14px;
  display:flex;align-items:center;gap:12px;
  position:relative;z-index:10;flex-shrink:0;
  min-height:72px
}}
.header-logo-wrap{{
  height:36px;display:flex;align-items:center;
  background:rgba(255,255,255,.15);border-radius:8px;
  padding:4px 10px;backdrop-filter:blur(4px);
  flex-shrink:0;max-width:140px
}}
.header-logo{{
  height:28px;width:auto;max-width:120px;object-fit:contain;
  filter:brightness(10) saturate(0);/* shows logo on dark bg */
  opacity:.92
}}
.header-logo-text{{
  color:#fff;font-weight:700;font-size:.85rem;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis
}}
.header-center{{flex:1;text-align:center}}
.header-concierge-name{{color:#fff;font-size:.95rem;font-weight:600;line-height:1.2}}
.header-prop-name{{color:rgba(255,255,255,.72);font-size:.75rem;margin-top:1px}}
.header-right{{display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex-shrink:0}}
.status-badge{{
  display:flex;align-items:center;gap:5px;
  background:rgba(255,255,255,.14);border-radius:100px;
  padding:3px 10px;backdrop-filter:blur(4px)
}}
.status-dot{{width:6px;height:6px;border-radius:50%;background:#4ade80;flex-shrink:0;animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1;box-shadow:0 0 0 0 rgba(74,222,128,.5)}}60%{{box-shadow:0 0 0 4px rgba(74,222,128,0)}}}}
.status-text{{color:rgba(255,255,255,.85);font-size:.7rem;font-weight:500}}
.header-concierge-emoji{{font-size:1.5rem;line-height:1}}

/* MESSAGES AREA */
.msgs-wrap{{
  flex:1;overflow-y:auto;overflow-x:hidden;
  padding:16px 14px 8px;
  -webkit-overflow-scrolling:touch;
  scroll-behavior:smooth;
  background:var(--bg)
}}
.msgs-wrap::-webkit-scrollbar{{display:none}}

/* DATE DIVIDER */
.date-divider{{text-align:center;margin:12px 0;font-size:.72rem;color:var(--text-faint);font-weight:500;position:relative}}
.date-divider::before{{content:'';position:absolute;top:50%;left:0;right:0;height:1px;background:var(--border);z-index:0}}
.date-divider span{{background:var(--bg);padding:0 10px;position:relative;z-index:1}}

/* CHAT BUBBLES */
.msg-group{{display:flex;flex-direction:column;gap:3px;margin-bottom:12px}}
.msg-group.user{{align-items:flex-end}}
.msg-group.bot{{align-items:flex-start}}
.msg-row{{display:flex;align-items:flex-end;gap:7px}}
.msg-group.user .msg-row{{flex-direction:row-reverse}}
.avatar{{
  width:28px;height:28px;border-radius:50%;
  background:linear-gradient(135deg,var(--grad-start),var(--grad-end));
  display:flex;align-items:center;justify-content:center;
  font-size:13px;flex-shrink:0;margin-bottom:2px;
  box-shadow:0 1px 4px rgba(0,0,0,.12)
}}
.bubble{{
  max-width:78%;padding:9px 13px;border-radius:18px;
  line-height:1.5;font-size:.9rem;word-break:break-word;
  position:relative
}}
.msg-group.bot .bubble{{
  background:var(--bot-bubble);color:var(--text);
  border:1px solid var(--border);
  border-bottom-left-radius:4px;
  box-shadow:0 1px 3px rgba(0,0,0,.06)
}}
.msg-group.user .bubble{{
  background:var(--user-bubble);color:#fff;
  border-bottom-right-radius:4px;
  box-shadow:0 1px 4px rgba(0,0,0,.15)
}}
.bubble strong{{font-weight:600}}
.bubble a{{color:inherit;text-decoration:underline;opacity:.85}}
.msg-time{{font-size:.67rem;color:var(--text-faint);padding:0 4px;margin-top:1px}}

/* TYPING */
.typing-bubble{{
  background:var(--bot-bubble);border:1px solid var(--border);
  border-radius:18px;border-bottom-left-radius:4px;
  padding:11px 14px;display:inline-flex;gap:4px;align-items:center;
  box-shadow:0 1px 3px rgba(0,0,0,.06)
}}
.tp{{width:6px;height:6px;border-radius:50%;background:var(--text-faint);animation:tp .9s infinite}}
.tp:nth-child(2){{animation-delay:.15s}}.tp:nth-child(3){{animation-delay:.3s}}
@keyframes tp{{0%,80%,100%{{transform:translateY(0)}}40%{{transform:translateY(-5px)}}}}

/* QUICK ACTIONS */
.quick-wrap{{padding:8px 14px 6px;background:var(--surface);border-top:1px solid var(--border);overflow-x:auto;-webkit-overflow-scrolling:touch;flex-shrink:0}}
.quick-wrap::-webkit-scrollbar{{display:none}}
.quick-row{{display:flex;gap:7px;padding-bottom:2px;min-width:max-content}}
.qa-pill{{
  background:var(--surface);border:1px solid var(--border);
  color:var(--text);border-radius:100px;padding:7px 14px;
  font-size:.8rem;font-weight:500;font-family:var(--font);
  cursor:pointer;white-space:nowrap;transition:all .15s;flex-shrink:0
}}
.qa-pill:hover,.qa-pill:active{{
  background:var(--primary);border-color:var(--primary);color:#fff
}}

/* INPUT BAR */
.input-bar{{
  padding:10px 14px calc(10px + var(--safe-bottom));
  background:var(--surface);border-top:1px solid var(--border);
  display:flex;align-items:center;gap:8px;flex-shrink:0
}}
.input-field{{
  flex:1;background:var(--input-bg);border:1.5px solid var(--border);
  border-radius:22px;padding:10px 16px;font-size:.9rem;color:var(--text);
  font-family:var(--font);outline:none;transition:border-color .15s;
  resize:none;overflow-y:hidden;line-height:1.4;max-height:120px;
  -webkit-appearance:none
}}
.input-field:focus{{border-color:var(--primary)}}
.input-field::placeholder{{color:var(--text-faint)}}

/* PALM TREE VOICE BUTTON */
.voice-btn{{
  width:42px;height:42px;border-radius:50%;
  background:linear-gradient(135deg,var(--grad-start),var(--grad-end));
  border:none;cursor:pointer;
  display:flex;align-items:center;justify-content:center;
  font-size:19px;flex-shrink:0;transition:all .18s;
  box-shadow:0 2px 8px rgba(0,0,0,.15);
  -webkit-tap-highlight-color:transparent
}}
.voice-btn:hover,.voice-btn:active{{transform:scale(1.08);box-shadow:0 4px 14px rgba(0,0,0,.2)}}
.voice-btn.recording{{
  animation:voice-pulse 1.2s infinite;
  background:linear-gradient(135deg,#dc2626,#ef4444)
}}
@keyframes voice-pulse{{
  0%,100%{{box-shadow:0 0 0 0 rgba(220,38,38,.4)}}
  50%{{box-shadow:0 0 0 8px rgba(220,38,38,0)}}
}}
.send-btn{{
  width:42px;height:42px;border-radius:50%;
  background:var(--primary);border:none;cursor:pointer;
  display:flex;align-items:center;justify-content:center;
  color:#fff;flex-shrink:0;transition:all .15s;
  box-shadow:0 2px 6px rgba(0,0,0,.14);
  -webkit-tap-highlight-color:transparent
}}
.send-btn:hover,.send-btn:active{{background:#0d6fa0;transform:scale(1.05)}}
.send-btn:disabled{{opacity:.4;cursor:not-allowed;transform:none}}

/* FEEDBACK */
.feedback-card{{
  background:var(--surface);border:1px solid var(--border);
  border-radius:16px;margin:8px 0;padding:16px;
}}
.feedback-title{{font-weight:600;font-size:.9rem;margin-bottom:12px;color:var(--text)}}
.star-row{{display:flex;gap:8px;margin-bottom:14px}}
.star-btn{{
  font-size:1.5rem;background:none;border:none;cursor:pointer;
  padding:4px;transition:transform .1s;-webkit-tap-highlight-color:transparent
}}
.star-btn:active{{transform:scale(1.25)}}
.fb-submit{{
  width:100%;padding:11px;background:var(--primary);color:#fff;
  border:none;border-radius:10px;font-size:.9rem;font-weight:600;
  font-family:var(--font);cursor:pointer
}}

/* EXPIRED/ERROR STATES */
.state-screen{{
  flex:1;display:flex;flex-direction:column;align-items:center;
  justify-content:center;padding:40px 28px;text-align:center;gap:16px
}}
.state-emoji{{font-size:3rem}}
.state-title{{font-size:1.1rem;font-weight:700;color:var(--text)}}
.state-sub{{font-size:.9rem;color:var(--text-muted);line-height:1.6}}
.state-phone{{
  color:var(--primary);font-weight:600;font-size:1rem;
  text-decoration:none;display:flex;align-items:center;gap:7px;
  margin-top:4px
}}
</style>
</head>
<body>
<div class="app" id="app">
  <!-- HEADER -->
  <div class="header">
    <div class="header-logo-wrap">
      {logo_html}
    </div>
    <div class="header-center">
      <div class="header-concierge-name">{branding["concierge_name"]}</div>
      <div class="header-prop-name">{property_name}</div>
    </div>
    <div class="header-right">
      <div class="status-badge">
        <div class="status-dot"></div>
        <span class="status-text">Online</span>
      </div>
      <div class="header-concierge-emoji">{branding["concierge_emoji"]}</div>
    </div>
  </div>

  <!-- MESSAGES -->
  <div class="msgs-wrap" id="msgs">
    <div class="date-divider"><span>Today</span></div>
    <div class="msg-group bot">
      <div class="msg-row">
        <div class="avatar">{branding["concierge_emoji"]}</div>
        <div>
          <div class="bubble">Welcome to {property_name}! 🌊 I'm {branding["concierge_name"]}, your personal concierge. Ask me anything about your stay — WiFi, door codes, check-out, local recommendations, or anything else!</div>
          <div class="msg-time">Now</div>
        </div>
      </div>
    </div>
  </div>

  <!-- QUICK ACTIONS -->
  <div class="quick-wrap">
    <div class="quick-row">
      {qa_html}
    </div>
  </div>

  <!-- INPUT BAR -->
  <div class="input-bar">
    <textarea
      class="input-field"
      id="inputField"
      placeholder="Ask {branding["concierge_name"]} anything..."
      rows="1"
      onkeydown="handleKey(event)"
      oninput="autoResize(this)"
    ></textarea>
    <button class="voice-btn" id="voiceBtn" onclick="toggleVoice()" title="Voice input">🌴</button>
    <button class="send-btn" id="sendBtn" onclick="sendMessage()" disabled>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <line x1="22" y1="2" x2="11" y2="13"/>
        <polygon points="22 2 15 22 11 13 2 9 22 2"/>
      </svg>
    </button>
  </div>
</div>

<script>
const TOKEN = '{token}';
const CONCIERGE = '{branding["concierge_name"]}';
const EMOJI = '{branding["concierge_emoji"]}';
const PRIMARY = '{branding["primary"]}';

// Fix mobile viewport height
function fixVh() {{
  const vh = window.innerHeight * 0.01;
  document.documentElement.style.setProperty('--vh', `${{vh}}px`);
}}
fixVh();
window.addEventListener('resize', fixVh);

// Auto-resize textarea
function autoResize(el) {{
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  document.getElementById('sendBtn').disabled = !el.value.trim();
}}

// Input key handler
function handleKey(e) {{
  if (e.key === 'Enter' && !e.shiftKey) {{ e.preventDefault(); sendMessage(); }}
}}

// Add message to DOM
function addMsg(text, isUser) {{
  const wrap = document.getElementById('msgs');
  const grp = document.createElement('div');
  grp.className = 'msg-group ' + (isUser ? 'user' : 'bot');

  const row = document.createElement('div');
  row.className = 'msg-row';

  if (!isUser) {{
    const av = document.createElement('div');
    av.className = 'avatar';
    av.textContent = EMOJI;
    row.appendChild(av);
  }}

  const inner = document.createElement('div');
  const bub = document.createElement('div');
  bub.className = 'bubble';
  bub.innerHTML = text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
  inner.appendChild(bub);

  const t = document.createElement('div');
  t.className = 'msg-time';
  t.textContent = new Date().toLocaleTimeString([], {{hour:'2-digit',minute:'2-digit'}});
  inner.appendChild(t);

  row.appendChild(inner);
  grp.appendChild(row);
  wrap.appendChild(grp);
  wrap.scrollTop = wrap.scrollHeight;
  return grp;
}}

// Show/remove typing indicator
let typingEl = null;
function showTyping() {{
  const wrap = document.getElementById('msgs');
  typingEl = document.createElement('div');
  typingEl.className = 'msg-group bot';
  typingEl.innerHTML = `<div class="msg-row"><div class="avatar">${{EMOJI}}</div><div class="typing-bubble"><div class="tp"></div><div class="tp"></div><div class="tp"></div></div></div>`;
  wrap.appendChild(typingEl);
  wrap.scrollTop = wrap.scrollHeight;
}}
function hideTyping() {{ if (typingEl) {{ typingEl.remove(); typingEl = null; }} }}

// Send message to API
async function sendMessage() {{
  const inp = document.getElementById('inputField');
  const text = inp.value.trim();
  if (!text) return;

  addMsg(text, true);
  inp.value = '';
  inp.style.height = 'auto';
  document.getElementById('sendBtn').disabled = true;
  showTyping();

  try {{
    const res = await fetch(`/c/${{TOKEN}}/chat`, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ message: text, channel: 'mobile' }})
    }});

    hideTyping();

    if (res.status === 410) {{
      addMsg('Your session has expired. For assistance, please contact us at {branding["support_phone"]}. Thank you for staying with us! 🌴', false);
      return;
    }}

    if (!res.ok) throw new Error('Request failed');

    const data = await res.json();
    addMsg(data.response, false);

    if (data.should_request_feedback) {{
      setTimeout(() => showFeedback(), 1500);
    }}
  }} catch (e) {{
    hideTyping();
    addMsg("Sorry, I hit a snag. Please try again or call us at {branding["support_phone"]}.", false);
  }}
}}

// Quick action
function sendQuick(text) {{
  document.getElementById('inputField').value = text;
  sendMessage();
}}

// Feedback card
function showFeedback() {{
  const wrap = document.getElementById('msgs');
  const card = document.createElement('div');
  card.className = 'feedback-card';
  card.innerHTML = `
    <div class="feedback-title">How's your stay going? Rate {branding["concierge_name"]}</div>
    <div class="star-row" id="stars">
      ${{[1,2,3,4,5].map(i=>`<button class="star-btn" onclick="setRating(${{i}})" data-n="${{i}}">☆</button>`).join('')}}
    </div>
    <button class="fb-submit" onclick="submitFeedback()">Submit Rating</button>
  `;
  wrap.appendChild(card);
  wrap.scrollTop = wrap.scrollHeight;
}}

let rating = 0;
function setRating(n) {{
  rating = n;
  document.querySelectorAll('.star-btn').forEach((b,i) => {{
    b.textContent = i < n ? '★' : '☆';
  }});
}}
async function submitFeedback() {{
  if (!rating) return;
  try {{
    await fetch(`/c/${{TOKEN}}/feedback`, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ rating, would_recommend: rating >= 4 }})
    }});
  }} catch(e) {{}}
  const cards = document.querySelectorAll('.feedback-card');
  cards.forEach(c => c.remove());
  addMsg(`Thanks for the ${{rating}}-star rating! Enjoy the rest of your stay 🌊`, false);
}}

// Voice input via palm tree 🌴
let recognition = null;
let isRecording = false;

function toggleVoice() {{
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {{
    addMsg("Voice input isn't supported on this browser. Chrome or Safari on iOS works best!", false);
    return;
  }}

  if (isRecording) {{
    recognition && recognition.stop();
    return;
  }}

  recognition = new SR();
  recognition.lang = 'en-US';
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onstart = () => {{
    isRecording = true;
    document.getElementById('voiceBtn').classList.add('recording');
    document.getElementById('inputField').placeholder = '🌴 Listening...';
  }};

  recognition.onresult = (e) => {{
    const transcript = e.results[0][0].transcript;
    document.getElementById('inputField').value = transcript;
    autoResize(document.getElementById('inputField'));
    sendMessage();
  }};

  recognition.onerror = (e) => {{
    console.warn('Voice error:', e.error);
    if (e.error !== 'aborted') {{
      addMsg("Couldn't catch that — try again or just type! 🐚", false);
    }}
  }};

  recognition.onend = () => {{
    isRecording = false;
    document.getElementById('voiceBtn').classList.remove('recording');
    document.getElementById('inputField').placeholder = 'Ask {branding["concierge_name"]} anything...';
    recognition = null;
  }};

  recognition.start();
}}
</script>
</body>
</html>"""


@router.get("/c/{{token}}", response_class=HTMLResponse)
async def guest_mobile_v3(
    token: str,
    db: AsyncSession = Depends(get_async_session)
):
    """
    Guest mobile concierge interface v3.
    Resolves operator branding from token → session → operator record.
    """
    try:
        from app.services.concierge.db_session_service import DatabaseSessionService
        svc = DatabaseSessionService(db=db)
        session = await svc.get_session(token)

        if not session:
            branding = _resolve_branding(None)
            html = _build_mobile_html(
                token=token,
                branding=branding,
                property_name="Your Stay",
                is_in_stay=False
            )
            return HTMLResponse(content=html)

        operator_id = getattr(session, 'operator_id', None)
        property_name = getattr(session, 'property_name', 'Your Property') or 'Your Property'
        branding = _resolve_branding(operator_id)

        html = _build_mobile_html(
            token=token,
            branding=branding,
            property_name=property_name,
        )
        return HTMLResponse(content=html)

    except Exception as e:
        logger.error(f"Guest mobile v3 error for token {token}: {{e}}")
        branding = _resolve_branding(None)
        html = _build_mobile_html(
            token=token,
            branding=branding,
            property_name="Your Property",
        )
        return HTMLResponse(content=html)


@router.post("/c/{{token}}/chat", response_model=ChatResponse)
async def guest_chat_v3(
    token: str,
    request: ChatRequest,
    db: AsyncSession = Depends(get_async_session)
):
    """Chat endpoint — delegates to the Brain session-channel adapter."""
    try:
        from app.services.concierge.db_session_service import (
            DEFAULT_TENANT_ID,
            get_db_session_service,
        )
        from app.services.messaging_brain.session_channel_adapter import (
            run_session_channel_message,
        )

        svc = get_db_session_service(DEFAULT_TENANT_ID)
        session = await svc.get_session_by_token(db, token, tenant_agnostic=True)
        if not session:
            raise HTTPException(status_code=410, detail="Session expired")

        tenant_id = getattr(session, "tenant_id", None) or DEFAULT_TENANT_ID
        result = await run_session_channel_message(
            message_text=request.message,
            db_session=db,
            db_row=session,
            session_tenant_id=tenant_id,
            token=token,
            channel="web_chat",
            source_provider="mobile_v3",
        )

        operator_id = getattr(session, 'operator_id', None)
        branding = _resolve_branding(operator_id)

        return ChatResponse(
            response=result.response_text or "Let me check on that for you!",
            session_token=token,
            concierge_name=branding["concierge_name"],
            timestamp=datetime.utcnow().isoformat(),
            should_request_feedback=result.should_request_feedback,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat v3 error: {{e}}")
        raise HTTPException(status_code=500, detail="Chat error")


@router.post("/c/{{token}}/feedback")
async def guest_feedback_v3(
    token: str,
    request: FeedbackRequest,
    db: AsyncSession = Depends(get_async_session)
):
    try:
        from app.services.concierge.db_session_service import DatabaseSessionService
        svc = DatabaseSessionService(db=db)
        await svc.record_feedback(
            session_token=token,
            rating=request.rating,
            would_recommend=request.would_recommend,
            comments=request.comments,
        )
        return {{"status": "ok"}}
    except Exception as e:
        logger.warning(f"Feedback v3 error: {{e}}")
        return {{"status": "ok"}}
