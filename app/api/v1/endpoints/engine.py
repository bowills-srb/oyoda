"""
engine.py — Oyvoda Engine Architecture Page

Served at GET /engine

Explains the five-layer Oyvoda architecture to operators in plain language.
No jargon. No hype. Specific claims backed by real implementation details.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Engine"])


ENGINE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>The Oyvoda Engine — How It Works</title>
<meta name="description" content="Oyvoda is built on five distinct layers: SENSE, THINK, ACT, WATCH, and LEARN. Each layer is purpose-built for the short-term rental guest experience.">
<meta name="theme-color" content="#08090f">
<meta property="og:title" content="The Oyvoda Engine — Built for Hospitality">
<meta property="og:description" content="Five layers, not one model. Every guest message passes through emotional intelligence, property-specific knowledge, governance, and real-time observability before a response is sent.">
<meta property="og:image" content="https://oyvoda-production.up.railway.app/static/og-image.svg">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%2308090f'/%3E%3Ctext x='16' y='23' font-family='Georgia,serif' font-size='21' font-weight='500' fill='%23f0ebe3' text-anchor='middle'%3Eo%3C/text%3E%3Cpath d='M20 7 Q24 4 27 8' stroke='%23c87832' stroke-width='2' fill='none' stroke-linecap='round'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;0,700;1,400;1,600&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html { scroll-behavior: smooth; }
  body {
    background: #08090f;
    color: #f0ebe3;
    font-family: 'DM Sans', -apple-system, sans-serif;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }

  /* ── NAV ── */
  nav {
    position: sticky; top: 0; z-index: 100;
    background: rgba(8, 9, 15, 0.92);
    backdrop-filter: blur(16px);
    border-bottom: 1px solid rgba(200, 120, 50, 0.12);
    padding: 0 48px; height: 64px;
    display: flex; align-items: center; justify-content: space-between;
  }
  .nav-logo {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: 22px; font-weight: 500;
    color: #f0ebe3; text-decoration: none;
    letter-spacing: -0.02em;
  }
  .nav-links { display: flex; align-items: center; gap: 8px; }
  .nav-link {
    color: rgba(240, 235, 227, 0.5);
    text-decoration: none; font-size: 14px; font-weight: 400;
    padding: 6px 14px; border-radius: 6px;
    transition: color 0.15s, background 0.15s;
  }
  .nav-link:hover { color: #f0ebe3; background: rgba(255,255,255,0.04); }
  .nav-cta {
    background: #c87832; color: #f0ebe3;
    text-decoration: none; font-size: 13px; font-weight: 500;
    padding: 8px 20px; border-radius: 8px;
    transition: background 0.15s; letter-spacing: 0.01em;
  }
  .nav-cta:hover { background: #e09040; }

  /* ── HERO ── */
  .hero {
    padding: 120px 48px 80px;
    max-width: 900px; margin: 0 auto;
    text-align: center;
    position: relative;
  }
  .hero-eyebrow {
    font-family: 'DM Mono', monospace;
    font-size: 11px; font-weight: 500;
    letter-spacing: 0.14em; text-transform: uppercase;
    color: #c87832; margin-bottom: 24px;
    display: flex; align-items: center; justify-content: center; gap: 10px;
  }
  .hero-eyebrow::before, .hero-eyebrow::after {
    content: '';
    width: 32px; height: 1px; background: rgba(200, 120, 50, 0.4);
  }
  .hero-title {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: clamp(44px, 7vw, 80px);
    font-weight: 600; line-height: 1.05;
    letter-spacing: -0.02em; color: #f0ebe3;
    margin-bottom: 28px;
  }
  .hero-title em { font-style: italic; color: #c87832; }
  .hero-sub {
    font-size: 18px; font-weight: 300;
    color: rgba(240, 235, 227, 0.6);
    max-width: 640px; margin: 0 auto 48px;
    line-height: 1.7;
  }
  .hero-sub strong { color: rgba(240, 235, 227, 0.85); font-weight: 500; }

  /* ── INTRO STAT ROW ── */
  .stat-row {
    display: flex; gap: 0;
    border: 1px solid rgba(200, 120, 50, 0.15);
    border-radius: 16px; overflow: hidden;
    max-width: 760px; margin: 0 auto 100px;
  }
  .stat-cell {
    flex: 1; padding: 28px 32px;
    border-right: 1px solid rgba(200, 120, 50, 0.1);
    text-align: center;
  }
  .stat-cell:last-child { border-right: none; }
  .stat-value {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: 40px; font-weight: 600;
    color: #f0ebe3; letter-spacing: -0.02em;
    line-height: 1;
  }
  .stat-label {
    font-size: 11px; font-weight: 500;
    letter-spacing: 0.1em; text-transform: uppercase;
    color: rgba(240, 235, 227, 0.35); margin-top: 8px;
  }

  /* ── SECTION DIVIDER ── */
  .section-label {
    font-family: 'DM Mono', monospace;
    font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase;
    color: rgba(240, 235, 227, 0.3);
    margin-bottom: 16px;
  }

  /* ── ARCHITECTURE OVERVIEW ── */
  .arch-overview {
    padding: 0 48px 80px;
    max-width: 1100px; margin: 0 auto;
  }
  .arch-intro {
    max-width: 700px; margin: 0 auto 72px; text-align: center;
  }
  .arch-intro h2 {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: clamp(32px, 4vw, 52px); font-weight: 600;
    letter-spacing: -0.02em; margin-bottom: 20px;
    color: #f0ebe3; line-height: 1.15;
  }
  .arch-intro p {
    font-size: 16px; color: rgba(240, 235, 227, 0.55);
    line-height: 1.75; font-weight: 300;
  }

  /* ── FLOW DIAGRAM ── */
  .flow-diagram {
    display: flex; align-items: center; justify-content: center;
    gap: 0; margin-bottom: 96px; flex-wrap: wrap;
  }
  .flow-node {
    display: flex; flex-direction: column; align-items: center;
    gap: 8px; padding: 20px 24px;
    border: 1px solid rgba(200, 120, 50, 0.2);
    border-radius: 12px; background: rgba(200, 120, 50, 0.04);
    min-width: 120px; text-align: center;
    transition: border-color 0.2s, background 0.2s;
  }
  .flow-node:hover {
    border-color: rgba(200, 120, 50, 0.4);
    background: rgba(200, 120, 50, 0.08);
  }
  .flow-node-name {
    font-family: 'DM Mono', monospace;
    font-size: 13px; font-weight: 500;
    color: #c87832; letter-spacing: 0.06em;
  }
  .flow-node-sub {
    font-size: 11px; color: rgba(240, 235, 227, 0.35);
    letter-spacing: 0.04em;
  }
  .flow-arrow {
    width: 40px; height: 1px;
    background: linear-gradient(to right, rgba(200,120,50,0.3), rgba(200,120,50,0.6));
    position: relative; flex-shrink: 0;
  }
  .flow-arrow::after {
    content: '›';
    position: absolute; right: -6px; top: -9px;
    color: rgba(200, 120, 50, 0.6); font-size: 16px;
  }

  /* ── LAYER CARDS ── */
  .layers { display: flex; flex-direction: column; gap: 2px; }

  .layer-card {
    border: 1px solid rgba(200, 120, 50, 0.1);
    border-radius: 20px; overflow: hidden;
    background: rgba(255, 255, 255, 0.015);
    transition: border-color 0.25s;
  }
  .layer-card:hover { border-color: rgba(200, 120, 50, 0.25); }

  .layer-header {
    display: grid;
    grid-template-columns: 64px 1fr auto;
    align-items: center; gap: 28px;
    padding: 36px 44px;
    cursor: pointer;
  }
  .layer-num {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: 48px; font-weight: 600;
    color: #c87832;
    opacity: 0.65;
    line-height: 1; text-align: center;
  }
  .layer-title-group {}
  .layer-tag {
    font-family: 'DM Mono', monospace;
    font-size: 10px; font-weight: 500;
    letter-spacing: 0.16em; text-transform: uppercase;
    color: #c87832; margin-bottom: 4px;
  }
  .layer-name {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: 28px; font-weight: 600;
    color: #f0ebe3; letter-spacing: -0.01em;
    line-height: 1.1;
  }
  .layer-tagline {
    font-size: 14px; color: rgba(240, 235, 227, 0.45);
    margin-top: 4px; font-weight: 300;
  }
  .layer-badge {
    font-size: 12px; font-weight: 500;
    color: rgba(240, 235, 227, 0.3);
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.07);
    padding: 6px 14px; border-radius: 20px;
    white-space: nowrap; letter-spacing: 0.02em;
  }

  .layer-body {
    padding: 0 44px 40px 136px;
    border-top: 1px solid rgba(255, 255, 255, 0.04);
  }
  .layer-description {
    font-size: 15px; color: rgba(240, 235, 227, 0.6);
    line-height: 1.8; font-weight: 300;
    max-width: 680px; padding-top: 28px; margin-bottom: 32px;
  }
  .layer-description strong { color: rgba(240, 235, 227, 0.85); font-weight: 500; }

  .capability-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 16px;
  }
  .capability-card {
    padding: 20px 22px;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.02);
  }
  .capability-title {
    font-size: 13px; font-weight: 500;
    color: #c87832; margin-bottom: 6px;
    display: flex; align-items: center; gap: 8px;
  }
  .capability-title::before {
    content: ''; width: 4px; height: 4px;
    border-radius: 50%; background: #c87832;
    flex-shrink: 0;
  }
  .capability-desc {
    font-size: 13px; color: rgba(240, 235, 227, 0.4);
    line-height: 1.6; font-weight: 300;
  }

  /* ── TECH SPEC TABLE ── */
  .tech-section {
    padding: 80px 48px;
    max-width: 1100px; margin: 0 auto;
    border-top: 1px solid rgba(255,255,255,0.05);
  }
  .tech-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1px;
    background: rgba(200, 120, 50, 0.08);
    border: 1px solid rgba(200, 120, 50, 0.08);
    border-radius: 16px; overflow: hidden;
    margin-top: 48px;
  }
  .tech-cell {
    background: #08090f;
    padding: 28px 32px;
  }
  .tech-cell-label {
    font-family: 'DM Mono', monospace;
    font-size: 10px; letter-spacing: 0.14em;
    text-transform: uppercase;
    color: rgba(240, 235, 227, 0.25);
    margin-bottom: 10px;
  }
  .tech-cell-value {
    font-size: 14px; font-weight: 400;
    color: rgba(240, 235, 227, 0.75);
    line-height: 1.5;
  }
  .tech-cell-value strong {
    display: block; font-family: 'Cormorant Garamond', serif;
    font-size: 22px; font-weight: 600;
    color: #f0ebe3; margin-bottom: 2px;
  }

  /* ── COMPARISON ── */
  .compare-section {
    padding: 80px 48px;
    max-width: 1100px; margin: 0 auto;
    border-top: 1px solid rgba(255,255,255,0.05);
  }
  .compare-intro { max-width: 600px; margin-bottom: 48px; }
  .compare-intro h2 {
    font-family: 'Cormorant Garamond', serif;
    font-size: clamp(28px, 4vw, 44px); font-weight: 600;
    letter-spacing: -0.02em; color: #f0ebe3;
    margin-bottom: 16px; line-height: 1.15;
  }
  .compare-intro p {
    font-size: 15px; color: rgba(240,235,227,0.5);
    line-height: 1.75; font-weight: 300;
  }
  .compare-table {
    width: 100%; border-collapse: collapse;
    border: 1px solid rgba(200,120,50,0.1);
    border-radius: 16px; overflow: hidden;
  }
  .compare-table th {
    padding: 16px 24px;
    font-size: 12px; font-weight: 500;
    letter-spacing: 0.08em; text-transform: uppercase;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    text-align: left;
  }
  .compare-table th:first-child { color: rgba(240,235,227,0.3); }
  .compare-table th.ours {
    color: #c87832;
    background: rgba(200,120,50,0.06);
  }
  .compare-table th.theirs { color: rgba(240,235,227,0.3); }
  .compare-table td {
    padding: 16px 24px;
    font-size: 14px; color: rgba(240,235,227,0.6);
    border-bottom: 1px solid rgba(255,255,255,0.03);
    vertical-align: top; line-height: 1.5;
  }
  .compare-table td:first-child {
    font-weight: 500; color: rgba(240,235,227,0.4);
    font-size: 13px; white-space: nowrap;
  }
  .compare-table td.ours {
    background: rgba(200,120,50,0.03);
    color: rgba(240,235,227,0.8);
  }
  .compare-table tr:last-child td { border-bottom: none; }
  .check { color: #c87832; font-weight: 600; }
  .cross { color: rgba(240,235,227,0.2); }

  /* ── FAQ ── */
  .faq-section {
    padding: 80px 48px;
    max-width: 800px; margin: 0 auto;
    border-top: 1px solid rgba(255,255,255,0.05);
  }
  .faq-section h2 {
    font-family: 'Cormorant Garamond', serif;
    font-size: clamp(28px, 4vw, 44px); font-weight: 600;
    letter-spacing: -0.02em; color: #f0ebe3;
    margin-bottom: 48px; line-height: 1.15;
  }
  .faq-item {
    border-bottom: 1px solid rgba(255,255,255,0.05);
    padding: 28px 0;
  }
  .faq-q {
    font-size: 16px; font-weight: 500;
    color: #f0ebe3; margin-bottom: 12px;
    letter-spacing: -0.01em;
  }
  .faq-a {
    font-size: 14px; color: rgba(240,235,227,0.5);
    line-height: 1.8; font-weight: 300;
  }
  .faq-a strong { color: rgba(240,235,227,0.75); font-weight: 500; }
  .faq-a code {
    font-family: 'DM Mono', monospace;
    font-size: 12px; background: rgba(200,120,50,0.1);
    color: #c87832; padding: 2px 6px; border-radius: 4px;
  }

  /* ── CTA ── */
  .cta-section {
    padding: 80px 48px 100px;
    text-align: center;
    border-top: 1px solid rgba(255,255,255,0.05);
  }
  .cta-section h2 {
    font-family: 'Cormorant Garamond', serif;
    font-size: clamp(32px, 5vw, 60px); font-weight: 600;
    letter-spacing: -0.02em; color: #f0ebe3;
    margin-bottom: 20px; line-height: 1.1;
  }
  .cta-section h2 em { font-style: italic; color: #c87832; }
  .cta-section p {
    font-size: 16px; color: rgba(240,235,227,0.45);
    max-width: 480px; margin: 0 auto 40px;
    line-height: 1.7; font-weight: 300;
  }
  .cta-buttons { display: flex; gap: 14px; justify-content: center; }
  .btn-primary {
    background: #c87832; color: #f0ebe3;
    text-decoration: none; font-size: 14px; font-weight: 500;
    padding: 14px 32px; border-radius: 10px;
    transition: background 0.15s, transform 0.15s;
    letter-spacing: 0.01em;
  }
  .btn-primary:hover { background: #e09040; transform: translateY(-1px); }
  .btn-ghost {
    background: transparent; color: rgba(240,235,227,0.6);
    text-decoration: none; font-size: 14px; font-weight: 400;
    padding: 14px 32px; border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.1);
    transition: color 0.15s, border-color 0.15s;
  }
  .btn-ghost:hover { color: #f0ebe3; border-color: rgba(255,255,255,0.2); }

  /* ── FOOTER ── */
  footer {
    padding: 24px 48px;
    border-top: 1px solid rgba(255,255,255,0.04);
    display: flex; align-items: center; justify-content: space-between;
  }
  .footer-logo {
    font-family: 'Cormorant Garamond', serif;
    font-size: 16px; font-weight: 500;
    color: rgba(240,235,227,0.3); text-decoration: none;
  }
  .footer-links { display: flex; gap: 24px; }
  .footer-link {
    font-size: 12px; color: rgba(240,235,227,0.2);
    text-decoration: none; letter-spacing: 0.04em;
    transition: color 0.15s;
  }
  .footer-link:hover { color: rgba(240,235,227,0.5); }

  /* ── STICKY SECTION NAV ── */
  .page-layout {
    display: grid;
    grid-template-columns: 200px 1fr;
    gap: 0;
    max-width: 1300px;
    margin: 0 auto;
    align-items: start;
  }
  .section-nav {
    position: sticky;
    top: 80px;
    padding: 40px 0 40px 48px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .section-nav-item {
    display: flex; align-items: center; gap: 10px;
    padding: 9px 12px; border-radius: 8px;
    text-decoration: none; cursor: pointer;
    transition: background 0.15s, color 0.15s;
    color: rgba(240,235,227,0.3);
    font-family: 'DM Mono', monospace;
    font-size: 11px; letter-spacing: 0.08em;
    text-transform: uppercase;
    border: none; background: none;
    white-space: nowrap;
  }
  .section-nav-item:hover, .section-nav-item.active {
    color: #c87832;
    background: rgba(200,120,50,0.06);
  }
  .section-nav-num {
    font-size: 11px; font-weight: 500;
    color: #c87832; opacity: 0.75;
    width: 20px; flex-shrink: 0;
    letter-spacing: 0.04em; text-align: right;
  }
  .section-nav-item.active .section-nav-num,
  .section-nav-item:hover .section-nav-num {
    opacity: 1; color: #e09040;
  }
  .section-nav-label {
    flex: 1;
  }
  .page-content { min-width: 0; }

  /* ── BUILT BY OPERATORS ── */
  .operator-cred {
    padding: 80px 48px;
    max-width: 1100px; margin: 0 auto;
    border-top: 1px solid rgba(255,255,255,0.05);
  }
  .operator-cred-inner {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 80px;
    align-items: center;
  }
  .operator-cred h2 {
    font-family: 'Cormorant Garamond', serif;
    font-size: clamp(28px, 4vw, 48px); font-weight: 600;
    letter-spacing: -0.02em; color: #f0ebe3;
    line-height: 1.1; margin-bottom: 20px;
  }
  .operator-cred h2 em { font-style: italic; color: #c87832; }
  .operator-cred p {
    font-size: 15px; color: rgba(240,235,227,0.55);
    line-height: 1.8; font-weight: 300; margin-bottom: 16px;
  }
  .operator-cred p strong { color: rgba(240,235,227,0.8); font-weight: 500; }
  .operator-card {
    border: 1px solid rgba(200,120,50,0.15);
    border-radius: 20px; padding: 36px;
    background: rgba(200,120,50,0.03);
  }
  .operator-card-quote {
    font-family: 'Cormorant Garamond', serif;
    font-size: 22px; font-weight: 400; font-style: italic;
    color: #f0ebe3; line-height: 1.5; margin-bottom: 28px;
  }
  .operator-card-quote::before { content: '\201C'; color: #c87832; }
  .operator-card-quote::after { content: '\201D'; color: #c87832; }
  .operator-card-meta {
    display: flex; align-items: center; gap: 16px;
    padding-top: 24px;
    border-top: 1px solid rgba(255,255,255,0.06);
  }
  .operator-card-avatar {
    width: 44px; height: 44px; border-radius: 50%;
    background: linear-gradient(135deg, #c87832, #8a4a18);
    display: flex; align-items: center; justify-content: center;
    font-family: 'Cormorant Garamond', serif;
    font-size: 18px; font-weight: 600; color: #f0ebe3;
    flex-shrink: 0;
  }
  .operator-card-info {}
  .operator-card-name {
    font-size: 14px; font-weight: 500; color: #f0ebe3;
    margin-bottom: 2px;
  }
  .operator-card-role {
    font-size: 12px; color: rgba(240,235,227,0.35);
    letter-spacing: 0.04em;
  }
  .cred-points {
    display: flex; flex-direction: column; gap: 16px;
    margin-top: 32px;
  }
  .cred-point {
    display: flex; gap: 12px; align-items: flex-start;
  }
  .cred-point-dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: #c87832; flex-shrink: 0; margin-top: 6px;
  }
  .cred-point-text {
    font-size: 14px; color: rgba(240,235,227,0.55);
    line-height: 1.6; font-weight: 300;
  }
  .cred-point-text strong { color: rgba(240,235,227,0.8); font-weight: 500; }

  /* ── RESPONSIVE ── */
  @media (max-width: 768px) {
    .page-layout { grid-template-columns: 1fr; }
    .section-nav { display: none; }
    nav { padding: 0 20px; }
    .hero { padding: 80px 20px 60px; }
    .arch-overview, .tech-section, .compare-section, .faq-section, .cta-section { padding-left: 20px; padding-right: 20px; }
    .layer-header { grid-template-columns: 1fr; padding: 24px; }
    .layer-num { display: none; }
    .layer-body { padding: 0 24px 32px; }
    .tech-grid { grid-template-columns: 1fr; }
    .compare-table { font-size: 12px; }
    .compare-table th, .compare-table td { padding: 12px 14px; }
    .stat-row { flex-direction: column; }
    .stat-cell { border-right: none; border-bottom: 1px solid rgba(200,120,50,0.1); }
    .stat-cell:last-child { border-bottom: none; }
    .flow-diagram { gap: 8px; }
    .flow-arrow { display: none; }
    .cta-buttons { flex-direction: column; align-items: center; }
    footer { flex-direction: column; gap: 16px; text-align: center; }
  }
</style>
</head>
<body>

<!-- NAV injected by shared_nav -->
NAV_PLACEHOLDER

<!-- HERO -->
<section class="hero">
  <div class="hero-eyebrow">The Oyvoda Engine</div>
  <h1 class="hero-title">
    Five layers.<br>
    <em>Not one model.</em>
  </h1>
  <p class="hero-sub">
    Most AI guest tools route every message into a single language model and hope for the best.
    Oyvoda runs <strong>five distinct, purpose-built layers</strong> before any response reaches a guest —
    each one engineered for the specific demands of short-term rental hospitality.
  </p>
</section>

<!-- STAT ROW — real numbers from architecture -->
<div style="padding: 0 48px; max-width: 1100px; margin: 0 auto;">
  <div class="stat-row">
    <div class="stat-cell">
      <div class="stat-value">9</div>
      <div class="stat-label">MCP Servers</div>
    </div>
    <div class="stat-cell">
      <div class="stat-value">&lt;200ms</div>
      <div class="stat-label">Avg Response</div>
    </div>
    <div class="stat-cell">
      <div class="stat-value">5</div>
      <div class="stat-label">Architecture Layers</div>
    </div>
    <div class="stat-cell">
      <div class="stat-value">Zero</div>
      <div class="stat-label">Ungovernered Actions</div>
    </div>
  </div>
</div>

<div class="page-layout">
<nav class="section-nav" id="section-nav">
  <a class="section-nav-item active" href="#architecture">
    <span class="section-nav-num">01</span><span class="section-nav-label">Architecture</span>
  </a>
  <a class="section-nav-item" href="#technology">
    <span class="section-nav-num">02</span><span class="section-nav-label">Technology</span>
  </a>
  <a class="section-nav-item" href="#compare">
    <span class="section-nav-num">03</span><span class="section-nav-label">Compare</span>
  </a>
  <a class="section-nav-item" href="#built-by">
    <span class="section-nav-num">04</span><span class="section-nav-label">Built By</span>
  </a>
  <a class="section-nav-item" href="#faq">
    <span class="section-nav-num">05</span><span class="section-nav-label">FAQ</span>
  </a>
</nav>
<div class="page-content">

<!-- ARCHITECTURE OVERVIEW -->
<section class="arch-overview" id="architecture">
  <div class="arch-intro">
    <div class="section-label">Architecture</div>
    <h2>Every message takes a journey before it becomes a reply.</h2>
    <p>A guest asks about the pool heater at 11pm. Here's exactly what happens inside Oyvoda before they see a response.</p>
  </div>

  <!-- FLOW DIAGRAM -->
  <div class="flow-diagram">
    <div class="flow-node">
      <div class="flow-node-name">SENSE</div>
      <div class="flow-node-sub">Emotional read</div>
    </div>
    <div class="flow-arrow"></div>
    <div class="flow-node">
      <div class="flow-node-name">THINK</div>
      <div class="flow-node-sub">Knowledge retrieval</div>
    </div>
    <div class="flow-arrow"></div>
    <div class="flow-node">
      <div class="flow-node-name">ACT</div>
      <div class="flow-node-sub">Governed execution</div>
    </div>
    <div class="flow-arrow"></div>
    <div class="flow-node">
      <div class="flow-node-name">WATCH</div>
      <div class="flow-node-sub">Live observability</div>
    </div>
    <div class="flow-arrow"></div>
    <div class="flow-node">
      <div class="flow-node-name">LEARN</div>
      <div class="flow-node-sub">Operator adaptation</div>
    </div>
  </div>

  <!-- LAYER CARDS -->
  <div class="layers">

    <!-- LAYER 1: SENSE -->
    <div class="layer-card">
      <div class="layer-header">
        <div class="layer-num">01</div>
        <div class="layer-title-group">
          <div class="layer-tag">Layer One · SENSE</div>
          <div class="layer-name">We read emotion before we read intent.</div>
          <div class="layer-tagline">Emotional Intelligence + Signal Detection</div>
        </div>
        <div class="layer-badge">eq_mcp · signal_mcp</div>
      </div>
      <div class="layer-body">
        <p class="layer-description">
          Before routing a guest message anywhere, Oyvoda runs it through an
          <strong>Emotional Intelligence layer</strong> that scores frustration, urgency, confusion,
          and sentiment. A guest asking "is the pool heated" at 2pm is different from a guest
          asking the same question at midnight with "we've been waiting 45 minutes."
          <br><br>
          Generic AI tools treat both messages identically. Oyvoda routes them differently —
          different tone, different urgency, different escalation threshold. Hospitality is
          fundamentally emotional. The engine reflects that.
        </p>
        <div class="capability-grid">
          <div class="capability-card">
            <div class="capability-title">Frustration Detection</div>
            <div class="capability-desc">Real-time scoring of guest emotional state. High frustration triggers escalation paths before the guest has to ask for a manager.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">Intent Classification</div>
            <div class="capability-desc">14 distinct intent categories specific to STR: check-in, maintenance, local recommendations, pre-booking, emergency, and more.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">Signal Aggregation</div>
            <div class="capability-desc">Market signals, property context, and guest history are bundled into a signal package before any response is drafted.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">Urgency Scoring</div>
            <div class="capability-desc">Time of day, message cadence, and emotional markers combine into an urgency score that determines response speed and escalation chain.</div>
          </div>
        </div>
      </div>
    </div>

    <!-- LAYER 2: THINK -->
    <div class="layer-card">
      <div class="layer-header">
        <div class="layer-num">02</div>
        <div class="layer-title-group">
          <div class="layer-tag">Layer Two · THINK</div>
          <div class="layer-name">Your property's knowledge. Not general knowledge.</div>
          <div class="layer-tagline">RAG · Vector Store · Librarian Agent</div>
        </div>
        <div class="layer-badge">knowledge_mcp · pms_mcp</div>
      </div>
      <div class="layer-body">
        <p class="layer-description">
          Every Oyvoda operator gets a <strong>property-specific vector knowledge base</strong> —
          indexed from your house manual, PMS data, local guidebooks, and operator Q&A.
          When a guest asks a question, the engine retrieves the exact relevant chunks from
          your property's knowledge, not a generic training corpus.
          <br><br>
          This is the difference between "pool hours are typically 8am–10pm at most vacation rentals"
          and "your pool at 34 Seagrove Drive is heated to 84°F and available 24/7 — enjoy."
          Precision requires property-specific knowledge retrieval. Oyvoda builds and maintains
          that knowledge base automatically from your PMS data.
        </p>
        <div class="capability-grid">
          <div class="capability-card">
            <div class="capability-title">Property Vector Store</div>
            <div class="capability-desc">Each property gets its own indexed knowledge base. Retrieval is property-scoped — guests only get answers about their specific unit.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">PMS-Native Sync</div>
            <div class="capability-desc">Live integration with Escapia, Guesty, and Track. Booking details, check-in instructions, and listing data sync automatically.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">Librarian Agent</div>
            <div class="capability-desc">A dedicated agent curates and maintains the knowledge base — identifying gaps, resolving conflicts, and flagging outdated information.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">KB Gap Detection</div>
            <div class="capability-desc">Every unanswered question surfaces in your operator dashboard. Approve an answer once and every guest gets it from that point forward.</div>
          </div>
        </div>
      </div>
    </div>

    <!-- LAYER 3: ACT -->
    <div class="layer-card">
      <div class="layer-header">
        <div class="layer-num">03</div>
        <div class="layer-title-group">
          <div class="layer-tag">Layer Three · ACT</div>
          <div class="layer-name">Every action is governed before it executes.</div>
          <div class="layer-tagline">Tool Execution · Governance · Sanitizer</div>
        </div>
        <div class="layer-badge">governance_mcp · sanitizer_mcp</div>
      </div>
      <div class="layer-body">
        <p class="layer-description">
          Oyvoda can take actions — draft replies, process late checkouts, log incidents,
          dispatch alerts, deliver gate codes. But every action passes through a
          <strong>hard-coded governance layer</strong> before execution. The architecture
          physically cannot take an action that hasn't been validated.
          <br><br>
          This isn't content filtering — it's structural safety. The 9 MCP servers that
          handle tool execution are registered at startup and cannot be modified at runtime.
          This eliminates prompt injection attacks, where a malicious guest message attempts
          to make the AI take unauthorized actions. The trust boundary is the architecture
          itself, not a rule set.
        </p>
        <div class="capability-grid">
          <div class="capability-card">
            <div class="capability-title">Hard-Coded Trust Registry</div>
            <div class="capability-desc">9 MCP servers registered at startup. No server can be added, removed, or modified at runtime. Eliminates prompt injection by design.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">Pre-Booking Pipeline</div>
            <div class="capability-desc">Full AI-drafted pre-booking reply workflow. Drafts queue for operator approval before sending. Confidence scoring determines auto-send threshold.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">Canary Rollout System</div>
            <div class="capability-desc">New AI behaviors roll out property by property, not portfolio-wide. One property advances to each phase before the next. Zero surprise deployments.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">Escalation Handoff</div>
            <div class="capability-desc">When a situation exceeds the AI's scope, it escalates with full context — guest name, issue, conversation history, and urgency score — to the right person.</div>
          </div>
        </div>
      </div>
    </div>

    <!-- LAYER 4: WATCH -->
    <div class="layer-card">
      <div class="layer-header">
        <div class="layer-num">04</div>
        <div class="layer-title-group">
          <div class="layer-tag">Layer Four · WATCH</div>
          <div class="layer-name">You know before your guests notice.</div>
          <div class="layer-tagline">SLO Monitoring · Real-Time Observability</div>
        </div>
        <div class="layer-badge">watch_layer · slo_metrics</div>
      </div>
      <div class="layer-body">
        <p class="layer-description">
          Oyvoda monitors every response for latency, accuracy, escalation rate, and
          knowledge retrieval quality — in real time, on every request.
          <strong>Service Level Objectives (SLOs)</strong> are defined per operator and tracked
          continuously. When the system degrades, the dashboard surfaces it before any guest
          has a bad experience.
          <br><br>
          This is the layer that makes reliability a measurable property of the system,
          not a marketing claim. Every operator sees their actual SLO metrics. Every
          knowledge gap is logged. Every escalation is tracked to resolution.
        </p>
        <div class="capability-grid">
          <div class="capability-card">
            <div class="capability-title">SLO Tracking</div>
            <div class="capability-desc">API latency (&lt;1200ms), knowledge latency (&lt;1500ms), error rate (&lt;1%), and escalation backlog (&lt;25) are monitored per operator, per property.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">Operator Dashboard</div>
            <div class="capability-desc">Live view of all guest sessions, pre-booking queue, escalations, knowledge gaps, and performance metrics. One screen, everything that matters.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">Alert Chain</div>
            <div class="capability-desc">Configurable escalation contacts per alert type per property. Primary contact → secondary contact → fallback, with timeout and acknowledgement tracking.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">Incident Tracking</div>
            <div class="capability-desc">Property incidents — maintenance issues, guest complaints, compensation decisions — are logged, tracked, and reported. Full audit trail, zero spreadsheets.</div>
          </div>
        </div>
      </div>
    </div>

    <!-- LAYER 5: LEARN -->
    <div class="layer-card">
      <div class="layer-header">
        <div class="layer-num">05</div>
        <div class="layer-title-group">
          <div class="layer-tag">Layer Five · LEARN</div>
          <div class="layer-name">The longer you use it, the better it knows you.</div>
          <div class="layer-tagline">Operator Learning · Preference Distillation</div>
        </div>
        <div class="layer-badge">operator_learning</div>
      </div>
      <div class="layer-body">
        <p class="layer-description">
          Every time an operator edits an AI draft — a word change, a tone adjustment,
          a policy clarification — Oyvoda analyzes the edit and updates that operator's
          preference profile. Over time, the system learns your specific voice, your
          specific policies, and your specific standards.
          <br><br>
          After 20 interactions, the AI writes drafts that need fewer edits.
          After 100, it writes like you. This is the layer that makes Oyvoda get
          <strong>permanently better for your specific operation</strong> — not just
          smarter in general, but smarter about you specifically. No other STR guest
          platform does this.
        </p>
        <div class="capability-grid">
          <div class="capability-card">
            <div class="capability-title">Edit Analysis</div>
            <div class="capability-desc">Every operator edit is classified by type: tone, policy, price signal, property fact. Each category trains a different aspect of the operator's AI profile.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">Preference Distillation</div>
            <div class="capability-desc">Observed patterns distill into operator-specific instructions. "Always mention the beach walkover code in check-in confirmations" becomes a permanent rule.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">Platform Intelligence</div>
            <div class="capability-desc">Anonymized, aggregated patterns across operators inform platform-wide improvements. Individual operator data is never shared.</div>
          </div>
          <div class="capability-card">
            <div class="capability-title">Confidence Scoring</div>
            <div class="capability-desc">Each learned preference has a confidence score that grows with observation count. Low-confidence rules require approval. High-confidence rules apply automatically.</div>
          </div>
        </div>
      </div>
    </div>

  </div>
</section>

<!-- TECH SPECS -->
<section class="tech-section" id="technology">
  <div class="section-label">Technical Specifications</div>
  <div class="tech-grid">
    <div class="tech-cell">
      <div class="tech-cell-label">LLM Provider</div>
      <div class="tech-cell-value"><strong>Groq · Llama 3.1</strong>~200ms inference latency</div>
    </div>
    <div class="tech-cell">
      <div class="tech-cell-label">Architecture</div>
      <div class="tech-cell-value"><strong>FastAPI + Celery</strong>Async Python, 3 worker queues</div>
    </div>
    <div class="tech-cell">
      <div class="tech-cell-label">Database</div>
      <div class="tech-cell-value"><strong>Supabase Postgres</strong>21 tables, daily backups</div>
    </div>
    <div class="tech-cell">
      <div class="tech-cell-label">Messaging</div>
      <div class="tech-cell-value"><strong>RCS-first</strong>SMS fallback, no app download</div>
    </div>
    <div class="tech-cell">
      <div class="tech-cell-label">PMS Integrations</div>
      <div class="tech-cell-value"><strong>Escapia · Guesty · Track</strong>More on request</div>
    </div>
    <div class="tech-cell">
      <div class="tech-cell-label">Security</div>
      <div class="tech-cell-value"><strong>Hard-coded trust registry</strong>Zero runtime MCP registration</div>
    </div>
    <div class="tech-cell">
      <div class="tech-cell-label">Deployment</div>
      <div class="tech-cell-value"><strong>Railway · Cloudflare</strong>Auto-deploy on every commit</div>
    </div>
    <div class="tech-cell">
      <div class="tech-cell-label">Observability</div>
      <div class="tech-cell-value"><strong>Prometheus · Grafana</strong>SLO monitoring, all services</div>
    </div>
    <div class="tech-cell">
      <div class="tech-cell-label">Uptime</div>
      <div class="tech-cell-value"><strong>99.9% target</strong>Health checks every 15s</div>
    </div>
  </div>
</section>

<!-- COMPARISON -->
<section class="compare-section" id="compare">
  <div class="compare-intro">
    <div class="section-label">How We Compare</div>
    <h2>Built for hospitality.<br>Not retrofitted for it.</h2>
    <p>Horizontal AI tools handle support tickets for e-commerce and SaaS.
    Oyvoda is built from the ground up for the specific demands of short-term rental —
    where context is property-specific, timing is everything, and the guest experience
    is your reputation.</p>
  </div>
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
        <td class="ours"><span class="check">✓</span> Per-property vector store, auto-synced from PMS</td>
        <td><span class="cross">✗</span> General knowledge only</td>
      </tr>
      <tr>
        <td>Emotional intelligence layer</td>
        <td class="ours"><span class="check">✓</span> Frustration, urgency, and sentiment scored before routing</td>
        <td><span class="cross">✗</span> Topic-based routing only</td>
      </tr>
      <tr>
        <td>Pre-booking AI</td>
        <td class="ours"><span class="check">✓</span> Full Escapia/Vrbo inquiry pipeline with approval workflow</td>
        <td><span class="cross">✗</span> Post-booking support only</td>
      </tr>
      <tr>
        <td>Operator learning</td>
        <td class="ours"><span class="check">✓</span> Learns your voice and policies from every edit</td>
        <td><span class="cross">✗</span> Static behavior, no per-operator adaptation</td>
      </tr>
      <tr>
        <td>Governed tool execution</td>
        <td class="ours"><span class="check">✓</span> Hard-coded trust registry, zero runtime modification</td>
        <td><span class="cross">✗</span> Content filtering only</td>
      </tr>
      <tr>
        <td>STR-specific intents</td>
        <td class="ours"><span class="check">✓</span> 14 STR-specific categories including pre-booking, maintenance, gate codes</td>
        <td><span class="cross">✗</span> Generic support intents</td>
      </tr>
      <tr>
        <td>PMS-native integration</td>
        <td class="ours"><span class="check">✓</span> Escapia, Guesty, Track — live booking data, not manual entry</td>
        <td><span class="cross">✗</span> Manual setup or CSV import</td>
      </tr>
      <tr>
        <td>Canary rollout</td>
        <td class="ours"><span class="check">✓</span> New behaviors test on one property before portfolio-wide</td>
        <td><span class="cross">✗</span> All-or-nothing deployment</td>
      </tr>
    </tbody>
  </table>
</section>

<!-- BUILT BY OPERATORS -->
<section class="operator-cred" id="built-by">
  <div class="operator-cred-inner">
    <div>
      <div class="section-label">Who Built This</div>
      <h2>Built <em>by operators.</em><br>For operators.</h2>
      <p>
        Oyvoda wasn't designed in a boardroom by engineers who've never managed a vacation rental.
        It was built in direct partnership with a <strong>30A Florida STR operator managing 50 units</strong> —
        someone who has fielded the 2am WiFi calls, navigated the pet fee disputes, and spent hours
        answering the same pre-booking questions from Vrbo guests.
      </p>
      <p>
        Every feature in the engine reflects a real operational pain. The pre-booking pipeline
        exists because inquiry response time directly affects Vrbo ranking. The emotional intelligence
        layer exists because a frustrated guest at checkout needs a different response than a curious
        guest at check-in. The operator learning layer exists because no two operators run their
        properties the same way.
      </p>
      <p>
        <strong>This is what domain expertise looks like in software.</strong> Not a feature list.
        A system that reflects how the work actually gets done.
      </p>
      <div class="cred-points">
        <div class="cred-point">
          <div class="cred-point-dot"></div>
          <div class="cred-point-text"><strong>Real operator feedback</strong> shaped every layer of the architecture — from the escalation chain to the pre-booking confidence thresholds.</div>
        </div>
        <div class="cred-point">
          <div class="cred-point-dot"></div>
          <div class="cred-point-text"><strong>30A market expertise</strong> is embedded in the local knowledge layer — restaurant data, beach access, seasonal patterns, vendor relationships.</div>
        </div>
        <div class="cred-point">
          <div class="cred-point-dot"></div>
          <div class="cred-point-text"><strong>PMS integrations built to spec</strong> — Escapia, Guesty, and Track were chosen because they're what 30A operators actually use.</div>
        </div>
      </div>
    </div>
    <div class="operator-card">
      <div class="operator-card-quote">
        We built this because we needed it ourselves. Every operator managing more than 10 units
        is drowning in messages that don't need a human. Oyvoda handles the ones that don't,
        so you can focus on the ones that do.
      </div>
      <div class="operator-card-meta">
        <div class="operator-card-avatar">O</div>
        <div class="operator-card-info">
          <div class="operator-card-name">Founding Operator</div>
          <div class="operator-card-role">30A Florida · 50 Units · Escapia</div>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- FAQ -->
<section class="faq-section" id="faq">
  <div class="section-label">Questions</div>
  <h2>How the engine works, plainly.</h2>

  <div class="faq-item">
    <div class="faq-q">How does Oyvoda know about my specific property?</div>
    <div class="faq-a">
      When you connect your PMS (Escapia, Guesty, or Track), Oyvoda syncs your property listings, booking data, and unit details automatically. You then complete a short operator questionnaire covering check-in rules, pet policies, local recommendations, and house rules. This data is indexed into a <strong>property-specific vector knowledge base</strong> — Oyvoda retrieves from your data, not a general training set.
    </div>
  </div>

  <div class="faq-item">
    <div class="faq-q">What happens when the AI doesn't know the answer?</div>
    <div class="faq-a">
      The AI doesn't guess. When retrieval confidence falls below threshold, the question surfaces in your operator dashboard as a <strong>Knowledge Gap</strong>. You approve an answer once, and every future guest asking the same question gets that answer automatically. The knowledge base grows with every interaction.
    </div>
  </div>

  <div class="faq-item">
    <div class="faq-q">Can the AI make mistakes that embarrass my business?</div>
    <div class="faq-a">
      The pre-booking pipeline operates in <strong>approval-required mode</strong> by default — every AI draft is reviewed by you before sending. As you build confidence in the system's accuracy for specific property and intent combinations, you can advance individual properties to auto-send mode. The canary rollout system means you never accidentally deploy a behavior change portfolio-wide.
    </div>
  </div>

  <div class="faq-item">
    <div class="faq-q">How is this different from a chatbot?</div>
    <div class="faq-a">
      A chatbot follows scripts. Oyvoda runs <strong>five distinct AI layers</strong> per message — emotional intelligence, property-specific knowledge retrieval, governed tool execution, real-time observability, and operator-specific learning. It handles the full pre-booking inquiry flow (before a guest has even booked), manages in-stay questions, detects and escalates emergencies, and improves with every operator interaction. No script could cover this range.
    </div>
  </div>

  <div class="faq-item">
    <div class="faq-q">Is my property data private?</div>
    <div class="faq-a">
      Yes. Each operator's data is isolated — scoped to their <code>company_id</code> at the database level. No operator's property knowledge, guest conversations, or booking data is accessible to other operators. Platform intelligence (anonymous aggregate patterns) is the only cross-operator data flow, and it contains no personally identifiable information.
    </div>
  </div>

  <div class="faq-item">
    <div class="faq-q">What does "RCS-first" mean for my guests?</div>
    <div class="faq-a">
      RCS (Rich Communication Services) is the upgraded messaging standard now supported on virtually all modern Android and iPhone devices. It delivers rich messages — read receipts, typing indicators, high-resolution images, interactive buttons — through the native Messages app. <strong>No app download, no signup, no friction for your guests.</strong> They just tap the link you send them. SMS is the fallback for older devices.
    </div>
  </div>
</section>

</div><!-- end page-content -->
</div><!-- end page-layout -->

<!-- CTA -->
<section class="cta-section">
  <h2>See the engine<br><em>working for your portfolio.</em></h2>
  <p>Connect your PMS and watch the first AI-drafted reply appear in your queue. Most operators are live within 48 hours.</p>
  <div class="cta-buttons">
    <a href="/signup" class="btn-primary">Start Free Trial →</a>
    <a href="/" class="btn-ghost">← Back to Platform</a>
  </div>
</section>

<!-- FOOTER -->
<footer>
  <a href="/" class="footer-logo">oyvoda</a>
  <div class="footer-links">
    <a href="/engine" class="footer-link">Engine</a>
    <a href="/security" class="footer-link">Security</a>
    <a href="/privacy" class="footer-link">Privacy</a>
    <a href="/signup" class="footer-link">Get Started</a>
    <a href="/docs" class="footer-link">API Docs</a>
  </div>
</footer>

<script>
// Scroll spy — highlights active section in left nav
(function() {
  const sections = ['architecture','technology','compare','built-by','faq'];
  const navItems = {};
  sections.forEach(id => {
    navItems[id] = document.querySelector('.section-nav-item[href="#' + id + '"]');
  });
  function onScroll() {
    let current = sections[0];
    sections.forEach(id => {
      const el = document.getElementById(id);
      if (el && window.scrollY >= el.offsetTop - 120) current = id;
    });
    sections.forEach(id => {
      if (navItems[id]) navItems[id].classList.toggle('active', id === current);
    });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
})();
</script>

</body>
</html>"""


@router.get("/engine", response_class=HTMLResponse, include_in_schema=False)
async def serve_engine():
    from app.api.v1.endpoints.shared_nav import nav_html, _NAV_CSS
    html = ENGINE_HTML.replace('NAV_PLACEHOLDER', nav_html('engine'))
    # Inject shared nav CSS before </style>
    html = html.replace('</style>\n</head>', _NAV_CSS + '\n</style>\n</head>', 1)
    return HTMLResponse(content=html)
