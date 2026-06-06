"""
Mobile Guest Concierge Interface

Token-based mobile interface with:
- Operator branding (logo, colors)
- Voice and text input
- Beach conditions (in-stay only)
- Feedback collection at checkout
- Session expiration handling
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import os
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Guest Mobile"])


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


class EscalateRequest(BaseModel):
    reason: str
    conversation_count: int = 0


def get_expired_session_html() -> str:
    """HTML for expired session"""
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Session Ended</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .card {
            background: white;
            border-radius: 20px;
            padding: 40px 30px;
            text-align: center;
            max-width: 400px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }
        .emoji { font-size: 64px; margin-bottom: 20px; }
        h1 { color: #0c4a6e; font-size: 24px; margin-bottom: 12px; }
        p { color: #64748b; font-size: 16px; line-height: 1.6; margin-bottom: 20px; }
        .cta {
            display: inline-block;
            background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
            color: white;
            padding: 14px 28px;
            border-radius: 30px;
            text-decoration: none;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="emoji">🐚</div>
        <h1>Thanks for Staying!</h1>
        <p>Your concierge session has ended. We hope you had an amazing beach getaway!</p>
        <a href="https://beachhabitats.com" class="cta">Book Your Next Trip</a>
    </div>
</body>
</html>'''


def get_feedback_html(session: dict) -> str:
    """HTML for feedback collection"""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>How Was Your Stay?</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 500px; margin: 0 auto; }}
        .header {{
            text-align: center;
            padding: 30px 0;
        }}
        .logo {{ font-size: 24px; font-weight: 700; color: #0c4a6e; }}
        .card {{
            background: white;
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }}
        h1 {{ color: #0f172a; font-size: 22px; margin-bottom: 8px; text-align: center; }}
        .subtitle {{ color: #64748b; text-align: center; margin-bottom: 30px; }}
        .stars {{
            display: flex;
            justify-content: center;
            gap: 8px;
            margin-bottom: 30px;
        }}
        .star {{
            font-size: 40px;
            cursor: pointer;
            transition: transform 0.2s;
            filter: grayscale(1);
        }}
        .star.active {{ filter: grayscale(0); }}
        .star:hover {{ transform: scale(1.2); }}
        .recommend {{
            background: #f8fafc;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        .recommend-label {{ font-weight: 600; margin-bottom: 12px; color: #334155; }}
        .recommend-btns {{ display: flex; gap: 12px; }}
        .recommend-btn {{
            flex: 1;
            padding: 14px;
            border: 2px solid #e2e8f0;
            border-radius: 10px;
            background: white;
            font-size: 16px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .recommend-btn.active {{
            border-color: #0ea5e9;
            background: #f0f9ff;
            color: #0284c7;
        }}
        textarea {{
            width: 100%;
            padding: 14px;
            border: 2px solid #e2e8f0;
            border-radius: 12px;
            font-size: 16px;
            font-family: inherit;
            resize: none;
            margin-bottom: 20px;
        }}
        textarea:focus {{ outline: none; border-color: #0ea5e9; }}
        .submit {{
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
        }}
        .submit:disabled {{ opacity: 0.5; }}
        .skip {{ text-align: center; margin-top: 16px; }}
        .skip a {{ color: #64748b; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">🏖️ {session.get('operator_name', 'Beach Habitats')}</div>
        </div>
        <div class="card">
            <h1>How Was Your Stay?</h1>
            <p class="subtitle">at {session.get('property_name', 'your property')}</p>
            
            <div class="stars" id="stars">
                <span class="star" data-rating="1">⭐</span>
                <span class="star" data-rating="2">⭐</span>
                <span class="star" data-rating="3">⭐</span>
                <span class="star" data-rating="4">⭐</span>
                <span class="star" data-rating="5">⭐</span>
            </div>
            
            <div class="recommend">
                <div class="recommend-label">Would you recommend us to friends?</div>
                <div class="recommend-btns">
                    <button class="recommend-btn" data-value="true" onclick="setRecommend(true)">👍 Yes!</button>
                    <button class="recommend-btn" data-value="false" onclick="setRecommend(false)">👎 Not really</button>
                </div>
            </div>
            
            <textarea id="comments" rows="3" placeholder="Any feedback or suggestions? (optional)"></textarea>
            
            <button class="submit" id="submitBtn" onclick="submitFeedback()" disabled>Submit Feedback</button>
            
            <div class="skip">
                <a href="#" onclick="skipFeedback()">Skip for now</a>
            </div>
        </div>
    </div>
    
    <script>
        const TOKEN = "{session.get('token', '')}";
        let rating = 0;
        let wouldRecommend = null;
        
        document.querySelectorAll('.star').forEach(star => {{
            star.addEventListener('click', () => {{
                rating = parseInt(star.dataset.rating);
                updateStars();
                checkSubmit();
            }});
        }});
        
        function updateStars() {{
            document.querySelectorAll('.star').forEach((s, i) => {{
                s.classList.toggle('active', i < rating);
            }});
        }}
        
        function setRecommend(value) {{
            wouldRecommend = value;
            document.querySelectorAll('.recommend-btn').forEach(btn => {{
                btn.classList.toggle('active', btn.dataset.value === String(value));
            }});
            checkSubmit();
        }}
        
        function checkSubmit() {{
            document.getElementById('submitBtn').disabled = !(rating > 0 && wouldRecommend !== null);
        }}
        
        async function submitFeedback() {{
            const comments = document.getElementById('comments').value;
            
            try {{
                await fetch(`/api/v1/mobile/${{TOKEN}}/feedback`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ rating, would_recommend: wouldRecommend, comments }})
                }});
                
                document.querySelector('.card').innerHTML = `
                    <div style="text-align: center; padding: 40px 0;">
                        <div style="font-size: 64px; margin-bottom: 20px;">🙏</div>
                        <h1>Thank You!</h1>
                        <p style="color: #64748b; margin-top: 12px;">Your feedback helps us improve. We hope to see you again soon!</p>
                    </div>
                `;
            }} catch (e) {{
                alert('Failed to submit. Please try again.');
            }}
        }}
        
        function skipFeedback() {{
            window.location.href = 'https://beachhabitats.com';
        }}
    </script>
</body>
</html>'''


def get_branded_mobile_html(session: dict, beach_conditions: Optional[dict] = None) -> str:
    """Generate operator-branded mobile interface"""
    
    guest_name = session.get("guest_first_name", "Guest")
    property_name = session.get("property_name", "your property")
    token = session.get("token", "")
    concierge_name = session.get("concierge_name", "Coral")
    concierge_emoji = session.get("concierge_emoji", "🐚")
    is_in_stay = session.get("is_in_stay", False)
    
    # Operator branding
    operator_name = session.get("operator_name", "Beach Habitats")
    operator_logo = session.get("operator_logo_url")
    primary_color = session.get("operator_primary_color", "#0ea5e9")
    support_phone = session.get("operator_support_phone", "(850) 555-0123")
    
    # Logo HTML - use image if available, otherwise text
    if operator_logo:
        logo_html = f'<img src="{operator_logo}" alt="{operator_name}" class="logo-img">'
    else:
        logo_html = f'<span class="logo-text">🏖️ {operator_name}</span>'
    
    # Beach flag HTML (only for in-stay)
    beach_flag_html = ""
    purple_warning_html = ""
    
    if is_in_stay and beach_conditions:
        flag = beach_conditions.get("flag", "yellow")
        flag_config = {
            "green": {"color": "#22c55e", "emoji": "🟢", "bg": "rgba(34, 197, 94, 0.15)"},
            "yellow": {"color": "#eab308", "emoji": "🟡", "bg": "rgba(234, 179, 8, 0.15)"},
            "red": {"color": "#ef4444", "emoji": "🔴", "bg": "rgba(239, 68, 68, 0.15)"},
            "double_red": {"color": "#dc2626", "emoji": "🚩", "bg": "rgba(220, 38, 38, 0.15)"},
        }
        cfg = flag_config.get(flag, flag_config["yellow"])
        status = beach_conditions.get("status", "Check conditions")
        
        beach_flag_html = f'''
        <div class="flag-banner" onclick="ask('Tell me about the current beach conditions')">
            <div class="flag-icon" style="background: {cfg['bg']}; color: {cfg['color']}">{cfg['emoji']}</div>
            <div class="flag-text">
                <div class="flag-status">{status}</div>
                <div class="flag-hint">Tap for beach tips</div>
            </div>
            <div class="flag-arrow">›</div>
        </div>'''
        
        if beach_conditions.get("has_purple"):
            purple_warning_html = '<div class="purple-alert"><span>🟣</span> Jellyfish spotted - shuffle feet when entering water</div>'

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="theme-color" content="{primary_color}">
    <title>{concierge_name} · {operator_name}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: #f0f9ff;
            min-height: 100vh;
            min-height: 100dvh;
            display: flex;
            flex-direction: column;
        }}
        .header {{
            background: linear-gradient(180deg, {primary_color} 0%, {primary_color}dd 100%);
            color: white;
            padding: 16px 20px 20px;
            position: sticky;
            top: 0;
            z-index: 100;
        }}
        .header-top {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }}
        .logo-img {{ height: 36px; width: auto; }}
        .logo-text {{ font-size: 18px; font-weight: 700; }}
        .concierge-pill {{
            background: rgba(255,255,255,0.2);
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 500;
        }}
        .welcome-section {{ margin-bottom: 12px; }}
        .welcome-text {{ font-size: 14px; opacity: 0.9; margin-bottom: 4px; }}
        .property-name {{ font-size: 20px; font-weight: 700; }}
        .flag-banner {{
            background: rgba(255,255,255,0.12);
            border-radius: 12px;
            padding: 12px 14px;
            display: flex;
            align-items: center;
            gap: 12px;
            cursor: pointer;
        }}
        .flag-icon {{
            width: 44px;
            height: 44px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
        }}
        .flag-text {{ flex: 1; }}
        .flag-status {{ font-weight: 600; font-size: 15px; }}
        .flag-hint {{ font-size: 13px; opacity: 0.8; }}
        .flag-arrow {{ font-size: 24px; opacity: 0.6; }}
        .purple-alert {{
            background: #ede9fe;
            color: #5b21b6;
            padding: 10px 16px;
            font-size: 13px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .messages {{
            flex: 1;
            overflow-y: auto;
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        .message {{
            max-width: 85%;
            padding: 14px 18px;
            border-radius: 20px;
            font-size: 15px;
            line-height: 1.5;
            animation: slideIn 0.3s ease;
        }}
        @keyframes slideIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .message.assistant {{
            background: white;
            align-self: flex-start;
            border-bottom-left-radius: 6px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }}
        .message.user {{
            background: {primary_color};
            color: white;
            align-self: flex-end;
            border-bottom-right-radius: 6px;
        }}
        .typing {{
            display: flex;
            gap: 5px;
            padding: 14px 18px;
            background: white;
            border-radius: 20px;
            align-self: flex-start;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }}
        .typing span {{
            width: 8px;
            height: 8px;
            background: #94a3b8;
            border-radius: 50%;
            animation: bounce 1.4s infinite;
        }}
        .typing span:nth-child(2) {{ animation-delay: 0.2s; }}
        .typing span:nth-child(3) {{ animation-delay: 0.4s; }}
        @keyframes bounce {{
            0%, 60%, 100% {{ transform: translateY(0); }}
            30% {{ transform: translateY(-8px); }}
        }}
        .quick-actions {{
            padding: 0 16px 12px;
            display: flex;
            gap: 8px;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }}
        .quick-actions::-webkit-scrollbar {{ display: none; }}
        .quick-btn {{
            flex-shrink: 0;
            background: white;
            border: none;
            padding: 10px 16px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 500;
            color: #334155;
            cursor: pointer;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }}
        .input-area {{
            background: white;
            padding: 12px 16px calc(12px + env(safe-area-inset-bottom));
            border-top: 1px solid #e2e8f0;
        }}
        .input-row {{ display: flex; gap: 10px; align-items: center; }}
        .voice-btn {{
            width: 50px;
            height: 50px;
            border-radius: 50%;
            border: none;
            background: #f1f5f9;
            color: #475569;
            font-size: 22px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }}
        .voice-btn.recording {{
            background: #ef4444;
            color: white;
            animation: pulse 1.5s infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }}
            50% {{ box-shadow: 0 0 0 12px rgba(239, 68, 68, 0); }}
        }}
        .text-input {{
            flex: 1;
            padding: 14px 18px;
            border: 2px solid #e2e8f0;
            border-radius: 25px;
            font-size: 16px;
            font-family: inherit;
            outline: none;
        }}
        .text-input:focus {{ border-color: {primary_color}; }}
        .send-btn {{
            width: 50px;
            height: 50px;
            border-radius: 50%;
            border: none;
            background: {primary_color};
            color: white;
            font-size: 20px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }}
        .escalation {{
            background: #fffbeb;
            border-left: 4px solid #f59e0b;
            margin: 0 16px 12px;
            padding: 14px 16px;
            border-radius: 0 10px 10px 0;
            display: none;
        }}
        .escalation.show {{ display: block; }}
        .escalation-title {{ font-weight: 600; color: #92400e; margin-bottom: 4px; }}
        .escalation-text {{ font-size: 14px; color: #a16207; margin-bottom: 10px; }}
        .escalation-btn {{
            background: #f59e0b;
            color: white;
            border: none;
            padding: 10px 18px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="header-top">
            {logo_html}
            <div class="concierge-pill">{concierge_emoji} {concierge_name}</div>
        </div>
        <div class="welcome-section">
            <div class="welcome-text">Hi {guest_name}! 👋</div>
            <div class="property-name">{property_name}</div>
        </div>
        {beach_flag_html}
    </div>
    
    {purple_warning_html}
    
    <div class="escalation" id="escalation">
        <div class="escalation-title">Need more help?</div>
        <div class="escalation-text">I can connect you with our team.</div>
        <button class="escalation-btn" onclick="escalate()">Talk to a Person</button>
    </div>
    
    <div class="messages" id="messages">
        <div class="message assistant">
            Hey {guest_name}! {concierge_emoji} I'm {concierge_name}, your personal beach concierge for {property_name}.
            <br><br>
            Ask me anything - WiFi, restaurants, beach tips, or whatever you need!
        </div>
    </div>
    
    <div class="quick-actions">
        <button class="quick-btn" onclick="ask('What\\'s the WiFi password?')">📶 WiFi</button>
        <button class="quick-btn" onclick="ask('What\\'s the door code?')">🔑 Door Code</button>
        <button class="quick-btn" onclick="ask('Restaurant recommendations?')">🍽️ Restaurants</button>
        <button class="quick-btn" onclick="ask('What time is checkout?')">⏰ Checkout</button>
        <button class="quick-btn" onclick="ask('I need help with something')">❓ Help</button>
    </div>
    
    <div class="input-area">
        <div class="input-row">
            <button class="voice-btn" id="voiceBtn" onclick="toggleVoice()">🎤</button>
            <input type="text" class="text-input" id="input" placeholder="Type your message..." onkeypress="if(event.key==='Enter')send()">
            <button class="send-btn" onclick="send()">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <path d="M22 2L11 13M22 2L15 22L11 13L2 9L22 2Z"/>
                </svg>
            </button>
        </div>
    </div>
    
    <script>
        const TOKEN = "{token}";
        const SUPPORT_PHONE = "{support_phone}";
        const messages = document.getElementById('messages');
        const input = document.getElementById('input');
        const voiceBtn = document.getElementById('voiceBtn');
        const escalation = document.getElementById('escalation');
        
        let recording = false;
        let recognition = null;
        let msgCount = 0;
        
        if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {{
            const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
            recognition = new SR();
            recognition.continuous = false;
            recognition.interimResults = true;
            recognition.lang = 'en-US';
            recognition.onresult = e => {{
                const text = Array.from(e.results).map(r => r[0].transcript).join('');
                input.value = text;
                if (e.results[0].isFinal) {{ stopVoice(); send(); }}
            }};
            recognition.onerror = stopVoice;
            recognition.onend = stopVoice;
        }} else {{
            voiceBtn.style.display = 'none';
        }}
        
        function toggleVoice() {{ recording ? stopVoice() : startVoice(); }}
        function startVoice() {{
            if (!recognition) return;
            recording = true;
            voiceBtn.classList.add('recording');
            voiceBtn.innerHTML = '⏹';
            input.placeholder = 'Listening...';
            try {{ recognition.start(); }} catch(e) {{ stopVoice(); }}
        }}
        function stopVoice() {{
            recording = false;
            voiceBtn.classList.remove('recording');
            voiceBtn.innerHTML = '🎤';
            input.placeholder = 'Type your message...';
            try {{ recognition?.stop(); }} catch(e) {{}}
        }}
        
        function ask(q) {{ input.value = q; send(); }}
        
        async function send() {{
            const text = input.value.trim();
            if (!text) return;
            
            addMsg(text, 'user');
            input.value = '';
            
            const typing = document.createElement('div');
            typing.className = 'typing';
            typing.innerHTML = '<span></span><span></span><span></span>';
            messages.appendChild(typing);
            messages.scrollTop = messages.scrollHeight;
            
            try {{
                const res = await fetch(`/api/v1/mobile/${{TOKEN}}/chat`, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{message: text, channel: 'mobile'}})
                }});
                const data = await res.json();
                typing.remove();
                addMsg(data.response, 'assistant');
                msgCount++;
                checkEscalation(text);
            }} catch(e) {{
                typing.remove();
                addMsg('Sorry, I had trouble connecting. Please try again.', 'assistant');
            }}
        }}
        
        function addMsg(text, role) {{
            const div = document.createElement('div');
            div.className = 'message ' + role;
            div.innerHTML = text.replace(/\\n/g, '<br>');
            messages.appendChild(div);
            messages.scrollTop = messages.scrollHeight;
        }}
        
        function checkEscalation(msg) {{
            const triggers = ['issue', 'problem', 'broken', 'not working', 'complaint', 'human', 'person', 'manager'];
            if (triggers.some(t => msg.toLowerCase().includes(t)) || msgCount >= 5)
                escalation.classList.add('show');
        }}
        
        async function escalate() {{
            addMsg("I'd like to speak with someone from your team.", 'user');
            try {{
                await fetch(`/api/v1/mobile/${{TOKEN}}/escalate`, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{reason: 'Guest requested human', conversation_count: msgCount}})
                }});
            }} catch(e) {{}}
            addMsg(`Absolutely! I've notified our team and someone will reach out shortly. For urgent matters, call ${{SUPPORT_PHONE}}.\\n\\nI'm still here if you have other questions!`, 'assistant');
            escalation.classList.remove('show');
        }}
        
        setTimeout(() => input.focus(), 300);
    </script>
</body>
</html>'''


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/c/{token}", response_class=HTMLResponse)
async def mobile_interface(token: str):
    """Mobile guest interface - SMS link destination"""
    from app.services.concierge.guest_session import get_session_manager, SessionPhase, SessionStatus
    from app.services.knowledge.beach_flag_scraper import get_current_beach_flag, get_flag_guidance
    
    manager = get_session_manager()
    session = await manager.get_session(token)
    
    # Session not found
    if not session:
        return HTMLResponse(content=get_expired_session_html(), status_code=404)
    
    # Session expired or closed
    if session.phase == SessionPhase.EXPIRED or session.status == SessionStatus.CLOSED:
        return HTMLResponse(content=get_expired_session_html())
    
    # Post-stay: show feedback form (if not already submitted)
    if session.phase == SessionPhase.POST_STAY and not session.feedback:
        session_data = {
            "token": session.token,
            "property_name": session.property_name,
            "operator_name": session.operator_name,
        }
        return HTMLResponse(content=get_feedback_html(session_data))
    
    # Active session: show chat interface
    beach_data = None
    if session.is_in_stay:
        try:
            conditions = await get_current_beach_flag()
            guidance = get_flag_guidance(conditions)
            beach_data = {
                "flag": conditions.primary_flag.value,
                "has_purple": conditions.has_purple,
                "status": guidance["status"],
            }
        except Exception as e:
            logger.warning(f"Beach flag fetch failed: {e}")
    
    session_data = {
        "token": session.token,
        "guest_first_name": session.guest_first_name,
        "property_name": session.property_name,
        "concierge_name": session.concierge_name,
        "concierge_emoji": session.concierge_emoji,
        "is_in_stay": session.is_in_stay,
        "operator_name": session.operator_name,
        "operator_logo_url": session.operator_logo_url,
        "operator_primary_color": session.operator_primary_color,
        "operator_support_phone": session.operator_support_phone,
    }
    
    return HTMLResponse(content=get_branded_mobile_html(session_data, beach_data))


# Hardcoded 30A restaurant recommendations
RESTAURANT_RECS = {
    'burgers': [
        {"name": "Pickles Beachside Grill", "price": "$", "desc": "Local Seaside favorite since 2001. Classic burgers, sandwiches, and their famous pickle chips. Casual outdoor spot.", "phone": "(850) 231-1009"},
        {"name": "Red Bar", "price": "$", "desc": "Legendary locally-owned Grayton Beach dive bar with solid burgers and live music every night.", "phone": "(850) 231-1008"},
        {"name": "Shades Bar & Grill", "price": "$", "desc": "Local spot at WaterColor with great burgers and pool views.", "phone": "(850) 534-5000"},
    ],
    'american': [
        {"name": "Pickles Beachside Grill", "price": "$", "desc": "Local Seaside staple - burgers, sandwiches, salads. Casual and quick.", "phone": "(850) 231-1009"},
        {"name": "Great Southern Cafe", "price": "$", "desc": "Locally-owned Southern American comfort food. Famous for Grits a Ya Ya.", "phone": "(850) 231-7327", "res": True},
        {"name": "Shades Bar & Grill", "price": "$", "desc": "American grill classics at WaterColor. Burgers, wings, salads.", "phone": "(850) 534-5000"},
    ],
    'seafood': [
        {"name": "Bud & Alley's", "price": "$$", "desc": "Family-owned 30A legend since 1986. Best sunset views, fresh Gulf seafood, rooftop bar. A must!", "phone": "(850) 231-5900", "res": True},
        {"name": "Stinky's Fish Camp", "price": "$", "desc": "Locally-owned casual spot with great fried seafood and bayou vibes. Super fun atmosphere.", "phone": "(850) 267-3053"},
        {"name": "Goatfeathers", "price": "$", "desc": "Local seafood market and restaurant in Seaside. Super fresh catch, casual vibe.", "phone": "(850) 231-4823"},
        {"name": "Fish Out of Water", "price": "$$", "desc": "Upscale coastal cuisine with Gulf views. Amazing seafood and craft cocktails.", "phone": "(850) 534-5050", "res": True},
    ],
    'breakfast': [
        {"name": "Scratch Biscuit Kitchen", "price": "$", "desc": "Locally-owned with famous scratch-made biscuits and creative Southern breakfast. A 30A must!", "phone": "(850) 231-6550"},
        {"name": "Black Bear Bread Co.", "price": "$", "desc": "Local artisan bakery in Grayton Beach. Fresh pastries, bread, and amazing breakfast sandwiches.", "phone": "(850) 231-4790"},
        {"name": "Great Southern Cafe", "price": "$", "desc": "Local institution for Southern breakfast. Try the Grits a Ya Ya!", "phone": "(850) 231-7327"},
        {"name": "Cowgirl Kitchen", "price": "$", "desc": "Local Rosemary Beach spot with great breakfast tacos and coffee.", "phone": "(850) 213-4444"},
    ],
    'fine dining': [
        {"name": "Edward's Fine Food & Wine", "price": "$$", "desc": "Locally-owned, best fine dining on 30A. Excellent wine list, creative seasonal menu.", "phone": "(850) 231-0550", "res": True},
        {"name": "Cafe Thirty-A", "price": "$$", "desc": "Local Seagrove favorite. Wood-fired cuisine, great wine, romantic atmosphere.", "phone": "(850) 231-2166", "res": True},
        {"name": "Fish Out of Water", "price": "$$", "desc": "Upscale coastal cuisine with stunning Gulf views. Rooftop bar is magical at sunset.", "phone": "(850) 534-5050", "res": True},
    ],
    'casual': [
        {"name": "Pickles Beachside Grill", "price": "$", "desc": "Local Seaside spot. Quick burgers, sandwiches, famous pickle chips.", "phone": "(850) 231-1009"},
        {"name": "Pizza by the Sea", "price": "$", "desc": "Local WaterColor pizza spot. Good for families, outdoor seating.", "phone": "(850) 231-3030"},
        {"name": "Chiringo", "price": "$", "desc": "Local Grayton beach shack with tacos and cocktails. Feet in the sand!", "phone": "(850) 213-4320"},
    ],
    'tacos': [
        {"name": "Chiringo", "price": "$", "desc": "Local Grayton beach shack with amazing tacos and ceviche. Feet in the sand, great vibe.", "phone": "(850) 213-4320"},
        {"name": "La Cocina", "price": "$", "desc": "Family-owned authentic Mexican in Santa Rosa Beach. Great tacos, enchiladas, margaritas.", "phone": "(850) 622-2252"},
        {"name": "Cowgirl Kitchen", "price": "$", "desc": "Local Rosemary Beach spot with great breakfast tacos and Tex-Mex.", "phone": "(850) 213-4444"},
    ],
    'mexican': [
        {"name": "La Cocina", "price": "$", "desc": "Family-owned authentic Mexican - tacos, enchiladas, great margaritas. Local favorite!", "phone": "(850) 622-2252"},
        {"name": "Chiringo", "price": "$", "desc": "Local beach shack with tacos, ceviche, and cocktails. Feet in the sand in Grayton!", "phone": "(850) 213-4320"},
        {"name": "Cowgirl Kitchen", "price": "$", "desc": "Local Tex-Mex breakfast tacos and lunch in Rosemary Beach.", "phone": "(850) 213-4444"},
    ],
    'pizza': [
        {"name": "Bruno's Pizza", "price": "$", "desc": "Family-owned local favorite since 2003. NY-style pizza, delivery available.", "phone": "(850) 231-0600"},
        {"name": "Pizza by the Sea", "price": "$", "desc": "Local WaterColor spot. Good for families, nice outdoor seating.", "phone": "(850) 231-3030"},
        {"name": "Angelina's Pizzeria", "price": "$", "desc": "Family-owned Italian pizza and pasta in Seagrove. Local gem.", "phone": "(850) 231-2500"},
    ],
    'italian': [
        {"name": "Angelina's Pizzeria", "price": "$", "desc": "Family-owned Italian classics - pizza, pasta, salads. Local Seagrove gem.", "phone": "(850) 231-2500"},
        {"name": "George's at Alys Beach", "price": "$$", "desc": "Locally-owned upscale Italian with great pasta and wine list.", "phone": "(850) 641-0017", "res": True},
        {"name": "Pizza by the Sea", "price": "$", "desc": "Local pizza and Italian dishes in WaterColor.", "phone": "(850) 231-3030"},
    ],
    'sushi': [
        {"name": "Dharma Blue", "price": "$$", "desc": "Locally-owned Pan-Asian with fresh sushi in Santa Rosa Beach. Great rolls and sake.", "phone": "(850) 267-3601", "res": True},
        {"name": "Harbor Docks", "price": "$", "desc": "Local Destin spot with sushi bar plus fresh Gulf seafood. Worth the drive.", "phone": "(850) 837-2506"},
    ],
    'asian': [
        {"name": "Dharma Blue", "price": "$$", "desc": "Locally-owned Pan-Asian with great sushi, Thai curries, and Asian fusion.", "phone": "(850) 267-3601", "res": True},
    ],
    'thai': [
        {"name": "Dharma Blue", "price": "$$", "desc": "Locally-owned with great Thai curries and Pan-Asian cuisine in Santa Rosa Beach.", "phone": "(850) 267-3601", "res": True},
    ],
    'chinese': [
        {"name": "Dharma Blue", "price": "$$", "desc": "Locally-owned Pan-Asian with some Chinese-inspired dishes. Upscale atmosphere.", "phone": "(850) 267-3601", "res": True},
    ],
    'steakhouse': [
        {"name": "Vue on 30A", "price": "$$", "desc": "Locally-owned upscale steakhouse with great cuts and Gulf views. Special occasion worthy.", "phone": "(850) 267-2305", "res": True},
        {"name": "Cafe Thirty-A", "price": "$$", "desc": "Local fine dining favorite with excellent wood-fired steaks in Seagrove.", "phone": "(850) 231-2166", "res": True},
        {"name": "Ruth's Chris", "price": "$$", "desc": "National chain in Destin (~25 min). Reliable prime steaks if local spots are booked.", "phone": "(850) 654-5115", "res": True},
    ],
    'steak': [
        {"name": "Vue on 30A", "price": "$$", "desc": "Locally-owned upscale steakhouse with great cuts and Gulf views. Special occasion worthy.", "phone": "(850) 267-2305", "res": True},
        {"name": "Cafe Thirty-A", "price": "$$", "desc": "Local fine dining favorite with excellent wood-fired steaks in Seagrove.", "phone": "(850) 231-2166", "res": True},
        {"name": "Ruth's Chris", "price": "$$", "desc": "National chain in Destin (~25 min). Reliable prime steaks if local spots are booked.", "phone": "(850) 654-5115", "res": True},
    ],
    'live music': [
        {"name": "Red Bar", "price": "$", "desc": "THE local spot for live music on 30A. Legendary Grayton Beach dive bar, eclectic decor, gets packed!", "phone": "(850) 231-1008"},
        {"name": "Bud & Alley's", "price": "$$", "desc": "Family-owned with live music at the rooftop bar and the best sunset views.", "phone": "(850) 231-5900"},
        {"name": "The Hub", "price": "$", "desc": "Local WaterSound spot with live music, craft beer, and good food.", "phone": "(850) 588-3035"},
    ],
    'sunset views': [
        {"name": "Bud & Alley's", "price": "$$", "desc": "Family-owned 30A legend with the best sunset views from the rooftop bar!", "phone": "(850) 231-5900", "res": True},
        {"name": "Vue on 30A", "price": "$$", "desc": "Locally-owned with panoramic Gulf views and great steaks.", "phone": "(850) 267-2305", "res": True},
        {"name": "Fish Out of Water", "price": "$$", "desc": "Stunning Gulf views, upscale dining. Rooftop bar is perfect for sunset.", "phone": "(850) 534-5050", "res": True},
    ],
    'southern': [
        {"name": "Great Southern Cafe", "price": "$", "desc": "Locally-owned Seaside institution. Famous for Grits a Ya Ya and fried green tomatoes.", "phone": "(850) 231-7327", "res": True},
        {"name": "Scratch Biscuit Kitchen", "price": "$", "desc": "Local favorite for amazing scratch-made biscuits and Southern breakfast.", "phone": "(850) 231-6550"},
        {"name": "Black Bear Bread Co.", "price": "$", "desc": "Local artisan bakery with Southern-inspired breakfast and pastries.", "phone": "(850) 231-4790"},
    ],
    'family friendly': [
        {"name": "Pizza by the Sea", "price": "$", "desc": "Great for kids! Local pizza spot with outdoor seating in WaterColor.", "phone": "(850) 231-3030"},
        {"name": "Pickles Beachside Grill", "price": "$", "desc": "Local casual spot with burgers and sandwiches. Quick, easy, kid-approved.", "phone": "(850) 231-1009"},
        {"name": "Great Southern Cafe", "price": "$", "desc": "Family-friendly locally-owned Southern comfort food in Seaside.", "phone": "(850) 231-7327"},
    ],
    'ice cream': [
        {"name": "Blue Mountain Creamery", "price": "$", "desc": "Locally-owned with homemade ice cream and creative flavors. A 30A favorite!", "phone": "(850) 267-0747"},
        {"name": "Seaside Sweets", "price": "$", "desc": "Local candy and ice cream shop in Seaside. Great after a beach day!", "phone": "(850) 231-5829"},
    ],
    'coffee': [
        {"name": "Amavida Coffee", "price": "$", "desc": "Locally-roasted organic coffee. Multiple 30A locations. Excellent espresso.", "phone": "(850) 213-4994"},
        {"name": "Black Bear Bread Co.", "price": "$", "desc": "Local artisan bakery with great coffee and fresh pastries in Grayton.", "phone": "(850) 231-4790"},
        {"name": "Fonville Press", "price": "$", "desc": "Local Alys Beach coffee shop with excellent brews and light bites.", "phone": "(850) 213-5765"},
    ],
    'brunch': [
        {"name": "Great Southern Cafe", "price": "$", "desc": "Local Seaside institution for brunch. Grits a Ya Ya, fried green tomatoes, bloody marys.", "phone": "(850) 231-7327", "res": True},
        {"name": "Scratch Biscuit Kitchen", "price": "$", "desc": "Local favorite with amazing biscuits and creative brunch dishes.", "phone": "(850) 231-6550"},
        {"name": "Black Bear Bread Co.", "price": "$", "desc": "Local artisan bakery in Grayton with fresh pastries and breakfast.", "phone": "(850) 231-4790"},
    ],
    'drinks': [
        {"name": "Red Bar", "price": "$", "desc": "Legendary local dive bar in Grayton. Great drinks, live music, unforgettable atmosphere.", "phone": "(850) 231-1008"},
        {"name": "Bud & Alley's", "price": "$$", "desc": "Family-owned with the best sunset cocktails on 30A from the rooftop bar.", "phone": "(850) 231-5900"},
        {"name": "The Hub", "price": "$", "desc": "Local WaterSound spot with craft beer, cocktails, and good vibes.", "phone": "(850) 588-3035"},
    ],
}


def get_restaurant_recommendation(msg: str, community: str = "watercolor") -> Optional[str]:
    """
    Smart restaurant recommendations based on what guest is looking for.
    """
    msg = msg.lower()
    
    # Check if they're asking for a specific type
    cuisine_keywords = {
        'burgers': ['burger', 'burgers', 'hamburger', 'hamburgers', 'cheeseburger'],
        'american': ['american', 'american food'],
        'seafood': ['seafood', 'fish', 'shrimp', 'oyster', 'gulf', 'catch', 'crab', 'lobster'],
        'breakfast': ['breakfast', 'brunch', 'morning', 'eggs', 'pancake', 'biscuit'],
        'fine dining': ['nice', 'fancy', 'upscale', 'romantic', 'date night', 'special occasion', 'anniversary', 'celebration', 'fine dining', 'expensive'],
        'casual': ['casual', 'quick', 'easy', 'simple', 'laid back', 'chill', 'low key'],
        'family friendly': ['kids', 'family', 'children', 'family friendly', 'kid friendly'],
        'pizza': ['pizza'],
        'italian': ['italian', 'pasta', 'spaghetti', 'lasagna'],
        'tacos': ['tacos', 'taco'],
        'mexican': ['mexican', 'tex-mex', 'enchilada', 'burrito', 'quesadilla'],
        'sushi': ['sushi', 'sashimi', 'rolls'],
        'asian': ['asian', 'pan-asian'],
        'thai': ['thai', 'pad thai', 'curry', 'thai food'],
        'chinese': ['chinese', 'chinese food', 'lo mein', 'fried rice', 'orange chicken'],
        'steak': ['steak', 'steakhouse', 'ribeye', 'filet', 'prime rib'],
        'live music': ['music', 'live band', 'live music', 'nightlife', 'dancing', 'party'],
        'sunset views': ['sunset', 'view', 'rooftop', 'scenic', 'water view', 'gulf view'],
        'southern': ['southern', 'comfort food', 'grits', 'fried chicken', 'soul food'],
        'ice cream': ['ice cream', 'gelato', 'frozen yogurt', 'dessert'],
        'coffee': ['coffee', 'espresso', 'latte', 'cappuccino', 'cafe'],
        'brunch': ['brunch'],
        'drinks': ['drinks', 'cocktail', 'cocktails', 'beer', 'wine', 'bar'],
    }
    
    matched_cuisine = None
    for cuisine, keywords in cuisine_keywords.items():
        if any(kw in msg for kw in keywords):
            matched_cuisine = cuisine
            break
    
    # If they specified a type, give specific recommendations
    if matched_cuisine and matched_cuisine in RESTAURANT_RECS:
        places = RESTAURANT_RECS[matched_cuisine]
        response = f"🍽️ Great choice! Here are my {matched_cuisine} recommendations:\n\n"
        for i, place in enumerate(places[:3], 1):
            response += f"{i}. **{place['name']}** ({place['price']})\n"
            response += f"   {place['desc']}\n"
            if place.get('res'):
                response += f"   📞 Reservations recommended: {place['phone']}\n"
            else:
                response += f"   📞 {place['phone']}\n"
            response += "\n"
        return response
    
    # General restaurant question - ask what they're in the mood for
    return None  # Let the prompt below handle it


def get_restaurant_prompt() -> str:
    """Return a conversational prompt asking about food preferences."""
    return (
        "🍽️ I'd love to help with restaurant recommendations! 30A has amazing food.\n\n"
        "A few of my favorites:\n"
        "• **Bud & Alley's** - 30A legend, best sunset views, great seafood\n"
        "• **Red Bar** - Fun dive bar with live music (gets packed!)\n"
        "• **Fish Out of Water** - Upscale dining with Gulf views\n"
        "• **Great Southern Cafe** - Southern comfort food, famous Grits a Ya Ya\n\n"
        "What sounds good? Looking for seafood, casual, fine dining, breakfast, or something else?"
    )


async def get_quick_answer(message: str, session) -> Optional[str]:
    """
    Try to answer common questions directly from session data.
    Returns None if AI should handle it.
    """
    msg = message.lower().strip()
    prop = session.property_context or {}
    
    # Activity provider requests (fishing, golf, beach chairs, etc.)
    activity_keywords = {
        'beach_chairs': ['beach chair', 'beach chairs', 'umbrella', 'beach setup', 'beach rental'],
        'fishing': ['fishing', 'charter', 'fish', 'deep sea', 'offshore'],
        'golf': ['golf', 'tee time', 'tee times', 'course', 'golfing'],
        'bikes': ['bike', 'bikes', 'bicycle', 'cycling', 'bike rental'],
        'pontoon': ['pontoon', 'boat rental', 'rent a boat', 'crab island'],
        'dolphin': ['dolphin', 'dolphin tour', 'dolphin cruise', 'dolphins'],
        'spa': ['spa', 'massage', 'facial', 'treatment', 'pamper'],
        'groceries': ['grocery', 'groceries', 'food delivery', 'instacart', 'publix'],
    }
    
    for activity_type, keywords in activity_keywords.items():
        if any(kw in msg for kw in keywords):
            try:
                from app.core.database import get_db_session
                from app.services.operator.stay_journey_service import get_activity_info_by_token

                async with get_db_session() as db:
                    info = await get_activity_info_by_token(db, session.token, activity_type=activity_type)
                if info:
                    return info
            except Exception as e:
                logger.error(f"Activity info error: {e}")
                # Fall through to static provider list
                from app.services.operator.stay_journey_service import ACTIVITY_PROVIDERS
                providers = ACTIVITY_PROVIDERS.get(activity_type, [])
                if providers:
                    lines = [f"Here are some local {activity_type.replace('_', ' ')} options:\n"]
                    for p in providers[:3]:
                        lines.append(f"**{p['name']}**")
                        lines.append(f"   {p['desc']}")
                        if p.get('phone'):
                            lines.append(f"   📞 {p['phone']}")
                        lines.append("")
                    return "\n".join(lines)
            break
    
    # Beach CONDITIONS / FLAG - check this FIRST before general beach questions
    if any(w in msg for w in ['condition', 'flag', 'surf', 'current', 'safe to swim', 'swimming', 'waves', 'hazard', 'jellyfish']):
        try:
            from app.services.knowledge.beach_flag_scraper import get_current_beach_flag, get_flag_guidance
            conditions = await get_current_beach_flag()
            guidance = get_flag_guidance(conditions)
            
            response = f"{guidance['emoji']} {guidance['status']}\n\n{guidance['message']}"
            
            if conditions.has_purple:
                response += f"\n\n{guidance.get('purple_message', '🟣 Purple flag - marine life spotted.')}"
            
            if guidance.get('tips'):
                response += "\n\nTips:\n" + "\n".join(f"• {tip}" for tip in guidance['tips'][:3])
            
            return response
        except Exception as e:
            logger.error(f"Beach flag error: {e}")
            return None  # Fall back to AI
    
    # WiFi
    if any(w in msg for w in ['wifi', 'wi-fi', 'internet', 'password', 'network']):
        network = prop.get('wifi_network', 'See welcome book')
        password = prop.get('wifi_password', 'See welcome book')
        return f"📶 WiFi Network: {network}\nPassword: {password}"
    
    # Door code
    if any(w in msg for w in ['door', 'code', 'lock', 'entry', 'get in', 'keypad']):
        code = prop.get('door_code', 'Check your welcome email')
        return f"🔑 Door Code: {code}"
    
    # Checkout time
    if any(w in msg for w in ['checkout', 'check out', 'check-out', 'leaving', 'leave time']):
        checkout_time = prop.get('check_out_time', '10:00 AM')
        return f"⏰ Checkout is at {checkout_time}. Please make sure all dishes are in the dishwasher and trash is taken out. Safe travels!"
    
    # Check-in time
    if any(w in msg for w in ['checkin', 'check in', 'check-in', 'arrival', 'arrive']):
        checkin_time = prop.get('check_in_time', '4:00 PM')
        return f"🏠 Check-in is at {checkin_time}. We'll send you the door code the morning of your arrival!"
    
    # Parking
    if any(w in msg for w in ['parking', 'park', 'car', 'garage', 'driveway']):
        parking = prop.get('parking_info', 'See property details')
        return f"🚗 Parking: {parking}"
    
    # Pool / Pool Heat
    if any(w in msg for w in ['pool', 'heated', 'heat the pool', 'warm pool']):
        pool_heatable = prop.get('pool_heated', False)
        if pool_heatable or 'heat' in msg:
            return """Your property has a **heated pool** option! 🏊‍♂️

Pool heating is **$50/day** and needs to be requested at least 48 hours before you want it turned on. It makes a big difference in the cooler months!

Would you like me to add pool heat to your stay?"""
        else:
            return "🏊 This property has a pool! Check the welcome book for pool rules and hours."
    
    # Beach ACCESS (not conditions) - wristbands, how to get there
    if any(w in msg for w in ['beach access', 'beach club', 'wristband', 'get to the beach', 'where is the beach']):
        beach = prop.get('beach_access', 'See welcome book for beach access details')
        return f"🏖️ Beach Access: {beach}"
    
    # Grill/BBQ
    if any(w in msg for w in ['grill', 'bbq', 'barbecue']):
        grill = prop.get('grill', 'Check the patio area')
        return f"🍖 Grill: {grill}"
    
    # Trash
    if any(w in msg for w in ['trash', 'garbage', 'recycl']):
        trash = prop.get('trash', 'Bins are typically in the garage')
        return f"🗑️ Trash: {trash}"
    
    # Restaurant / Food recommendations
    # First check if they mentioned a specific food type (even in longer sentences like "looking for a good hamburger")
    specific_rec = get_restaurant_recommendation(msg)
    if specific_rec:
        return specific_rec
    
    # If no specific type, but asking about food generally
    if any(w in msg for w in ['restaurant', 'food', 'eat', 'dinner', 'lunch', 'hungry', 'dining', 'recommend', 'where to eat', 'good place']):
        return get_restaurant_prompt()
    
    return None  # Let AI handle it


@router.post("/api/v1/mobile/{token}/chat", response_model=ChatResponse)
async def mobile_chat(token: str, request: ChatRequest):
    """Handle chat message - tries quick answers first, then AI"""
    from app.services.concierge.guest_session import get_session_manager, build_concierge_context, build_system_prompt, SessionStatus
    from app.core.config import get_settings
    import httpx
    
    settings = get_settings()
    manager = get_session_manager()
    session = await manager.get_session(token)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if session.is_expired or session.status == SessionStatus.CLOSED:
        raise HTTPException(status_code=410, detail="Session has expired")
    
    # Try quick answer from session data first
    quick_answer = await get_quick_answer(request.message, session)
    if quick_answer:
        await manager.increment_conversation_count(token)
        return ChatResponse(
            response=quick_answer,
            session_token=token,
            concierge_name=session.concierge_name,
            timestamp=datetime.utcnow().isoformat(),
            should_request_feedback=session.should_request_feedback,
        )
    
    # Fall back to AI for complex questions
    context = build_concierge_context(session)
    system_prompt = build_system_prompt(context)
    
    response_text = "I'm not sure about that one. For immediate help, please call our team!"
    
    groq_key = settings.groq_api_key or os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": request.message},
                        ],
                        "max_tokens": 150,
                        "temperature": 0.7,
                    },
                    timeout=10.0,
                )
                data = resp.json()
                if "choices" in data:
                    response_text = data["choices"][0]["message"]["content"]
                else:
                    logger.error(f"Groq API error: {data}")
        except Exception as e:
            logger.error(f"LLM error: {e}")
    
    await manager.increment_conversation_count(token)
    
    return ChatResponse(
        response=response_text,
        session_token=token,
        concierge_name=session.concierge_name,
        timestamp=datetime.utcnow().isoformat(),
        should_request_feedback=session.should_request_feedback,
    )


@router.post("/api/v1/mobile/{token}/feedback")
async def submit_feedback(token: str, request: FeedbackRequest):
    """Submit guest feedback and close session"""
    from app.services.concierge.guest_session import get_session_manager
    
    manager = get_session_manager()
    session = await manager.submit_feedback(
        token=token,
        rating=request.rating,
        would_recommend=request.would_recommend,
        comments=request.comments,
    )
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"status": "ok", "message": "Thank you for your feedback!"}


@router.post("/api/v1/mobile/{token}/escalate")
async def escalate(token: str, request: EscalateRequest):
    """Guest requests human assistance"""
    from app.services.concierge.guest_session import get_session_manager
    from app.services.concierge.escalation_service import get_escalation_service
    
    manager = get_session_manager()
    session = await manager.get_session(token)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    escalation_svc = get_escalation_service()
    ticket = await escalation_svc.create_manual_escalation(
        session_token=token,
        reason=request.reason,
        session_info={
            "guest_name": session.guest_name,
            "guest_phone": session.guest_phone,
            "guest_email": session.guest_email,
            "property_name": session.property_name,
            "property_code": session.property_code,
        },
        conversation_history=[],
    )
    
    return {"status": "ok", "ticket_id": ticket.id}
