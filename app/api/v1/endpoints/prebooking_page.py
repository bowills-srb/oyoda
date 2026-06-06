"""
prebooking_page.py — Standalone Pre-Booking Inbox Page

Served at /app/pre-booking — a focused inbox UI for reviewing
and actioning AI-drafted replies to guest inquiries.

Auth: same httpOnly JWT cookie as the rest of the operator app.
Linked from the main dashboard's Pre-Booking nav item.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import json, base64, time

router = APIRouter(prefix="/app", tags=["Pre-Booking Page"])


def _get_current_user(request: Request):
    token = request.cookies.get("oyvoda_access")
    if not token:
        return None
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


PRE_BOOKING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pre-Booking Inbox — Oyvoda</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500&family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#08090f;color:#f0ebe3;font-family:'DM Sans',sans-serif;min-height:100vh;-webkit-font-smoothing:antialiased}

/* ── Top nav ── */
.topnav{display:flex;align-items:center;justify-content:space-between;padding:0 28px;height:56px;
  background:rgba(13,18,32,0.95);border-bottom:1px solid rgba(255,255,255,0.06);position:sticky;top:0;z-index:100}
.logo{font-family:'Cormorant Garamond',serif;font-size:22px;color:#f0ebe3;text-decoration:none}
.back-btn{font-size:12px;color:rgba(240,235,227,0.4);text-decoration:none;display:flex;align-items:center;gap:6px;
  transition:color 0.15s}
.back-btn:hover{color:#f0ebe3}

/* ── Layout ── */
.container{max-width:960px;margin:0 auto;padding:32px 24px}
.page-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:28px}
h1{font-size:22px;font-weight:600}
.stats-row{display:flex;gap:12px}
.stat-pill{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:20px;
  padding:5px 14px;font-size:12px;color:rgba(240,235,227,0.5)}
.stat-pill span{color:#f0ebe3;font-weight:600;margin-right:4px}

/* ── Tabs ── */
.tabs{display:flex;gap:4px;margin-bottom:20px;border-bottom:1px solid rgba(255,255,255,0.07);padding-bottom:0}
.tab{padding:8px 16px;font-size:13px;color:rgba(240,235,227,0.4);cursor:pointer;border-bottom:2px solid transparent;
  margin-bottom:-1px;transition:all 0.15s;border-radius:6px 6px 0 0}
.tab:hover{color:#f0ebe3;background:rgba(255,255,255,0.03)}
.tab.active{color:#c87832;border-bottom-color:#c87832;background:rgba(200,120,50,0.05)}
.tab .badge{background:rgba(200,120,50,0.15);color:#c87832;border-radius:10px;
  padding:1px 7px;font-size:10px;font-weight:600;margin-left:6px}

/* ── Cards ── */
.inquiry-list{display:flex;flex-direction:column;gap:14px}
.inquiry-card{background:rgba(13,18,32,0.95);border:1px solid rgba(255,255,255,0.08);border-radius:14px;
  padding:20px;transition:border-color 0.15s}
.inquiry-card:hover{border-color:rgba(200,120,50,0.2)}
.inquiry-card.replied{opacity:0.55}
.card-header{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:12px}
.guest-info{display:flex;align-items:center;gap:12px}
.guest-avatar{width:36px;height:36px;border-radius:50%;background:rgba(200,120,50,0.12);
  border:1px solid rgba(200,120,50,0.2);display:flex;align-items:center;justify-content:center;
  font-size:13px;font-weight:600;color:#c87832;flex-shrink:0}
.guest-name{font-size:14px;font-weight:600;color:#f0ebe3}
.guest-meta{font-size:11px;color:rgba(240,235,227,0.4);margin-top:2px}
.card-right{display:flex;flex-direction:column;align-items:flex-end;gap:6px}
.platform-badge{font-size:10px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;
  padding:3px 8px;border-radius:6px}
.platform-vrbo{background:rgba(0,120,200,0.1);color:#3ba0e0;border:1px solid rgba(0,120,200,0.2)}
.platform-airbnb{background:rgba(255,90,95,0.1);color:#ff5a5f;border:1px solid rgba(255,90,95,0.2)}
.platform-booking{background:rgba(0,100,220,0.1);color:#4488ee;border:1px solid rgba(0,100,220,0.2)}
.platform-direct{background:rgba(120,120,120,0.1);color:#aaa;border:1px solid rgba(120,120,120,0.2)}
.platform-unknown{background:rgba(120,120,120,0.1);color:#aaa;border:1px solid rgba(120,120,120,0.2)}
.time-ago{font-size:11px;color:rgba(240,235,227,0.3)}
.confidence-bar{height:3px;background:rgba(255,255,255,0.06);border-radius:2px;margin-bottom:14px;width:100%}
.confidence-fill{height:100%;border-radius:2px;background:linear-gradient(90deg,#8b3a10,#c87832)}

/* ── Message & Draft ── */
.message-block,.draft-block{background:rgba(255,255,255,0.03);border-radius:10px;padding:12px 14px;
  font-size:13px;line-height:1.6;margin-bottom:10px}
.message-block{border-left:3px solid rgba(255,255,255,0.08);color:rgba(240,235,227,0.65)}
.draft-block{border-left:3px solid rgba(200,120,50,0.4);color:#f0ebe3;position:relative}
.block-label{font-size:10px;letter-spacing:0.1em;text-transform:uppercase;
  color:rgba(240,235,227,0.3);margin-bottom:6px;font-weight:500}
.draft-editable{width:100%;background:transparent;border:none;color:#f0ebe3;font-family:'DM Sans',sans-serif;
  font-size:13px;line-height:1.6;resize:vertical;min-height:72px;outline:none}
.draft-editable:focus{background:rgba(200,120,50,0.04)}
.edit-hint{font-size:11px;color:rgba(200,120,50,0.5);margin-top:4px}

/* ── Flags ── */
.flags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}
.flag{font-size:11px;padding:3px 10px;border-radius:6px;border:1px solid;background:rgba(245,158,11,0.06);
  color:#fbbf24;border-color:rgba(245,158,11,0.2)}
.warn{background:rgba(239,68,68,0.06);color:#fca5a5;border-color:rgba(239,68,68,0.2)}

/* ── Property strip ── */
.prop-strip{font-size:11px;color:rgba(240,235,227,0.35);margin-bottom:14px;display:flex;align-items:center;gap:6px}
.prop-strip span{color:rgba(240,235,227,0.55)}

/* ── Actions ── */
.card-actions{display:flex;gap:8px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.05)}
.btn{padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif;
  cursor:pointer;border:none;transition:all 0.15s;display:flex;align-items:center;gap:6px}
.btn-approve{background:#c87832;color:#fff}
.btn-approve:hover{background:#e09040}
.btn-approve:disabled{opacity:0.5;cursor:not-allowed}
.btn-edit{background:rgba(255,255,255,0.06);color:#f0ebe3;border:1px solid rgba(255,255,255,0.1)}
.btn-edit:hover{background:rgba(255,255,255,0.1)}
.btn-reject{background:transparent;color:rgba(240,235,227,0.35);border:1px solid rgba(255,255,255,0.06)}
.btn-reject:hover{color:#fca5a5;border-color:rgba(239,68,68,0.25)}
.btn-reject:disabled{opacity:0.4;cursor:not-allowed}
.action-result{font-size:12px;padding:6px 12px;border-radius:6px;display:none}
.action-result.ok{background:rgba(34,197,94,0.08);color:#86efac;border:1px solid rgba(34,197,94,0.2);display:block}
.action-result.err{background:rgba(239,68,68,0.08);color:#fca5a5;border:1px solid rgba(239,68,68,0.2);display:block}

/* ── Empty state ── */
.empty{text-align:center;padding:60px 20px;color:rgba(240,235,227,0.3)}
.empty-icon{font-size:40px;margin-bottom:12px}
.empty h3{font-size:16px;font-weight:500;color:rgba(240,235,227,0.5);margin-bottom:6px}
.empty p{font-size:13px;line-height:1.6}

/* ── Loading ── */
.loading{text-align:center;padding:48px;color:rgba(240,235,227,0.3);font-size:13px}
.spinner{display:inline-block;width:18px;height:18px;border:2px solid rgba(200,120,50,0.2);
  border-top-color:#c87832;border-radius:50%;animation:spin 0.6s linear infinite;margin-right:8px;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── Toast ── */
.toast{position:fixed;bottom:24px;right:24px;background:rgba(13,18,32,0.97);border:1px solid rgba(34,197,94,0.3);
  color:#86efac;padding:12px 18px;border-radius:10px;font-size:13px;box-shadow:0 8px 32px rgba(0,0,0,0.4);
  transform:translateY(80px);opacity:0;transition:all 0.3s;z-index:200}
.toast.show{transform:translateY(0);opacity:1}
.toast.error{border-color:rgba(239,68,68,0.3);color:#fca5a5}
</style>
</head>
<body>

<nav class="topnav">
  <a href="/app/dashboard" class="back-btn">← Dashboard</a>
  <a href="/" class="logo">oyvoda</a>
  <div style="width:100px"></div>
</nav>

<div class="container">
  <div class="page-header">
    <h1>Pre-Booking Inbox</h1>
    <div class="stats-row" id="stats-row">
      <div class="stat-pill"><span id="stat-pending">—</span>pending</div>
      <div class="stat-pill"><span id="stat-replied">—</span>replied</div>
      <div class="stat-pill"><span id="stat-total">—</span>30d total</div>
    </div>
  </div>

  <div class="tabs">
    <div class="tab active" onclick="switchTab('pending_review')" id="tab-pending">
      Pending Review <span class="badge" id="badge-pending">0</span>
    </div>
    <div class="tab" onclick="switchTab('replied')" id="tab-replied">Replied</div>
    <div class="tab" onclick="switchTab('all')" id="tab-all">All</div>
  </div>

  <div id="inquiry-list" class="inquiry-list">
    <div class="loading"><span class="spinner"></span>Loading inquiries...</div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
var currentTab = 'pending_review';
var inquiries = [];

function timeAgo(iso) {
  if (!iso) return '';
  var diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff/60) + 'm ago';
  if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
  return Math.floor(diff/86400) + 'd ago';
}

function initials(name) {
  if (!name) return '?';
  return name.split(' ').map(p=>p[0]).join('').toUpperCase().slice(0,2);
}

function platformClass(p) {
  if (!p) return 'platform-unknown';
  var m = {'vrbo':'platform-vrbo','airbnb':'platform-airbnb','booking':'platform-booking','direct':'platform-direct'};
  return m[p.toLowerCase()] || 'platform-unknown';
}

function escHtml(s) {
  return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function loadStats() {
  try {
    var r = await fetch('/app/api/inquiries/stats');
    var d = await r.json();
    document.getElementById('stat-pending').textContent = d.pending;
    document.getElementById('stat-replied').textContent = d.replied;
    document.getElementById('stat-total').textContent = d.total_30d;
    document.getElementById('badge-pending').textContent = d.pending;
  } catch(e) {}
}

async function loadInquiries(status) {
  var list = document.getElementById('inquiry-list');
  list.innerHTML = '<div class="loading"><span class="spinner"></span>Loading...</div>';
  try {
    var r = await fetch('/app/api/inquiries?status=' + status + '&limit=50');
    var d = await r.json();
    inquiries = d.items || [];
    renderList(inquiries);
  } catch(e) {
    list.innerHTML = '<div class="empty"><h3>Could not load inquiries</h3><p>' + escHtml(String(e)) + '</p></div>';
  }
}

function renderList(items) {
  var list = document.getElementById('inquiry-list');
  if (!items.length) {
    var msgs = {pending_review:'No inquiries pending review',replied:'No replied inquiries',all:'No inquiries yet'};
    list.innerHTML = '<div class="empty"><h3>' + (msgs[currentTab]||'Nothing here') + '</h3><p>Guest inquiries from Vrbo and Airbnb will appear here when they arrive.</p></div>';
    return;
  }
  list.innerHTML = items.map(function(inq) { return renderCard(inq); }).join('');
}

function renderCard(inq) {
  var isActioned = inq.status === 'replied' || inq.status === 'rejected';
  var flags = (inq.policy_flags||[]).map(function(f){return '<span class="flag">'+escHtml(f)+'</span>';}).join('');
  var warns = (inq.policy_warnings||[]).map(function(w){return '<span class="flag warn">'+escHtml(w)+'</span>';}).join('');
  var allFlags = flags + warns;
  var conf = Math.round((inq.confidence||0)*100);
  var propLine = inq.property_name && inq.property_name !== 'Unknown property'
    ? '<div class="prop-strip"><span>' + escHtml(inq.property_name) + '</span></div>'
    : '';
  var datesLine = '';
  if (inq.requested_check_in) {
    datesLine = '<div class="prop-strip"><span>' + escHtml(inq.requested_check_in) + ' to ' + escHtml(inq.requested_check_out||'?') + '</span>' +
      (inq.requested_guests ? ' <span>' + inq.requested_guests + ' guests</span>' : '') + '</div>';
  }
  var editableOrText = isActioned
    ? '<div class="draft-block"><div class="block-label">' + (inq.status==='replied'?'Sent reply':'Draft (not sent)') + '</div>' + escHtml(inq.final_reply || inq.draft_text) + '</div>'
    : '<div class="draft-block"><div class="block-label">AI Draft — edit if needed</div><textarea class="draft-editable" id="draft-' + escHtml(inq.draft_id) + '" rows="4">' + escHtml(inq.draft_text) + '</textarea><div class="edit-hint">Edit above, then click Send</div></div>';
  var actions = isActioned
    ? '<div class="action-result ok" id="result-' + escHtml(inq.draft_id) + '">' + (inq.status==='replied' ? 'Reply sent ' + timeAgo(inq.replied_at) : 'Rejected') + '</div>'
    : '<div class="card-actions"><button class="btn btn-approve" onclick="approve(\'' + escHtml(inq.draft_id) + '\')">Send Reply →</button>' +
      '<button class="btn btn-reject" onclick="reject(\'' + escHtml(inq.draft_id) + '\')">Reject</button>' +
      '<div class="action-result" id="result-' + escHtml(inq.draft_id) + '"></div></div>';
  return '<div class="inquiry-card' + (isActioned?' replied':'') + '" id="card-' + escHtml(inq.draft_id) + '">' +
    '<div class="card-header">' +
      '<div class="guest-info">' +
        '<div class="guest-avatar">' + escHtml(initials(inq.guest_name)) + '</div>' +
        '<div><div class="guest-name">' + escHtml(inq.guest_name) + '</div>' +
        '<div class="guest-meta">' + escHtml(inq.guest_email||'') + '</div></div>' +
      '</div>' +
      '<div class="card-right">' +
        '<span class="platform-badge ' + platformClass(inq.platform) + '">' + escHtml((inq.platform||'').toUpperCase()) + '</span>' +
        '<span class="time-ago">' + timeAgo(inq.received_at) + '</span>' +
      '</div>' +
    '</div>' +
    propLine + datesLine +
    '<div class="confidence-bar"><div class="confidence-fill" style="width:' + conf + '%"></div></div>' +
    (allFlags ? '<div class="flags">' + allFlags + '</div>' : '') +
    '<div class="message-block"><div class="block-label">Guest message</div>' + escHtml(inq.message_text) + '</div>' +
    editableOrText +
    actions +
  '</div>';
}

async function approve(draftId) {
  var ta = document.getElementById('draft-' + draftId);
  var replyText = ta ? ta.value.trim() : null;
  setCardLoading(draftId, true);
  try {
    var body = replyText ? {reply_text: replyText} : {};
    var endpoint = replyText ? '/app/api/inquiries/' + draftId + '/edit' : '/app/api/inquiries/' + draftId + '/approve';
    var r = await fetch(endpoint, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    var d = await r.json();
    if (r.ok && d.ok) {
      showToast('Reply sent successfully');
      markCardDone(draftId, 'replied');
      loadStats();
    } else {
      showToast(d.error || 'Send failed', true);
      setCardLoading(draftId, false);
    }
  } catch(e) {
    showToast('Connection error', true);
    setCardLoading(draftId, false);
  }
}

async function reject(draftId) {
  if (!confirm('Reject this inquiry without sending a reply?')) return;
  setCardLoading(draftId, true);
  try {
    var r = await fetch('/app/api/inquiries/' + draftId + '/reject', {method:'POST'});
    var d = await r.json();
    if (r.ok && d.ok) {
      showToast('Inquiry rejected');
      markCardDone(draftId, 'rejected');
      loadStats();
    } else {
      showToast(d.error || 'Reject failed', true);
      setCardLoading(draftId, false);
    }
  } catch(e) {
    showToast('Connection error', true);
    setCardLoading(draftId, false);
  }
}

function setCardLoading(draftId, loading) {
  var card = document.getElementById('card-' + draftId);
  if (!card) return;
  card.querySelectorAll('.btn').forEach(function(b){ b.disabled = loading; });
  if (loading) {
    var result = document.getElementById('result-' + draftId);
    if (result) result.innerHTML = '<span class="spinner"></span>Sending...';
  }
}

function markCardDone(draftId, status) {
  var card = document.getElementById('card-' + draftId);
  if (!card) return;
  card.classList.add('replied');
  var actions = card.querySelector('.card-actions');
  if (actions) {
    actions.innerHTML = '<div class="action-result ok">' + (status==='replied'?'Reply sent':'Rejected') + '</div>';
  }
}

function showToast(msg, isError) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show' + (isError ? ' error' : '');
  setTimeout(function(){ t.className = 'toast' + (isError?' error':''); }, 3000);
}

function switchTab(status) {
  currentTab = status;
  ['pending_review','replied','all'].forEach(function(s) {
    var tab = document.getElementById('tab-' + (s==='pending_review'?'pending':s));
    if (tab) tab.className = 'tab' + (s===status?' active':'');
  });
  loadInquiries(status);
}

// Init
loadStats();
loadInquiries('pending_review');

// Auto-refresh every 60s when on pending tab
setInterval(function(){
  if (currentTab === 'pending_review') { loadInquiries('pending_review'); loadStats(); }
}, 60000);
</script>
</body>
</html>"""


@router.get("/pre-booking", response_class=HTMLResponse)
async def pre_booking_page(request: Request):
    """Pre-booking inbox page — review and action AI-drafted replies."""
    user = _get_current_user(request)
    if not user:
        return RedirectResponse("/app", status_code=302)
    return HTMLResponse(content=PRE_BOOKING_HTML)
