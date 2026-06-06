"""
privacy.py — Oyvoda Privacy Policy + Security & Compliance pages

GET /privacy   — Privacy Policy
GET /security  — Security, Compliance & Audit page
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Legal"])

_FAVICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%2308090f'/%3E%3Ctext x='16' y='23' font-family='Georgia,serif' font-size='21' font-weight='500' fill='%23f0ebe3' text-anchor='middle'%3Eo%3C/text%3E%3Cpath d='M20 7 Q24 4 27 8' stroke='%23c87832' stroke-width='2' fill='none' stroke-linecap='round'/%3E%3C/svg%3E"

_CSS = """
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html { scroll-behavior: smooth; }
  body { background: #08090f; color: #f0ebe3; font-family: 'DM Sans', sans-serif; line-height: 1.7; -webkit-font-smoothing: antialiased; }
  nav { position: sticky; top: 0; z-index: 100; background: rgba(8,9,15,0.92); backdrop-filter: blur(16px); border-bottom: 1px solid rgba(200,120,50,0.12); padding: 0 48px; height: 64px; display: flex; align-items: center; justify-content: space-between; }
  .nav-logo { font-family: 'Cormorant Garamond', serif; font-size: 22px; font-weight: 500; color: #f0ebe3; text-decoration: none; letter-spacing: -0.02em; }
  .nav-links { display: flex; gap: 8px; align-items: center; }
  .nav-link { color: rgba(240,235,227,0.5); text-decoration: none; font-size: 14px; padding: 6px 14px; border-radius: 6px; transition: color 0.15s; }
  .nav-link:hover { color: #f0ebe3; background: rgba(255,255,255,0.04); }
  .nav-cta { background: #c87832; color: #f0ebe3; text-decoration: none; font-size: 13px; font-weight: 500; padding: 8px 20px; border-radius: 8px; transition: background 0.15s; }
  .nav-cta:hover { background: #e09040; }
  .container { max-width: 820px; margin: 0 auto; padding: 80px 48px 120px; }
  .eyebrow { font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase; color: #c87832; margin-bottom: 16px; }
  h1 { font-family: 'Cormorant Garamond', serif; font-size: clamp(36px, 5vw, 60px); font-weight: 600; letter-spacing: -0.02em; color: #f0ebe3; line-height: 1.1; margin-bottom: 16px; }
  .updated { font-size: 12px; color: rgba(240,235,227,0.3); margin-bottom: 64px; letter-spacing: 0.04em; }
  h2 { font-family: 'Cormorant Garamond', serif; font-size: 26px; font-weight: 600; color: #f0ebe3; margin: 52px 0 16px; letter-spacing: -0.01em; }
  h3 { font-family: 'DM Mono', monospace; font-size: 11px; font-weight: 500; color: rgba(240,235,227,0.5); margin: 28px 0 10px; letter-spacing: 0.1em; text-transform: uppercase; }
  p { font-size: 15px; color: rgba(240,235,227,0.6); margin-bottom: 16px; font-weight: 300; }
  p strong { color: rgba(240,235,227,0.85); font-weight: 500; }
  code { font-family: 'DM Mono', monospace; font-size: 12px; background: rgba(200,120,50,0.1); color: #c87832; padding: 2px 6px; border-radius: 4px; }
  ul { margin: 12px 0 16px 0; padding-left: 0; list-style: none; }
  ul li { font-size: 15px; color: rgba(240,235,227,0.6); font-weight: 300; padding: 5px 0 5px 20px; position: relative; }
  ul li::before { content: '—'; position: absolute; left: 0; color: rgba(200,120,50,0.5); }
  a { color: #c87832; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .contact-box { background: rgba(200,120,50,0.05); border: 1px solid rgba(200,120,50,0.15); border-radius: 16px; padding: 32px; margin-top: 48px; }
  .contact-box h3 { margin-top: 0; }
  footer { padding: 24px 48px; border-top: 1px solid rgba(255,255,255,0.04); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
  .footer-logo { font-family: 'Cormorant Garamond', serif; font-size: 15px; color: rgba(240,235,227,0.3); text-decoration: none; }
  .footer-links { display: flex; gap: 24px; }
  .footer-link { font-size: 12px; color: rgba(240,235,227,0.2); text-decoration: none; transition: color 0.15s; }
  .footer-link:hover { color: rgba(240,235,227,0.5); }
  /* Security extras */
  .badge-row { display: flex; flex-wrap: wrap; gap: 12px; margin: 24px 0; }
  .badge { display: flex; align-items: center; gap: 8px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 10px 16px; font-size: 12px; color: rgba(240,235,227,0.5); font-family: 'DM Mono', monospace; letter-spacing: 0.04em; }
  .badge-ok { color: #22c55e; }
  .badge-wip { color: #f97316; }
  .status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px,1fr)); gap: 14px; margin: 24px 0; }
  .sc { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; padding: 18px 20px; }
  .sc-label { font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: rgba(240,235,227,0.3); margin-bottom: 6px; }
  .sc-val { font-size: 14px; color: rgba(240,235,227,0.75); }
  .sc-val.green { color: #22c55e; }
  .sc-val.amber { color: #c87832; }
  .lr { display: flex; gap: 14px; align-items: flex-start; padding: 18px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
  .lr:last-child { border-bottom: none; }
  .lr-icon { width: 34px; height: 34px; border-radius: 8px; background: rgba(200,120,50,0.1); display: flex; align-items: center; justify-content: center; font-size: 15px; flex-shrink: 0; margin-top: 2px; }
  .lr h4 { font-size: 14px; font-weight: 500; color: #f0ebe3; margin-bottom: 5px; }
  .lr p { margin: 0; font-size: 13px; }
  @media (max-width: 768px) {
    nav { padding: 0 20px; }
    .container { padding: 60px 20px 80px; }
    footer { flex-direction: column; text-align: center; }
    .nav-links .nav-link { display: none; }
  }
</style>"""

_NAV = """
<nav>
  <a href="/" class="nav-logo">oyvoda</a>
  <div class="nav-links">
    <a href="/" class="nav-link">Platform</a>
    <a href="/engine" class="nav-link">Engine</a>
    <a href="/security" class="nav-link">Security</a>
    <a href="/privacy" class="nav-link">Privacy</a>
    <a href="/#pricing" class="nav-link">Pricing</a>
    <a href="/app" class="nav-cta">Sign In</a>
  </div>
</nav>"""

_FOOTER = """
<footer>
  <a href="/" class="footer-logo">oyvoda</a>
  <div class="footer-links">
    <a href="/privacy" class="footer-link">Privacy</a>
    <a href="/security" class="footer-link">Security</a>
    <a href="/engine" class="footer-link">Engine</a>
    <a href="/signup" class="footer-link">Get Started</a>
    <a href="/app" class="footer-link">Sign In</a>
  </div>
</footer>
</body>
</html>"""


def _page(title: str, description: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
<meta name="theme-color" content="#08090f">
<link rel="icon" type="image/svg+xml" href="{_FAVICON}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
{_CSS}
</head>
<body>
{_NAV}
{body}
{_FOOTER}"""


# ── PRIVACY BODY ──────────────────────────────────────────────────────────

_PRIVACY_BODY = """
<div class="container">
  <div class="eyebrow">Legal</div>
  <h1>Privacy Policy</h1>
  <p class="updated">Last updated: March 2026 &nbsp;·&nbsp; Effective: March 2026</p>

  <p>Oyvoda operates an AI-powered guest experience platform for short-term rental operators and boutique hotels. This Privacy Policy explains how we collect, use, store, and protect information when you use our platform as an operator, and how we handle guest data on your behalf.</p>

  <h2>1. Who We Are</h2>
  <p>Oyvoda is a software platform that processes guest communications and property management data on behalf of STR operators. Oyvoda acts as a <strong>data processor</strong> for guest data and a <strong>data controller</strong> for platform account data.</p>
  <ul>
    <li>Platform: oyvoda.com</li>
    <li>Privacy contact: privacy@oyvoda.com</li>
    <li>Data requests: privacy@oyvoda.com (30-day response SLA)</li>
  </ul>

  <h2>2. Information We Collect</h2>
  <h3>Operator Account Data</h3>
  <ul>
    <li>Name, email address, business name</li>
    <li>PMS credentials (stored encrypted, never logged in plaintext)</li>
    <li>Property details, house rules, operator preferences</li>
    <li>Billing information (processed by Stripe — not stored by Oyvoda)</li>
  </ul>
  <h3>Guest Data (Processed on Behalf of Operators)</h3>
  <ul>
    <li>Guest name, phone number, email address from PMS booking records</li>
    <li>Reservation dates and property assignment</li>
    <li>Message content from guest conversations via RCS/SMS</li>
    <li>Escalation notes and incident records created by operators</li>
  </ul>
  <h3>Platform Usage Data</h3>
  <ul>
    <li>API request logs — path, method, status code, latency (no message bodies)</li>
    <li>Dashboard usage patterns for product improvement</li>
    <li>Error logs for debugging, stripped of PII before storage</li>
  </ul>

  <h2>3. How We Use Data</h2>
  <ul>
    <li><strong>Service delivery:</strong> Processing guest messages, generating AI responses, routing escalations, syncing PMS data</li>
    <li><strong>Platform improvement:</strong> Anonymized, aggregated usage patterns only — individual operator data is never used in cross-operator model training without explicit consent</li>
    <li><strong>Security and monitoring:</strong> Detecting abuse, preventing prompt injection, maintaining SLO compliance</li>
    <li><strong>Communications:</strong> Service notifications, product updates — operators can opt out at any time</li>
  </ul>

  <h2>4. Data Storage and Retention</h2>
  <p>All data is stored in <strong>Supabase (PostgreSQL)</strong> hosted on AWS us-east-1. Data is isolated at the <code>company_id</code> level — no operator can access another operator's data.</p>
  <ul>
    <li>Guest conversation records: 90 days after checkout, then permanently deleted</li>
    <li>Escalation and incident records: 12 months</li>
    <li>API request logs: 30 days</li>
    <li>Operator account data: duration of account plus 30 days post-cancellation</li>
    <li>Encrypted backups: 7-day rolling retention</li>
  </ul>

  <h2>5. Data Sharing</h2>
  <p>We do not sell, rent, or share personal data for advertising purposes. Data is shared only with:</p>
  <ul>
    <li><strong>Groq:</strong> LLM inference provider. Message content sent for AI processing under their enterprise DPA with zero retention on inference infrastructure.</li>
    <li><strong>Supabase:</strong> Database hosting, SOC 2 Type II certified.</li>
    <li><strong>Railway:</strong> Application hosting. Data does not persist beyond the running process.</li>
    <li><strong>Cloudflare:</strong> CDN and DDoS protection. Traffic metadata only — no message content.</li>
    <li><strong>PMS providers (Escapia, Guesty, Track):</strong> Read-only API access to booking data you explicitly authorize.</li>
  </ul>

  <h2>6. Guest Data and Operator Responsibility</h2>
  <p>Operators are responsible for obtaining appropriate consent from guests to process their communications through Oyvoda. Connecting a PMS and deploying the Oyvoda concierge constitutes a representation that the operator has the right to process guest communications through our platform. Oyvoda provides standard guest consent language for inclusion in welcome messages on request.</p>

  <h2>7. Security</h2>
  <p>Core security controls include SSL/TLS encryption in transit, AES-256 encryption at rest, a hard-coded MCP trust registry that eliminates prompt injection by architecture, a sanitizer layer before every LLM call, governance validation before every action, and company-scoped data isolation at the query level. See our <a href="/security">Security &amp; Compliance page</a> for full technical detail.</p>

  <h2>8. Your Rights</h2>
  <p>Depending on your location, you may have rights to access, correct, delete, or export your data.</p>
  <ul>
    <li><strong>Operators:</strong> Email privacy@oyvoda.com — 30-day response, 72-hour response for urgent deletion</li>
    <li><strong>Guests:</strong> Contact the operator whose property you stayed at. Operators can export and delete guest data from the operator dashboard.</li>
  </ul>

  <h2>9. CCPA (California Residents)</h2>
  <p>California residents have the right to know what personal information is collected, request deletion, and opt out of sale. We do not sell personal information. Submit CCPA requests to privacy@oyvoda.com.</p>

  <h2>10. GDPR (EEA/UK Residents)</h2>
  <p>For EEA and UK residents, Oyvoda acts as data processor for guest data and data controller for operator account data. Lawful basis for processing: contractual necessity. A Data Processing Agreement (DPA) is available on request for operators who require it — contact privacy@oyvoda.com.</p>

  <h2>11. Cookies</h2>
  <p>The Oyvoda dashboard uses session cookies for authentication only. No advertising or tracking cookies. No third-party analytics scripts are loaded.</p>

  <h2>12. Policy Changes</h2>
  <p>Material changes will be communicated by email with at least 14 days notice. Continued use after the effective date constitutes acceptance.</p>

  <div class="contact-box">
    <h3>Privacy Contact</h3>
    <p style="margin-bottom:8px;">Questions, data requests, DPA agreements:</p>
    <p><a href="mailto:privacy@oyvoda.com"><strong>privacy@oyvoda.com</strong></a></p>
    <p style="margin-top:8px;font-size:13px;color:rgba(240,235,227,0.4);">30-day response SLA. Urgent deletion requests: 72 hours.</p>
  </div>
</div>"""


# ── SECURITY BODY ─────────────────────────────────────────────────────────

_SECURITY_BODY = """
<div class="container">
  <div class="eyebrow">Trust &amp; Safety</div>
  <h1>Security &amp;<br>Compliance</h1>
  <p class="updated">Architecture review: March 2026 &nbsp;·&nbsp; Infrastructure: Railway + Supabase + Cloudflare</p>

  <p>This page documents Oyvoda's security architecture, compliance posture, and audit capabilities for operators conducting security reviews and external reviewers evaluating the platform.</p>

  <h2>Certification Status</h2>
  <div class="badge-row">
    <div class="badge"><span class="badge-ok">✓</span> SSL/TLS All Connections</div>
    <div class="badge"><span class="badge-ok">✓</span> AES-256 At Rest</div>
    <div class="badge"><span class="badge-ok">✓</span> Company-Scoped Data Isolation</div>
    <div class="badge"><span class="badge-ok">✓</span> Structural Prompt Injection Defense</div>
    <div class="badge"><span class="badge-ok">✓</span> Governed Tool Execution</div>
    <div class="badge"><span class="badge-ok">✓</span> Hallucination Guard (RAG + Confidence Threshold)</div>
    <div class="badge"><span class="badge-ok">✓</span> Supabase SOC 2 Type II</div>
    <div class="badge"><span class="badge-ok">✓</span> Railway SOC 2 Type II</div>
    <div class="badge"><span class="badge-ok">✓</span> Cloudflare Enterprise DDoS</div>
    <div class="badge"><span class="badge-wip">○</span> Oyvoda SOC 2 — In Progress (target Q4 2026)</div>
    <div class="badge"><span class="badge-wip">○</span> GDPR DPA — Available on Request</div>
  </div>

  <div class="status-grid">
    <div class="sc"><div class="sc-label">Uptime Target</div><div class="sc-val green">99.9%</div></div>
    <div class="sc"><div class="sc-label">Health Check</div><div class="sc-val">Every 15 seconds</div></div>
    <div class="sc"><div class="sc-label">Data Isolation</div><div class="sc-val green">Per company_id</div></div>
    <div class="sc"><div class="sc-label">Injection Defense</div><div class="sc-val green">Architectural</div></div>
    <div class="sc"><div class="sc-label">LLM Provider</div><div class="sc-val">Groq (zero retention)</div></div>
    <div class="sc"><div class="sc-label">Audit Export</div><div class="sc-val amber">Dashboard + API</div></div>
  </div>

  <h2>Security Architecture</h2>
  <p>Oyvoda's security is <strong>structural, not rule-based</strong>. Most AI platforms defend against attacks by filtering content. Oyvoda defends by making certain attack vectors architecturally impossible.</p>

  <div class="lr">
    <div class="lr-icon">🔒</div>
    <div>
      <h4>Hard-Coded MCP Trust Registry</h4>
      <p>All 9 Model Context Protocol servers are registered at application startup from a static, code-defined list. No server can be added, removed, or modified at runtime — not by user input, not by AI inference, not by API call. This eliminates the entire class of prompt injection attacks that attempt to register malicious tools — by architectural constraint, not filtering.</p>
    </div>
  </div>
  <div class="lr">
    <div class="lr-icon">🛡️</div>
    <div>
      <h4>Sanitizer MCP Layer</h4>
      <p>Every guest message passes through sanitizer_mcp before reaching the LLM. It strips injection patterns, removes control characters, truncates to safe lengths, and validates encoding. Content that fails sanitization is logged and rejected — it never reaches inference.</p>
    </div>
  </div>
  <div class="lr">
    <div class="lr-icon">⚖️</div>
    <div>
      <h4>Governance MCP — Pre-Execution Validation</h4>
      <p>Every proposed AI action passes through governance_mcp before execution. Checks: action is in the permitted set, operator has enabled it, parameters are within bounds, action is scoped to the correct operator. Actions that fail validation are blocked and logged — the AI cannot act outside its authorized scope.</p>
    </div>
  </div>
  <div class="lr">
    <div class="lr-icon">🧠</div>
    <div>
      <h4>Hallucination Guard — Response Grounding Verification</h4>
      <p>Every AI response is compared against the retrieved source chunks using token-level Jaccard similarity. Responses that diverge significantly from source material are flagged or blocked before delivery. Number fabrication detection checks that specific values in responses (prices, codes, times) exist in the source context. Emergency-intent responses are held to stricter thresholds and automatically escalated if grounding fails.</p>
    </div>
  </div>
  <div class="lr">
    <div class="lr-icon">🗃️</div>
    <div>
      <h4>Company-Scoped Data Isolation</h4>
      <p>Every database query is scoped by company_id at the query level. There is no mechanism by which one operator's data is accessible in another operator's context. This is enforced at the data access layer — a bug in the application cannot cross company boundaries.</p>
    </div>
  </div>
  <div class="lr">
    <div class="lr-icon">🔐</div>
    <div>
      <h4>Credential Handling</h4>
      <p>PMS credentials are stored encrypted and never appear in logs, API responses, or error messages. Secrets are injected at runtime via environment variables — they are not stored in the codebase or version control.</p>
    </div>
  </div>
  <div class="lr">
    <div class="lr-icon">🌐</div>
    <div>
      <h4>Transport Security</h4>
      <p>All connections use TLS 1.2+. Cloudflare terminates TLS at the edge. Database connections use SSL with certificate verification. No unencrypted paths exist between any system components.</p>
    </div>
  </div>

  <h2 id="audit">Audit Capabilities</h2>
  <h3>Internal Operator Audit</h3>
  <p>From the operator dashboard, operators can access and export:</p>
  <ul>
    <li>All guest conversations — timestamps, AI decision metadata, intent scores, confidence</li>
    <li>Pre-booking draft history — original AI draft, operator edits, final sent version</li>
    <li>Escalation log — trigger reason, assignee, resolution, time-to-resolve</li>
    <li>Knowledge base change log — additions, edits, approvals with timestamps</li>
    <li>Canary rollout history — which behaviors deployed, when, to which properties</li>
  </ul>
  <p>Export formats: CSV and JSON. Date-range filtering supported. Access via the <a href="/operator-dashboard">dashboard</a> Audit tab or directly via <a href="/api/v1/audit/export?format=json&days=30">the audit API</a>.</p>

  <h3>External / Third-Party Audit</h3>
  <p>For formal external reviews, Oyvoda can provide:</p>
  <ul>
    <li>Architecture documentation and data flow diagrams</li>
    <li>SOC 2 Type II reports from Supabase and Railway (available now)</li>
    <li>Oyvoda SOC 2 readiness assessment (target Q4 2026)</li>
    <li>Data Processing Agreement (DPA) for GDPR-regulated operators</li>
    <li>Penetration test results (planned Q3 2026)</li>
  </ul>
  <p>Request via <a href="mailto:security@oyvoda.com">security@oyvoda.com</a>.</p>

  <h2>Incident Response</h2>
  <ul>
    <li>Operators notified within 72 hours of confirmed breach affecting their data</li>
    <li>Notification includes: nature of incident, data categories affected, remediation taken</li>
    <li>Operators responsible for guest notification in accordance with applicable law</li>
    <li>All incidents logged and post-mortem published internally within 14 days</li>
  </ul>

  <h2>Infrastructure</h2>
  <div class="status-grid">
    <div class="sc"><div class="sc-label">Hosting</div><div class="sc-val">Railway (SOC 2 Type II)</div></div>
    <div class="sc"><div class="sc-label">Database</div><div class="sc-val">Supabase (SOC 2 Type II)</div></div>
    <div class="sc"><div class="sc-label">CDN / DDoS</div><div class="sc-val">Cloudflare Enterprise</div></div>
    <div class="sc"><div class="sc-label">LLM Inference</div><div class="sc-val">Groq (zero retention)</div></div>
    <div class="sc"><div class="sc-label">Backups</div><div class="sc-val">Daily, encrypted, 7-day retention</div></div>
    <div class="sc"><div class="sc-label">Region</div><div class="sc-val">AWS us-east-1</div></div>
  </div>

  <div class="contact-box">
    <h3>Security Contact</h3>
    <p style="margin-bottom:8px;">Vulnerability reports, security documentation requests, compliance discussions:</p>
    <p><a href="mailto:security@oyvoda.com"><strong>security@oyvoda.com</strong></a></p>
    <p style="margin-top:8px;font-size:13px;color:rgba(240,235,227,0.4);">Critical vulnerabilities: 24-hour response. Responsible disclosure policy — good-faith researchers will not face legal action.</p>
  </div>
</div>"""


# ── ROUTES ────────────────────────────────────────────────────────────────

@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def serve_privacy():
    from app.api.v1.endpoints.shared_nav import nav_html as _nav, _NAV_CSS as _ncss
    head = f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Privacy Policy — Oyvoda</title><meta name="description" content="Oyvoda privacy policy."><meta name="theme-color" content="#08090f"><link rel="icon" type="image/svg+xml" href="{_FAVICON}"><link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">{_CSS}<style>{_ncss}</style></head><body>'
    return HTMLResponse(content=head + _nav('privacy') + _PRIVACY_BODY + _FOOTER)


@router.get("/security", response_class=HTMLResponse, include_in_schema=False)
async def serve_security():
    from app.api.v1.endpoints.shared_nav import nav_html as _nav, _NAV_CSS as _ncss
    head = f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Security &amp; Compliance — Oyvoda</title><meta name="description" content="Oyvoda security architecture and compliance."><meta name="theme-color" content="#08090f"><link rel="icon" type="image/svg+xml" href="{_FAVICON}"><link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">{_CSS}<style>{_ncss}</style></head><body>'
    return HTMLResponse(content=head + _nav('security') + _SECURITY_BODY + _FOOTER)
