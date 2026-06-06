"""
public_landing.py — Oyvoda Public Marketing Landing Page

Served at GET /

Full marketing site with dropdown navigation, product overview,
feature deep-dives, social proof, and CTA to start trial.
Replaces the redirect to /operator-dashboard.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Public"])

_FAVICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%2308090f'/%3E%3Ctext x='16' y='23' font-family='Georgia,serif' font-size='21' font-weight='500' fill='%23f0ebe3' text-anchor='middle'%3Eo%3C/text%3E%3Cpath d='M20 7 Q24 4 27 8' stroke='%23c87832' stroke-width='2' fill='none' stroke-linecap='round'/%3E%3C/svg%3E"

LANDING_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Oyvoda — Professional Hospitality for the Private Stay</title>
<meta name="description" content="AI-powered, RCS-first guest experience platform for STR operators and boutique hotels. White-labeled to your brand, synced to any PMS. 89% of questions resolved automatically.">
<meta name="theme-color" content="#08090f">
<meta property="og:type" content="website">
<meta property="og:url" content="https://oyvoda.com/">
<meta property="og:title" content="Oyvoda — Professional Hospitality for the Private Stay">
<meta property="og:description" content="AI-powered guest experience for STR operators. RCS-first, white-labeled, synced to any PMS.">
<meta property="og:image" content="https://oyvoda-production.up.railway.app/static/og-image.svg">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Oyvoda — Professional Hospitality for the Private Stay">
<meta name="twitter:image" content="https://oyvoda-production.up.railway.app/static/og-image.svg">
<link rel="icon" type="image/svg+xml" href="{_FAVICON}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;0,700;1,400;1,600&family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
/* ── RESET & BASE ── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scroll-behavior: smooth; }}
body {{
  background: #08090f; color: #f0ebe3;
  font-family: 'DM Sans', -apple-system, sans-serif;
  line-height: 1.6; -webkit-font-smoothing: antialiased;
}}

/* ── TOKENS ── */
:root {{
  --ink: #08090f; --navy: #0d1220; --slate: #171f30;
  --mid: #1f2d44; --muted: #374d6a; --dim: #5a7090;
  --ghost: #8a9dba; --pale: #dde5f0; --white: #f4f6fa;
  --amber: #c87832; --gold: #e09040; --glow: #f0ac58;
  --green: #22c55e; --red: #ef4444;
}}

/* ── TOPBAR NAV ── */
.topbar {{
  position: sticky; top: 0; z-index: 200;
  background: rgba(8,9,15,0.95); backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(200,120,50,0.12);
  height: 64px; padding: 0 48px;
  display: flex; align-items: center; justify-content: space-between;
}}
.nav-logo {{
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-size: 24px; font-weight: 500; color: #f0ebe3;
  text-decoration: none; letter-spacing: -0.02em;
}}
.nav-center {{ display: flex; align-items: center; gap: 2px; }}

/* Top-level nav items */
.nav-item {{
  position: relative;
  display: flex; align-items: center; gap: 5px;
  padding: 8px 14px; border-radius: 8px;
  font-size: 14px; font-weight: 400; color: rgba(240,235,227,0.6);
  text-decoration: none; cursor: pointer;
  border: none; background: none;
  transition: color 0.15s, background 0.15s;
  white-space: nowrap;
}}
.nav-item:hover {{ color: #f0ebe3; background: rgba(255,255,255,0.05); }}
.nav-item .chevron {{
  font-size: 9px; opacity: 0.5;
  transition: transform 0.2s;
}}
.nav-item:hover .chevron {{ transform: rotate(180deg); opacity: 0.8; }}

/* Dropdown panels */
.nav-item .dropdown {{
  display: none;
  position: absolute; top: 100%; left: 0;
  background: #0d1220; border: 1px solid rgba(200,120,50,0.15);
  border-radius: 16px; padding: 8px;
  min-width: 260px; box-shadow: 0 24px 60px rgba(0,0,0,0.6);
  z-index: 300;
}}
.nav-item .dropdown.wide {{ min-width: 520px; display: none; }}
.nav-item .dropdown.wide .dd-grid {{
  display: grid; grid-template-columns: 1fr 1fr; gap: 4px;
}}
.nav-item:hover .dropdown,
.nav-item .dropdown:hover,
.nav-item.open .dropdown {{ display: block; }}
/* Bridge gap so mouse doesn’t lose hover */
.nav-item {{ padding-bottom: 8px; margin-bottom: -8px; }}
.dd-item {{
  display: flex; gap: 12px; align-items: flex-start;
  padding: 12px 14px; border-radius: 10px;
  text-decoration: none; color: inherit;
  transition: background 0.15s;
}}
.dd-item:hover {{ background: rgba(200,120,50,0.08); }}
.dd-icon {{
  width: 34px; height: 34px; border-radius: 8px;
  background: rgba(200,120,50,0.1); flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 15px;
}}
.dd-text h4 {{
  font-size: 13px; font-weight: 500; color: #f0ebe3;
  margin-bottom: 2px;
}}
.dd-text p {{
  font-size: 12px; color: rgba(240,235,227,0.4);
  line-height: 1.4; font-weight: 300;
}}
.dd-divider {{
  border: none; border-top: 1px solid rgba(255,255,255,0.06);
  margin: 6px 8px;
}}
.dd-footer {{
  padding: 10px 14px; font-size: 12px;
  color: rgba(240,235,227,0.35);
  display: flex; align-items: center; justify-content: space-between;
}}
.dd-footer a {{ color: var(--amber); text-decoration: none; font-weight: 500; }}
.dd-section-label {{
  padding: 6px 14px 4px;
  font-family: 'DM Mono', monospace;
  font-size: 9px; letter-spacing: 0.14em;
  text-transform: uppercase; color: rgba(240,235,227,0.25);
}}

.nav-right {{ display: flex; align-items: center; gap: 8px; }}
.nav-login {{
  font-size: 13px; color: rgba(240,235,227,0.5);
  text-decoration: none; padding: 8px 16px; border-radius: 8px;
  transition: color 0.15s;
}}
.nav-login:hover {{ color: #f0ebe3; }}
.nav-cta {{
  background: var(--amber); color: #f0ebe3;
  text-decoration: none; font-size: 13px; font-weight: 600;
  padding: 9px 22px; border-radius: 9px;
  transition: background 0.15s, transform 0.15s;
}}
.nav-cta:hover {{ background: var(--gold); transform: translateY(-1px); }}

/* ── HERO ── */
.hero {{
  padding: 100px 48px 80px;
  text-align: center; position: relative; overflow: hidden;
}}
.hero-grid-bg {{
  position: absolute; inset: 0; z-index: 0;
  background-image: linear-gradient(rgba(200,120,50,0.03) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(200,120,50,0.03) 1px, transparent 1px);
  background-size: 60px 60px;
}}
.hero-glow {{
  position: absolute; bottom: -100px; left: 50%; transform: translateX(-50%);
  width: 600px; height: 400px;
  background: radial-gradient(ellipse, rgba(200,120,50,0.08) 0%, transparent 70%);
  z-index: 0;
}}
.hero-content {{ position: relative; z-index: 1; max-width: 860px; margin: 0 auto; }}
.hero-badge {{
  display: inline-flex; align-items: center; gap: 8px;
  background: rgba(200,120,50,0.1); border: 1px solid rgba(200,120,50,0.25);
  border-radius: 20px; padding: 6px 16px; margin-bottom: 28px;
  font-family: 'DM Mono', monospace; font-size: 11px;
  letter-spacing: 0.1em; text-transform: uppercase; color: var(--amber);
}}
.hero-title {{
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-size: clamp(48px, 7vw, 88px); font-weight: 600;
  letter-spacing: -0.03em; line-height: 1.05; color: #f0ebe3;
  margin-bottom: 24px;
}}
.hero-title em {{ font-style: italic; color: var(--amber); }}
.hero-sub {{
  font-size: 18px; font-weight: 300; color: rgba(240,235,227,0.6);
  max-width: 580px; margin: 0 auto 44px; line-height: 1.7;
}}
.hero-sub strong {{ color: rgba(240,235,227,0.85); font-weight: 500; }}
.hero-actions {{ display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; margin-bottom: 64px; }}
.btn-primary {{
  background: var(--amber); color: #f0ebe3; text-decoration: none;
  font-size: 15px; font-weight: 600; padding: 14px 32px; border-radius: 10px;
  transition: background 0.15s, transform 0.15s;
  display: inline-flex; align-items: center; gap: 8px;
}}
.btn-primary:hover {{ background: var(--gold); transform: translateY(-2px); }}
.btn-ghost {{
  background: transparent; color: rgba(240,235,227,0.7); text-decoration: none;
  font-size: 15px; font-weight: 400; padding: 14px 32px; border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.12);
  transition: color 0.15s, border-color 0.15s;
  display: inline-flex; align-items: center; gap: 8px;
}}
.btn-ghost:hover {{ color: #f0ebe3; border-color: rgba(255,255,255,0.25); }}

/* ── STAT BAR ── */
.stat-bar {{
  display: flex; gap: 0;
  border: 1px solid rgba(200,120,50,0.12);
  border-radius: 14px; overflow: hidden;
  max-width: 700px; margin: 0 auto;
}}
.stat-cell {{
  flex: 1; padding: 22px 24px; text-align: center;
  border-right: 1px solid rgba(200,120,50,0.08);
}}
.stat-cell:last-child {{ border-right: none; }}
.stat-val {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 34px; font-weight: 600; color: #f0ebe3;
  letter-spacing: -0.02em; line-height: 1;
}}
.stat-lbl {{
  font-size: 11px; color: rgba(240,235,227,0.35);
  margin-top: 5px; letter-spacing: 0.06em; text-transform: uppercase;
}}

/* ── SECTIONS ── */
.section {{ padding: 80px 48px; max-width: 1100px; margin: 0 auto; }}
.section-divider {{ border: none; border-top: 1px solid rgba(255,255,255,0.05); }}
.eyebrow {{
  font-family: 'DM Mono', monospace; font-size: 10px;
  letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--amber); margin-bottom: 16px;
}}
.section-title {{
  font-family: 'Cormorant Garamond', serif;
  font-size: clamp(32px, 4vw, 52px); font-weight: 600;
  letter-spacing: -0.02em; color: #f0ebe3;
  line-height: 1.1; margin-bottom: 16px;
}}
.section-title em {{ font-style: italic; color: var(--amber); }}
.section-sub {{
  font-size: 16px; color: rgba(240,235,227,0.55);
  max-width: 580px; line-height: 1.75; font-weight: 300;
  margin-bottom: 48px;
}}

/* ── LAYER PIPELINE ── */
.pipeline {{
  display: grid; grid-template-columns: repeat(5, 1fr);
  gap: 8px; margin-bottom: 64px;
}}
.pipe-node {{
  background: rgba(200,120,50,0.04); border: 1px solid rgba(200,120,50,0.15);
  border-radius: 12px; padding: 20px 16px; text-align: center;
  transition: border-color 0.2s, background 0.2s;
  cursor: default;
}}
.pipe-node:hover {{
  border-color: rgba(200,120,50,0.4); background: rgba(200,120,50,0.08);
}}
.pipe-name {{
  font-family: 'DM Mono', monospace; font-size: 12px;
  font-weight: 500; color: var(--amber); letter-spacing: 0.08em;
  margin-bottom: 4px;
}}
.pipe-sub {{ font-size: 11px; color: rgba(240,235,227,0.35); }}

/* ── FEATURE GRID ── */
.feature-grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
}}
.feat-card {{
  background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06);
  border-radius: 16px; padding: 28px;
  transition: border-color 0.2s;
}}
.feat-card:hover {{ border-color: rgba(200,120,50,0.2); }}
.feat-icon {{ font-size: 24px; margin-bottom: 14px; }}
.feat-title {{
  font-size: 15px; font-weight: 500; color: #f0ebe3;
  margin-bottom: 8px; letter-spacing: -0.01em;
}}
.feat-body {{ font-size: 13px; color: rgba(240,235,227,0.5); line-height: 1.65; font-weight: 300; }}

/* ── CHANNEL GRID ── */
.channel-grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px; margin-top: 40px;
}}
.channel-card {{
  background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px; padding: 20px;
  display: flex; align-items: center; gap: 12px;
}}
.channel-icon {{ font-size: 20px; }}
.channel-name {{ font-size: 13px; font-weight: 500; color: rgba(240,235,227,0.8); }}
.channel-status {{
  font-size: 10px; font-family: 'DM Mono', monospace;
  letter-spacing: 0.08em; text-transform: uppercase;
  margin-top: 2px;
}}
.channel-status.live {{ color: #22c55e; }}
.channel-status.soon {{ color: var(--amber); }}

/* ── COMPARISON ── */
.compare-table {{
  width: 100%; border-collapse: collapse;
  border: 1px solid rgba(200,120,50,0.1);
  border-radius: 16px; overflow: hidden;
  margin-top: 40px;
}}
.compare-table th {{
  padding: 14px 20px; font-size: 11px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  border-bottom: 1px solid rgba(255,255,255,0.05); text-align: left;
}}
.compare-table th.ours {{ color: var(--amber); background: rgba(200,120,50,0.06); }}
.compare-table th.theirs {{ color: rgba(240,235,227,0.3); }}
.compare-table td {{
  padding: 14px 20px; font-size: 13px; color: rgba(240,235,227,0.6);
  border-bottom: 1px solid rgba(255,255,255,0.03);
  line-height: 1.4;
}}
.compare-table td:first-child {{
  font-size: 12px; font-weight: 500; color: rgba(240,235,227,0.4);
}}
.compare-table td.ours {{ color: rgba(240,235,227,0.85); background: rgba(200,120,50,0.02); }}
.compare-table tr:last-child td {{ border-bottom: none; }}
.chk {{ color: var(--amber); font-weight: 700; }}
.crs {{ color: rgba(240,235,227,0.15); }}

/* ── PMS LOGOS ── */
.pms-row {{
  display: flex; flex-wrap: wrap; gap: 12px;
  align-items: center; margin-top: 40px;
}}
.pms-badge {{
  background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08);
  border-radius: 10px; padding: 12px 20px;
  font-family: 'DM Mono', monospace; font-size: 12px;
  color: rgba(240,235,227,0.5); letter-spacing: 0.04em;
  display: flex; align-items: center; gap: 8px;
}}
.pms-badge .dot {{ width: 6px; height: 6px; border-radius: 50%; background: #22c55e; }}

/* ── PRICING CARDS ── */
.pricing-grid {{
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 14px; margin-top: 48px;
}}
.price-card {{
  background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07);
  border-radius: 20px; padding: 28px;
  transition: border-color 0.2s;
}}
.price-card.featured {{
  border-color: rgba(200,120,50,0.35); background: rgba(200,120,50,0.04);
  position: relative;
}}
.price-card.featured::before {{
  content: 'MOST POPULAR';
  position: absolute; top: -1px; left: 50%; transform: translateX(-50%);
  background: var(--amber); color: #f0ebe3;
  font-family: 'DM Mono', monospace; font-size: 9px;
  letter-spacing: 0.12em; padding: 4px 14px;
  border-radius: 0 0 8px 8px;
}}
.price-tier {{
  font-family: 'DM Mono', monospace; font-size: 10px;
  letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--amber); margin-bottom: 14px;
}}
.price-amount {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 42px; font-weight: 600; color: #f0ebe3;
  letter-spacing: -0.03em; line-height: 1;
}}
.price-unit {{ font-size: 13px; color: rgba(240,235,227,0.4); margin-bottom: 2px; font-family: 'DM Sans'; }}
.price-per-unit {{
  font-size: 13px; color: rgba(200,120,50,0.8); margin-bottom: 4px;
  font-family: 'DM Mono', monospace; font-size: 11px;
  letter-spacing: 0.04em;
}}
.price-props {{ font-size: 12px; color: rgba(240,235,227,0.35); margin-bottom: 20px; }}
.price-divider {{ border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 16px 0; }}
.price-features {{ list-style: none; display: flex; flex-direction: column; gap: 9px; margin-bottom: 24px; }}
.price-features li {{
  font-size: 12px; color: rgba(240,235,227,0.6);
  display: flex; gap: 8px; align-items: flex-start; font-weight: 300;
}}
.price-features li::before {{ content: '✓'; color: var(--amber); font-weight: 600; flex-shrink: 0; }}
.price-features li.muted {{ color: rgba(240,235,227,0.3); }}
.price-features li.muted::before {{ color: rgba(240,235,227,0.15); }}
.price-cta {{
  display: block; text-align: center; text-decoration: none;
  padding: 11px; border-radius: 10px; font-size: 13px; font-weight: 500;
  transition: all 0.15s;
  border: 1px solid rgba(200,120,50,0.3); color: var(--amber);
}}
.price-card.featured .price-cta {{
  background: var(--amber); color: #f0ebe3; border-color: transparent;
}}
.price-cta:hover {{ background: var(--amber); color: #f0ebe3; border-color: transparent; }}

/* ── FOUNDER QUOTE ── */
.founder-block {{
  background: rgba(200,120,50,0.05); border: 1px solid rgba(200,120,50,0.15);
  border-radius: 20px; padding: 48px;
  display: grid; grid-template-columns: 1fr auto;
  gap: 48px; align-items: center;
  max-width: 1100px; margin: 0 auto;
}}
.founder-quote {{
  font-family: 'Cormorant Garamond', serif;
  font-size: clamp(20px, 3vw, 28px); font-weight: 400; font-style: italic;
  color: #f0ebe3; line-height: 1.5;
  position: relative; padding-left: 24px;
}}
.founder-quote::before {{
  content: '"'; position: absolute; left: 0; top: -8px;
  font-size: 60px; color: rgba(200,120,50,0.4); line-height: 1;
}}
.founder-meta {{ text-align: right; flex-shrink: 0; }}
.founder-name {{ font-size: 14px; font-weight: 500; color: #f0ebe3; margin-bottom: 4px; }}
.founder-role {{ font-size: 12px; color: rgba(240,235,227,0.4); letter-spacing: 0.04em; }}
.founder-badge {{
  display: inline-flex; align-items: center; gap: 6px;
  background: rgba(200,120,50,0.1); border: 1px solid rgba(200,120,50,0.2);
  border-radius: 16px; padding: 4px 12px; margin-top: 8px;
  font-family: 'DM Mono', monospace; font-size: 10px;
  color: var(--amber); letter-spacing: 0.06em;
}}

/* ── FINAL CTA ── */
.final-cta {{
  padding: 100px 48px; text-align: center;
  border-top: 1px solid rgba(255,255,255,0.05);
}}
.final-cta h2 {{
  font-family: 'Cormorant Garamond', serif;
  font-size: clamp(36px, 5vw, 64px); font-weight: 600;
  letter-spacing: -0.03em; color: #f0ebe3;
  margin-bottom: 20px; line-height: 1.1;
}}
.final-cta h2 em {{ font-style: italic; color: var(--amber); }}
.final-cta p {{
  font-size: 16px; color: rgba(240,235,227,0.5);
  max-width: 480px; margin: 0 auto 40px;
  line-height: 1.7; font-weight: 300;
}}
.final-cta-actions {{ display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }}

/* ── FOOTER ── */
.site-footer {{
  border-top: 1px solid rgba(255,255,255,0.05);
  padding: 48px 48px 32px;
}}
.footer-top {{
  display: grid; grid-template-columns: 2fr 1fr 1fr 1fr 1fr;
  gap: 48px; margin-bottom: 48px;
}}
.footer-brand {{ }}
.footer-logo {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 22px; font-weight: 500; color: #f0ebe3;
  text-decoration: none; display: block; margin-bottom: 12px;
}}
.footer-tagline {{ font-size: 13px; color: rgba(240,235,227,0.35); line-height: 1.6; max-width: 220px; font-weight: 300; }}
.footer-col h4 {{
  font-family: 'DM Mono', monospace; font-size: 10px;
  letter-spacing: 0.12em; text-transform: uppercase;
  color: rgba(240,235,227,0.3); margin-bottom: 16px;
}}
.footer-col a {{
  display: block; font-size: 13px; color: rgba(240,235,227,0.45);
  text-decoration: none; margin-bottom: 10px;
  transition: color 0.15s; font-weight: 300;
}}
.footer-col a:hover {{ color: rgba(240,235,227,0.8); }}
.footer-bottom {{
  display: flex; justify-content: space-between; align-items: center;
  padding-top: 24px; border-top: 1px solid rgba(255,255,255,0.04);
  flex-wrap: wrap; gap: 12px;
}}
.footer-copy {{ font-size: 12px; color: rgba(240,235,227,0.2); }}
.footer-legal {{ display: flex; gap: 24px; }}
.footer-legal a {{ font-size: 12px; color: rgba(240,235,227,0.2); text-decoration: none; }}
.footer-legal a:hover {{ color: rgba(240,235,227,0.5); }}

/* ── RESPONSIVE ── */
@media (max-width: 900px) {{
  .topbar {{ padding: 0 20px; }}
  .nav-center {{ display: none; }}
  .hero {{ padding: 80px 20px 60px; }}
  .section {{ padding: 60px 20px; }}
  .pipeline {{ grid-template-columns: repeat(3, 1fr); }}
  .pricing-grid {{ grid-template-columns: repeat(2, 1fr); }}
  .founder-block {{ grid-template-columns: 1fr; gap: 24px; }}
  .founder-meta {{ text-align: left; }}
  .footer-top {{ grid-template-columns: 1fr 1fr; gap: 32px; }}
  .footer-brand {{ grid-column: 1 / -1; }}
  .final-cta {{ padding: 60px 20px; }}
  .site-footer {{ padding: 40px 20px 24px; }}
}}
</style>
</head>
<body>

<!-- ── TOPBAR ── -->
<header class="topbar">
  <a href="/" class="nav-logo" style="text-decoration:none;">oyvoda</a>

  <nav class="nav-center">

    <!-- Product dropdown -->
    <div class="nav-item">
      Product <span class="chevron">▾</span>
      <div class="dropdown wide">
        <div class="dd-section-label">Platform</div>
        <div class="dd-grid">
          <a href="/engine#architecture" class="dd-item">
            <div class="dd-icon">🧠</div>
            <div class="dd-text">
              <h4>The Oyvoda Engine</h4>
              <p>Five-layer AI architecture built for STR hospitality</p>
            </div>
          </a>
          <a href="/engine#technology" class="dd-item">
            <div class="dd-icon">⚡</div>
            <div class="dd-text">
              <h4>Technical Specs</h4>
              <p>Groq inference, RAG, 9 MCP servers, Supabase</p>
            </div>
          </a>
          <a href="/#features" class="dd-item">
            <div class="dd-icon">✨</div>
            <div class="dd-text">
              <h4>Features</h4>
              <p>Pre-booking AI, guest concierge, escalation, analytics</p>
            </div>
          </a>
          <a href="/#channels" class="dd-item">
            <div class="dd-icon">📡</div>
            <div class="dd-text">
              <h4>Channels</h4>
              <p>RCS, SMS, email, voice — all under one platform</p>
            </div>
          </a>
        </div>
        <hr class="dd-divider">
        <div class="dd-footer">
          <span>Built by STR operators, for STR operators</span>
          <a href="/engine">Full architecture →</a>
        </div>
      </div>
    </div>

    <!-- Solutions dropdown -->
    <div class="nav-item">
      Solutions <span class="chevron">▾</span>
      <div class="dropdown">
        <div class="dd-section-label">By Role</div>
        <a href="/#operators" class="dd-item">
          <div class="dd-icon">🏡</div>
          <div class="dd-text">
            <h4>STR Operators</h4>
            <p>Manage 10–500 units with AI handling guest comms</p>
          </div>
        </a>
        <a href="/#vendors" class="dd-item">
          <div class="dd-icon">🤝</div>
          <div class="dd-text">
            <h4>Local Vendors</h4>
            <p>Get in front of guests the moment they're ready to book</p>
          </div>
        </a>
        <hr class="dd-divider">
        <div class="dd-section-label">By PMS</div>
        <a href="/#pms" class="dd-item" style="padding: 8px 14px;">
          <div class="dd-text">
            <p style="color: rgba(240,235,227,0.6);">Escapia · Guesty · Track · More on request</p>
          </div>
        </a>
      </div>
    </div>

    <!-- Trust dropdown -->
    <div class="nav-item">
      Trust <span class="chevron">▾</span>
      <div class="dropdown">
        <a href="/security" class="dd-item">
          <div class="dd-icon">🔒</div>
          <div class="dd-text">
            <h4>Security & Compliance</h4>
            <p>Architecture, certifications, audit capabilities</p>
          </div>
        </a>
        <a href="/privacy" class="dd-item">
          <div class="dd-icon">🛡️</div>
          <div class="dd-text">
            <h4>Privacy Policy</h4>
            <p>Data handling, retention, GDPR/CCPA rights</p>
          </div>
        </a>
        <a href="/engine#built-by" class="dd-item">
          <div class="dd-icon">🏖️</div>
          <div class="dd-text">
            <h4>Built by Operators</h4>
            <p>30A Florida · 50 units · Escapia · Real feedback</p>
          </div>
        </a>
        <hr class="dd-divider">
        <a href="/api/v1/audit/summary" class="dd-item" style="padding: 8px 14px;">
          <div class="dd-text">
            <p style="color: rgba(240,235,227,0.5); font-size: 12px;">Audit API · Hallucination Guard · SOC 2 in progress</p>
          </div>
        </a>
      </div>
    </div>

    <!-- Resources dropdown -->
    <div class="nav-item">
      Resources <span class="chevron">▾</span>
      <div class="dropdown">
        <a href="/engine" class="dd-item">
          <div class="dd-icon">📐</div>
          <div class="dd-text">
            <h4>Engine Overview</h4>
            <p>Full architecture documentation with FAQ</p>
          </div>
        </a>
        <a href="/docs" class="dd-item">
          <div class="dd-icon">📖</div>
          <div class="dd-text">
            <h4>API Reference</h4>
            <p>Interactive API docs for developers and integrators</p>
          </div>
        </a>
        <a href="/security#audit" class="dd-item">
          <div class="dd-icon">📊</div>
          <div class="dd-text">
            <h4>Audit & Export</h4>
            <p>Download full audit trails — CSV or JSON</p>
          </div>
        </a>
        <hr class="dd-divider">
        <a href="mailto:hello@oyvoda.com" class="dd-item" style="padding: 8px 14px;">
          <div class="dd-text">
            <p style="color: rgba(240,235,227,0.5); font-size: 12px;">📧 hello@oyvoda.com — we respond same day</p>
          </div>
        </a>
      </div>
    </div>

    <!-- How It Works link -->
    <a href="/operator-dashboard" class="nav-item">How It Works</a>

    <!-- Pricing link -->
    <a href="/#pricing" class="nav-item">Pricing</a>

  </nav>

  <div class="nav-right">
    <a href="/app" class="nav-login">Log in</a>
    <a href="/signup" class="nav-cta">Get Started →</a>
  </div>
</header>

<!-- ── HERO ── -->
<section class="hero">
  <div class="hero-grid-bg"></div>
  <div class="hero-glow"></div>
  <div class="hero-content">
    <div class="hero-badge">✦ RCS-first · White-labeled · PMS-native</div>
    <h1 class="hero-title">
      Professional Hospitality<br>
      <em>for the Private Stay.</em>
    </h1>
    <p class="hero-sub">
      Your AI co-host handles guest questions, surfaces local experiences,
      and manages pre-booking inquiries — <strong>24/7, under your brand,
      via RCS.</strong> No app. No friction. No missed messages.
    </p>
    <div class="hero-actions">
      <a href="/signup" class="btn-primary">Get Started Free →</a>
      <a href="/engine" class="btn-ghost">See How It Works ↗</a>
    </div>
    <div class="stat-bar">
      <div class="stat-cell">
        <div class="stat-val">89%</div>
        <div class="stat-lbl">Questions resolved automatically</div>
      </div>
      <div class="stat-cell">
        <div class="stat-val">&lt;200ms</div>
        <div class="stat-lbl">Response time</div>
      </div>
      <div class="stat-cell">
        <div class="stat-val">5</div>
        <div class="stat-lbl">AI layers per message</div>
      </div>
      <div class="stat-cell">
        <div class="stat-val">Zero</div>
        <div class="stat-lbl">Ungoverned actions</div>
      </div>
    </div>
  </div>
</section>

<!-- ── ENGINE OVERVIEW ── -->
<hr class="section-divider">
<section class="section" id="engine">
  <div class="eyebrow">The Oyvoda Engine</div>
  <h2 class="section-title">Five layers.<br><em>Not one model.</em></h2>
  <p class="section-sub">Most AI guest tools drop every message into a single language model and hope for the best. Oyvoda runs five distinct, purpose-built layers before any response reaches a guest.</p>
  <div class="pipeline">
    <div class="pipe-node">
      <div class="pipe-name">SENSE</div>
      <div class="pipe-sub">Emotional read · Urgency scoring · Intent classification</div>
    </div>
    <div class="pipe-node">
      <div class="pipe-name">THINK</div>
      <div class="pipe-sub">Property-specific RAG · Vector store · KB gap detection</div>
    </div>
    <div class="pipe-node">
      <div class="pipe-name">ACT</div>
      <div class="pipe-sub">Governed execution · Pre-booking pipeline · Canary rollout</div>
    </div>
    <div class="pipe-node">
      <div class="pipe-name">WATCH</div>
      <div class="pipe-sub">SLO monitoring · Escalation tracking · Observability</div>
    </div>
    <div class="pipe-node">
      <div class="pipe-name">LEARN</div>
      <div class="pipe-sub">Operator adaptation · Preference distillation · Voice matching</div>
    </div>
  </div>
  <div style="text-align:center;">
    <a href="/engine" class="btn-ghost" style="display:inline-flex;">Full architecture documentation →</a>
  </div>
</section>

<!-- ── FEATURES ── -->
<hr class="section-divider">
<section class="section" id="features">
  <div class="eyebrow">Capabilities</div>
  <h2 class="section-title">Everything your guests need.<br><em>Nothing they don't.</em></h2>
  <p class="section-sub">Built specifically for STR operators who are tired of answering the same questions at midnight.</p>
  <div class="feature-grid">
    <div class="feat-card">
      <div class="feat-icon">⚡</div>
      <div class="feat-title">Pre-Booking AI Pipeline</div>
      <div class="feat-body">Every Vrbo and Escapia inquiry gets an AI-drafted reply in your queue. Review, edit, and send — or set confidence thresholds for auto-send. Response time directly affects your platform ranking.</div>
    </div>
    <div class="feat-card">
      <div class="feat-icon">🧠</div>
      <div class="feat-title">Property-Specific Knowledge Base</div>
      <div class="feat-body">Each property gets its own vector knowledge base indexed from your house manual, PMS data, and Q&A. Guests get answers about their specific unit — not generic vacation rental advice.</div>
    </div>
    <div class="feat-card">
      <div class="feat-icon">😤</div>
      <div class="feat-title">Emotional Intelligence Layer</div>
      <div class="feat-body">A frustrated guest at 2am gets a different response path than a curious guest at noon. Oyvoda scores frustration, urgency, and sentiment before routing — not after.</div>
    </div>
    <div class="feat-card">
      <div class="feat-icon">🚨</div>
      <div class="feat-title">Smart Escalation</div>
      <div class="feat-body">Emergencies, maintenance issues, and frustrated guests are detected and escalated to the right person with full context — guest name, issue, conversation history, urgency score. ETA sent to guest automatically.</div>
    </div>
    <div class="feat-card">
      <div class="feat-icon">📚</div>
      <div class="feat-title">KB Gap Detection & Learning</div>
      <div class="feat-body">Every unanswered question surfaces as a Knowledge Gap. Approve an answer once and every future guest gets it automatically. The system gets permanently smarter with each interaction.</div>
    </div>
    <div class="feat-card">
      <div class="feat-icon">🎨</div>
      <div class="feat-title">White-Label Under Your Brand</div>
      <div class="feat-body">Custom concierge name, colors, and persona. Guests see your brand, not "Oyvoda." RCS messages appear from your sender ID. The AI writes in your voice — refined by the LEARN layer over time.</div>
    </div>
    <div class="feat-card">
      <div class="feat-icon">📊</div>
      <div class="feat-title">Operator Dashboard</div>
      <div class="feat-body">Live view of all guest sessions, pre-booking queue, escalations, knowledge gaps, and SLO metrics. One screen. No spreadsheets. Full audit export available as CSV or JSON at any time.</div>
    </div>
    <div class="feat-card">
      <div class="feat-icon">🔒</div>
      <div class="feat-title">Structural Security</div>
      <div class="feat-body">Hard-coded MCP trust registry eliminates prompt injection by architecture — not by filtering. Governance MCP validates every action before execution. Hallucination guard checks response grounding on every message.</div>
    </div>
    <div class="feat-card">
      <div class="feat-icon">🔄</div>
      <div class="feat-title">Canary Rollout System</div>
      <div class="feat-body">New AI behaviors deploy property-by-property, not portfolio-wide. One property advances to each phase before the next. Zero surprise deployments. You stay in control at every step.</div>
    </div>
  </div>
</section>

<!-- ── CHANNELS ── -->
<hr class="section-divider">
<section class="section" id="channels">
  <span id="operators" style="display:block;position:relative;top:-80px;"></span>
  <span id="vendors" style="display:block;"></span>
  <div class="eyebrow">Channels</div>
  <h2 class="section-title">Meet guests where they are.<br><em>No app required.</em></h2>
  <p class="section-sub">Oyvoda delivers through the channels guests already use — starting with RCS, the upgraded messaging standard built into every modern iPhone and Android.</p>
  <div class="channel-grid">
    <div class="channel-card">
      <div class="channel-icon">💬</div>
      <div>
        <div class="channel-name">RCS Messaging</div>
        <div class="channel-status live">● Live</div>
      </div>
    </div>
    <div class="channel-card">
      <div class="channel-icon">📱</div>
      <div>
        <div class="channel-name">SMS Fallback</div>
        <div class="channel-status live">● Live</div>
      </div>
    </div>
    <div class="channel-card">
      <div class="channel-icon">📧</div>
      <div>
        <div class="channel-name">Email (Pre-Booking)</div>
        <div class="channel-status live">● Live</div>
      </div>
    </div>
    <div class="channel-card">
      <div class="channel-icon">🌐</div>
      <div>
        <div class="channel-name">Web Chat Widget</div>
        <div class="channel-status soon">◎ Coming Soon</div>
      </div>
    </div>
    <div class="channel-card">
      <div class="channel-icon">🎙️</div>
      <div>
        <div class="channel-name">Voice</div>
        <div class="channel-status soon">◎ Coming Soon</div>
      </div>
    </div>
    <div class="channel-card">
      <div class="channel-icon">📘</div>
      <div>
        <div class="channel-name">Social (Meta)</div>
        <div class="channel-status soon">◎ Roadmap</div>
      </div>
    </div>
  </div>
</section>

<!-- ── PMS INTEGRATIONS ── -->
<hr class="section-divider">
<section class="section" id="pms">
  <div class="eyebrow">Integrations</div>
  <h2 class="section-title">Synced to your PMS.<br><em>From day one.</em></h2>
  <p class="section-sub">Oyvoda connects directly to your property management system — no manual data entry, no CSV imports. Booking data, guest details, and listing information sync automatically.</p>
  <div class="pms-row">
    <div class="pms-badge"><span class="dot"></span> Escapia</div>
    <div class="pms-badge"><span class="dot"></span> Guesty</div>
    <div class="pms-badge"><span class="dot"></span> Track</div>
    <div class="pms-badge" style="opacity:0.5;">◎ Additional systems on request</div>
  </div>
</section>

<!-- ── COMPARISON ── -->
<hr class="section-divider">
<section class="section" id="compare">
  <div class="eyebrow">How We Compare</div>
  <h2 class="section-title">Built for hospitality.<br><em>Not retrofitted for it.</em></h2>
  <p class="section-sub">Horizontal AI tools handle support tickets for e-commerce and SaaS. Oyvoda is built from the ground up for STR — where context is property-specific, timing is everything, and the guest experience is your reputation.</p>
  <table class="compare-table">
    <thead>
      <tr>
        <th></th>
        <th class="ours">Oyvoda</th>
        <th class="theirs">Generic AI Tools</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Property-specific knowledge base</td>
        <td class="ours"><span class="chk">✓</span> Per-property vector store, auto-synced from PMS</td>
        <td><span class="crs">✗</span> General knowledge only</td>
      </tr>
      <tr>
        <td>Emotional intelligence layer</td>
        <td class="ours"><span class="chk">✓</span> Frustration, urgency, sentiment scored before routing</td>
        <td><span class="crs">✗</span> Topic-based routing only</td>
      </tr>
      <tr>
        <td>Pre-booking AI</td>
        <td class="ours"><span class="chk">✓</span> Full Escapia/Vrbo inquiry pipeline with approval flow</td>
        <td><span class="crs">✗</span> Post-booking support only</td>
      </tr>
      <tr>
        <td>Operator learning</td>
        <td class="ours"><span class="chk">✓</span> Learns your voice and policies from every edit</td>
        <td><span class="crs">✗</span> Static behavior, no per-operator adaptation</td>
      </tr>
      <tr>
        <td>Structural security</td>
        <td class="ours"><span class="chk">✓</span> Hard-coded trust registry, architectural injection defense</td>
        <td><span class="crs">✗</span> Content filtering only</td>
      </tr>
      <tr>
        <td>PMS-native integration</td>
        <td class="ours"><span class="chk">✓</span> Escapia, Guesty, Track — live data, not manual entry</td>
        <td><span class="crs">✗</span> Manual setup or CSV import</td>
      </tr>
    </tbody>
  </table>
</section>

<!-- ── PRICING ── -->
<hr class="section-divider">
<section class="section" id="pricing">
  <div class="eyebrow">Pricing</div>
  <h2 class="section-title">Base platform fee.<br><em>Plus per-unit scaling.</em></h2>
  <p class="section-sub">Every plan includes the full Oyvoda concierge platform. You pay a flat monthly base plus a per-unit fee that drops as you grow. No surprises, no per-message charges.</p>
  <div class="pricing-grid">

    <!-- Essentials -->
    <div class="price-card">
      <div class="price-tier">Essentials</div>
      <div class="price-amount">$49</div>
      <div class="price-unit">/month base</div>
      <div class="price-per-unit">+ $5 / property / month</div>
      <div class="price-props">2–15 properties &middot; SMS only</div>
      <hr class="price-divider">
      <ul class="price-features">
        <li>AI Guest Concierge (SMS)</li>
        <li>Property Knowledge Base</li>
        <li>Pre-booking inquiry AI</li>
        <li>Operator dashboard</li>
        <li>1 PMS integration</li>
        <li>Team members (2)</li>
        <li>Email support</li>
        <li class="muted">RCS messaging</li>
        <li class="muted">Vendor marketplace</li>
      </ul>
      <a href="/signup" class="price-cta">Start Free Trial</a>
    </div>

    <!-- Growth -->
    <div class="price-card featured">
      <div class="price-tier">Growth</div>
      <div class="price-amount">$99</div>
      <div class="price-unit">/month base</div>
      <div class="price-per-unit">+ $4 / property / month</div>
      <div class="price-props">10–75 properties &middot; RCS + SMS</div>
      <hr class="price-divider">
      <ul class="price-features">
        <li>Everything in Essentials</li>
        <li>RCS messaging (AT&amp;T + Verizon)</li>
        <li>Guest Intelligence Feed</li>
        <li>KB Gap Auto-fix</li>
        <li>Vendor Marketplace</li>
        <li>Returning Guest Memory</li>
        <li>3 PMS integrations</li>
        <li>Team members (10)</li>
        <li>Priority support</li>
      </ul>
      <a href="/signup" class="price-cta">Start Free Trial</a>
    </div>

    <!-- Professional -->
    <div class="price-card">
      <div class="price-tier">Professional</div>
      <div class="price-amount">$199</div>
      <div class="price-unit">/month base</div>
      <div class="price-per-unit">+ $3 / property / month</div>
      <div class="price-props">50–200 properties &middot; Full RCS</div>
      <hr class="price-divider">
      <ul class="price-features">
        <li>Everything in Growth</li>
        <li>Full RCS (all carriers)</li>
        <li>Geo-fenced Maintenance</li>
        <li>Referral Revenue Share</li>
        <li>Multi-location analytics</li>
        <li>Unlimited PMS integrations</li>
        <li>Unlimited team members</li>
        <li>Canary rollout controls</li>
        <li>Dedicated onboarding</li>
      </ul>
      <a href="/signup" class="price-cta">Start Free Trial</a>
    </div>

    <!-- Enterprise -->
    <div class="price-card">
      <div class="price-tier">Enterprise</div>
      <div class="price-amount">Custom</div>
      <div class="price-unit">&nbsp;</div>
      <div class="price-per-unit">Volume pricing available</div>
      <div class="price-props">200+ properties &middot; White-glove</div>
      <hr class="price-divider">
      <ul class="price-features">
        <li>Everything in Professional</li>
        <li>Custom AI voice &amp; persona</li>
        <li>Multi-operator console</li>
        <li>Direct API access</li>
        <li>Custom PMS integrations</li>
        <li>SLA guarantees</li>
        <li>Dedicated CSM</li>
        <li>SOC 2 audit package</li>
        <li>On-site onboarding</li>
      </ul>
      <a href="mailto:info@oyvoda.com" class="price-cta">Contact Sales</a>
    </div>

  </div>
  <p style="text-align:center;font-size:13px;color:rgba(240,235,227,0.35);margin-top:24px;font-weight:300;">14-day free trial on all plans &middot; No credit card required &middot; Cancel any time</p>
</section>

<!-- ── FOUNDER QUOTE ── -->
<hr class="section-divider">
<section style="padding: 80px 48px;">
  <div class="founder-block">
    <blockquote class="founder-quote">
      We built this because we needed it ourselves. Every operator managing more than 10 units
      is drowning in messages that don't need a human. Oyvoda handles the ones that don't —
      so you can focus on the ones that do.
    </blockquote>
    <div class="founder-meta">
      <div class="founder-name">Founding Operator</div>
      <div class="founder-role">30A Florida</div>
      <div class="founder-badge">✦ 50 Units · Escapia</div>
    </div>
  </div>
</section>

<!-- ── FINAL CTA ── -->
<section class="final-cta">
  <h2>Ready to stop answering<br><em>texts at midnight?</em></h2>
  <p>See a live demo against your actual property data. Most operators are live within 48 hours of signing up.</p>
  <div class="final-cta-actions">
    <a href="/signup" class="btn-primary">Get Started Free →</a>
    <a href="mailto:info@oyvoda.com" class="btn-ghost">Talk to Us ↗</a>
  </div>
</section>

<!-- ── FOOTER ── -->
<footer class="site-footer">
  <div class="footer-top">
    <div class="footer-brand">
      <a href="/" class="footer-logo">oyvoda</a>
      <p class="footer-tagline">AI-powered, RCS-first guest experience for STR operators. White-labeled. PMS-native.</p>
    </div>
    <div class="footer-col">
      <h4>Product</h4>
      <a href="/operator-dashboard">How It Works</a>
      <a href="/engine">Engine</a>
      <a href="/#features">Features</a>
      <a href="/#channels">Channels</a>
      <a href="/#pricing">Pricing</a>
    </div>
    <div class="footer-col">
      <h4>Solutions</h4>
      <a href="/#operators">STR Operators</a>
      <a href="/#vendors">Local Vendors</a>
      <a href="/#pms">PMS Integrations</a>
      <a href="/operator-dashboard">How It Works</a>
    </div>
    <div class="footer-col">
      <h4>Trust</h4>
      <a href="/security">Security</a>
      <a href="/privacy">Privacy Policy</a>
      <a href="/engine#built-by">Built By Operators</a>
      <a href="/docs">API Reference</a>
    </div>
    <div class="footer-col">
      <h4>Company</h4>
      <a href="/#compare">How We Compare</a>
      <a href="/engine#faq">FAQ</a>
      <a href="mailto:info@oyvoda.com">Contact</a>
      <a href="mailto:info@oyvoda.com">Security</a>
    </div>
  </div>
  <div class="footer-bottom">
    <span class="footer-copy">© 2026 Oyvoda. All rights reserved.</span>
    <div class="footer-legal">
      <a href="/privacy">Privacy Policy</a>
      <a href="/security">Security</a>
      <a href="/docs">API</a>
    </div>
  </div>
</footer>

<script>
// Click-to-toggle dropdowns for reliable mobile + desktop behavior
(function() {{
  let openItem = null;
  document.querySelectorAll('.nav-item').forEach(function(item) {{
    const dropdown = item.querySelector('.dropdown');
    if (!dropdown) return;
    item.addEventListener('click', function(e) {{
      if (e.target.closest('.dd-item')) return;
      e.stopPropagation();
      const isOpen = item.classList.contains('open');
      if (openItem && openItem !== item) {{
        openItem.classList.remove('open');
      }}
      item.classList.toggle('open', !isOpen);
      openItem = isOpen ? null : item;
    }});
  }});
  document.addEventListener('click', function() {{
    if (openItem) {{ openItem.classList.remove('open'); openItem = null; }}
  }});
}})();
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_public_landing():
    return HTMLResponse(content=LANDING_HTML)
