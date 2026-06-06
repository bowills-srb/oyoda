"""
operator_tour.py — Oyvoda Operator Product Tour

GET /operator-dashboard

A scrolling product tour page showing operators exactly how Oyvoda works:
- Pre-booking queue (message arrives → AI drafts → operator reviews → sends)
- Guest messaging console (sessions, AI responses, escalations)
- Training & analytics (KB gaps, edits train the AI, voice matching)

No backend links. No PMS connection flows. Commercial CTAs only.
Same visual identity as Engine page — Cormorant Garamond, dark navy, amber.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Operator Tour"])

_FAVICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%2308090f'/%3E%3Ctext x='16' y='23' font-family='Georgia,serif' font-size='21' font-weight='500' fill='%23f0ebe3' text-anchor='middle'%3Eo%3C/text%3E%3Cpath d='M20 7 Q24 4 27 8' stroke='%23c87832' stroke-width='2' fill='none' stroke-linecap='round'/%3E%3C/svg%3E"

TOUR_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>The Operator Experience — Oyvoda</title>
<meta name="description" content="See exactly how Oyvoda works for STR operators — pre-booking queue, guest messaging, AI training, and analytics. All in one platform.">
<meta name="theme-color" content="#08090f">
<link rel="icon" type="image/svg+xml" href="FAVICON_PLACEHOLDER">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;0,700;1,400;1,600&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  background: #08090f; color: #f0ebe3;
  font-family: 'DM Sans', -apple-system, sans-serif;
  line-height: 1.6; -webkit-font-smoothing: antialiased;
}

/* ── TOKENS ── */
:root {
  --amber: #c87832; --gold: #e09040; --glow: #f0ac58;
  --green: #22c55e; --red: #ef4444; --yellow: #f59e0b;
  --ink: #08090f; --navy: #0d1220;
  --dim: rgba(240,235,227,0.35); --ghost: rgba(240,235,227,0.6);
  --white: #f0ebe3; --border: rgba(255,255,255,0.06);
}

/* ── NAV ── */
nav {
  position: sticky; top: 0; z-index: 100;
  background: rgba(8,9,15,0.95); backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(200,120,50,0.12);
  height: 64px; padding: 0 48px;
  display: flex; align-items: center; justify-content: space-between;
}
.nav-logo { font-family: 'Cormorant Garamond', serif; font-size: 22px; font-weight: 500; color: var(--white); text-decoration: none; letter-spacing: -0.02em; }
.nav-links { display: flex; align-items: center; gap: 6px; }
.nav-link { color: var(--dim); text-decoration: none; font-size: 14px; padding: 6px 14px; border-radius: 6px; transition: all 0.15s; }
.nav-link:hover { color: var(--white); background: rgba(255,255,255,0.05); }
.nav-right { display: flex; align-items: center; gap: 8px; }
.btn-outline { border: 1px solid rgba(200,120,50,0.4); color: var(--amber); text-decoration: none; font-size: 13px; padding: 8px 20px; border-radius: 8px; transition: all 0.15s; }
.btn-outline:hover { background: rgba(200,120,50,0.08); }
.btn-cta { background: var(--amber); color: var(--white); text-decoration: none; font-size: 13px; font-weight: 600; padding: 9px 22px; border-radius: 9px; transition: all 0.15s; }
.btn-cta:hover { background: var(--gold); transform: translateY(-1px); }

/* ── PAGE LAYOUT with sticky section nav ── */
.page-layout {
  display: grid;
  grid-template-columns: 200px 1fr;
  max-width: 1260px; margin: 0 auto;
  align-items: start;
}
.section-nav {
  position: sticky; top: 80px;
  padding: 48px 0 48px 48px;
  display: flex; flex-direction: column; gap: 4px;
}
.section-nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 14px; border-radius: 8px;
  text-decoration: none; color: rgba(240,235,227,0.7);
  font-family: 'DM Mono', monospace; font-size: 11px;
  letter-spacing: 0.08em; text-transform: uppercase;
  transition: all 0.15s; border: none; background: none; cursor: pointer;
  white-space: nowrap;
}
.section-nav-item:hover, .section-nav-item.active {
  color: var(--amber); background: rgba(200,120,50,0.06);
}
.snav-num { font-size: 10px; opacity: 0.6; width: 18px; flex-shrink: 0; text-align: right; }
.snav-label { flex: 1; }

/* Subtle vertical bar separating nav from content */
.page-content {
  border-left: 1px solid rgba(200,120,50,0.08);
  min-width: 0;
}

/* ── HERO ── */
.hero {
  padding: 100px 72px 80px;
  position: relative; overflow: hidden;
}
.hero-grid {
  position: absolute; inset: 0; z-index: 0;
  background-image:
    linear-gradient(rgba(200,120,50,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(200,120,50,0.025) 1px, transparent 1px);
  background-size: 60px 60px;
}
.hero-glow {
  position: absolute; bottom: -60px; left: 20%; z-index: 0;
  width: 500px; height: 300px;
  background: radial-gradient(ellipse, rgba(200,120,50,0.07) 0%, transparent 70%);
}
.hero-inner { position: relative; z-index: 1; max-width: 760px; }
.hero-eyebrow {
  font-family: 'DM Mono', monospace; font-size: 10px;
  letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--amber); margin-bottom: 20px;
  display: flex; align-items: center; gap: 10px;
}
.hero-eyebrow::after { content: ''; flex: 1; max-width: 40px; height: 1px; background: rgba(200,120,50,0.3); }
h1 {
  font-family: 'Cormorant Garamond', serif;
  font-size: clamp(44px, 5.5vw, 72px); font-weight: 600;
  letter-spacing: -0.025em; line-height: 1.05; color: var(--white);
  margin-bottom: 24px;
}
h1 em { font-style: italic; color: var(--amber); }
.hero-sub {
  font-size: 17px; font-weight: 300; color: var(--ghost);
  line-height: 1.75; max-width: 600px; margin-bottom: 40px;
}
.hero-sub strong { color: var(--white); font-weight: 500; }
.hero-ctas { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.cta-primary {
  background: var(--amber); color: var(--white); text-decoration: none;
  font-size: 14px; font-weight: 600; padding: 13px 28px; border-radius: 10px;
  transition: all 0.15s; display: inline-flex; align-items: center; gap: 8px;
}
.cta-primary:hover { background: var(--gold); transform: translateY(-1px); }
.cta-secondary {
  background: transparent; color: var(--ghost); text-decoration: none;
  font-size: 14px; padding: 13px 28px; border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.12); transition: all 0.15s;
  display: inline-flex; align-items: center; gap: 8px;
}
.cta-secondary:hover { color: var(--white); border-color: rgba(255,255,255,0.25); }

/* ── SECTIONS ── */
.content-section { padding: 80px 72px; border-top: 1px solid var(--border); }
.section-label {
  font-family: 'DM Mono', monospace; font-size: 10px;
  letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--amber); margin-bottom: 16px;
}
.section-step {
  font-family: 'DM Mono', monospace; font-size: 10px;
  letter-spacing: 0.12em; text-transform: uppercase;
  color: rgba(200,120,50,0.5); margin-bottom: 6px;
}
h2 {
  font-family: 'Cormorant Garamond', serif;
  font-size: clamp(32px, 4vw, 52px); font-weight: 600;
  letter-spacing: -0.02em; color: var(--white);
  line-height: 1.1; margin-bottom: 16px;
}
h2 em { font-style: italic; color: var(--amber); }
.section-sub {
  font-size: 15px; color: var(--ghost); line-height: 1.8;
  font-weight: 300; max-width: 600px; margin-bottom: 48px;
}
.section-sub strong { color: var(--white); font-weight: 500; }

/* ── MOCK UI COMPONENTS ── */
/* Shared mock chrome */
.mock-chrome {
  background: #0d1220; border: 1px solid rgba(200,120,50,0.15);
  border-radius: 16px; overflow: hidden;
  box-shadow: 0 24px 80px rgba(0,0,0,0.5);
}
.mock-titlebar {
  background: #0a0f1a; border-bottom: 1px solid rgba(255,255,255,0.05);
  padding: 12px 16px; display: flex; align-items: center; gap: 8px;
}
.mock-dot { width: 10px; height: 10px; border-radius: 50%; }
.mock-dot-r { background: #ef4444; }
.mock-dot-y { background: #f59e0b; }
.mock-dot-g { background: #22c55e; }
.mock-title { font-size: 12px; color: var(--dim); font-family: 'DM Mono', monospace; margin-left: 8px; }

/* Pre-booking split view */
.prebooking-layout {
  display: grid; grid-template-columns: 280px 1fr;
  min-height: 420px;
}
.msg-list { border-right: 1px solid var(--border); }
.msg-item {
  padding: 14px 16px; border-bottom: 1px solid rgba(255,255,255,0.03);
  cursor: pointer; transition: background 0.15s;
}
.msg-item.active { background: rgba(200,120,50,0.06); border-left: 2px solid var(--amber); }
.msg-item:hover:not(.active) { background: rgba(255,255,255,0.02); }
.msg-guest { font-size: 12px; font-weight: 500; color: var(--white); margin-bottom: 2px; }
.msg-preview { font-size: 11px; color: var(--dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.msg-time { font-size: 10px; color: rgba(240,235,227,0.2); font-family: 'DM Mono', monospace; }
.msg-badge {
  display: inline-block; font-size: 9px; font-family: 'DM Mono', monospace;
  letter-spacing: 0.06em; padding: 2px 7px; border-radius: 4px;
  margin-bottom: 4px;
}
.badge-new { background: rgba(200,120,50,0.15); color: var(--amber); }
.badge-draft { background: rgba(34,197,94,0.1); color: var(--green); }

.draft-panel { padding: 20px; display: flex; flex-direction: column; gap: 16px; }
.draft-label {
  font-family: 'DM Mono', monospace; font-size: 9px;
  letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--dim); margin-bottom: 6px;
}
.guest-msg-bubble {
  background: rgba(255,255,255,0.04); border: 1px solid var(--border);
  border-radius: 12px 12px 12px 2px; padding: 12px 14px;
  font-size: 13px; color: var(--ghost); line-height: 1.6;
  max-width: 85%;
}
.ai-draft-box {
  background: rgba(200,120,50,0.04); border: 1px solid rgba(200,120,50,0.2);
  border-radius: 12px; padding: 16px;
}
.ai-draft-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 10px;
}
.ai-chip {
  background: rgba(200,120,50,0.1); color: var(--amber);
  font-family: 'DM Mono', monospace; font-size: 9px;
  letter-spacing: 0.08em; padding: 3px 8px; border-radius: 4px;
}
.confidence-bar {
  flex: 1; background: rgba(255,255,255,0.06); border-radius: 4px; height: 4px;
}
.confidence-fill {
  height: 4px; border-radius: 4px; background: var(--green);
  width: 87%;
}
.confidence-label { font-size: 10px; font-family: 'DM Mono', monospace; color: var(--green); }
.ai-draft-text { font-size: 13px; color: var(--white); line-height: 1.7; }
.draft-actions {
  display: flex; gap: 8px; padding-top: 4px;
}
.action-btn {
  padding: 8px 16px; border-radius: 8px; font-size: 12px;
  font-weight: 500; cursor: pointer; font-family: 'DM Sans', sans-serif;
  border: none; transition: all 0.15s;
}
.action-send { background: var(--amber); color: var(--white); }
.action-send:hover { background: var(--gold); }
.action-edit { background: rgba(255,255,255,0.06); color: var(--ghost); border: 1px solid var(--border); }
.action-edit:hover { background: rgba(255,255,255,0.1); color: var(--white); }
.action-reject { background: transparent; color: var(--dim); border: 1px solid var(--border); }
.learn-note {
  display: flex; align-items: center; gap: 8px;
  font-size: 11px; color: var(--dim); padding-top: 4px;
}
.learn-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--green); flex-shrink: 0; }

/* Session console */
.console-layout { display: grid; grid-template-columns: 240px 1fr 200px; min-height: 400px; }
.session-list { border-right: 1px solid var(--border); }
.session-item {
  padding: 12px 14px; border-bottom: 1px solid rgba(255,255,255,0.03);
  cursor: pointer;
}
.session-item.active { background: rgba(200,120,50,0.05); border-left: 2px solid var(--amber); }
.session-name { font-size: 12px; font-weight: 500; color: var(--white); margin-bottom: 2px; }
.session-prop { font-size: 11px; color: var(--dim); margin-bottom: 3px; }
.session-phase {
  font-size: 9px; font-family: 'DM Mono', monospace; letter-spacing: 0.06em;
  padding: 2px 6px; border-radius: 3px;
}
.phase-in-stay { background: rgba(34,197,94,0.1); color: var(--green); }
.phase-pre { background: rgba(200,120,50,0.1); color: var(--amber); }
.phase-post { background: rgba(255,255,255,0.06); color: var(--dim); }

.chat-area { display: flex; flex-direction: column; padding: 16px; gap: 10px; border-right: 1px solid var(--border); }
.chat-msg { max-width: 80%; }
.chat-msg.guest { align-self: flex-start; }
.chat-msg.ai { align-self: flex-end; }
.chat-bubble-guest {
  background: rgba(255,255,255,0.05); border: 1px solid var(--border);
  border-radius: 12px 12px 12px 2px; padding: 10px 13px;
  font-size: 12px; color: var(--ghost); line-height: 1.5;
}
.chat-bubble-ai {
  background: rgba(200,120,50,0.08); border: 1px solid rgba(200,120,50,0.15);
  border-radius: 12px 12px 2px 12px; padding: 10px 13px;
  font-size: 12px; color: var(--white); line-height: 1.5;
}
.chat-meta { font-size: 10px; color: var(--dim); margin-top: 3px; font-family: 'DM Mono', monospace; }
.chat-esc {
  background: rgba(239,68,68,0.06); border: 1px solid rgba(239,68,68,0.2);
  border-radius: 8px; padding: 10px 13px;
  font-size: 11px; color: var(--red); font-family: 'DM Mono', monospace;
  display: flex; align-items: center; gap: 8px;
}

.session-meta { padding: 16px; font-size: 12px; }
.meta-row { display: flex; flex-direction: column; gap: 3px; margin-bottom: 14px; }
.meta-label { font-family: 'DM Mono', monospace; font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--dim); }
.meta-val { color: var(--ghost); font-size: 12px; }
.meta-val.green { color: var(--green); }
.intent-bar { display: flex; flex-direction: column; gap: 6px; }
.intent-item { display: flex; align-items: center; gap: 8px; }
.intent-label { font-size: 10px; color: var(--dim); width: 80px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.intent-track { flex: 1; background: rgba(255,255,255,0.05); border-radius: 3px; height: 4px; }
.intent-fill { height: 4px; border-radius: 3px; background: var(--amber); }

/* Training UI */
.training-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 0; min-height: 380px; }
.kb-panel { border-right: 1px solid var(--border); padding: 20px; }
.kb-panel-title { font-size: 11px; font-family: 'DM Mono', monospace; letter-spacing: 0.08em; text-transform: uppercase; color: var(--dim); margin-bottom: 14px; }
.kb-entry {
  background: rgba(255,255,255,0.02); border: 1px solid var(--border);
  border-radius: 10px; padding: 12px 14px; margin-bottom: 8px;
}
.kb-q { font-size: 12px; font-weight: 500; color: var(--white); margin-bottom: 4px; }
.kb-a { font-size: 11px; color: var(--ghost); line-height: 1.5; }
.kb-entry-meta {
  display: flex; align-items: center; gap: 8px; margin-top: 8px;
}
.kb-status {
  font-size: 9px; font-family: 'DM Mono', monospace; letter-spacing: 0.06em;
  padding: 2px 7px; border-radius: 3px;
}
.kb-active { background: rgba(34,197,94,0.1); color: var(--green); }
.kb-gap { background: rgba(239,68,68,0.1); color: var(--red); }
.kb-draft { background: rgba(200,120,50,0.1); color: var(--amber); }
.kb-conf { font-size: 10px; color: var(--dim); font-family: 'DM Mono', monospace; margin-left: auto; }
.gap-item {
  background: rgba(239,68,68,0.04); border: 1px solid rgba(239,68,68,0.15);
  border-radius: 10px; padding: 12px 14px; margin-bottom: 8px;
}
.gap-q { font-size: 12px; color: var(--white); margin-bottom: 8px; }
.gap-input {
  background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px; padding: 8px 10px; font-size: 11px;
  color: var(--ghost); width: 100%; margin-bottom: 8px; font-family: 'DM Sans', sans-serif;
}
.gap-save {
  background: var(--amber); color: var(--white); border: none;
  border-radius: 6px; padding: 6px 14px; font-size: 11px;
  font-weight: 600; cursor: pointer; font-family: 'DM Sans', sans-serif;
}

/* Analytics */
.analytics-layout { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; padding: 20px; }
.analytics-layout.two { grid-template-columns: 1fr 1fr; padding: 20px; gap: 12px; }
.metric-card {
  background: rgba(255,255,255,0.02); border: 1px solid var(--border);
  border-radius: 12px; padding: 16px 18px;
}
.metric-card.wide { grid-column: span 3; }
.metric-card.wide-2 { grid-column: span 2; }
.metric-label { font-family: 'DM Mono', monospace; font-size: 9px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--dim); margin-bottom: 8px; }
.metric-value { font-family: 'Cormorant Garamond', serif; font-size: 32px; font-weight: 600; color: var(--white); line-height: 1; }
.metric-value.green { color: var(--green); }
.metric-value.amber { color: var(--amber); }
.metric-sub { font-size: 11px; color: var(--dim); margin-top: 4px; }
.sparkline { display: flex; align-items: flex-end; gap: 3px; height: 32px; margin-top: 10px; }
.spark-bar { flex: 1; border-radius: 2px 2px 0 0; background: rgba(200,120,50,0.3); transition: background 0.15s; }
.spark-bar:hover { background: rgba(200,120,50,0.7); }
.mini-table { width: 100%; }
.mini-table td { font-size: 11px; padding: 5px 0; border-bottom: 1px solid rgba(255,255,255,0.04); color: var(--ghost); }
.mini-table td:last-child { text-align: right; color: var(--dim); font-family: 'DM Mono', monospace; }
.mini-table tr:last-child td { border-bottom: none; }
.learn-track { margin-top: 12px; }
.learn-bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.learn-bar-label { font-size: 10px; color: var(--dim); width: 100px; flex-shrink: 0; }
.learn-bar-track { flex: 1; background: rgba(255,255,255,0.05); border-radius: 3px; height: 5px; }
.learn-bar-fill { height: 5px; border-radius: 3px; }

/* ── CALLOUT BOXES ── */
.callout {
  background: rgba(200,120,50,0.05); border: 1px solid rgba(200,120,50,0.15);
  border-radius: 12px; padding: 20px 24px; margin-top: 32px;
  display: flex; gap: 16px; align-items: flex-start;
}
.callout-icon { font-size: 20px; flex-shrink: 0; margin-top: 2px; }
.callout-title { font-size: 13px; font-weight: 500; color: var(--white); margin-bottom: 4px; }
.callout-body { font-size: 13px; color: var(--ghost); line-height: 1.6; font-weight: 300; }

/* ── STATS STRIP ── */
.stats-strip {
  display: flex; gap: 0;
  border: 1px solid rgba(200,120,50,0.1); border-radius: 14px;
  overflow: hidden; margin-bottom: 48px;
}
.stats-strip-cell {
  flex: 1; padding: 20px 24px; text-align: center;
  border-right: 1px solid rgba(200,120,50,0.06);
}
.stats-strip-cell:last-child { border-right: none; }
.strip-val { font-family: 'Cormorant Garamond', serif; font-size: 32px; font-weight: 600; color: var(--white); line-height: 1; }
.strip-lbl { font-size: 11px; color: var(--dim); margin-top: 4px; letter-spacing: 0.04em; }

/* ── WORKFLOW STEPS ── */
.workflow-steps { display: flex; gap: 0; margin-bottom: 40px; position: relative; }
.workflow-steps::before {
  content: ''; position: absolute;
  top: 22px; left: 28px; right: 28px; height: 1px;
  background: linear-gradient(to right, rgba(200,120,50,0.3), rgba(200,120,50,0.1));
}
.wf-step { flex: 1; text-align: center; position: relative; }
.wf-num {
  width: 44px; height: 44px; border-radius: 50%;
  background: rgba(200,120,50,0.1); border: 1px solid rgba(200,120,50,0.3);
  display: flex; align-items: center; justify-content: center;
  font-family: 'Cormorant Garamond', serif; font-size: 20px; font-weight: 600;
  color: var(--amber); margin: 0 auto 10px; position: relative; z-index: 1;
  background: #08090f;
}
.wf-label { font-size: 12px; font-weight: 500; color: var(--white); margin-bottom: 3px; }
.wf-sub { font-size: 11px; color: var(--dim); font-weight: 300; line-height: 1.5; }

/* ── FINAL CTA ── */
.final-cta {
  padding: 80px 72px; border-top: 1px solid var(--border);
  background: rgba(200,120,50,0.03);
}
.final-cta h2 { font-size: clamp(32px, 4vw, 52px); margin-bottom: 16px; }
.final-cta p { font-size: 16px; color: var(--ghost); font-weight: 300; line-height: 1.7; max-width: 520px; margin-bottom: 32px; }
.final-actions { display: flex; gap: 12px; flex-wrap: wrap; }
.demo-note { font-size: 12px; color: var(--dim); margin-top: 14px; }

/* ── FOOTER ── */
footer {
  padding: 24px 72px; border-top: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
}
.footer-logo { font-family: 'Cormorant Garamond', serif; font-size: 16px; color: var(--dim); text-decoration: none; }
.footer-links { display: flex; gap: 24px; }
.footer-link { font-size: 12px; color: rgba(240,235,227,0.2); text-decoration: none; transition: color 0.15s; }
.footer-link:hover { color: rgba(240,235,227,0.5); }

/* ── RESPONSIVE ── */
@media (max-width: 900px) {
  .page-layout { grid-template-columns: 1fr; }
  .section-nav { display: none; }
  .page-content { border-left: none; }
  nav { padding: 0 20px; }
  .hero, .content-section { padding-left: 24px; padding-right: 24px; }
  .prebooking-layout { grid-template-columns: 1fr; }
  .console-layout { grid-template-columns: 1fr; }
  .training-layout { grid-template-columns: 1fr; }
  .analytics-layout, .analytics-layout.two { grid-template-columns: 1fr 1fr; }
  .metric-card.wide, .metric-card.wide-2 { grid-column: span 2; }
  .workflow-steps { flex-direction: column; gap: 16px; }
  .workflow-steps::before { display: none; }
  footer { flex-direction: column; gap: 12px; padding: 20px 24px; }
}
</style>
</head>
<body>

<!-- ── NAV ── -->
<nav>
  <a href="/" class="nav-logo">oyvoda</a>
  <div class="nav-links">
    <a href="/" class="nav-link">← Platform</a>
    <a href="/engine" class="nav-link">Engine</a>
    <a href="/security" class="nav-link">Security</a>
    <a href="/#pricing" class="nav-link">Pricing</a>
  </div>
  <div class="nav-right">
    <a href="mailto:hello@oyvoda.com" class="btn-outline">Talk to Sales</a>
    <a href="mailto:demo@oyvoda.com" class="btn-cta">Request Demo →</a>
  </div>
</nav>

<!-- ── PAGE LAYOUT ── -->
<div class="page-layout">

  <!-- ── SECTION NAV ── -->
  <nav class="section-nav" id="section-nav">
    <a class="section-nav-item active" href="#overview">
      <span class="snav-num">01</span><span class="snav-label">Overview</span>
    </a>
    <a class="section-nav-item" href="#prebooking">
      <span class="snav-num">02</span><span class="snav-label">Pre-Booking</span>
    </a>
    <a class="section-nav-item" href="#sessions">
      <span class="snav-num">03</span><span class="snav-label">Guest Console</span>
    </a>
    <a class="section-nav-item" href="#training">
      <span class="snav-num">04</span><span class="snav-label">AI Training</span>
    </a>
    <a class="section-nav-item" href="#analytics">
      <span class="snav-num">05</span><span class="snav-label">Analytics</span>
    </a>
  </nav>

  <!-- ── PAGE CONTENT ── -->
  <div class="page-content">

    <!-- ── HERO ── -->
    <section class="hero" id="overview">
      <div class="hero-grid"></div>
      <div class="hero-glow"></div>
      <div class="hero-inner">
        <div class="hero-eyebrow">The Operator Experience</div>
        <h1>Your entire guest operation.<br><em>One screen.</em></h1>
        <p class="hero-sub">
          Oyvoda puts pre-booking inquiries, guest conversations, AI training,
          and performance analytics all in one place — built around
          <strong>how STR operators actually work.</strong> Every message reviewed.
          Every edit remembered. Every interaction making the AI smarter.
        </p>
        <div class="hero-ctas">
          <a href="mailto:demo@oyvoda.com" class="cta-primary">Request a Demo →</a>
          <a href="mailto:hello@oyvoda.com" class="cta-secondary">Talk to Sales</a>
        </div>
      </div>

      <!-- Stats strip -->
      <div class="stats-strip" style="margin-top: 56px;">
        <div class="stats-strip-cell">
          <div class="strip-val">89%</div>
          <div class="strip-lbl">Questions resolved without operator</div>
        </div>
        <div class="stats-strip-cell">
          <div class="strip-val">&lt;200ms</div>
          <div class="strip-lbl">AI response time per message</div>
        </div>
        <div class="stats-strip-cell">
          <div class="strip-val">8.4 min</div>
          <div class="strip-lbl">Saved per guest interaction</div>
        </div>
        <div class="stats-strip-cell">
          <div class="strip-val">Zero</div>
          <div class="strip-lbl">Ungoverned AI actions</div>
        </div>
      </div>
    </section>

    <!-- ── PRE-BOOKING ── -->
    <section class="content-section" id="prebooking">
      <div class="section-label">Workflow 01 · Pre-Booking Queue</div>
      <h2>Inquiry arrives.<br><em>Draft is waiting.</em></h2>
      <p class="section-sub">
        Every Vrbo and Escapia inquiry hits your queue with an
        <strong>AI-drafted reply already written</strong> — grounded in your property
        knowledge, in your voice. You review, edit if needed, and send. Response time
        directly affects your platform ranking. Oyvoda makes it effortless.
      </p>

      <!-- Workflow steps -->
      <div class="workflow-steps">
        <div class="wf-step">
          <div class="wf-num">1</div>
          <div class="wf-label">Inquiry arrives</div>
          <div class="wf-sub">Guest messages via Vrbo or Escapia</div>
        </div>
        <div class="wf-step">
          <div class="wf-num">2</div>
          <div class="wf-label">AI drafts reply</div>
          <div class="wf-sub">In your voice, from your KB</div>
        </div>
        <div class="wf-step">
          <div class="wf-num">3</div>
          <div class="wf-label">You review</div>
          <div class="wf-sub">Send, edit, or reject</div>
        </div>
        <div class="wf-step">
          <div class="wf-num">4</div>
          <div class="wf-label">AI learns</div>
          <div class="wf-sub">Every edit trains your voice</div>
        </div>
      </div>

      <!-- Mock pre-booking UI -->
      <div class="mock-chrome">
        <div class="mock-titlebar">
          <div class="mock-dot mock-dot-r"></div>
          <div class="mock-dot mock-dot-y"></div>
          <div class="mock-dot mock-dot-g"></div>
          <span class="mock-title">Pre-Booking Queue · 3 pending</span>
        </div>
        <div class="prebooking-layout">
          <!-- Inquiry list -->
          <div class="msg-list">
            <div class="msg-item active">
              <div class="msg-badge badge-draft">AI Draft Ready</div>
              <div class="msg-guest">Sarah M.</div>
              <div class="msg-preview">Hi! We're looking at your pr...</div>
              <div class="msg-time">2 min ago · Vrbo</div>
            </div>
            <div class="msg-item">
              <div class="msg-badge badge-new">New Inquiry</div>
              <div class="msg-guest">James & Lisa K.</div>
              <div class="msg-preview">Is the pool heated in March?</div>
              <div class="msg-time">18 min ago · Escapia</div>
            </div>
            <div class="msg-item">
              <div class="msg-badge badge-draft">AI Draft Ready</div>
              <div class="msg-guest">David R.</div>
              <div class="msg-preview">Do you allow early check-in?</div>
              <div class="msg-time">1 hr ago · Vrbo</div>
            </div>
          </div>

          <!-- Draft panel -->
          <div class="draft-panel">
            <div>
              <div class="draft-label">Guest Inquiry — Sarah M. via Vrbo</div>
              <div class="guest-msg-bubble">
                Hi! We're looking at your property for the week of March 15th — 5 adults, no pets. Does the pool heat up quickly? And is there parking for 2 cars? We're driving down from Atlanta.
              </div>
            </div>

            <div class="ai-draft-box">
              <div class="ai-draft-header">
                <span class="ai-chip">AI DRAFT</span>
                <div class="confidence-bar">
                  <div class="confidence-fill"></div>
                </div>
                <span class="confidence-label">87% confidence</span>
              </div>
              <div class="ai-draft-text">
                Hi Sarah! Great news — we'd love to have you for March 15th. The pool is heated and maintains 84°F year-round, so it'll be perfect for your stay. We have 2 dedicated parking spots in the private driveway, with additional street parking available right out front. Atlanta is about a 5-hour drive, so you'll be checking in right around sunset — beautiful time to arrive. Feel free to reach out with any other questions!
              </div>
            </div>

            <div>
              <div class="draft-actions">
                <button class="action-btn action-send">✓ Send Reply</button>
                <button class="action-btn action-edit">✏ Edit Draft</button>
                <button class="action-btn action-reject">✕ Reject</button>
              </div>
              <div class="learn-note">
                <div class="learn-dot"></div>
                Edits you make train the AI to write more like you over time
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="callout">
        <div class="callout-icon">💡</div>
        <div>
          <div class="callout-title">Approval-required mode keeps you in control</div>
          <div class="callout-body">Every AI draft is reviewed by you before sending. As confidence builds, you can advance specific inquiry types to auto-send. The canary rollout system ensures no behavior changes go portfolio-wide without your sign-off.</div>
        </div>
      </div>
    </section>

    <!-- ── GUEST SESSIONS ── -->
    <section class="content-section" id="sessions">
      <div class="section-label">Workflow 02 · Guest Messaging Console</div>
      <h2>Every guest. Every property.<br><em>One place.</em></h2>
      <p class="section-sub">
        Once a guest books, their session opens automatically. Oyvoda handles check-in
        instructions, WiFi codes, restaurant recommendations, and maintenance questions
        <strong>24 hours a day</strong> — escalating to you only when a human is needed,
        with full context already assembled.
      </p>

      <!-- Mock session console -->
      <div class="mock-chrome">
        <div class="mock-titlebar">
          <div class="mock-dot mock-dot-r"></div>
          <div class="mock-dot mock-dot-y"></div>
          <div class="mock-dot mock-dot-g"></div>
          <span class="mock-title">Guest Sessions · 8 active</span>
        </div>
        <div class="console-layout">
          <!-- Session list -->
          <div class="session-list">
            <div class="session-item active">
              <div class="session-name">Marcus & Jenny T.</div>
              <div class="session-prop">34 Seagrove Drive</div>
              <span class="session-phase phase-in-stay">In-Stay</span>
            </div>
            <div class="session-item">
              <div class="session-name">The Williams Family</div>
              <div class="session-prop">Blue Heron Cottage</div>
              <span class="session-phase phase-in-stay">In-Stay</span>
            </div>
            <div class="session-item">
              <div class="session-name">Alex C.</div>
              <div class="session-prop">Rosemary Retreat</div>
              <span class="session-phase phase-pre">Arriving Tomorrow</span>
            </div>
            <div class="session-item">
              <div class="session-name">Diana & Rob M.</div>
              <div class="session-prop">Gulf Pines Unit 4</div>
              <span class="session-phase phase-post">Post-Stay</span>
            </div>
          </div>

          <!-- Chat area -->
          <div class="chat-area">
            <div class="chat-msg guest">
              <div class="chat-bubble-guest">Hey, what's the WiFi password? Can't find it in the welcome book.</div>
              <div class="chat-meta">Marcus · 10:42 PM</div>
            </div>
            <div class="chat-msg ai">
              <div class="chat-bubble-ai">Hi Marcus! Network: SeagroveGuest_5G · Password: Welcome2024! Should connect up to 12 devices. Let me know if you have any trouble!</div>
              <div class="chat-meta">Oyvoda · instant · from KB</div>
            </div>
            <div class="chat-msg guest">
              <div class="chat-bubble-guest">Perfect thanks. Also the AC seems to be making a weird noise?</div>
              <div class="chat-meta">Marcus · 10:49 PM</div>
            </div>
            <div class="chat-esc">
              ⚠ Escalation created · Maintenance · 34 Seagrove Drive · Urgency: Medium
            </div>
            <div class="chat-msg ai">
              <div class="chat-bubble-ai">I've flagged this for our maintenance team and they'll follow up first thing in the morning. In the meantime, you can adjust the fan speed using the wall panel — that sometimes helps. Sorry for the inconvenience!</div>
              <div class="chat-meta">Oyvoda · 10:49 PM · escalated to owner</div>
            </div>
          </div>

          <!-- Session metadata -->
          <div class="session-meta">
            <div class="meta-row">
              <div class="meta-label">Guest</div>
              <div class="meta-val">Marcus & Jenny T.</div>
            </div>
            <div class="meta-row">
              <div class="meta-label">Property</div>
              <div class="meta-val">34 Seagrove Dr</div>
            </div>
            <div class="meta-row">
              <div class="meta-label">Stay</div>
              <div class="meta-val">Mar 18–25</div>
            </div>
            <div class="meta-row">
              <div class="meta-label">Messages</div>
              <div class="meta-val green">12 · 11 AI-handled</div>
            </div>
            <div class="meta-row">
              <div class="meta-label">Intent mix</div>
              <div class="intent-bar">
                <div class="intent-item">
                  <div class="intent-label">Info requests</div>
                  <div class="intent-track"><div class="intent-fill" style="width:70%"></div></div>
                </div>
                <div class="intent-item">
                  <div class="intent-label">Maintenance</div>
                  <div class="intent-track"><div class="intent-fill" style="width:20%;background:var(--red)"></div></div>
                </div>
                <div class="intent-item">
                  <div class="intent-label">Local recs</div>
                  <div class="intent-track"><div class="intent-fill" style="width:10%;background:var(--green)"></div></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="callout">
        <div class="callout-icon">🧠</div>
        <div>
          <div class="callout-title">The SENSE layer reads emotion before routing</div>
          <div class="callout-body">A guest asking about the AC at 11pm gets a different response path than the same question at noon. Oyvoda scores frustration, urgency, and sentiment — then routes accordingly. You're only notified when it matters.</div>
        </div>
      </div>
    </section>

    <!-- ── AI TRAINING ── -->
    <section class="content-section" id="training">
      <div class="section-label">Workflow 03 · AI Training & Knowledge Base</div>
      <h2>Every edit teaches.<br><em>Every gap closes.</em></h2>
      <p class="section-sub">
        When a guest asks something Oyvoda can't answer confidently, it surfaces
        as a <strong>Knowledge Gap</strong> — not a failed response. You approve
        an answer once and every future guest gets it automatically. The more you
        use it, the more it sounds like you.
      </p>

      <!-- Mock training UI -->
      <div class="mock-chrome">
        <div class="mock-titlebar">
          <div class="mock-dot mock-dot-r"></div>
          <div class="mock-dot mock-dot-y"></div>
          <div class="mock-dot mock-dot-g"></div>
          <span class="mock-title">Knowledge Base · 34 Seagrove Drive</span>
        </div>
        <div class="training-layout">
          <!-- KB entries -->
          <div class="kb-panel">
            <div class="kb-panel-title">Active Knowledge · 24 entries</div>

            <div class="kb-entry">
              <div class="kb-q">What is the WiFi password?</div>
              <div class="kb-a">Network: SeagroveGuest_5G · Password: Welcome2024!</div>
              <div class="kb-entry-meta">
                <span class="kb-status kb-active">Active</span>
                <span class="kb-conf">98% confidence</span>
              </div>
            </div>

            <div class="kb-entry">
              <div class="kb-q">What time is check-in?</div>
              <div class="kb-a">Check-in at 4 PM. Early check-in may be available — message us 24hrs ahead.</div>
              <div class="kb-entry-meta">
                <span class="kb-status kb-active">Active</span>
                <span class="kb-conf">95% confidence</span>
              </div>
            </div>

            <div class="kb-entry">
              <div class="kb-q">Is the pool heated?</div>
              <div class="kb-a">Yes — heated to 84°F year-round, available 24/7. No glass near the pool deck.</div>
              <div class="kb-entry-meta">
                <span class="kb-status kb-draft">Edited by you</span>
                <span class="kb-conf">→ AI learned your tone</span>
              </div>
            </div>
          </div>

          <!-- Gap panel -->
          <div class="kb-panel">
            <div class="kb-panel-title">Knowledge Gaps · 2 to close</div>

            <div class="gap-item">
              <div class="gap-q">Is there a kayak or paddleboard rental nearby?</div>
              <input class="gap-input" type="text" placeholder="Type your answer..." value="Yes! Sunrise Watersports is 5 min away on Hwy 30A. They deliver to the beach walkover — just call (850) 555-0192 day before." readonly>
              <button class="gap-save">Save & Activate</button>
            </div>

            <div class="gap-item" style="opacity:0.6">
              <div class="gap-q">Is there a grocery store that delivers?</div>
              <input class="gap-input" type="text" placeholder="Type your answer...">
              <button class="gap-save">Save & Activate</button>
            </div>

            <div style="padding: 14px 0; font-size: 11px; color: var(--dim); line-height: 1.7;">
              Approve an answer once →<br>every future guest asking this<br>gets it automatically.
            </div>
          </div>
        </div>
      </div>

      <div class="callout">
        <div class="callout-icon">🎯</div>
        <div>
          <div class="callout-title">The LEARN layer watches every edit you make</div>
          <div class="callout-body">When you change "Hello" to "Hey there!" the system notes your tone preference. When you add a detail about the parking, it updates that property's knowledge. After 100 interactions, the AI drafts in your voice without being explicitly told how.</div>
        </div>
      </div>
    </section>

    <!-- ── ANALYTICS ── -->
    <section class="content-section" id="analytics">
      <div class="section-label">Workflow 04 · Analytics & Performance</div>
      <h2>Data that drives<br><em>real decisions.</em></h2>
      <p class="section-sub">
        Every interaction generates structured data. See which properties generate
        the most guest questions, which intents the AI handles best, where your
        knowledge gaps cluster, and how your response time compares to your Vrbo ranking.
        <strong>All of it in one dashboard.</strong>
      </p>

      <!-- Mock analytics -->
      <div class="mock-chrome">
        <div class="mock-titlebar">
          <div class="mock-dot mock-dot-r"></div>
          <div class="mock-dot mock-dot-y"></div>
          <div class="mock-dot mock-dot-g"></div>
          <span class="mock-title">Analytics · Last 30 days</span>
        </div>
        <div class="analytics-layout">
          <div class="metric-card">
            <div class="metric-label">AI Resolution Rate</div>
            <div class="metric-value green">89%</div>
            <div class="metric-sub">↑ 4% vs last month</div>
            <div class="sparkline">
              <div class="spark-bar" style="height:40%"></div>
              <div class="spark-bar" style="height:55%"></div>
              <div class="spark-bar" style="height:50%"></div>
              <div class="spark-bar" style="height:65%"></div>
              <div class="spark-bar" style="height:60%"></div>
              <div class="spark-bar" style="height:70%"></div>
              <div class="spark-bar" style="height:75%"></div>
              <div class="spark-bar" style="height:80%"></div>
              <div class="spark-bar" style="height:85%"></div>
              <div class="spark-bar" style="height:89%;background:rgba(200,120,50,0.7)"></div>
            </div>
          </div>

          <div class="metric-card">
            <div class="metric-label">Avg Response Time</div>
            <div class="metric-value">180ms</div>
            <div class="metric-sub">SLO target: &lt;1200ms</div>
          </div>

          <div class="metric-card">
            <div class="metric-label">Pre-Booking Sent</div>
            <div class="metric-value amber">47</div>
            <div class="metric-sub">12 edited · 35 sent as-is</div>
          </div>

          <div class="metric-card wide">
            <div class="metric-label">Top Guest Intents · This Month</div>
            <table class="mini-table">
              <tr><td>📶 WiFi & connectivity</td><td>31%</td></tr>
              <tr><td>⏰ Check-in / check-out</td><td>22%</td></tr>
              <tr><td>🏊 Pool & amenities</td><td>18%</td></tr>
              <tr><td>🍽️ Restaurant recommendations</td><td>14%</td></tr>
              <tr><td>🔑 Access & parking</td><td>11%</td></tr>
              <tr><td>🚨 Maintenance / escalations</td><td>4%</td></tr>
            </table>
          </div>

          <div class="metric-card wide-2">
            <div class="metric-label">LEARN Layer Progress · Voice Matching</div>
            <div class="metric-sub" style="margin-bottom:12px">How closely the AI drafts match your actual sent messages</div>
            <div class="learn-track">
              <div class="learn-bar-row">
                <div class="learn-bar-label">Tone & warmth</div>
                <div class="learn-bar-track"><div class="learn-bar-fill" style="width:82%;background:var(--green)"></div></div>
                <span style="font-size:10px;color:var(--green);font-family:'DM Mono',monospace;margin-left:6px">82%</span>
              </div>
              <div class="learn-bar-row">
                <div class="learn-bar-label">Policy accuracy</div>
                <div class="learn-bar-track"><div class="learn-bar-fill" style="width:94%;background:var(--green)"></div></div>
                <span style="font-size:10px;color:var(--green);font-family:'DM Mono',monospace;margin-left:6px">94%</span>
              </div>
              <div class="learn-bar-row">
                <div class="learn-bar-label">Local knowledge</div>
                <div class="learn-bar-track"><div class="learn-bar-fill" style="width:71%;background:var(--amber)"></div></div>
                <span style="font-size:10px;color:var(--amber);font-family:'DM Mono',monospace;margin-left:6px">71%</span>
              </div>
              <div class="learn-bar-row">
                <div class="learn-bar-label">Edit frequency</div>
                <div class="learn-bar-track"><div class="learn-bar-fill" style="width:35%;background:var(--amber)"></div></div>
                <span style="font-size:10px;color:var(--dim);font-family:'DM Mono',monospace;margin-left:6px">↓ improving</span>
              </div>
            </div>
          </div>

          <div class="metric-card">
            <div class="metric-label">Escalations</div>
            <div class="metric-value" style="color:var(--red)">3</div>
            <div class="metric-sub">Avg resolve: 18 min</div>
          </div>
        </div>
      </div>

      <div class="callout">
        <div class="callout-icon">📊</div>
        <div>
          <div class="callout-title">Full audit trail — exportable any time</div>
          <div class="callout-body">Every guest message, AI decision, operator edit, and knowledge base change is logged with timestamps and metadata. Export as CSV or JSON for your records, your accountant, or your property management software.</div>
        </div>
      </div>
    </section>

    <!-- ── FINAL CTA ── -->
    <section class="final-cta">
      <div class="section-label">Ready to get started</div>
      <h2>See it working on<br><em>your properties.</em></h2>
      <p>We'll walk through your PMS integration, set up your first property's knowledge base, and show you a live pre-booking draft generated from a real inquiry. Most operators are live within 48 hours.</p>
      <div class="final-actions">
        <a href="mailto:demo@oyvoda.com" class="cta-primary">Request a Demo →</a>
        <a href="mailto:hello@oyvoda.com" class="cta-secondary">Talk to Sales</a>
      </div>
      <div class="demo-note">Or explore the architecture: <a href="/engine" style="color:var(--amber)">Read the Engine docs →</a></div>
    </section>

    <!-- ── FOOTER ── -->
    <footer>
      <a href="/" class="footer-logo">oyvoda</a>
      <div class="footer-links">
        <a href="/" class="footer-link">Platform</a>
        <a href="/engine" class="footer-link">Engine</a>
        <a href="/security" class="footer-link">Security</a>
        <a href="/privacy" class="footer-link">Privacy</a>
        <a href="/signup" class="footer-link">Get Started</a>
        <a href="/app" class="footer-link">Sign In</a>
      </div>
    </footer>

  </div><!-- end page-content -->
</div><!-- end page-layout -->

<script>
// Scroll spy for section nav
(function() {
  const sections = ['overview','prebooking','sessions','training','analytics'];
  const navItems = {};
  sections.forEach(function(id) {
    navItems[id] = document.querySelector('.section-nav-item[href="#' + id + '"]');
  });
  function onScroll() {
    let current = sections[0];
    sections.forEach(function(id) {
      const el = document.getElementById(id);
      if (el && window.scrollY >= el.offsetTop - 120) current = id;
    });
    sections.forEach(function(id) {
      if (navItems[id]) navItems[id].classList.toggle('active', id === current);
    });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
})();
</script>

</body>
</html>""".replace("FAVICON_PLACEHOLDER", _FAVICON)


@router.get("/operator-dashboard", response_class=HTMLResponse, include_in_schema=False)
async def serve_operator_tour():
    from app.api.v1.endpoints.shared_nav import nav_html, _NAV_CSS
    html = TOUR_HTML
    # Replace the existing nav block with shared nav
    import re
    html = re.sub(r'<!-- ─+ NAV.*?</nav>', nav_html('operator'), html, flags=re.DOTALL)
    # Inject shared nav CSS
    html = html.replace('</style>\n</head>', _NAV_CSS + '\n</style>\n</head>', 1)
    return HTMLResponse(content=html)
