/**
 * main.js — Dashboard shell entry point.
 *
 * Section-specific behavior now lives in `js/sections/*`.
 * This file owns shared shell concerns, bootstrapping, and a small number of
 * backwards-compatible helpers that still hang off `window`.
 */

import { loadSession } from './auth.js?v=2026-04-21-d';
import { navigate } from './router.js?v=2026-05-19-b';
import { init as initMessages } from './sections/messages.js?v=2026-05-20-b';
import { init as initSessions } from './sections/sessions.js?v=2026-04-29-g';
import { init as initEscalations } from './sections/escalations.js?v=2026-04-23-a';
import { init as initKnowledge } from './sections/knowledge.js?v=2026-05-20-b';
import { init as initVendors } from './sections/vendors.js?v=2026-04-23-a';
import { init as initSettings } from './sections/settings.js?v=2026-04-29-c';
import { init as initNotifications } from './sections/notifications.js?v=2026-05-19-b';
import { init as initToday, refreshAll as refreshTodayAll } from './sections/today.js?v=2026-05-19-g';
import { init as initProperties } from './sections/properties.js?v=2026-04-28-b';
import { init as initTeam } from './sections/team.js?v=2026-04-23-a';
import { init as initAnalytics } from './sections/analytics.js?v=2026-04-21-e';
import { init as initLlmUsage } from './sections/llm-usage.js?v=2026-05-13-a';
import { init as initMarket } from './sections/market.js?v=2026-04-23-a';
import { init as initAudit } from './sections/audit.js?v=2026-04-29-a';
import { init as initShell, loadOnboardingStatus } from './sections/shell.js?v=2026-05-19-d';

window.__oyvodaPropertiesModule = true;
window.__oyvodaMarketModule = true;

function setSidebarCollapsed(collapsed) {
  document.body.classList.toggle('sidebar-collapsed', !!collapsed);
  const toggle = document.getElementById('sidebar-toggle');
  if (toggle) {
    toggle.setAttribute('aria-hidden', 'true');
    toggle.tabIndex = -1;
  }
}

function initSidebarChrome() {
  const apply = () => {
    setSidebarCollapsed(window.innerWidth >= 1200);
  };
  apply();
  window.addEventListener('resize', apply);
}

async function refreshAll() {
  await refreshTodayAll();
}

function reassignDraft() { showModal('assign-modal') || navigate('team'); }

function resolveEscalation() {
  if (confirm('Mark this escalation as resolved?')) {
    document.querySelector('#view-escalations .data-table tbody').innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--dim);padding:24px;font-size:12px">No open escalations</td></tr>';
    document.getElementById('nb-esc').textContent = '0';
  }
}

function assignEscalation(sel) {
  alert('Escalation assigned to: ' + sel.options[sel.selectedIndex].text);
}

function showModal(id) {
  document.getElementById(id).style.display = 'flex';
}

document.addEventListener('click', function(e) {
  const panel = document.getElementById('notif-panel');
  if (!e.target.closest('#notif-panel') && !e.target.closest('[onclick="toggleNotifs()"]')) {
    panel.classList.remove('open');
  }
});

document.addEventListener('DOMContentLoaded', async function() {
  try {
    const r = await fetch('/app/auth/refresh', { method: 'POST' });
    if (!r.ok) {
      window.location.href = '/app';
      return;
    }
  } catch (_) {
    // If refresh fails we still attempt to load the session; auth.js handles
    // the authoritative session bootstrap path.
  }

  await loadSession();

  document.body.setAttribute('data-current-view', 'today');
  initSidebarChrome();

  await refreshAll();
  loadOnboardingStatus();

  initMessages();
  initSessions();
  initEscalations();
  initKnowledge();
  initVendors();
  initSettings();
  initNotifications();
  initToday();
  initProperties();
  initTeam();
  initAnalytics();
  initLlmUsage();
  initMarket();
  initAudit();
  initShell();

  setInterval(refreshAll, 30000);
  document.getElementById('notif-badge').style.display = 'block';
});

window.refreshAll = refreshAll;
window.reassignDraft = reassignDraft;
window.resolveEscalation = resolveEscalation;
window.assignEscalation = assignEscalation;

// Legacy stubs for old cached HTML shells. The canonical wiring now lives in
// section modules, but these prevent noisy ReferenceErrors during cache lag.
window.sendDraft = window.sendDraft || function(){};
window.editDraft = window.editDraft || function(){};
window.rejectDraft = window.rejectDraft || function(){};
window.selectInquiry = window.selectInquiry || function() {};
