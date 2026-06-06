"""
Beach Habitats — Public Landing Page v2

Fin.ai-inspired marketing site with:
- Hero with live interactive demo chat (no auth required)
- How It Works (3 steps)
- Feature grid
- Second live demo section
- White-label branding showcase
- Pricing table
- Testimonials
- CTA section + footer

Design: Coastal luxury · Playfair Display + DM Sans · Navy/ocean palette
Served at GET /

Replace the existing landing.py route with this file.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from app.core.config import get_settings

router = APIRouter(tags=["Landing v2"])

LANDING_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Beach Habitats — AI Concierge for Vacation Rentals</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --ink:#0a0e1a;--ink-muted:#4a5568;--ink-faint:#94a3b8;
  --shell:#f7f4ee;--shell-dark:#ede9df;--white:#fff;
  --ocean:#0b5a87;--ocean-mid:#1279b5;--ocean-light:#3fa5d8;--ocean-pale:#ddf0fc;
  --seafoam:#0d9488;--sand:#f59e0b;
  --border:#e4ddd0;--border-strong:#c9bfae;
  --display:'Playfair Display',Georgia,serif;
  --body:'DM Sans',-apple-system,sans-serif;
  --mono:'DM Mono',monospace;
}
html{scroll-behavior:smooth}
body{font-family:var(--body);color:var(--ink);background:var(--white);overflow-x:hidden;line-height:1.6}
h1,h2,h3{font-family:var(--display);line-height:1.12;letter-spacing:-.02em}
h1{font-size:clamp(2.4rem,5vw,4rem);font-weight:900}
h2{font-size:clamp(1.8rem,3.5vw,2.6rem);font-weight:700}
h3{font-size:1.1rem;font-weight:700}
p{color:var(--ink-muted);font-size:.98rem}

/* NAV */
nav{position:fixed;top:0;left:0;right:0;z-index:100;height:66px;display:flex;align-items:center;padding:0 6%;background:rgba(247,244,238,.92);backdrop-filter:blur(14px);border-bottom:1px solid var(--border)}
.logo{display:flex;align-items:center;gap:10px;text-decoration:none}
.logo-mark{width:36px;height:36px;background:linear-gradient(135deg,var(--ocean),var(--ocean-mid));border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px}
.logo-text{font-family:var(--display);font-weight:700;font-size:1rem;color:var(--ink)}
.logo-sub{display:block;font-size:.65rem;color:var(--ink-faint);letter-spacing:.07em;text-transform:uppercase;line-height:1;font-family:var(--body)}
.nav-links{display:flex;gap:28px;margin-left:40px}
.nav-links a{color:var(--ink-muted);text-decoration:none;font-size:.87rem;font-weight:500;transition:color .15s}
.nav-links a:hover{color:var(--ocean)}
.nav-sep{flex:1}
.btn-ghost{color:var(--ocean);font-size:.87rem;font-weight:500;text-decoration:none;padding:7px 13px;border-radius:7px;transition:background .15s}
.btn-ghost:hover{background:var(--ocean-pale)}
.btn-primary{background:var(--ocean);color:#fff;border:none;cursor:pointer;padding:10px 20px;border-radius:8px;font-size:.87rem;font-weight:600;font-family:var(--body);text-decoration:none;display:inline-flex;align-items:center;gap:6px;transition:all .15s;box-shadow:0 1px 4px rgba(11,90,135,.28)}
.btn-primary:hover{background:var(--ocean-mid);transform:translateY(-1px);box-shadow:0 4px 14px rgba(11,90,135,.34)}

/* HERO */
.hero{min-height:100vh;display:grid;grid-template-columns:1fr 1fr;align-items:center;gap:60px;padding:110px 6% 80px;background:var(--shell);position:relative;overflow:hidden}
.hero::after{content:'';position:absolute;top:0;right:0;width:52%;height:100%;background:linear-gradient(155deg,var(--ocean-pale) 0%,#e8f5fd 50%,var(--shell) 85%);clip-path:polygon(10% 0,100% 0,100% 100%,0 100%);z-index:0}
.hero-l{position:relative;z-index:2}
.hero-r{position:relative;z-index:2}
.eyebrow{display:inline-flex;align-items:center;gap:7px;background:var(--white);border:1px solid var(--border-strong);border-radius:100px;padding:5px 14px 5px 8px;font-size:.77rem;font-weight:600;color:var(--ocean);margin-bottom:24px;letter-spacing:.02em}
.e-dot{width:8px;height:8px;border-radius:50%;background:var(--seafoam);animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(13,148,136,.4)}60%{box-shadow:0 0 0 5px rgba(13,148,136,0)}}
.grad-text{background:linear-gradient(135deg,var(--ink) 0%,var(--ocean) 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hero-sub{font-size:1.07rem;color:var(--ink-muted);margin-bottom:30px;max-width:450px;line-height:1.72}
.hero-btns{display:flex;align-items:center;gap:13px;margin-bottom:42px;flex-wrap:wrap}
.btn-xl{padding:13px 26px;font-size:.94rem;border-radius:10px}
.btn-outline{background:transparent;color:var(--ocean);border:1.5px solid var(--ocean);padding:12px 22px;border-radius:10px;font-size:.94rem;font-weight:600;font-family:var(--body);cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:6px;transition:all .15s}
.btn-outline:hover{background:var(--ocean);color:#fff}
.stats{display:flex;gap:34px}
.stat-n{font-family:var(--display);font-size:1.75rem;font-weight:700;color:var(--ocean);line-height:1}
.stat-l{font-size:.76rem;color:var(--ink-faint);font-weight:500;margin-top:2px}

/* PHONE */
.phone{width:300px;background:var(--white);border-radius:30px;box-shadow:0 28px 72px rgba(11,90,135,.15),0 0 0 1px rgba(11,90,135,.07);overflow:hidden;font-size:.87rem;margin:0 auto}
.ph-hdr{display:flex;align-items:center;gap:11px;padding:16px 16px 13px}
.ph-av{width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,.16);display:flex;align-items:center;justify-content:center;font-size:17px;flex-shrink:0}
.ph-name{color:#fff;font-weight:600;font-size:.88rem}
.ph-prop{color:rgba(255,255,255,.68);font-size:.72rem}
.ph-stat{display:flex;align-items:center;gap:4px;margin-top:2px}
.s-dot{width:6px;height:6px;border-radius:50%;background:#4ade80}
.s-txt{color:rgba(255,255,255,.62);font-size:.68rem}
.ph-msgs{padding:13px;background:#f8fafc;min-height:280px;max-height:320px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;scroll-behavior:smooth}
.msg{display:flex;flex-direction:column;gap:2px}
.msg.u{align-items:flex-end}
.msg.b{align-items:flex-start}
.bub{padding:8px 11px;border-radius:13px;line-height:1.45;word-break:break-word;font-size:.8rem}
.msg.b .bub{background:var(--white);color:var(--ink);border:1px solid var(--border);border-bottom-left-radius:3px}
.msg.u .bub{background:var(--ocean);color:#fff;border-bottom-right-radius:3px}
.mt{font-size:.64rem;color:var(--ink-faint);padding:0 3px}
.typ{display:flex;gap:3px;align-items:center;background:var(--white);border:1px solid var(--border);border-radius:13px;border-bottom-left-radius:3px;padding:8px 11px}
.td{width:5px;height:5px;border-radius:50%;background:var(--ink-faint);animation:td .9s infinite}
.td:nth-child(2){animation-delay:.15s}.td:nth-child(3){animation-delay:.3s}
@keyframes td{0%,80%,100%{transform:translateY(0)}40%{transform:translateY(-4px)}}
.ph-inp{padding:10px 13px;border-top:1px solid var(--border);background:var(--white);display:flex;gap:7px;align-items:center}
.inp-f{flex:1;background:#f1f5f9;border:1px solid transparent;border-radius:100px;padding:7px 13px;font-size:.8rem;color:var(--ink);font-family:var(--body);outline:none;transition:border-color .15s}
.inp-f:focus{border-color:var(--ocean-light);background:var(--white)}
.send-b{width:30px;height:30px;border-radius:50%;background:var(--ocean);border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;color:#fff;flex-shrink:0;transition:all .15s}
.send-b:hover{background:var(--ocean-mid);transform:scale(1.06)}
.palm-b{width:30px;height:30px;border-radius:50%;background:var(--shell-dark);border:1px solid var(--border);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0;transition:all .15s}
.palm-b:hover{background:var(--ocean-pale);border-color:var(--ocean-light)}
.ph-foot{display:block;text-align:center;padding:7px;background:var(--white);border-top:1px solid var(--border);font-size:.7rem;color:var(--seafoam);font-weight:600}

/* METRICS */
.met{background:var(--ink);padding:52px 6%}
.met-row{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:rgba(255,255,255,.05)}
.met-i{background:var(--ink);padding:30px 22px;text-align:center;transition:background .15s;cursor:default}
.met-i:hover{background:#111827}
.met-n{font-family:var(--display);font-size:2.1rem;font-weight:900;color:var(--ocean-light);line-height:1;margin-bottom:6px}
.met-l{font-size:.8rem;color:#64748b;font-weight:500}

/* SECTIONS */
section{padding:84px 6%}
.stag{font-size:.74rem;font-weight:700;letter-spacing:.13em;text-transform:uppercase;color:var(--ocean);margin-bottom:12px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:26px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:56px;align-items:center}

/* HIW */
.hiw{background:var(--white)}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:34px;position:relative}
.steps::before{content:'';position:absolute;top:24px;left:calc(16.6% + 16px);right:calc(16.6% + 16px);height:1px;background:linear-gradient(90deg,var(--ocean-light),var(--seafoam));z-index:0}
.step{text-align:center;position:relative;z-index:1}
.step-n{width:48px;height:48px;border-radius:50%;margin:0 auto 16px;display:flex;align-items:center;justify-content:center;font-family:var(--display);font-size:1.1rem;font-weight:700;background:var(--white);border:2px solid var(--ocean);color:var(--ocean);box-shadow:0 0 0 6px var(--shell)}
.step h3{margin-bottom:7px}
.step p{font-size:.86rem}

/* FEAT CARDS */
.feats{background:var(--shell)}
.fc{background:var(--white);border:1px solid var(--border);border-radius:13px;padding:24px;transition:all .2s;position:relative;overflow:hidden}
.fc::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--ocean),var(--seafoam));transform:scaleX(0);transform-origin:left;transition:transform .25s}
.fc:hover{transform:translateY(-2px);box-shadow:0 10px 30px rgba(11,90,135,.09);border-color:var(--ocean-light)}
.fc:hover::before{transform:scaleX(1)}
.fi{width:40px;height:40px;border-radius:10px;background:var(--ocean-pale);display:flex;align-items:center;justify-content:center;font-size:18px;margin-bottom:13px}
.fc h3{margin-bottom:7px;font-size:.92rem}
.fc p{font-size:.83rem;line-height:1.6}

/* DEMO BAND */
.demo-b{background:linear-gradient(160deg,var(--ocean) 0%,#0d4f7a 100%);color:#fff;overflow:hidden;position:relative}
.demo-b::before{content:'';position:absolute;bottom:-70px;right:-70px;width:320px;height:320px;border-radius:50%;background:rgba(255,255,255,.04)}
.demo-b .stag{color:rgba(255,255,255,.55)}
.demo-b h2,.demo-b h4{color:#fff}
.demo-b p{color:rgba(255,255,255,.68)}
.dfl{display:flex;flex-direction:column;gap:17px}
.df{display:flex;gap:12px;align-items:flex-start}
.dfi{width:34px;height:34px;border-radius:8px;background:rgba(255,255,255,.11);display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0;margin-top:1px}
.dfh{font-size:.87rem;font-weight:600;margin-bottom:2px;color:#fff}
.dfp{font-size:.8rem;color:rgba(255,255,255,.6)}

/* BRAND SECTION */
.brand-s{background:var(--white)}
.up-box{border:2px dashed var(--border-strong);border-radius:13px;padding:26px;text-align:center;cursor:pointer;transition:all .15s;background:var(--shell);margin-bottom:13px}
.up-box:hover{border-color:var(--ocean);background:var(--ocean-pale)}
.bt{background:var(--shell);border:1px solid var(--border);border-radius:8px;padding:9px 13px}
.bt-l{font-size:.68rem;color:var(--ink-faint);font-weight:700;text-transform:uppercase;letter-spacing:.07em;margin-bottom:5px}

/* PRICING */
.pricing{background:var(--shell)}
.pg{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;max-width:880px;margin:0 auto}
.pc{background:var(--white);border:1px solid var(--border);border-radius:13px;padding:26px;position:relative}
.pc.feat{border-color:var(--ocean);box-shadow:0 0 0 3px rgba(11,90,135,.07)}
.pb{position:absolute;top:-10px;left:50%;transform:translateX(-50%);background:var(--ocean);color:#fff;font-size:.68rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:3px 11px;border-radius:100px;white-space:nowrap}
.ptier{font-size:.72rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--ocean);margin-bottom:9px}
.pamt{font-family:var(--display);font-size:1.9rem;font-weight:700;color:var(--ink);line-height:1;margin-bottom:4px}
.pamt span{font-size:.88rem;font-weight:400;color:var(--ink-muted)}
.pdesc{font-size:.82rem;color:var(--ink-muted);margin-bottom:18px;padding-bottom:18px;border-bottom:1px solid var(--border)}
.pfl{display:flex;flex-direction:column;gap:8px;margin-bottom:20px}
.pf{display:flex;gap:8px;font-size:.82rem;color:var(--ink-muted)}
.ck{color:var(--seafoam);font-weight:700;flex-shrink:0}
.btn-t{width:100%;padding:10px;border-radius:8px;font-size:.87rem;font-weight:600;font-family:var(--body);cursor:pointer;border:1.5px solid var(--ocean);color:var(--ocean);background:transparent;transition:all .15s}
.pc.feat .btn-t{background:var(--ocean);color:#fff}
.btn-t:hover{background:var(--ocean);color:#fff}

/* TESTI */
.tg{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
.tc{background:var(--shell);border:1px solid var(--border);border-radius:13px;padding:24px}
.tstars{color:var(--sand);margin-bottom:10px}
.tq{font-size:.88rem;color:var(--ink);line-height:1.65;margin-bottom:16px;font-style:italic}
.tau{display:flex;align-items:center;gap:10px}
.tav{width:36px;height:36px;border-radius:50%;background:var(--ocean-pale);display:flex;align-items:center;justify-content:center;font-size:16px}
.tn{font-weight:600;font-size:.84rem;color:var(--ink)}
.tr{font-size:.74rem;color:var(--ink-faint)}

/* CTA */
.cta{background:linear-gradient(135deg,var(--ink) 0%,#0f1d35 100%);padding:84px 6%;text-align:center;position:relative;overflow:hidden}
.cta::before{content:'🌴';font-size:210px;opacity:.04;position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);pointer-events:none;filter:grayscale(1)}
.cta h2{color:#fff;margin-bottom:13px}
.cta p{color:rgba(255,255,255,.58);max-width:460px;margin:0 auto 30px;font-size:.98rem}
.cta-bs{display:flex;gap:13px;justify-content:center;flex-wrap:wrap}
.btn-ow{background:transparent;color:rgba(255,255,255,.78);border:1.5px solid rgba(255,255,255,.28);padding:12px 22px;border-radius:10px;font-size:.94rem;font-weight:600;font-family:var(--body);cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:6px;transition:all .15s}
.btn-ow:hover{background:rgba(255,255,255,.1);border-color:rgba(255,255,255,.46)}

/* FOOTER */
footer{background:var(--ink);padding:44px 6%;display:grid;grid-template-columns:1.5fr 1fr 1fr 1fr;gap:34px;border-top:1px solid rgba(255,255,255,.06)}
.fb p{color:rgba(255,255,255,.33);font-size:.83rem;margin-top:11px;line-height:1.72}
.fcol h4{color:rgba(255,255,255,.68);font-size:.76rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:13px}
.fcol a{display:block;color:rgba(255,255,255,.33);text-decoration:none;font-size:.84rem;margin-bottom:8px;transition:color .15s}
.fcol a:hover{color:rgba(255,255,255,.72)}
.fbot{background:var(--ink);padding:16px 6%;border-top:1px solid rgba(255,255,255,.05);display:flex;justify-content:space-between;font-size:.78rem;color:rgba(255,255,255,.24)}

/* SCROLL ANIM */
.fu{opacity:0;transform:translateY(18px);transition:all .52s cubic-bezier(.22,.9,.36,1)}
.fu.vs{opacity:1;transform:translateY(0)}
.d1{transition-delay:.1s}.d2{transition-delay:.2s}.d3{transition-delay:.3s}

@media(max-width:880px){
  .hero{grid-template-columns:1fr;padding:96px 6% 52px}.hero::after{display:none}.hero-r{display:none}
  .grid2,.grid3,.steps,.met-row,.pg,.tg{grid-template-columns:1fr}
  .steps::before{display:none}.nav-links{display:none}
  footer{grid-template-columns:1fr 1fr}
}
</style>
</head>
<body>

<nav>
  <a href="/" class="logo">
    <div class="logo-mark">🌴</div>
    <div><div class="logo-text">Beach Habitats</div><span class="logo-sub">AI Concierge</span></div>
  </a>
  <div class="nav-links">
    <a href="#hiw">How It Works</a>
    <a href="#features">Features</a>
    <a href="#demo">Demo</a>
    <a href="#pricing">Pricing</a>
  </div>
  <div class="nav-sep"></div>
  <a href="/operator-dashboard" class="btn-ghost">Sign In</a>
  <a href="/onboarding-setup" class="btn-primary" style="margin-left:8px">Get Started →</a>
</nav>

<!-- HERO -->
<section class="hero">
  <div class="hero-l fu vs">
    <div class="eyebrow"><span class="e-dot"></span>Live on 30A · Gulf Coast · Florida</div>
    <h1><span class="grad-text">Your guests deserve a concierge, not a voicemail.</span></h1>
    <p class="hero-sub" style="margin-top:18px">Beach Habitats AI answers every question instantly — WiFi, door codes, local restaurants — at 2am, on check-in day, in any weather.</p>
    <div class="hero-btns">
      <a href="#demo" class="btn-primary btn-xl">See it in action</a>
      <a href="/onboarding-setup" class="btn-outline btn-xl">List your property →</a>
    </div>
    <div class="stats">
      <div><div class="stat-n">&lt;2s</div><div class="stat-l">avg response</div></div>
      <div><div class="stat-n">94%</div><div class="stat-l">no escalation needed</div></div>
      <div><div class="stat-n">24/7</div><div class="stat-l">always on</div></div>
    </div>
  </div>
  <div class="hero-r fu vs d2">
    <div class="phone">
      <div class="ph-hdr" style="background:linear-gradient(135deg,#0b5a87,#1279b5)">
        <div class="ph-av">🐚</div>
        <div>
          <div class="ph-name">Coral · Beach Habitats</div>
          <div class="ph-prop">134 Mystic Cobalt · 30A</div>
          <div class="ph-stat"><div class="s-dot"></div><span class="s-txt">Online · Checked in</span></div>
        </div>
      </div>
      <div class="ph-msgs" id="heroMsgs">
        <div class="msg b"><div class="bub">Welcome to 134 Mystic Cobalt! 🌊 I'm Coral. Ask me anything about your stay.</div><div class="mt">Now</div></div>
      </div>
      <div class="ph-inp">
        <input class="inp-f" id="heroIn" type="text" placeholder="Ask about WiFi, parking, checkout...">
        <button class="palm-b" onclick="voiceHero()" title="Voice">🌴</button>
        <button class="send-b" onclick="sendH()"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button>
      </div>
      <span class="ph-foot">✓ Responses from your actual guidebook</span>
    </div>
  </div>
</section>

<!-- METRICS -->
<div class="met">
  <div class="met-row">
    <div class="met-i fu"><div class="met-n">42</div><div class="met-l">Properties Live</div></div>
    <div class="met-i fu d1"><div class="met-n">12K+</div><div class="met-l">Guest Messages Handled</div></div>
    <div class="met-i fu d2"><div class="met-n">$0</div><div class="met-l">After-Hours Staff Cost</div></div>
    <div class="met-i fu d3"><div class="met-n">4.9★</div><div class="met-l">Average Guest Rating</div></div>
  </div>
</div>

<!-- HOW IT WORKS -->
<section class="hiw" id="hiw">
  <div style="text-align:center;max-width:520px;margin:0 auto 52px">
    <div class="stag fu">How It Works</div>
    <h2 class="fu d1">Set it up in 15 minutes. Let it run forever.</h2>
  </div>
  <div class="steps">
    <div class="step fu"><div class="step-n">1</div><h3>Upload your guidebook</h3><p>Connect Breezeway, Guesty, or Escapia — or paste your property info. We index and embed everything.</p></div>
    <div class="step fu d1"><div class="step-n">2</div><h3>Brand it as yours</h3><p>Upload your logo, set colors, name your concierge. Guests see your brand only.</p></div>
    <div class="step fu d2"><div class="step-n">3</div><h3>Send one link</h3><p>One SMS or email per booking. No app download, no account, no friction.</p></div>
  </div>
</section>

<!-- FEATURES -->
<section class="feats" id="features">
  <div class="stag fu">What's Included</div>
  <h2 class="fu d1" style="margin-bottom:10px">Everything your guests need.</h2>
  <p class="fu d2" style="margin-bottom:40px;max-width:500px">Built for short-term rentals — not a generic chatbot.</p>
  <div class="grid3">
    <div class="fc fu"><div class="fi">🧠</div><h3>Property-Specific Knowledge</h3><p>Door codes, WiFi, trash day — trained on your actual guidebook, not generic advice.</p></div>
    <div class="fc fu d1"><div class="fi">🍽️</div><h3>Dining Reservations</h3><p>Search local restaurants and book — right inside the chat.</p></div>
    <div class="fc fu d2"><div class="fi">🏖️</div><h3>Beach Conditions</h3><p>Real-time beach flag status for 30A guests. Red flag? Coral knows before they ask.</p></div>
    <div class="fc fu"><div class="fi">📱</div><h3>No App Required</h3><p>PWA-quality experience via one link. Works on every device, every browser.</p></div>
    <div class="fc fu d1"><div class="fi">🔀</div><h3>Smart Escalation</h3><p>When Coral can't answer, she routes to your team with full context.</p></div>
    <div class="fc fu d2"><div class="fi">📊</div><h3>Operator Analytics</h3><p>Top questions, escalation rates, quality scores — per property, per operator.</p></div>
    <div class="fc fu"><div class="fi">🌐</div><h3>Multi-PMS Integration</h3><p>Native connectors for Escapia, Guesty, Breezeway. Auto-synced data.</p></div>
    <div class="fc fu d1"><div class="fi">🎨</div><h3>White-Label Branding</h3><p>Your logo, colors, concierge persona. Guests see your brand, not ours.</p></div>
    <div class="fc fu d2"><div class="fi">🔐</div><h3>Token-Gated Access</h3><p>Unique, expiring link per guest. No passwords, no accounts.</p></div>
  </div>
</section>

<!-- LIVE DEMO -->
<section class="demo-b" id="demo">
  <div class="grid2">
    <div>
      <div class="stag fu">Interactive Demo</div>
      <h2 class="fu d1">Talk to Coral. Right now.</h2>
      <p class="fu d1" style="margin-bottom:24px;max-width:400px">Real concierge, sample property. Ask about WiFi, check-out, parking, restaurants. No account needed.</p>
      <div class="dfl fu d2">
        <div class="df"><div class="dfi">⚡</div><div><div class="dfh">Sub-2 second responses</div><div class="dfp">Groq-powered. No spinners.</div></div></div>
        <div class="df"><div class="dfi">📚</div><div><div class="dfh">Real guidebook knowledge</div><div class="dfp">42 Breezeway guides indexed.</div></div></div>
        <div class="df"><div class="dfi">🌴</div><div><div class="dfh">Voice via the palm tree</div><div class="dfp">Tap 🌴 for hands-free input.</div></div></div>
      </div>
    </div>
    <div class="fu d2">
      <div class="phone">
        <div class="ph-hdr" style="background:linear-gradient(135deg,#0b5a87,#0d9488)">
          <div class="ph-av">🐚</div>
          <div>
            <div class="ph-name">Coral · Demo Property</div>
            <div class="ph-prop">Watercolor · 30A, Florida</div>
            <div class="ph-stat"><div class="s-dot"></div><span class="s-txt">Demo mode · Ask anything</span></div>
          </div>
        </div>
        <div class="ph-msgs" id="demoMsgs">
          <div class="msg b"><div class="bub">Hey! 🐚 Try asking about WiFi, check-out, parking, or local restaurants!</div></div>
        </div>
        <div class="ph-inp">
          <input class="inp-f" id="demoIn" type="text" placeholder="What's the WiFi password?">
          <button class="palm-b" title="Voice">🌴</button>
          <button class="send-b" onclick="sendD()"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button>
        </div>
        <span class="ph-foot">✓ Connected to Beach Habitats knowledge base</span>
      </div>
    </div>
  </div>
</section>

<!-- BRANDING -->
<section class="brand-s" id="branding">
  <div class="grid2">
    <div class="fu">
      <div class="stag">White-Label Ready</div>
      <h2 style="margin-bottom:13px">Your brand. Your concierge.</h2>
      <p style="margin-bottom:26px">Guests never see "Beach Habitats." Upload your logo — it propagates to the guest interface, dashboard, and all notifications instantly.</p>
      <div class="up-box">
        <div style="font-size:26px;margin-bottom:9px">🖼️</div>
        <div style="font-weight:600;color:var(--ink);font-size:.9rem;margin-bottom:3px">Drop your logo here</div>
        <div style="font-size:.8rem;color:var(--ink-muted)">PNG, SVG, or JPG · Auto-applies everywhere</div>
      </div>
      <div style="display:flex;gap:10px">
        <div class="bt" style="flex:1"><div class="bt-l">Brand Color</div><div style="display:flex;gap:7px;align-items:center"><div style="width:22px;height:22px;border-radius:5px;background:var(--ocean);border:1px solid var(--border)"></div><span style="font-family:var(--mono);font-size:.8rem;color:var(--ink)">#0b5a87</span></div></div>
        <div class="bt" style="flex:1"><div class="bt-l">Concierge Name</div><span style="font-family:var(--mono);font-size:.8rem;color:var(--ink)">Coral 🐚</span></div>
      </div>
    </div>
    <div class="fu d2" style="display:flex;justify-content:center">
      <div style="transform:rotate(-4deg);z-index:1;position:relative">
        <div class="phone" style="width:210px;box-shadow:0 18px 44px rgba(11,90,135,.14)">
          <div class="ph-hdr" style="background:linear-gradient(135deg,#0b5a87,#1279b5);padding:12px"><div style="display:flex;align-items:center;gap:7px"><span>🌴</span><span style="color:#fff;font-weight:700;font-size:.8rem">Beach Habitats</span></div></div>
          <div style="padding:9px;background:#f8fafc">
            <div style="background:#fff;border:1px solid var(--border);border-radius:9px;padding:7px;font-size:.72rem;color:var(--ink-muted);margin-bottom:6px">What time is check-out?</div>
            <div style="background:var(--ocean);color:#fff;border-radius:9px;padding:7px;font-size:.72rem;margin-left:12px">Check-out is 10am! 🏖️</div>
          </div>
        </div>
      </div>
      <div style="transform:rotate(3deg);margin-left:-22px;margin-top:20px;position:relative;z-index:2">
        <div class="phone" style="width:210px;box-shadow:0 18px 44px rgba(0,0,0,.11)">
          <div class="ph-hdr" style="background:linear-gradient(135deg,#1a2e4a,#2d4a6b);padding:12px"><div style="display:flex;align-items:center;gap:7px"><span>🏡</span><span style="color:#fff;font-weight:700;font-size:.8rem">Coastal Stays</span></div></div>
          <div style="padding:9px;background:#f8fafc">
            <div style="background:#fff;border:1px solid var(--border);border-radius:9px;padding:7px;font-size:.72rem;color:var(--ink-muted);margin-bottom:6px">WiFi password?</div>
            <div style="background:#1a2e4a;color:#fff;border-radius:9px;padding:7px;font-size:.72rem;margin-left:12px">WiFi: CoastalGuest<br>Pass: Sunset2024! 📶</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- PRICING -->
<section class="pricing" id="pricing">
  <div style="text-align:center;max-width:500px;margin:0 auto 44px">
    <div class="stag fu">Simple Pricing</div>
    <h2 class="fu d1">Pay per property. Not per message.</h2>
    <p class="fu d2">Flat monthly rate. No usage fees. No per-conversation billing.</p>
  </div>
  <div class="pg">
    <div class="pc fu">
      <div class="ptier">Starter</div>
      <div class="pamt">$29<span>/mo per property</span></div>
      <p class="pdesc">Independent hosts managing a handful of units.</p>
      <div class="pfl"><div class="pf"><span class="ck">✓</span>Up to 5 properties</div><div class="pf"><span class="ck">✓</span>Unlimited guest messages</div><div class="pf"><span class="ck">✓</span>Logo + color branding</div><div class="pf"><span class="ck">✓</span>Knowledge indexing</div><div class="pf"><span class="ck">✓</span>Email escalation</div></div>
      <button class="btn-t">Get Started</button>
    </div>
    <div class="pc feat fu d1">
      <div class="pb">Most Popular</div>
      <div class="ptier">Professional</div>
      <div class="pamt">$19<span>/mo per property</span></div>
      <p class="pdesc">PMCs managing 6–50 properties needing analytics and integrations.</p>
      <div class="pfl"><div class="pf"><span class="ck">✓</span>Unlimited properties</div><div class="pf"><span class="ck">✓</span>Full white-label branding</div><div class="pf"><span class="ck">✓</span>PMS integration (Escapia, Guesty)</div><div class="pf"><span class="ck">✓</span>Dining reservation tool</div><div class="pf"><span class="ck">✓</span>Analytics dashboard</div><div class="pf"><span class="ck">✓</span>SMS + email escalation</div></div>
      <button class="btn-t">Start Free Trial</button>
    </div>
    <div class="pc fu d2">
      <div class="ptier">Enterprise</div>
      <div class="pamt">Custom</div>
      <p class="pdesc">50+ properties, custom integrations, SLA guarantees.</p>
      <div class="pfl"><div class="pf"><span class="ck">✓</span>Everything in Professional</div><div class="pf"><span class="ck">✓</span>Custom PMS connectors</div><div class="pf"><span class="ck">✓</span>SLA guarantee (99.9%)</div><div class="pf"><span class="ck">✓</span>White-glove onboarding</div><div class="pf"><span class="ck">✓</span>Custom concierge persona</div></div>
      <button class="btn-t">Contact Sales</button>
    </div>
  </div>
</section>

<!-- TESTIMONIALS -->
<section style="background:var(--white);padding:84px 6%">
  <div style="text-align:center;max-width:460px;margin:0 auto 44px">
    <div class="stag fu">From Operators</div>
    <h2 class="fu d1">They stopped answering texts at midnight.</h2>
  </div>
  <div class="tg">
    <div class="tc fu"><div class="tstars">★★★★★</div><p class="tq">"Check-in weekend used to mean 80 texts before noon. Last Labor Day our team got zero. Coral handled everything."</p><div class="tau"><div class="tav">🏠</div><div><div class="tn">Sarah M.</div><div class="tr">PMC Owner · 18 Properties · 30A</div></div></div></div>
    <div class="tc fu d1"><div class="tstars">★★★★★</div><p class="tq">"We sell premium gulf-front stays. A branded AI concierge on day one feels like a 5-star hotel. Our reviews jumped a full point."</p><div class="tau"><div class="tav">🌊</div><div><div class="tn">Marcus T.</div><div class="tr">Luxury Rental Manager · Destin</div></div></div></div>
    <div class="tc fu d2"><div class="tstars">★★★★★</div><p class="tq">"The analytics alone are worth it. I know exactly which properties have knowledge gaps and where our guides need updating."</p><div class="tau"><div class="tav">📊</div><div><div class="tn">Jennifer R.</div><div class="tr">Operations Director · 31 Properties</div></div></div></div>
  </div>
</section>

<!-- CTA -->
<section class="cta">
  <div class="stag fu">Ready?</div>
  <h2 class="fu d1">Your first property is live in 15 minutes.</h2>
  <p class="fu d2">No credit card for 30 days. No contract. Cancel anytime.</p>
  <div class="cta-bs fu d3">
    <a href="/onboarding-setup" class="btn-primary btn-xl">Start Free Trial →</a>
    <a href="#demo" class="btn-ow btn-xl">Watch the demo</a>
  </div>
</section>

<footer>
  <div class="fb">
    <a href="/" class="logo"><div class="logo-mark">🌴</div><div style="margin-left:9px"><div class="logo-text" style="color:#fff">Beach Habitats</div><span class="logo-sub">AI Concierge Platform</span></div></a>
    <p>Making vacation rental management effortless — for operators and guests alike.</p>
  </div>
  <div class="fcol"><h4>Product</h4><a href="#features">Features</a><a href="#pricing">Pricing</a><a href="#demo">Demo</a><a href="/operator-dashboard">Dashboard</a></div>
  <div class="fcol"><h4>Platform</h4><a href="/onboarding-setup">Get Started</a><a href="#">API Docs</a><a href="#">Integrations</a><a href="#">Status</a></div>
  <div class="fcol"><h4>Company</h4><a href="#">About</a><a href="#">Contact</a><a href="#">Privacy</a><a href="#">Terms</a></div>
</footer>
<div class="fbot"><span>© 2025 Beach Habitats AI Concierge. Built for 30A and beyond.</span><span>Made with 🌊 on the Gulf Coast</span></div>

<script>
// Scroll
const obs=new IntersectionObserver(e=>e.forEach(x=>{if(x.isIntersecting)x.target.classList.add('vs')}),{threshold:.1});
document.querySelectorAll('.fu:not(.vs)').forEach(el=>obs.observe(el));

// Responses
const R={
  wifi:["WiFi: **GulfBreeze_5G** · Password: **BeachLife2024** 📶"],
  password:["WiFi network: **GulfBreeze_5G** · Password: **BeachLife2024** — no spaces! 🔐"],
  checkout:["Check-out is **10:00 AM** 🌅 Need late check-out? I'll check with the team!"],
  "check-out":["Check-out is **10:00 AM** 🌅"],
  parking:["You have **2 dedicated spots** in the carport — labeled 134A and 134B. 🚗"],
  door:["Door code: **#4821** — works front and back. Expires at check-out! 🔑"],
  code:["Your door code is **#4821** 🔑 Let me know if you have any issues!"],
  restaurant:["Great picks nearby! Bud & Alley's in Seaside (book ahead!), Café Thirty-A for sunsets, George's at Alys Beach for casual. Want me to check availability? 🍽️"],
  pool:["Heated pool: **7am–10pm**, set to 84°F. Towels in the bin by the back door! 🏊"],
  beach:["Beach access: **3 min walk** south on Cobalt Ct — look for the public access path. Chairs + umbrella in the garage! 🏖️"],
  trash:["Trash pickup: **Tuesday morning** — bins out Monday night, left side of driveway. ♻️"],
  hello:["Welcome! I'm Coral 🐚 I can help with WiFi, door codes, parking, check-out, restaurants, pool, and more!"],
  hi:["Hey! 🌊 I'm Coral, your concierge. What do you need?"]
};

function resp(i){
  const m=i.toLowerCase();
  for(const[k,v]of Object.entries(R)){if(m.includes(k))return v[0];}
  return"Let me check your property guide... That might need the team. I can connect you or keep looking — what do you prefer? 🐚";
}
function addMsg(c,t,u){
  const el=document.getElementById(c);
  const d=document.createElement('div');d.className='msg '+(u?'u':'b');
  const b=document.createElement('div');b.className='bub';
  b.innerHTML=t.replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>');
  d.appendChild(b);
  if(u){const mt=document.createElement('div');mt.className='mt';mt.textContent='Now';d.appendChild(mt);}
  el.appendChild(d);el.scrollTop=el.scrollHeight;
}
function showTyp(c){
  const el=document.getElementById(c);
  const d=document.createElement('div');d.className='msg b';d.id='tp_'+c;
  d.innerHTML='<div class="typ"><div class="td"></div><div class="td"></div><div class="td"></div></div>';
  el.appendChild(d);el.scrollTop=el.scrollHeight;
}
function hideTyp(c){const e=document.getElementById('tp_'+c);if(e)e.remove();}
function fire(ii,mc){
  const inp=document.getElementById(ii);const txt=inp.value.trim();if(!txt)return;
  addMsg(mc,txt,true);inp.value='';showTyp(mc);
  setTimeout(()=>{hideTyp(mc);addMsg(mc,resp(txt),false);},750+Math.random()*450);
}
function sendH(){fire('heroIn','heroMsgs');}
function sendD(){fire('demoIn','demoMsgs');}
function voiceHero(){
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){alert('Voice requires Chrome/Edge — try typing!');return;}
  const r=new SR();r.lang='en-US';
  r.onresult=e=>{document.getElementById('heroIn').value=e.results[0][0].transcript;sendH();};
  r.start();
}
document.getElementById('heroIn').onkeydown=e=>{if(e.key==='Enter')sendH();};
document.getElementById('demoIn').onkeydown=e=>{if(e.key==='Enter')sendD();};
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
async def landing_page():
    return HTMLResponse(content=LANDING_HTML)


@router.get("/home", response_class=HTMLResponse)
async def landing_home():
    return HTMLResponse(content=LANDING_HTML)
