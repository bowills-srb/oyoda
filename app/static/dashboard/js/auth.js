/**
 * auth.js — Session, impersonation, logout.
 *
 * loadSession()           — fetches /app/auth/session and caches operator
 * populateOperatorUI(op)  — writes operator name/company/badges into topbar/sidebar
 * exitImpersonation()     — super-admin exits scoped operator view
 * doLogout()              — clears cookies, redirects to login
 *
 * All behavior preserved verbatim from the pre-refactor build.
 */

import { state } from './state.js?v=2026-04-21-b';

let operator = null;  // cached in module scope; also stored in state

function clearSessionState() {
  operator = null;
  sessionStorage.removeItem('oyvoda_op');
  state.clear('operator');
}

async function loadSession() {
  const r = await fetch('/app/auth/session');
  if (!r.ok) {
    clearSessionState();
    window.location.href = '/app';
    return;
  }
  const data = await r.json();
  operator = data.operator;
  sessionStorage.setItem('oyvoda_op', JSON.stringify(operator));
  state.set('operator', operator);
  populateOperatorUI();
}

function populateOperatorUI() {
  if (!operator) return;
  const hasAdminDashboardAccess = Boolean(
    operator.is_super_admin || ['company_admin', 'ops_admin'].includes(operator.role)
  );

  // Tiny helper: set textContent only if the element exists.
  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };

  setText('op-name', operator.name || 'Operator');
  setText('op-badge', (operator.pms || 'PMS') + ' · ' + (operator.properties || 0) + ' units');
  setText('sb-op-name', operator.company || operator.name);
  setText('sb-op-meta', (operator.pms || '—') + ' · ' + (operator.properties || 0) + ' properties');
  setText('ov-greeting', 'Good morning, ' + (operator.name || 'Operator').split(' ')[0]);
  setText('team-owner-name', operator.name || 'Owner');
  setText('team-owner-email', operator.email || '');
  if (operator.impersonating) {
    const banner = document.getElementById('impersonation-banner');
    const copy = document.getElementById('impersonation-copy');
    if (banner && copy) {
      copy.innerHTML = 'Viewing as <strong>' + (operator.name || 'Operator') + '</strong> · ' + (operator.company || '') + ' · signed in as ' + (operator.admin_email || 'super admin');
      banner.classList.add('show');
      document.body.classList.add('impersonating');
    }
  } else {
    const banner = document.getElementById('impersonation-banner');
    if (banner) banner.classList.remove('show');
    document.body.classList.remove('impersonating');
  }
  if (operator.is_super_admin && !operator.impersonating) {
    // Sidebar nav section (new)
    const adminNav = document.getElementById('super-admin-nav');
    if (adminNav) adminNav.style.display = '';
    const adminDivider = document.getElementById('super-admin-divider');
    if (adminDivider) adminDivider.style.display = '';
    // Settings "Super Admin Tools" card (pre-existing)
    const adminTools = document.getElementById('super-admin-tools');
    if (adminTools) adminTools.style.display = '';
    const sloCard = document.getElementById('slo-card');
    if (sloCard) sloCard.style.display = '';
  } else {
    const adminNav = document.getElementById('super-admin-nav');
    if (adminNav) adminNav.style.display = 'none';
    const adminDivider = document.getElementById('super-admin-divider');
    if (adminDivider) adminDivider.style.display = 'none';
    const adminTools = document.getElementById('super-admin-tools');
    if (adminTools) adminTools.style.display = 'none';
    const sloCard = document.getElementById('slo-card');
    if (sloCard) sloCard.style.display = 'none';
  }

  const llmUsageNav = document.getElementById('nav-llm-usage');
  if (llmUsageNav) llmUsageNav.style.display = hasAdminDashboardAccess ? '' : 'none';
}

async function exitImpersonation() {
  const r = await fetch('/app/api/admin/scope', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({operator_id: null})
  });
  const data = await r.json();
  if (!r.ok) {
    alert(data.detail || 'Could not exit operator view.');
    return;
  }
  sessionStorage.setItem('oyvoda_op', JSON.stringify(data.operator));
  state.set('operator', data.operator);
  window.location.href = '/app/dashboard';
}

async function doLogout() {
  await fetch('/app/auth/logout', {method:'POST'});
  clearSessionState();
  window.location.href = '/app';
}

// Keep the module's `operator` in sync when other code updates state
state.subscribe('operator', (v) => { operator = v; });

// Expose functions called from HTML onclick="..." attributes
window.exitImpersonation = exitImpersonation;
window.doLogout = doLogout;

// Other modules import these directly
export { loadSession, populateOperatorUI, exitImpersonation, doLogout };
