import api from '../api.js?v=2026-04-21-c';
import { normalizeDashboardSummary } from '../adapters.js?v=2026-04-21-b';

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function fmtNumber(value) {
  return Number(value || 0).toLocaleString();
}

async function loadAnalytics() {
  try {
    const [summaryPayload, auditPayload] = await Promise.all([
      api.summary(),
      api.raw.auditSummary(30),
    ]);
    const summary = normalizeDashboardSummary(summaryPayload);
    const audit = auditPayload || {};

    setText('an-sessions', fmtNumber(summary.sessions.total30d));
    setText('an-messages', fmtNumber(summary.messages30d));
    setText('an-pb', fmtNumber(summary.preBooking.replied30d));
    setText('an-esc', fmtNumber(summary.escalations.open));

    setText('an-kb-entries', fmtNumber(summary.kbEntries));
    setText('an-kb-gaps', fmtNumber(summary.kbGaps));
    setText('an-vendors', fmtNumber(summary.vendors));
    setText('an-props', fmtNumber(summary.properties));

    setText('an-pb-pending', fmtNumber(summary.preBooking.pending));
    setText('an-pb-sent', fmtNumber(summary.preBooking.replied30d));
    setText('an-in-stay', fmtNumber(summary.sessions.inStay));
    setText('an-arriving', fmtNumber(summary.sessions.arriving));

    setText('aud-sess', fmtNumber(audit.guest_sessions));
    setText('aud-msgs', fmtNumber(audit.messages_processed));
    setText('aud-pb', fmtNumber(audit.pre_booking_drafts));
    setText('aud-kb', fmtNumber(audit.kb_entries_added));
  } catch (error) {
    console.warn('[Analytics] load failed:', error);
  }
}

function isAnalyticsView() {
  const analytics = document.getElementById('view-analytics');
  const audit = document.getElementById('view-audit');
  return (analytics && analytics.style.display !== 'none') || (audit && audit.style.display !== 'none');
}

export function init() {
  window.addEventListener('oyvoda:view-changed', (event) => {
    const view = event.detail?.view;
    if (view === 'analytics' || view === 'audit') {
      loadAnalytics();
    }
  });
  if (isAnalyticsView()) {
    loadAnalytics();
  }
}
