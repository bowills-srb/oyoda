"""
Beach Habitats — Public Landing Page

Served at GET /

Purpose:
- Demo surface for prospective operators
- "Try it now" interactive concierge preview (no real session needed)
- Direct CTA to operator onboarding and dashboard

Design: Tailwind via CDN. Clean, coastal. Dark header, light body.
No build step, no React, ships immediately.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(tags=["Landing"])


class DemoChatRequest(BaseModel):
    message: str


class DemoChatResponse(BaseModel):
    response: str
    source: str


def _build_landing_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Beach Habitats — AI Concierge for Short-Term Rentals</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/alpinejs/3.13.5/cdn.min.js" defer></script>
<style>
  :root {
    --ocean-deep: #0c4a6e;
    --ocean-mid:  #0369a1;
    --ocean-sky:  #0ea5e9;
    --ocean-light:#e0f2fe;
    --sand:       #fef9f0;
    --text:       #0f172a;
    --text-muted: #64748b;
    --border:     #e2e8f0;
    --white:      #ffffff;
    --green:      #16a34a;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html { scroll-behavior: smooth; }
  body { font-family: 'Inter', -apple-system, sans-serif; color: var(--text); background: var(--white); line-height: 1.6; }

  /* ── NAV ── */
  nav {
    position: sticky; top: 0; z-index: 50;
    background: rgba(12,74,110,.97); backdrop-filter: blur(12px);
    border-bottom: 1px solid rgba(255,255,255,.08);
    padding: 0 24px; height: 60px;
    display: flex; align-items: center; justify-content: space-between;
  }
  .nav-logo { display: flex; align-items: center; gap: 10px; text-decoration: none; }
  .nav-logo-mark { width: 32px; height: 32px; border-radius: 8px; background: linear-gradient(135deg,#38bdf8,#0ea5e9); display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 13px; color: #fff; }
  .nav-logo-name { color: #fff; font-weight: 700; font-size: 16px; letter-spacing: -.02em; }
  .nav-links { display: flex; align-items: center; gap: 8px; }
  .nav-link { color: rgba(255,255,255,.7); text-decoration: none; font-size: 14px; font-weight: 450; padding: 6px 12px; border-radius: 6px; transition: all .15s; }
  .nav-link:hover { color: #fff; background: rgba(255,255,255,.08); }
  .nav-cta { background: var(--ocean-sky); color: #fff; padding: 8px 18px; border-radius: 8px; font-size: 14px; font-weight: 600; text-decoration: none; transition: background .15s; }
  .nav-cta:hover { background: #38bdf8; }

  /* ── HERO ── */
  .hero {
    background: linear-gradient(160deg, var(--ocean-deep) 0%, var(--ocean-mid) 55%, #075985 100%);
    padding: 100px 24px 80px;
    text-align: center; position: relative; overflow: hidden;
  }
  .hero::before {
    content: '';
    position: absolute; inset: 0;
    background: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.03'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
  }
  .hero-eyebrow {
    display: inline-flex; align-items: center; gap: 6px;
    background: rgba(56,189,248,.15); border: 1px solid rgba(56,189,248,.3);
    color: #7dd3fc; padding: 5px 14px; border-radius: 20px;
    font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em;
    margin-bottom: 24px;
  }
  .hero-title {
    font-size: clamp(36px, 6vw, 68px); font-weight: 800;
    color: #fff; letter-spacing: -.03em; line-height: 1.1;
    max-width: 900px; margin: 0 auto 20px;
  }
  .hero-title em { font-style: normal; color: #7dd3fc; }
  .hero-sub {
    font-size: clamp(16px, 2.5vw, 20px); color: rgba(255,255,255,.75);
    max-width: 620px; margin: 0 auto 40px; font-weight: 400;
  }
  .hero-actions { display: flex; gap: 14px; justify-content: center; flex-wrap: wrap; }
  .btn-primary-lg {
    background: linear-gradient(135deg, #0ea5e9, #0284c7);
    color: #fff; padding: 15px 32px; border-radius: 12px;
    font-size: 16px; font-weight: 700; text-decoration: none;
    display: inline-flex; align-items: center; gap: 8px;
    box-shadow: 0 4px 20px rgba(14,165,233,.4);
    transition: all .2s;
  }
  .btn-primary-lg:hover { transform: translateY(-2px); box-shadow: 0 8px 28px rgba(14,165,233,.5); }
  .btn-ghost-lg {
    background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.25);
    color: #fff; padding: 15px 32px; border-radius: 12px;
    font-size: 16px; font-weight: 600; text-decoration: none;
    display: inline-flex; align-items: center; gap: 8px;
    transition: all .15s;
  }
  .btn-ghost-lg:hover { background: rgba(255,255,255,.18); }
  .hero-stat-row {
    display: flex; gap: 40px; justify-content: center; flex-wrap: wrap;
    margin-top: 64px; padding-top: 48px;
    border-top: 1px solid rgba(255,255,255,.1);
  }
  .hero-stat { text-align: center; }
  .hero-stat-value { font-size: 36px; font-weight: 800; color: #fff; letter-spacing: -.03em; }
  .hero-stat-label { font-size: 13px; color: rgba(255,255,255,.6); margin-top: 3px; }

  /* ── DEMO SECTION ── */
  .demo-section {
    background: var(--ocean-light);
    padding: 80px 24px;
  }
  .section-label {
    font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .1em;
    color: var(--ocean-sky); margin-bottom: 10px; text-align: center;
  }
  .section-title {
    font-size: clamp(28px, 4vw, 42px); font-weight: 800;
    letter-spacing: -.02em; text-align: center; color: var(--text); margin-bottom: 12px;
  }
  .section-sub {
    font-size: 17px; color: var(--text-muted); text-align: center;
    max-width: 520px; margin: 0 auto 48px;
  }
  .demo-wrapper {
    max-width: 420px; margin: 0 auto;
    background: #fff;
    border-radius: 28px;
    overflow: hidden;
    box-shadow: 0 24px 80px rgba(0,0,0,.14), 0 0 0 1px rgba(0,0,0,.04);
  }
  .demo-header {
    background: linear-gradient(135deg, var(--ocean-deep) 0%, var(--ocean-mid) 100%);
    padding: 20px;
  }
  .demo-header-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
  .demo-logo-text { color: #fff; font-weight: 700; font-size: 15px; }
  .demo-badge { background: rgba(255,255,255,.2); color: #fff; padding: 4px 12px; border-radius: 16px; font-size: 12px; font-weight: 500; }
  .demo-prop { color: rgba(255,255,255,.8); font-size: 12px; margin-bottom: 3px; }
  .demo-prop-name { color: #fff; font-size: 19px; font-weight: 700; }
  .demo-messages { padding: 16px; min-height: 280px; display: flex; flex-direction: column; gap: 10px; max-height: 340px; overflow-y: auto; }
  .demo-msg { max-width: 85%; padding: 11px 14px; border-radius: 16px; font-size: 14px; line-height: 1.5; animation: slideUp .25s ease; }
  @keyframes slideUp { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }
  .demo-msg.assistant { background: #f8fafc; border: 1px solid #e2e8f0; align-self: flex-start; border-bottom-left-radius: 4px; }
  .demo-msg.user { background: linear-gradient(135deg, var(--ocean-sky), var(--ocean-deep)); color: #fff; align-self: flex-end; border-bottom-right-radius: 4px; }
  .demo-typing { display: flex; gap: 5px; padding: 13px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 16px; border-bottom-left-radius: 4px; align-self: flex-start; }
  .demo-typing span { width: 7px; height: 7px; background: var(--ocean-sky); border-radius: 50%; animation: bounce 1.4s infinite; }
  .demo-typing span:nth-child(2) { animation-delay: .2s; }
  .demo-typing span:nth-child(3) { animation-delay: .4s; }
  @keyframes bounce { 0%,60%,100% { transform:translateY(0); } 30% { transform:translateY(-6px); } }
  .demo-quick-actions { padding: 0 14px 10px; display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; }
  .demo-quick-actions::-webkit-scrollbar { display: none; }
  .demo-quick-btn { flex-shrink: 0; background: #fff; border: 2px solid #e2e8f0; padding: 7px 13px; border-radius: 20px; font-size: 12.5px; font-weight: 500; color: #334155; cursor: pointer; font-family: inherit; transition: border-color .15s; }
  .demo-quick-btn:hover, .demo-quick-btn:focus { border-color: var(--ocean-sky); outline: none; }
  .demo-input-area { border-top: 1px solid #e2e8f0; padding: 12px 14px; display: flex; gap: 8px; align-items: center; background: #fff; }
  .demo-input { flex: 1; padding: 10px 14px; border: 2px solid #e2e8f0; border-radius: 20px; font-size: 14px; font-family: inherit; outline: none; }
  .demo-input:focus { border-color: var(--ocean-sky); }
  .demo-send-btn { width: 40px; height: 40px; border-radius: 50%; border: none; background: linear-gradient(135deg, var(--ocean-sky), var(--ocean-deep)); color: #fff; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
  .demo-send-btn svg { width: 16px; height: 16px; }
  .demo-note { text-align: center; font-size: 12px; color: var(--text-muted); padding: 12px; background: #f8fafc; border-top: 1px solid #e2e8f0; }

  /* ── HOW IT WORKS ── */
  .how-section { padding: 80px 24px; background: #fff; }
  .steps-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 32px; max-width: 1000px; margin: 0 auto; }
  .step-card { padding: 28px; border-radius: 16px; border: 1px solid var(--border); background: #fff; transition: box-shadow .2s; }
  .step-card:hover { box-shadow: 0 8px 32px rgba(0,0,0,.08); }
  .step-num { width: 40px; height: 40px; border-radius: 12px; background: var(--ocean-light); color: var(--ocean-sky); font-weight: 800; font-size: 18px; display: flex; align-items: center; justify-content: center; margin-bottom: 16px; }
  .step-title { font-size: 17px; font-weight: 700; margin-bottom: 8px; }
  .step-body { font-size: 14px; color: var(--text-muted); line-height: 1.65; }

  /* ── FEATURES ── */
  .features-section { padding: 80px 24px; background: var(--sand); }
  .features-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; max-width: 1040px; margin: 0 auto; }
  .feature-card { padding: 24px; border-radius: 14px; background: #fff; border: 1px solid var(--border); }
  .feature-icon { font-size: 28px; margin-bottom: 12px; }
  .feature-title { font-size: 16px; font-weight: 700; margin-bottom: 6px; }
  .feature-body { font-size: 13.5px; color: var(--text-muted); line-height: 1.6; }

  /* ── CTA BANNER ── */
  .cta-section {
    background: linear-gradient(135deg, var(--ocean-deep) 0%, #0369a1 100%);
    padding: 80px 24px; text-align: center;
  }
  .cta-title { font-size: clamp(28px, 4vw, 44px); font-weight: 800; color: #fff; letter-spacing: -.02em; margin-bottom: 14px; }
  .cta-sub { font-size: 18px; color: rgba(255,255,255,.75); max-width: 500px; margin: 0 auto 36px; }

  /* ── FOOTER ── */
  footer {
    background: #0a0f1a; padding: 32px 24px;
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;
  }
  .footer-logo { color: rgba(255,255,255,.7); font-size: 14px; }
  .footer-links { display: flex; gap: 24px; }
  .footer-link { color: rgba(255,255,255,.4); font-size: 13px; text-decoration: none; }
  .footer-link:hover { color: rgba(255,255,255,.7); }

  /* ── RESPONSIVE ── */
  @media (max-width: 600px) {
    .nav-links .nav-link { display: none; }
    .hero { padding: 72px 20px 60px; }
    .hero-stat-row { gap: 28px; }
    footer { flex-direction: column; text-align: center; }
  }
</style>
</head>
<body>

<!-- NAV -->
<nav>
  <a href="/" class="nav-logo">
    <div class="nav-logo-mark">🐚</div>
    <span class="nav-logo-name">Beach Habitats</span>
  </a>
  <div class="nav-links">
    <a href="#how-it-works" class="nav-link">How it works</a>
    <a href="#features" class="nav-link">Features</a>
    <a href="/operator-dashboard" class="nav-link">Dashboard</a>
    <a href="/onboarding-setup" class="nav-cta">Get Started</a>
  </div>
</nav>

<!-- HERO -->
<section class="hero">
  <div class="hero-eyebrow">
    <span>🌊</span> AI Concierge for 30A Vacation Rentals
  </div>
  <h1 class="hero-title">
    Your guests get answers<br>at <em>2am</em>.<br>You get zero phone calls.
  </h1>
  <p class="hero-sub">
    Coral, your AI concierge, handles WiFi passwords, door codes, restaurant recs,
    and local tips — 24/7 — so your team doesn't have to.
  </p>
  <div class="hero-actions">
    <a href="#demo" class="btn-primary-lg">
      ✨ Try Coral Now
    </a>
    <a href="/onboarding-setup" class="btn-ghost-lg">
      🚀 Set Up Your Property →
    </a>
  </div>
  <div class="hero-stat-row">
    <div class="hero-stat">
      <div class="hero-stat-value">&lt;200ms</div>
      <div class="hero-stat-label">Avg response time</div>
    </div>
    <div class="hero-stat">
      <div class="hero-stat-value">60%</div>
      <div class="hero-stat-label">Queries answered instantly<br>without any AI call</div>
    </div>
    <div class="hero-stat">
      <div class="hero-stat-value">24/7</div>
      <div class="hero-stat-label">Always available</div>
    </div>
    <div class="hero-stat">
      <div class="hero-stat-value">~$0.02</div>
      <div class="hero-stat-label">Per conversation</div>
    </div>
  </div>
</section>

<!-- DEMO -->
<section class="demo-section" id="demo" x-data="demoChat()">
  <div class="section-label">Live Demo</div>
  <h2 class="section-title">Talk to Coral right now</h2>
  <p class="section-sub">
    No sign-up. No token. This is the actual AI your guests will use.
  </p>

  <div class="demo-wrapper">
    <div class="demo-header">
      <div class="demo-header-row">
        <span class="demo-logo-text">🐚 Beach Habitats</span>
        <span class="demo-badge">Coral</span>
      </div>
      <div class="demo-prop">Demo Property</div>
      <div class="demo-prop-name">Seaside Escape · 30A</div>
    </div>

    <div class="demo-messages" id="demo-messages">
      <div class="demo-msg assistant">
        Hey there! 🐚 I'm Coral, your Beach Habitats concierge for <strong>Seaside Escape</strong>.<br><br>
        Ask me anything — WiFi, door code, restaurants, beach tips, or whatever you need!
      </div>
    </div>

    <div class="demo-quick-actions">
      <button class="demo-quick-btn" @click="sendQuick('What is the WiFi password?')">📶 WiFi</button>
      <button class="demo-quick-btn" @click="sendQuick('What is the door code?')">🔑 Door Code</button>
      <button class="demo-quick-btn" @click="sendQuick('Best seafood restaurants nearby?')">🍽️ Restaurants</button>
      <button class="demo-quick-btn" @click="sendQuick('Beach chair rentals?')">🏖️ Beach Chairs</button>
      <button class="demo-quick-btn" @click="sendQuick('What time is checkout?')">⏰ Checkout</button>
    </div>

    <div class="demo-input-area">
      <input
        class="demo-input"
        type="text"
        placeholder="Ask Coral anything…"
        x-model="inputText"
        @keypress.enter="sendMessage()"
        :disabled="isLoading"
      >
      <button class="demo-send-btn" @click="sendMessage()" :disabled="isLoading">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M22 2L11 13M22 2L15 22L11 13L2 9L22 2Z"/>
        </svg>
      </button>
    </div>
    <div class="demo-note">This is a live AI — responses powered by your actual concierge engine</div>
  </div>
</section>

<!-- HOW IT WORKS -->
<section class="how-section" id="how-it-works">
  <div class="section-label">Process</div>
  <h2 class="section-title">Up and running in minutes</h2>
  <p class="section-sub">No technical knowledge required. We handle the setup.</p>

  <div class="steps-grid">
    <div class="step-card">
      <div class="step-num">1</div>
      <div class="step-title">Add your property</div>
      <div class="step-body">Enter your WiFi, door code, check-in/out times, and any house rules. Takes about 5 minutes.</div>
    </div>
    <div class="step-card">
      <div class="step-num">2</div>
      <div class="step-title">We index your knowledge</div>
      <div class="step-body">Coral learns your property from guidebooks, Breezeway profiles, and your custom notes — all searchable in real-time.</div>
    </div>
    <div class="step-card">
      <div class="step-num">3</div>
      <div class="step-title">Create a guest session</div>
      <div class="step-body">Add a reservation in the operator dashboard. A personalized link generates instantly.</div>
    </div>
    <div class="step-card">
      <div class="step-num">4</div>
      <div class="step-title">Send the link via SMS</div>
      <div class="step-body">One click sends your guest a welcome text. They open a mobile-native chat — no app download needed.</div>
    </div>
    <div class="step-card">
      <div class="step-num">5</div>
      <div class="step-title">Coral handles the rest</div>
      <div class="step-body">Coral answers questions 24/7. Real emergencies get escalated to you immediately with context and priority.</div>
    </div>
    <div class="step-card">
      <div class="step-num">6</div>
      <div class="step-title">You see everything</div>
      <div class="step-body">The operator dashboard shows every conversation, escalation, knowledge gap, and analytics at a glance.</div>
    </div>
  </div>
</section>

<!-- FEATURES -->
<section class="features-section" id="features">
  <div class="section-label">Capabilities</div>
  <h2 class="section-title">Everything a concierge should do</h2>
  <p class="section-sub">Built specifically for 30A short-term rental operators.</p>

  <div class="features-grid">
    <div class="feature-card">
      <div class="feature-icon">⚡</div>
      <div class="feature-title">Instant answers, zero LLM cost</div>
      <div class="feature-body">WiFi, door codes, check-in/out times are answered from templates in milliseconds — no AI token cost at all.</div>
    </div>
    <div class="feature-card">
      <div class="feature-icon">🧠</div>
      <div class="feature-title">Deep property knowledge</div>
      <div class="feature-body">249+ indexed guidebook chunks. Coral knows your property rules, amenities, beach access, and parking before your guest asks.</div>
    </div>
    <div class="feature-card">
      <div class="feature-icon">🏖️</div>
      <div class="feature-title">Local area expertise</div>
      <div class="feature-body">Restaurant recommendations, beach chair rentals, fishing charters, groceries, urgent care — all from real 30A data.</div>
    </div>
    <div class="feature-card">
      <div class="feature-icon">🚨</div>
      <div class="feature-title">Smart escalation</div>
      <div class="feature-body">Emergencies, maintenance issues, and frustrated guests are detected instantly and escalated to your team with full context.</div>
    </div>
    <div class="feature-card">
      <div class="feature-icon">🎨</div>
      <div class="feature-title">Your brand, not ours</div>
      <div class="feature-body">Custom concierge name, logo, colors, and persona. Guests see your brand, not "Beach Habitats AI."</div>
    </div>
    <div class="feature-card">
      <div class="feature-icon">📊</div>
      <div class="feature-title">Operator analytics</div>
      <div class="feature-body">Track response times, quick-answer rates, guest intents, knowledge gaps, and escalation SLAs — all in one dashboard.</div>
    </div>
    <div class="feature-card">
      <div class="feature-icon">📱</div>
      <div class="feature-title">No app download</div>
      <div class="feature-body">Guests get a personalized SMS link. One tap opens a mobile-native web chat — works on any phone, any browser.</div>
    </div>
    <div class="feature-card">
      <div class="feature-icon">🔁</div>
      <div class="feature-title">Learns from gaps</div>
      <div class="feature-body">Every unanswered question becomes a knowledge gap in your dashboard. Approve an answer once and Coral knows it forever.</div>
    </div>
  </div>
</section>

<!-- CTA -->
<section class="cta-section">
  <h2 class="cta-title">Ready to stop answering texts at midnight?</h2>
  <p class="cta-sub">Set up your first property in under 10 minutes. No credit card required.</p>
  <a href="/onboarding-setup" class="btn-primary-lg" style="font-size:18px;padding:18px 40px">
    🐚 Set Up My Concierge
  </a>
</section>

<!-- FOOTER -->
<footer>
  <span class="footer-logo">🐚 Beach Habitats — 30A, Florida</span>
  <div class="footer-links">
    <a href="/operator-dashboard" class="footer-link">Dashboard</a>
    <a href="/onboarding-setup" class="footer-link">Get Started</a>
    <a href="/docs" class="footer-link">API Docs</a>
  </div>
</footer>

<script>
function demoChat() {
  return {
    inputText: '',
    isLoading: false,
    messageCount: 0,

    // Demo knowledge base — answers common questions without hitting the server
    // For a real demo session, swap these for an actual /api/v1/mobile/{token}/chat call
    demoKnowledge: {
      wifi: { triggers: ['wifi','wi-fi','internet','password','network'], response: "📶 <strong>WiFi Network:</strong> SeaEscape_5G<br><strong>Password:</strong> BeachLife2024!<br><br>Connects up to 12 devices. Let me know if you have any trouble!" },
      door: { triggers: ['door','code','access','get in','lock','key'], response: "🔑 Your door code is <strong>7749#</strong><br><br>Enter it on the keypad to the right of the front door. The lock will beep twice and the light turns green. Works 24/7 throughout your stay!" },
      checkout: { triggers: ['checkout','check out','check-out','leave','depart'], response: "⏰ <strong>Checkout is at 10:00 AM</strong><br><br>Please start your dishwasher, take out any trash, and leave the keys on the kitchen counter. Safe travels! 🐚" },
      checkin: { triggers: ['check in','check-in','checkin','arrive','arrival'], response: "⏰ <strong>Check-in is at 4:00 PM</strong><br><br>You can head straight to the property — no need to stop anywhere first. Your door code is ready when you arrive!" },
      beach: { triggers: ['beach','ocean','swim','water','chairs','umbrella'], response: "🏖️ <strong>Beach Access:</strong> Private walkover on the east side of the property — look for the blue gate.<br><br><strong>Chair Rentals:</strong> Chairs by the Sea sets up daily around 7:30 AM, right at the walkover. $30/day for 2 chairs + umbrella." },
      parking: { triggers: ['park','parking','car','garage'], response: "🚗 <strong>Parking:</strong> 2 spots in the driveway (space for a boat trailer too). Street parking available on Rosemary Ave, no permits required." },
      pool: { triggers: ['pool','hot tub','jacuzzi','spa'], response: "🏊 The <strong>heated pool</strong> is available 24/7! Pool temp is set to 84°F year-round. Please shower before entering and keep glass away from the pool deck." },
      restaurant: { triggers: ['restaurant','eat','food','dinner','lunch','breakfast','seafood','coffee','bar'], response: "🍽️ Great picks nearby:<br><br>🦞 <strong>The Bay</strong> — waterfront seafood, 5 min drive. Best sunset views on 30A.<br>🥞 <strong>The Pearl</strong> — breakfast/brunch, expect a wait on weekends.<br>☕ <strong>The Meltdown</strong> — best coffee in Rosemary, opens 7am.<br><br>Want me to check availability or recommend by cuisine?" },
      grocery: { triggers: ['grocery','groceries','store','market','walmart','publix'], response: "🛒 <strong>Nearest grocery:</strong><br>• Publix — 12 min drive in Santa Rosa Beach<br>• WaterColor Market — 5 min, small but great for basics<br>• Dewey Destin's market — local seafood, 10 min" },
    },

    addMessage(text, role) {
      const msgs = document.getElementById('demo-messages');
      const div = document.createElement('div');
      div.className = `demo-msg ${role}`;
      div.innerHTML = text;
      msgs.appendChild(div);
      msgs.scrollTop = msgs.scrollHeight;
    },

    showTyping() {
      const msgs = document.getElementById('demo-messages');
      const div = document.createElement('div');
      div.className = 'demo-typing'; div.id = 'demo-typing';
      div.innerHTML = '<span></span><span></span><span></span>';
      msgs.appendChild(div);
      msgs.scrollTop = msgs.scrollHeight;
    },
    removeTyping() { document.getElementById('demo-typing')?.remove(); },

    getLocalResponse(message) {
      const lower = message.toLowerCase();
      for (const [key, item] of Object.entries(this.demoKnowledge)) {
        if (item.triggers.some(t => lower.includes(t))) return item.response;
      }
      return null;
    },

    async sendQuick(text) {
      this.inputText = text;
      await this.sendMessage();
    },

    async sendMessage() {
      const text = this.inputText.trim();
      if (!text || this.isLoading) return;
      this.addMessage(text, 'user');
      this.inputText = '';
      this.isLoading = true;
      this.messageCount++;

      // Local response first (instant)
      const local = this.getLocalResponse(text);
      if (local) {
        await new Promise(r => setTimeout(r, 280 + Math.random() * 200));
        this.addMessage(local, 'assistant');
        this.isLoading = false;
        return;
      }

      // Fall back to actual API for unrecognized questions
      this.showTyping();
      try {
        const resp = await fetch('/api/v1/demo/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text })
        });
        this.removeTyping();
        if (resp.ok) {
          const data = await resp.json();
          this.addMessage(data.response, 'assistant');
        } else {
          this.addMessage("I don't have that info in the demo, but I'd know it for your actual property! Try setting up a free account to see everything I can do.", 'assistant');
        }
      } catch(e) {
        this.removeTyping();
        this.addMessage("I'd love to answer that! For your real property I'd have all the details. <a href='/onboarding-setup' style='color:#0ea5e9'>Set up your property →</a>", 'assistant');
      }
      this.isLoading = false;
    }
  };
}
</script>
</body>
</html>"""


# / is now served by public_landing.py — removed redirect


@router.post("/api/v1/demo/chat", response_model=DemoChatResponse, include_in_schema=False)
async def demo_chat(request: DemoChatRequest) -> DemoChatResponse:
    """
    Lightweight demo responder for landing page questions.
    Keeps the public demo deterministic and fast, with optional LLM fallback.
    """
    message = (request.message or "").strip()
    lower = message.lower()

    # Keyword rules — use whole-word or specific phrases to avoid false matches
    # e.g. "check in" must not match "indoors", "raining", etc.
    rules = [
        (("wifi", "wi-fi", "internet", "password"), "WiFi info is one of our highest-volume intents. Coral answers it instantly and can include network/password from your property profile."),
        (("door code", "door lock", "check-in code", "arrival code", "how do i get in"), "Coral handles check-in details like door access and arrival instructions, so guests avoid late-night calls."),
        (("restaurant", "food", "dinner", "lunch", "breakfast", "where to eat"), "Coral gives local-first restaurant recommendations tailored to your market, with practical details guests actually need."),
        (("pool heat", "heated pool", "is the pool"), "Pool heat policies can be configured per property, including fees and lead-time requirements."),
        (("escalation", "speak to human", "speak to manager", "real person"), "When a request needs a person, Coral escalates immediately and tracks acknowledgement/resolution in the operator dashboard."),
        (("dashboard", "analytics", "operator stats"), "Operators get live visibility into sessions, escalations, response quality, and concierge usage from a single dashboard."),
    ]
    for keywords, answer in rules:
        if any(k in lower for k in keywords):
            return DemoChatResponse(response=answer, source="rule")

    settings = get_settings()
    if settings.groq_api_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.groq_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are Coral, a warm and knowledgeable AI concierge for a 30A Florida vacation rental. "
                                    "Be specific, friendly, and brief. Use real local knowledge when relevant."
                                ),
                            },
                            {"role": "user", "content": message},
                        ],
                        "temperature": 0.7,
                        "max_tokens": 150,
                    },
                )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            if text:
                return DemoChatResponse(response=text, source="groq")
        except Exception:
            pass

    fallback = (
        "Coral can answer that for real guest stays using your property knowledge base. "
        "Set up a property to see live concierge responses end-to-end."
    )
    return DemoChatResponse(response=fallback, source="fallback")
