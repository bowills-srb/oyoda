"""
shared_nav.py — Single source of truth for Oyvoda navigation

Every public-facing page imports _NAV_HTML and _NAV_CSS from here.
One change here updates all pages simultaneously.

Navigation reading journey (logical order for a visitor):
  Platform (/)  →  How It Works (/operator-dashboard)  →  Engine (/engine)  →  Security (/security)  →  Pricing (/#pricing)

Right side:
  Talk to Sales  |  Request Demo →

Active page is highlighted by passing the current_page parameter.
"""

_FAVICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%2308090f'/%3E%3Ctext x='16' y='23' font-family='Georgia,serif' font-size='21' font-weight='500' fill='%23f0ebe3' text-anchor='middle'%3Eo%3C/text%3E%3Cpath d='M20 7 Q24 4 27 8' stroke='%23c87832' stroke-width='2' fill='none' stroke-linecap='round'/%3E%3C/svg%3E"

_NAV_CSS = """
/* ── SHARED TOPNAV ── */
.oyvoda-nav {
  position: sticky; top: 0; z-index: 200;
  background: rgba(8,9,15,0.96); backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(200,120,50,0.12);
  height: 64px; padding: 0 48px;
  display: flex; align-items: center; justify-content: space-between;
  font-family: 'DM Sans', -apple-system, sans-serif;
}
.oyvoda-nav-logo {
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-size: 22px; font-weight: 500; color: #f0ebe3;
  text-decoration: none; letter-spacing: -0.02em;
  flex-shrink: 0;
}
.oyvoda-nav-links {
  display: flex; align-items: center; gap: 2px;
  position: absolute; left: 50%; transform: translateX(-50%);
}
.oyvoda-nav-link {
  color: rgba(240,235,227,0.5);
  text-decoration: none; font-size: 14px; font-weight: 400;
  padding: 7px 15px; border-radius: 7px;
  transition: color 0.15s, background 0.15s;
  white-space: nowrap;
}
.oyvoda-nav-link:hover {
  color: #f0ebe3; background: rgba(255,255,255,0.05);
}
.oyvoda-nav-link.active {
  color: #c87832; background: rgba(200,120,50,0.08);
}
.oyvoda-nav-right {
  display: flex; align-items: center; gap: 8px; flex-shrink: 0;
}
.oyvoda-nav-sales {
  font-size: 13px; color: rgba(240,235,227,0.5);
  text-decoration: none; padding: 8px 16px; border-radius: 8px;
  border: 1px solid rgba(200,120,50,0.25); color: #c87832;
  transition: all 0.15s;
}
.oyvoda-nav-sales:hover {
  background: rgba(200,120,50,0.08); color: #e09040;
}
.oyvoda-nav-cta {
  background: #c87832; color: #f0ebe3;
  text-decoration: none; font-size: 13px; font-weight: 600;
  padding: 9px 22px; border-radius: 9px;
  transition: background 0.15s, transform 0.15s;
}
.oyvoda-nav-cta:hover { background: #e09040; transform: translateY(-1px); }

/* ── SECTION NAV NUMBERS (brighter amber) ── */
.snav-num {
  font-family: 'DM Mono', monospace;
  font-size: 11px; font-weight: 500;
  color: #c87832 !important;
  opacity: 0.7;
  width: 22px; flex-shrink: 0;
  letter-spacing: 0.04em;
}
.section-nav-item.active .snav-num,
.section-nav-item:hover .snav-num {
  opacity: 1;
  color: #e09040 !important;
}
/* Layer card numbers on engine page */
.layer-num {
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-size: 48px; font-weight: 600;
  color: #c87832 !important;
  opacity: 0.6;
  line-height: 1; text-align: center;
}
/* Workflow step numbers on operator tour */
.wf-num {
  color: #c87832 !important;
  border-color: rgba(200,120,50,0.4) !important;
}

@media (max-width: 900px) {
  .oyvoda-nav { padding: 0 20px; }
  .oyvoda-nav-links { display: none; }
}
"""


def nav_html(current_page: str = "") -> str:
    """
    Returns the full topnav HTML with the current page link highlighted.
    current_page: 'landing' | 'operator' | 'engine' | 'security' | 'privacy'
    """
    def link(href: str, label: str, page_key: str) -> str:
        active = ' class="oyvoda-nav-link active"' if current_page == page_key else ' class="oyvoda-nav-link"'
        return f'<a href="{href}"{active}>{label}</a>'

    return f"""<nav class="oyvoda-nav">
  <a href="/" class="oyvoda-nav-logo">oyvoda</a>
  <div class="oyvoda-nav-links">
    {link("/", "Platform", "landing")}
    {link("/operator-dashboard", "How It Works", "operator")}
    {link("/engine", "Engine", "engine")}
    {link("/security", "Security", "security")}
    {link("/#pricing", "Pricing", "pricing")}
  </div>
  <div class="oyvoda-nav-right">
    <a href="/app" class="oyvoda-nav-sales">Sign In</a>
    <a href="/signup" class="oyvoda-nav-cta">Get Started →</a>
  </div>
</nav>"""
