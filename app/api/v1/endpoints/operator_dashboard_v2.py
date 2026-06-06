"""
operator_dashboard_v2.py — Oyvoda Operator Dashboard

GET /operator-dashboard

Proper operator-facing product dashboard that:
- Matches the Oyvoda visual identity (dark navy, amber, Cormorant Garamond)
- Surfaces live backend data via the audit API, health endpoint, and SLO metrics  
- Shows pre-booking queue, guest sessions, escalations, KB gaps, system status
- Has the same nav as engine/security/privacy pages
- Fetches data client-side so it works before DB is connected (graceful empty states)
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Dashboard V2"])

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Operator Dashboard — Oyvoda</title>
<meta name="description" content="Oyvoda operator dashboard — manage guest sessions, pre-booking queue, escalations, and knowledge base.">
<meta name="theme-color" content="#08090f">
<meta name="robots" content="noindex">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%2308090f'/%3E%3Ctext x='16' y='23' font-family='Georgia,serif' font-size='21' font-weight='500' fill='%23f0ebe3' text-anchor='middle'%3Eo%3C/text%3E%3Cpath d='M20 7 Q24 4 27 8' stroke='%23c87832' stroke-width='2' fill='none' stroke-linecap='round'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body { background: #08090f; color: #f0ebe3; font-family: 'DM Sans', sans-serif; line-height: 1.6; -webkit-font-smoothing: antialiased; min-height: 100vh; }

/* ── TOKENS ── */
:root {
  --amber: #c87832; --gold: #e09040; --glow: #f0ac58;
  --green: #22c55e; --red: #ef4444; --yellow: #f59e0b;
  --ink: #08090f; --navy: #0d1220; --slate: #131c2e;
  --mid: #1e2d44; --dim: rgba(240,235,227,0.35);
  --ghost: rgba(240,235,227,0.6); --white: #f0ebe3;
}

/* ── NAV ── */
.topnav {
  position: sticky; top: 0; z-index: 100;
  background: rgba(8,9,15,0.95); backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(200,120,50,0.12);
  height: 64px; padding: 0 32px;
  display: flex; align-items: center; justify-content: space-between;
}
.nav-logo { font-family: 'Cormorant Garamond', serif; font-size: 22px; font-weight: 500; color: var(--white); text-decoration: none; letter-spacing: -0.02em; }
.nav-links { display: flex; align-items: center; gap: 6px; }
.nav-link { color: var(--dim); text-decoration: none; font-size: 13px; padding: 6px 12px; border-radius: 7px; transition: all 0.15s; }
.nav-link:hover { color: var(--white); background: rgba(255,255,255,0.05); }
.nav-link.active { color: var(--amber); background: rgba(200,120,50,0.1); }
.nav-right { display: flex; align-items: center; gap: 10px; }
.nav-status { display: flex; align-items: center; gap: 6px; font-size: 11px; font-family: 'DM Mono', monospace; color: var(--dim); }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--green); animation: pulse 2s infinite; }
.status-dot.warn { background: var(--yellow); }
.status-dot.error { background: var(--red); animation: none; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
.nav-cta { background: var(--amber); color: var(--white); text-decoration: none; font-size: 12px; font-weight: 600; padding: 7px 16px; border-radius: 8px; border: none; cursor: pointer; }

/* ── LAYOUT ── */
.layout { display: grid; grid-template-columns: 220px 1fr; min-height: calc(100vh - 64px); }

/* ── SIDEBAR ── */
.sidebar { background: var(--navy); border-right: 1px solid rgba(255,255,255,0.05); padding: 24px 0; position: sticky; top: 64px; height: calc(100vh - 64px); overflow-y: auto; }
.sidebar-section { padding: 0 16px; margin-bottom: 8px; }
.sidebar-label { font-family: 'DM Mono', monospace; font-size: 9px; letter-spacing: 0.14em; text-transform: uppercase; color: rgba(240,235,227,0.2); padding: 0 8px; margin-bottom: 4px; }
.sidebar-link { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 8px; cursor: pointer; transition: all 0.15s; color: var(--dim); font-size: 13px; text-decoration: none; border: none; background: none; width: 100%; text-align: left; }
.sidebar-link:hover { background: rgba(255,255,255,0.04); color: var(--white); }
.sidebar-link.active { background: rgba(200,120,50,0.1); color: var(--amber); }
.sidebar-link .icon { font-size: 15px; width: 20px; text-align: center; }
.sidebar-badge { margin-left: auto; background: rgba(200,120,50,0.2); color: var(--amber); font-size: 10px; font-family: 'DM Mono', monospace; padding: 2px 7px; border-radius: 10px; }
.sidebar-badge.red { background: rgba(239,68,68,0.15); color: var(--red); }
.sidebar-divider { border: none; border-top: 1px solid rgba(255,255,255,0.05); margin: 12px 16px; }
.operator-switcher { margin: 0 16px 20px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 10px; padding: 12px; }
.operator-name { font-size: 13px; font-weight: 500; color: var(--white); margin-bottom: 2px; }
.operator-meta { font-size: 11px; color: var(--dim); font-family: 'DM Mono', monospace; }

/* ── MAIN CONTENT ── */
.main { padding: 28px 32px; overflow-y: auto; }

/* ── SECTION HEADER ── */
.section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.section-title { font-family: 'Cormorant Garamond', serif; font-size: 26px; font-weight: 600; color: var(--white); letter-spacing: -0.02em; }
.section-eyebrow { font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--amber); margin-bottom: 4px; }
.section-actions { display: flex; gap: 8px; }
.btn { padding: 8px 16px; border-radius: 8px; font-size: 12px; font-weight: 500; cursor: pointer; border: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.04); color: var(--ghost); transition: all 0.15s; font-family: 'DM Sans', sans-serif; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; }
.btn:hover { background: rgba(255,255,255,0.08); color: var(--white); }
.btn-amber { background: var(--amber); color: var(--white); border-color: transparent; }
.btn-amber:hover { background: var(--gold); }

/* ── STAT CARDS ── */
.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 24px; }
.stat-card { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 14px; padding: 20px; transition: border-color 0.2s; }
.stat-card:hover { border-color: rgba(200,120,50,0.2); }
.stat-label { font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--dim); margin-bottom: 10px; }
.stat-value { font-family: 'Cormorant Garamond', serif; font-size: 36px; font-weight: 600; color: var(--white); line-height: 1; letter-spacing: -0.02em; }
.stat-sub { font-size: 11px; color: var(--dim); margin-top: 4px; }
.stat-value.green { color: var(--green); }
.stat-value.amber { color: var(--amber); }
.stat-value.red { color: var(--red); }

/* ── CARDS ── */
.card { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 14px; margin-bottom: 16px; overflow: hidden; }
.card-header { padding: 16px 20px; border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; align-items: center; justify-content: space-between; }
.card-title { font-size: 13px; font-weight: 500; color: var(--white); }
.card-subtitle { font-size: 12px; color: var(--dim); }
.card-body { padding: 20px; }

/* ── TABLE ── */
.data-table { width: 100%; border-collapse: collapse; }
.data-table th { font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--dim); padding: 10px 14px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.05); font-weight: 500; }
.data-table td { padding: 12px 14px; font-size: 13px; color: var(--ghost); border-bottom: 1px solid rgba(255,255,255,0.03); }
.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: rgba(255,255,255,0.02); }

/* ── BADGES ── */
.badge { display: inline-flex; align-items: center; gap: 5px; font-size: 10px; font-family: 'DM Mono', monospace; letter-spacing: 0.06em; padding: 3px 8px; border-radius: 5px; }
.badge-green { background: rgba(34,197,94,0.12); color: var(--green); }
.badge-amber { background: rgba(200,120,50,0.12); color: var(--amber); }
.badge-red { background: rgba(239,68,68,0.12); color: var(--red); }
.badge-dim { background: rgba(255,255,255,0.06); color: var(--dim); }

/* ── SLO METERS ── */
.slo-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.slo-item { }
.slo-label { font-size: 11px; color: var(--dim); margin-bottom: 6px; font-family: 'DM Mono', monospace; letter-spacing: 0.04em; }
.slo-bar-track { background: rgba(255,255,255,0.06); border-radius: 4px; height: 5px; margin-bottom: 4px; }
.slo-bar-fill { height: 5px; border-radius: 4px; background: var(--green); transition: width 1s ease; }
.slo-bar-fill.warn { background: var(--yellow); }
.slo-bar-fill.ok { background: var(--green); }
.slo-values { display: flex; justify-content: space-between; font-size: 10px; font-family: 'DM Mono', monospace; color: var(--dim); }

/* ── EMPTY STATE ── */
.empty-state { text-align: center; padding: 48px 24px; }
.empty-state-icon { font-size: 32px; margin-bottom: 12px; opacity: 0.4; }
.empty-state-title { font-size: 14px; font-weight: 500; color: var(--ghost); margin-bottom: 6px; }
.empty-state-sub { font-size: 13px; color: var(--dim); line-height: 1.6; max-width: 320px; margin: 0 auto 20px; font-weight: 300; }

/* ── SETUP BANNER ── */
.setup-banner { background: rgba(200,120,50,0.06); border: 1px solid rgba(200,120,50,0.2); border-radius: 14px; padding: 24px; margin-bottom: 24px; display: flex; align-items: center; gap: 20px; }
.setup-icon { font-size: 28px; flex-shrink: 0; }
.setup-title { font-size: 14px; font-weight: 500; color: var(--white); margin-bottom: 4px; }
.setup-body { font-size: 13px; color: var(--ghost); font-weight: 300; }
.setup-actions { margin-left: auto; flex-shrink: 0; display: flex; gap: 8px; }

/* ── SYSTEM STATUS ── */
.status-row { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
.status-row:last-child { border-bottom: none; }
.status-label { font-size: 13px; color: var(--ghost); flex: 1; }
.status-value { font-size: 12px; font-family: 'DM Mono', monospace; color: var(--dim); }
.status-indicator { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.ind-green { background: var(--green); }
.ind-yellow { background: var(--yellow); }
.ind-red { background: var(--red); }
.ind-dim { background: rgba(255,255,255,0.15); }

/* ── CHANNEL CARDS ── */
.channel-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.channel-card { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; padding: 16px; }
.channel-icon { font-size: 20px; margin-bottom: 10px; }
.channel-name { font-size: 13px; font-weight: 500; color: var(--white); margin-bottom: 3px; }
.channel-status-text { font-size: 11px; font-family: 'DM Mono', monospace; }
.channel-status-text.live { color: var(--green); }
.channel-status-text.soon { color: var(--amber); }
.channel-stat { font-size: 11px; color: var(--dim); margin-top: 8px; }

/* ── TWO COL ── */
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.three-col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }

/* ── TABS ── */
.tab-bar { display: flex; gap: 4px; padding: 4px; background: rgba(255,255,255,0.03); border-radius: 10px; margin-bottom: 20px; width: fit-content; }
.tab { padding: 6px 16px; border-radius: 7px; font-size: 12px; font-weight: 500; cursor: pointer; border: none; background: none; color: var(--dim); transition: all 0.15s; }
.tab.active { background: var(--amber); color: var(--white); }
.tab:hover:not(.active) { color: var(--white); background: rgba(255,255,255,0.05); }

/* ── LOADING SKELETON ── */
.skeleton { background: linear-gradient(90deg, rgba(255,255,255,0.04) 25%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.04) 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite; border-radius: 6px; }
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

/* ── RESPONSIVE ── */
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .sidebar { display: none; }
  .stat-row { grid-template-columns: repeat(2, 1fr); }
  .channel-grid { grid-template-columns: repeat(2, 1fr); }
  .two-col, .three-col { grid-template-columns: 1fr; }
  .slo-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
</head>
<body>

<!-- ── TOPNAV ── -->
<nav class="topnav">
  <a href="/" class="nav-logo">oyvoda</a>
  <div class="nav-links">
    <a href="/" class="nav-link">← Platform</a>
    <a href="/operator-dashboard" class="nav-link active">Dashboard</a>
    <a href="/engine" class="nav-link">Engine</a>
    <a href="/security" class="nav-link">Security</a>
  </div>
  <div class="nav-right">
    <div class="nav-status" id="system-status">
      <div class="status-dot" id="status-dot"></div>
      <span id="status-text">Checking...</span>
    </div>
    <a href="/onboarding-setup" class="nav-cta">Connect PMS →</a>
  </div>
</nav>

<!-- ── LAYOUT ── -->
<div class="layout">

  <!-- ── SIDEBAR ── -->
  <aside class="sidebar">
    <div class="operator-switcher">
      <div class="operator-name" id="sb-operator-name">No operator connected</div>
      <div class="operator-meta" id="sb-operator-meta">Run setup to connect your PMS</div>
    </div>

    <div class="sidebar-section">
      <div class="sidebar-label">Overview</div>
      <button class="sidebar-link active" onclick="showSection('overview')">
        <span class="icon">📊</span> Dashboard
      </button>
      <button class="sidebar-link" onclick="showSection('prebooking')">
        <span class="icon">📥</span> Pre-Booking Queue
        <span class="sidebar-badge" id="sb-prebooking-count">0</span>
      </button>
      <button class="sidebar-link" onclick="showSection('sessions')">
        <span class="icon">💬</span> Guest Sessions
        <span class="sidebar-badge" id="sb-sessions-count">0</span>
      </button>
      <button class="sidebar-link" onclick="showSection('escalations')">
        <span class="icon">🚨</span> Escalations
        <span class="sidebar-badge red" id="sb-escalations-count">0</span>
      </button>
    </div>
    <hr class="sidebar-divider">
    <div class="sidebar-section">
      <div class="sidebar-label">Knowledge</div>
      <button class="sidebar-link" onclick="showSection('knowledge')">
        <span class="icon">🧠</span> Knowledge Base
      </button>
      <button class="sidebar-link" onclick="showSection('gaps')">
        <span class="icon">❓</span> KB Gaps
        <span class="sidebar-badge" id="sb-gaps-count">0</span>
      </button>
      <button class="sidebar-link" onclick="showSection('training')">
        <span class="icon">🎯</span> Train Agent
      </button>
    </div>
    <hr class="sidebar-divider">
    <div class="sidebar-section">
      <div class="sidebar-label">System</div>
      <button class="sidebar-link" onclick="showSection('system')">
        <span class="icon">⚙️</span> System Status
      </button>
      <button class="sidebar-link" onclick="showSection('audit')">
        <span class="icon">📋</span> Audit & Export
      </button>
      <a href="/docs" class="sidebar-link">
        <span class="icon">📖</span> API Docs
      </a>
    </div>
  </aside>

  <!-- ── MAIN ── -->
  <main class="main" id="main-content">

    <!-- ───────────────────────────────────── OVERVIEW ── -->
    <div id="section-overview">
      <div class="section-head">
        <div>
          <div class="section-eyebrow">Operator Dashboard</div>
          <div class="section-title">Overview</div>
        </div>
        <div class="section-actions">
          <button class="btn" onclick="refreshAll()">↻ Refresh</button>
          <a href="/api/v1/audit/export?format=csv&days=30" class="btn">Export CSV</a>
        </div>
      </div>

      <!-- Setup banner (shown when DB not connected) -->
      <div class="setup-banner" id="setup-banner" style="display:none">
        <div class="setup-icon">🔌</div>
        <div>
          <div class="setup-title">Connect your PMS to get started</div>
          <div class="setup-body">Run <code style="font-family:'DM Mono',monospace;color:var(--amber)">python pre_booking_setup.py</code> to connect Escapia, Guesty, or Track and activate your first property.</div>
        </div>
        <div class="setup-actions">
          <a href="/onboarding-setup" class="btn btn-amber">Start Setup →</a>
        </div>
      </div>

      <!-- Stat row -->
      <div class="stat-row">
        <div class="stat-card">
          <div class="stat-label">Guest Sessions</div>
          <div class="stat-value" id="stat-sessions">—</div>
          <div class="stat-sub">Last 30 days</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Messages Handled</div>
          <div class="stat-value" id="stat-messages">—</div>
          <div class="stat-sub">AI-processed</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Pre-Booking Drafts</div>
          <div class="stat-value amber" id="stat-prebooking">—</div>
          <div class="stat-sub">Awaiting review</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">KB Entries Added</div>
          <div class="stat-value" id="stat-kb">—</div>
          <div class="stat-sub">Knowledge base growth</div>
        </div>
      </div>

      <!-- Two column: system status + channels -->
      <div class="two-col">

        <div class="card">
          <div class="card-header">
            <div class="card-title">System Status</div>
            <span class="badge badge-green" id="overall-status-badge">● HEALTHY</span>
          </div>
          <div class="card-body">
            <div class="status-row">
              <div class="status-indicator ind-green" id="ind-api"></div>
              <div class="status-label">API Server</div>
              <div class="status-value" id="val-api">v0.1.0</div>
            </div>
            <div class="status-row">
              <div class="status-indicator" id="ind-db"></div>
              <div class="status-label">Database</div>
              <div class="status-value" id="val-db">Checking...</div>
            </div>
            <div class="status-row">
              <div class="status-indicator ind-green" id="ind-mcp"></div>
              <div class="status-label">MCP Registry (9 servers)</div>
              <div class="status-value">Operational</div>
            </div>
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">Concierge Engine</div>
              <div class="status-value" id="val-concierge">Active</div>
            </div>
            <div class="status-row">
              <div class="status-indicator" id="ind-groq"></div>
              <div class="status-label">LLM (Groq / Llama 3.1)</div>
              <div class="status-value" id="val-groq">Checking...</div>
            </div>
            <div class="status-row">
              <div class="status-indicator" id="ind-redis"></div>
              <div class="status-label">Session Store (Redis)</div>
              <div class="status-value" id="val-redis">Checking...</div>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <div class="card-title">Active Channels</div>
            <a href="/#channels" class="btn" style="font-size:11px">View all →</a>
          </div>
          <div class="card-body">
            <div class="channel-grid" style="grid-template-columns: 1fr 1fr;">
              <div class="channel-card">
                <div class="channel-icon">💬</div>
                <div class="channel-name">RCS Messaging</div>
                <div class="channel-status-text live">● Live</div>
                <div class="channel-stat">Primary guest channel</div>
              </div>
              <div class="channel-card">
                <div class="channel-icon">📱</div>
                <div class="channel-name">SMS Fallback</div>
                <div class="channel-status-text live">● Live</div>
                <div class="channel-stat">Auto-fallback</div>
              </div>
              <div class="channel-card">
                <div class="channel-icon">📧</div>
                <div class="channel-name">Email (Pre-Booking)</div>
                <div class="channel-status-text live">● Live</div>
                <div class="channel-stat">Escapia / Vrbo</div>
              </div>
              <div class="channel-card">
                <div class="channel-icon">🌐</div>
                <div class="channel-name">Web Chat</div>
                <div class="channel-status-text soon">◎ Coming Soon</div>
                <div class="channel-stat">Widget embed</div>
              </div>
            </div>
          </div>
        </div>

      </div>

      <!-- SLO Metrics -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">SLO Thresholds</div>
          <div class="card-subtitle">Service Level Objectives — current targets</div>
        </div>
        <div class="card-body">
          <div class="slo-grid" id="slo-grid">
            <div>
              <div class="slo-label">API Latency Target</div>
              <div class="slo-bar-track"><div class="slo-bar-fill ok" style="width:85%"></div></div>
              <div class="slo-values"><span id="slo-api-val">—</span><span>target</span></div>
            </div>
            <div>
              <div class="slo-label">Knowledge Latency Target</div>
              <div class="slo-bar-track"><div class="slo-bar-fill ok" style="width:75%"></div></div>
              <div class="slo-values"><span id="slo-kb-val">—</span><span>target</span></div>
            </div>
            <div>
              <div class="slo-label">Error Rate Ceiling</div>
              <div class="slo-bar-track"><div class="slo-bar-fill ok" style="width:10%"></div></div>
              <div class="slo-values"><span id="slo-err-val">—</span><span>ceiling</span></div>
            </div>
            <div>
              <div class="slo-label">Voice Latency Target</div>
              <div class="slo-bar-track"><div class="slo-bar-fill ok" style="width:70%"></div></div>
              <div class="slo-values"><span id="slo-voice-val">—</span><span>target</span></div>
            </div>
            <div>
              <div class="slo-label">Empty Retrieval Ceiling</div>
              <div class="slo-bar-track"><div class="slo-bar-fill ok" style="width:5%"></div></div>
              <div class="slo-values"><span id="slo-retrieval-val">—</span><span>ceiling</span></div>
            </div>
            <div>
              <div class="slo-label">Escalation Backlog Ceiling</div>
              <div class="slo-bar-track"><div class="slo-bar-fill ok" style="width:0%"></div></div>
              <div class="slo-values"><span>0</span><span id="slo-esc-val">—</span></div>
            </div>
          </div>
        </div>
      </div>

      <!-- PMS Integrations -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">PMS Integrations</div>
          <a href="/onboarding-setup" class="btn btn-amber" style="font-size:11px">+ Connect PMS</a>
        </div>
        <div class="card-body">
          <table class="data-table">
            <thead>
              <tr>
                <th>System</th>
                <th>Status</th>
                <th>Properties</th>
                <th>Last Sync</th>
              </tr>
            </thead>
            <tbody id="pms-table-body">
              <tr>
                <td><strong style="color:var(--white)">Escapia</strong></td>
                <td><span class="badge badge-dim">Not connected</span></td>
                <td style="color:var(--dim)">—</td>
                <td style="color:var(--dim)">Never</td>
              </tr>
              <tr>
                <td><strong style="color:var(--white)">Guesty</strong></td>
                <td><span class="badge badge-dim">Not connected</span></td>
                <td style="color:var(--dim)">—</td>
                <td style="color:var(--dim)">Never</td>
              </tr>
              <tr>
                <td><strong style="color:var(--white)">Track</strong></td>
                <td><span class="badge badge-dim">Not connected</span></td>
                <td style="color:var(--dim)">—</td>
                <td style="color:var(--dim)">Never</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ───────────────────────────────── PRE-BOOKING ── -->
    <div id="section-prebooking" style="display:none">
      <div class="section-head">
        <div>
          <div class="section-eyebrow">Pre-Booking Pipeline</div>
          <div class="section-title">Inquiry Queue</div>
        </div>
        <div class="section-actions">
          <button class="btn">Filter ▾</button>
          <button class="btn btn-amber">Review All</button>
        </div>
      </div>
      <div class="card">
        <div class="card-body">
          <div class="empty-state">
            <div class="empty-state-icon">📥</div>
            <div class="empty-state-title">No pending inquiries</div>
            <div class="empty-state-sub">When guests inquire via Vrbo or Escapia, AI-drafted replies will appear here for your review before sending. Connect your PMS to activate.</div>
            <a href="/onboarding-setup" class="btn btn-amber">Connect PMS →</a>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><div class="card-title">How Pre-Booking Works</div></div>
        <div class="card-body">
          <div class="three-col">
            <div style="padding:16px;background:rgba(255,255,255,0.02);border-radius:10px">
              <div style="font-size:20px;margin-bottom:10px">1️⃣</div>
              <div style="font-size:13px;font-weight:500;color:var(--white);margin-bottom:6px">Guest Inquiry Arrives</div>
              <div style="font-size:12px;color:var(--dim);font-weight:300;line-height:1.6">Vrbo or Escapia inquiry hits your inbox. Oyvoda detects it and extracts guest info, dates, and intent.</div>
            </div>
            <div style="padding:16px;background:rgba(255,255,255,0.02);border-radius:10px">
              <div style="font-size:20px;margin-bottom:10px">2️⃣</div>
              <div style="font-size:13px;font-weight:500;color:var(--white);margin-bottom:6px">AI Drafts a Reply</div>
              <div style="font-size:12px;color:var(--dim);font-weight:300;line-height:1.6">The THINK layer retrieves your property knowledge. ACT layer drafts a reply in your voice. Appears here in your queue.</div>
            </div>
            <div style="padding:16px;background:rgba(255,255,255,0.02);border-radius:10px">
              <div style="font-size:20px;margin-bottom:10px">3️⃣</div>
              <div style="font-size:13px;font-weight:500;color:var(--white);margin-bottom:6px">You Review & Send</div>
              <div style="font-size:12px;color:var(--dim);font-weight:300;line-height:1.6">Edit, approve, or reject. Every edit trains the LEARN layer. Over time, drafts need fewer changes.</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ─────────────────────────────────── SESSIONS ── -->
    <div id="section-sessions" style="display:none">
      <div class="section-head">
        <div>
          <div class="section-eyebrow">Guest Experience</div>
          <div class="section-title">Active Sessions</div>
        </div>
        <div class="section-actions">
          <button class="btn">Last 30 days ▾</button>
          <a href="/api/v1/audit/export?format=csv&days=30&include=sessions" class="btn">Export CSV</a>
        </div>
      </div>
      <div class="stat-row" style="grid-template-columns:repeat(3,1fr)">
        <div class="stat-card">
          <div class="stat-label">Total Sessions</div>
          <div class="stat-value" id="sessions-total">0</div>
          <div class="stat-sub">Last 30 days</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Active Now</div>
          <div class="stat-value green">0</div>
          <div class="stat-sub">In-stay guests</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Messages Handled</div>
          <div class="stat-value" id="sessions-messages">0</div>
          <div class="stat-sub">AI-resolved</div>
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <div class="card-title">Recent Sessions</div>
        </div>
        <div class="card-body">
          <div class="empty-state">
            <div class="empty-state-icon">💬</div>
            <div class="empty-state-title">No guest sessions yet</div>
            <div class="empty-state-sub">Once you connect a PMS and add guests, their sessions will appear here with full conversation history, intent scores, and AI decision metadata.</div>
            <a href="/onboarding-setup" class="btn btn-amber">Connect PMS →</a>
          </div>
        </div>
      </div>
    </div>

    <!-- ─────────────────────────────────── ESCALATIONS ── -->
    <div id="section-escalations" style="display:none">
      <div class="section-head">
        <div>
          <div class="section-eyebrow">Alert Management</div>
          <div class="section-title">Escalations</div>
        </div>
        <div class="section-actions">
          <button class="btn">All Properties ▾</button>
        </div>
      </div>
      <div class="stat-row" style="grid-template-columns:repeat(3,1fr)">
        <div class="stat-card">
          <div class="stat-label">Open Escalations</div>
          <div class="stat-value red">0</div>
          <div class="stat-sub">Requires attention</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Resolved (30d)</div>
          <div class="stat-value green">0</div>
          <div class="stat-sub">Closed this month</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Backlog Ceiling</div>
          <div class="stat-value amber" id="esc-ceiling">25</div>
          <div class="stat-sub">SLO threshold</div>
        </div>
      </div>
      <div class="card">
        <div class="card-body">
          <div class="empty-state">
            <div class="empty-state-icon">✅</div>
            <div class="empty-state-title">No open escalations</div>
            <div class="empty-state-sub">Emergencies, frustrated guests, and maintenance issues detected by the SENSE layer will escalate here automatically with full context.</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ─────────────────────────────────── KNOWLEDGE ── -->
    <div id="section-knowledge" style="display:none">
      <div class="section-head">
        <div>
          <div class="section-eyebrow">THINK Layer</div>
          <div class="section-title">Knowledge Base</div>
        </div>
        <div class="section-actions">
          <button class="btn">All Properties ▾</button>
          <button class="btn btn-amber" onclick="showSection('training')">+ Add Entry</button>
        </div>
      </div>
      <div class="card">
        <div class="card-body">
          <div class="empty-state">
            <div class="empty-state-icon">🧠</div>
            <div class="empty-state-title">No knowledge base entries yet</div>
            <div class="empty-state-sub">Your AI reads from a property-specific vector knowledge base. Connect your PMS to auto-populate from your listings, then add Q&A entries to train your concierge.</div>
            <button class="btn btn-amber" onclick="showSection('training')">Train Your Agent →</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ─────────────────────────────────────── GAPS ── -->
    <div id="section-gaps" style="display:none">
      <div class="section-head">
        <div>
          <div class="section-eyebrow">Learning Queue</div>
          <div class="section-title">Knowledge Gaps</div>
        </div>
      </div>
      <div class="card">
        <div class="card-body">
          <div class="empty-state">
            <div class="empty-state-icon">❓</div>
            <div class="empty-state-title">No knowledge gaps detected</div>
            <div class="empty-state-sub">When guests ask questions your AI can't answer confidently, they surface here. Approve an answer once and every future guest gets it automatically.</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ─────────────────────────────────── TRAINING ── -->
    <div id="section-training" style="display:none">
      <div class="section-head">
        <div>
          <div class="section-eyebrow">LEARN Layer</div>
          <div class="section-title">Train Your Agent</div>
        </div>
        <div class="section-actions">
          <a href="/operator-dashboard/training" class="btn btn-amber">Open Training Studio →</a>
        </div>
      </div>
      <div class="two-col">
        <div class="card">
          <div class="card-header"><div class="card-title">What Training Does</div></div>
          <div class="card-body">
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">Add Q&A pairs to your property knowledge base</div>
            </div>
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">Close knowledge gaps from guest conversations</div>
            </div>
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">Test how the AI responds to any guest question</div>
            </div>
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">Review grounding scores and confidence levels</div>
            </div>
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">Deploy changes property-by-property (canary rollout)</div>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-header"><div class="card-title">LEARN Layer Stats</div></div>
          <div class="card-body">
            <div class="stat-row" style="grid-template-columns:1fr 1fr;gap:10px;margin:0">
              <div class="stat-card" style="padding:14px">
                <div class="stat-label" style="font-size:9px">Active Rules</div>
                <div class="stat-value" style="font-size:28px">0</div>
              </div>
              <div class="stat-card" style="padding:14px">
                <div class="stat-label" style="font-size:9px">Pending Drafts</div>
                <div class="stat-value amber" style="font-size:28px">0</div>
              </div>
              <div class="stat-card" style="padding:14px">
                <div class="stat-label" style="font-size:9px">KB Gaps</div>
                <div class="stat-value red" style="font-size:28px">0</div>
              </div>
              <div class="stat-card" style="padding:14px">
                <div class="stat-label" style="font-size:9px">Total Entries</div>
                <div class="stat-value" style="font-size:28px">0</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ─────────────────────────────────────── SYSTEM ── -->
    <div id="section-system" style="display:none">
      <div class="section-head">
        <div>
          <div class="section-eyebrow">Infrastructure</div>
          <div class="section-title">System Status</div>
        </div>
        <div class="section-actions">
          <button class="btn" onclick="refreshAll()">↻ Refresh</button>
          <a href="/docs" class="btn">API Docs →</a>
        </div>
      </div>
      <div class="two-col">
        <div class="card">
          <div class="card-header"><div class="card-title">Service Health</div></div>
          <div class="card-body" id="system-health-detail">
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">API Server (FastAPI)</div>
              <div class="status-value" id="sys-version">v0.1.0</div>
            </div>
            <div class="status-row">
              <div class="status-indicator" id="sys-ind-db"></div>
              <div class="status-label">Supabase Database</div>
              <div class="status-value" id="sys-val-db">Checking...</div>
            </div>
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">MCP Registry (9 servers)</div>
              <div class="status-value">Registered</div>
            </div>
            <div class="status-row">
              <div class="status-indicator" id="sys-ind-groq"></div>
              <div class="status-label">Groq LLM (Llama 3.1)</div>
              <div class="status-value" id="sys-val-groq">Checking...</div>
            </div>
            <div class="status-row">
              <div class="status-indicator" id="sys-ind-redis"></div>
              <div class="status-label">Redis Session Store</div>
              <div class="status-value" id="sys-val-redis">Checking...</div>
            </div>
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">Cloudflare CDN</div>
              <div class="status-value">Proxied</div>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-header"><div class="card-title">SLO Configuration</div></div>
          <div class="card-body" id="slo-detail">
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">API Latency Ceiling</div>
              <div class="status-value" id="sys-slo-api">—</div>
            </div>
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">Knowledge Latency Ceiling</div>
              <div class="status-value" id="sys-slo-kb">—</div>
            </div>
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">Voice Latency Ceiling</div>
              <div class="status-value" id="sys-slo-voice">—</div>
            </div>
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">Error Rate Ceiling</div>
              <div class="status-value" id="sys-slo-err">—</div>
            </div>
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">Empty Retrieval Ceiling</div>
              <div class="status-value" id="sys-slo-ret">—</div>
            </div>
            <div class="status-row">
              <div class="status-indicator ind-green"></div>
              <div class="status-label">Escalation Backlog Ceiling</div>
              <div class="status-value" id="sys-slo-esc">—</div>
            </div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><div class="card-title">Environment Configuration</div></div>
        <div class="card-body">
          <table class="data-table">
            <thead>
              <tr><th>Setting</th><th>Value</th><th>Status</th></tr>
            </thead>
            <tbody id="env-table">
              <tr><td>Environment</td><td id="env-env">—</td><td><span class="badge badge-green">Active</span></td></tr>
              <tr><td>Focus Mode</td><td id="env-focus">—</td><td><span class="badge badge-green">Configured</span></td></tr>
              <tr><td>Market Signals</td><td id="env-market">—</td><td><span class="badge badge-dim">Optional</span></td></tr>
              <tr><td>Market Intel API</td><td id="env-intel">—</td><td><span class="badge badge-dim">Optional</span></td></tr>
              <tr><td>Watch API</td><td id="env-watch">—</td><td><span class="badge badge-dim">Optional</span></td></tr>
              <tr><td>Strict Startup Checks</td><td id="env-strict">—</td><td><span class="badge badge-amber">Review</span></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ─────────────────────────────────────── AUDIT ── -->
    <div id="section-audit" style="display:none">
      <div class="section-head">
        <div>
          <div class="section-eyebrow">Compliance & Records</div>
          <div class="section-title">Audit & Export</div>
        </div>
        <div class="section-actions">
          <a href="/api/v1/audit/export?format=csv&days=30" class="btn">Export CSV (30d)</a>
          <a href="/api/v1/audit/export?format=json&days=30" class="btn btn-amber">Export JSON</a>
        </div>
      </div>
      <div class="stat-row" id="audit-stats">
        <div class="stat-card">
          <div class="stat-label">Guest Sessions</div>
          <div class="stat-value" id="aud-sessions">—</div>
          <div class="stat-sub">Last 30 days</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Messages Logged</div>
          <div class="stat-value" id="aud-messages">—</div>
          <div class="stat-sub">Full conversation records</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Pre-Booking Records</div>
          <div class="stat-value" id="aud-drafts">—</div>
          <div class="stat-sub">Draft + edit + sent history</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">KB Changes</div>
          <div class="stat-value" id="aud-kb">—</div>
          <div class="stat-sub">Additions & edits logged</div>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><div class="card-title">What's Included in Exports</div></div>
        <div class="card-body">
          <table class="data-table">
            <thead><tr><th>Dataset</th><th>Fields</th><th>Export</th></tr></thead>
            <tbody>
              <tr>
                <td><strong style="color:var(--white)">Guest Sessions</strong></td>
                <td style="color:var(--dim)">Session ID, guest name, phone, property, check-in/out, status, phase</td>
                <td><a href="/api/v1/audit/export?format=csv&days=30&include=sessions" class="btn" style="font-size:11px;padding:4px 10px">CSV</a></td>
              </tr>
              <tr>
                <td><strong style="color:var(--white)">Message History</strong></td>
                <td style="color:var(--dim)">Role, content, intent, confidence score, latency, timestamp</td>
                <td><a href="/api/v1/audit/export?format=csv&days=30&include=messages" class="btn" style="font-size:11px;padding:4px 10px">CSV</a></td>
              </tr>
              <tr>
                <td><strong style="color:var(--white)">Knowledge Base</strong></td>
                <td style="color:var(--dim)">Question, answer, source, approved by, timestamps</td>
                <td><a href="/api/v1/audit/export?format=csv&days=30&include=kb" class="btn" style="font-size:11px;padding:4px 10px">CSV</a></td>
              </tr>
              <tr>
                <td><strong style="color:var(--white)">Full Export (All)</strong></td>
                <td style="color:var(--dim)">All datasets combined — sessions, messages, KB, pre-booking</td>
                <td><a href="/api/v1/audit/export?format=json&days=30" class="btn btn-amber" style="font-size:11px;padding:4px 10px">JSON</a></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><div class="card-title">Security & Compliance</div></div>
        <div class="card-body">
          <div class="two-col">
            <div>
              <div class="status-row"><div class="status-indicator ind-green"></div><div class="status-label">SSL/TLS encryption in transit</div></div>
              <div class="status-row"><div class="status-indicator ind-green"></div><div class="status-label">AES-256 encryption at rest (Supabase)</div></div>
              <div class="status-row"><div class="status-indicator ind-green"></div><div class="status-label">Company-scoped data isolation</div></div>
              <div class="status-row"><div class="status-indicator ind-green"></div><div class="status-label">Structural prompt injection defense</div></div>
            </div>
            <div>
              <div class="status-row"><div class="status-indicator ind-green"></div><div class="status-label">Governance MCP — pre-execution validation</div></div>
              <div class="status-row"><div class="status-indicator ind-green"></div><div class="status-label">Hallucination guard (response grounding)</div></div>
              <div class="status-row"><div class="status-indicator ind-green"></div><div class="status-label">Supabase SOC 2 Type II certified</div></div>
              <div class="status-row"><div class="status-indicator ind-yellow"></div><div class="status-label">Oyvoda SOC 2 — in progress (Q4 2026)</div></div>
            </div>
          </div>
          <div style="margin-top:16px;display:flex;gap:10px">
            <a href="/security" class="btn">Full Security Page →</a>
            <a href="/privacy" class="btn">Privacy Policy →</a>
            <a href="mailto:security@oyvoda.com" class="btn">Request DPA / SOC 2</a>
          </div>
        </div>
      </div>
    </div>

  </main>
</div>

<script>
// ── SECTION NAVIGATION ──────────────────────────────────────
const sections = ['overview','prebooking','sessions','escalations','knowledge','gaps','training','system','audit'];

function showSection(name) {
  sections.forEach(s => {
    const el = document.getElementById('section-' + s);
    if (el) el.style.display = s === name ? '' : 'none';
  });
  // Update sidebar active state
  document.querySelectorAll('.sidebar-link').forEach(l => l.classList.remove('active'));
  document.querySelectorAll('.sidebar-link').forEach(l => {
    if (l.getAttribute('onclick') === `showSection('${name}')`) l.classList.add('active');
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── DATA LOADING ─────────────────────────────────────────────
async function loadHealth() {
  try {
    const r = await fetch('/health');
    const d = await r.json();
    
    // Status dot
    const dot = document.getElementById('status-dot');
    const txt = document.getElementById('status-text');
    if (d.status === 'healthy') {
      dot.className = 'status-dot';
      txt.textContent = 'All systems operational';
    }

    // Version
    ['sys-version'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = 'v' + d.version;
    });

    // Environment config table
    const setVal = (id, val) => { const el = document.getElementById(id); if(el) el.textContent = String(val); };
    setVal('env-env', d.environment || '—');
    setVal('env-focus', d.focus_concierge_only ? 'Concierge Only' : 'Full Platform');
    setVal('env-market', d.concierge_market_signals ? 'Enabled' : 'Disabled');
    setVal('env-intel', d.market_intel_api ? 'Enabled' : 'Disabled');
    setVal('env-watch', d.watch_api ? 'Enabled' : 'Disabled');
    setVal('env-strict', d.strict_startup_checks ? 'Enabled' : 'Disabled');

    // SLO thresholds
    const slo = d.slo_thresholds || {};
    setVal('slo-api-val', slo.api_latency_ms + 'ms');
    setVal('slo-kb-val', slo.knowledge_latency_ms + 'ms');
    setVal('slo-err-val', (slo.error_rate * 100).toFixed(0) + '%');
    setVal('slo-voice-val', slo.voice_latency_ms + 'ms');
    setVal('slo-retrieval-val', (slo.empty_retrieval_rate * 100).toFixed(0) + '%');
    setVal('slo-esc-val', '/ ' + slo.escalation_backlog + ' max');
    setVal('esc-ceiling', slo.escalation_backlog);
    setVal('sys-slo-api', slo.api_latency_ms + 'ms');
    setVal('sys-slo-kb', slo.knowledge_latency_ms + 'ms');
    setVal('sys-slo-voice', slo.voice_latency_ms + 'ms');
    setVal('sys-slo-err', (slo.error_rate * 100).toFixed(1) + '%');
    setVal('sys-slo-ret', (slo.empty_retrieval_rate * 100).toFixed(0) + '%');
    setVal('sys-slo-esc', slo.escalation_backlog + ' max');

    // DB status (inferred from warnings — if audit summary has "note" then DB is down)
  } catch(e) {
    document.getElementById('status-dot').className = 'status-dot error';
    document.getElementById('status-text').textContent = 'API unreachable';
  }
}

async function loadAudit() {
  try {
    const r = await fetch('/api/v1/audit/summary?days=30');
    const d = await r.json();
    
    const dbConnected = !d.note; // no note = DB connected
    
    // Update stat cards
    const setNum = (id, val) => { const el = document.getElementById(id); if(el) { el.textContent = val.toLocaleString(); } };
    setNum('stat-sessions', d.guest_sessions || 0);
    setNum('stat-messages', d.messages_processed || 0);
    setNum('stat-prebooking', d.pre_booking_drafts || 0);
    setNum('stat-kb', d.kb_entries_added || 0);
    setNum('sessions-total', d.guest_sessions || 0);
    setNum('sessions-messages', d.messages_processed || 0);
    setNum('aud-sessions', d.guest_sessions || 0);
    setNum('aud-messages', d.messages_processed || 0);
    setNum('aud-drafts', d.pre_booking_drafts || 0);
    setNum('aud-kb', d.kb_entries_added || 0);
    setNum('sb-sessions-count', d.guest_sessions || 0);
    setNum('sb-prebooking-count', d.pre_booking_drafts || 0);

    // DB indicator
    const indDb = document.getElementById('ind-db');
    const valDb = document.getElementById('val-db');
    const sysIndDb = document.getElementById('sys-ind-db');
    const sysValDb = document.getElementById('sys-val-db');
    if (dbConnected) {
      if(indDb) { indDb.className = 'status-indicator ind-green'; }
      if(valDb) valDb.textContent = 'Connected';
      if(sysIndDb) sysIndDb.className = 'status-indicator ind-green';
      if(sysValDb) sysValDb.textContent = 'Connected';
    } else {
      if(indDb) { indDb.className = 'status-indicator ind-yellow'; }
      if(valDb) valDb.textContent = 'Not connected';
      if(sysIndDb) sysIndDb.className = 'status-indicator ind-yellow';
      if(sysValDb) sysValDb.textContent = 'Needs setup';
      // Show setup banner
      const banner = document.getElementById('setup-banner');
      if(banner) banner.style.display = 'flex';
    }

    // Groq indicator (infer from environment — if GROQ_API_KEY not set)
    // We can't know for sure client-side, mark as unknown
    const indGroq = document.getElementById('ind-groq');
    const valGroq = document.getElementById('val-groq');
    const sysIndGroq = document.getElementById('sys-ind-groq');
    const sysValGroq = document.getElementById('sys-val-groq');
    // Railway logs show "No LLM API key configured" warning — mark yellow
    if(indGroq) indGroq.className = 'status-indicator ind-yellow';
    if(valGroq) valGroq.textContent = 'Check GROQ_API_KEY';
    if(sysIndGroq) sysIndGroq.className = 'status-indicator ind-yellow';
    if(sysValGroq) sysValGroq.textContent = 'Check Railway vars';

    // Redis indicator
    const indRedis = document.getElementById('ind-redis');
    const valRedis = document.getElementById('val-redis');
    const sysIndRedis = document.getElementById('sys-ind-redis');
    const sysValRedis = document.getElementById('sys-val-redis');
    // Logs show "No REDIS_URL set, using DB-only persistence"
    if(indRedis) indRedis.className = 'status-indicator ind-yellow';
    if(valRedis) valRedis.textContent = 'DB fallback mode';
    if(sysIndRedis) sysIndRedis.className = 'status-indicator ind-yellow';
    if(sysValRedis) sysValRedis.textContent = 'DB fallback (no REDIS_URL)';

    // Sidebar operator info
    document.getElementById('sb-operator-name').textContent = dbConnected ? 'Operator Connected' : 'No operator connected';
    document.getElementById('sb-operator-meta').textContent = dbConnected ? '30A Florida · Escapia' : 'Run pre_booking_setup.py';

  } catch(e) {
    console.warn('Audit load failed:', e);
  }
}

function refreshAll() {
  loadHealth();
  loadAudit();
}

// ── INIT ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  refreshAll();
  // Auto-refresh every 30 seconds
  setInterval(refreshAll, 30000);
});
</script>

</body>
</html>"""


@router.get("/operator-dashboard", response_class=HTMLResponse, include_in_schema=False)
async def serve_operator_dashboard_v2(request: Request):
    return HTMLResponse(content=DASHBOARD_HTML)
