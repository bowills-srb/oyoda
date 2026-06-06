/**
 * sessions.js — Guest Sessions workspace
 *
 * Minimal operator reader for active and recent guest conversations.
 * Used directly by Guest Sessions and as the handoff target from Escalations.
 */

import api from '../api.js?v=2026-04-29-c';
import { normalizeSessionDetail, normalizeSessionsList } from '../adapters.js?v=2026-04-29-c';
import { state as appState } from '../state.js?v=2026-04-21-b';

const PREF_NS = 'oyvoda.dashboard.sessions';

const state = {
  filter: 'all',
  workView: 'live_sessions',
  mode: 'auto',
  scopeFilter: 'all',
  items: [],
  portfolios: [],
  proactivePolicy: null,
  activeId: null,
  detail: null,
  summary: {
    total: 0,
    inStay: 0,
    arriving: 0,
    postStay: 0,
    openEscalations: 0,
  },
  loading: false,
  pendingSessionId: null,
  pendingEscalation: null,
  lastLoadedAt: null,
};

let pollTimer = null;

function operatorKey() {
  const operator = appState.get('operator') || {};
  return operator.id || operator.company || 'operator';
}

function prefKey(field) {
  return `${PREF_NS}.${operatorKey()}.${field}`;
}

function loadPreference(field, fallback) {
  try {
    const value = localStorage.getItem(prefKey(field));
    return value == null ? fallback : value;
  } catch (_) {
    return fallback;
  }
}

function savePreference(field, value) {
  try {
    localStorage.setItem(prefKey(field), String(value));
  } catch (_) {
    // ignore storage failures
  }
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function fmtTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = (now - d) / 1000;
    if (diff < 60) return `${Math.round(diff)}s ago`;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    return `${Math.round(diff / 86400)}d ago`;
  } catch (_) {
    return '';
  }
}

function fmtAbsolute(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch (_) {
    return '';
  }
}

function phaseLabel(phase) {
  return {
    pre_arrival: 'Arriving',
    arrival_day: 'Arrival Day',
    in_stay: 'In-Stay',
    departure_day: 'Departure Day',
    post_stay: 'Post-Stay',
  }[phase] || phase || 'Session';
}

function phaseClass(phase) {
  return {
    pre_arrival: 'badge-amber',
    arrival_day: 'badge-amber',
    in_stay: 'badge-green',
    departure_day: 'badge-dim',
    post_stay: 'badge-dim',
  }[phase] || 'badge-dim';
}

function workflowActionLabel(actionType) {
  return {
    proactive_outreach: 'Proactive Outreach',
    knowledge_response: 'Knowledge Response',
    ops_review: 'Ops Review',
    vendor_coordination: 'Vendor Coordination',
    guest_eta_update: 'Guest ETA Update',
    turnover_coordination: 'Turnover Coordination',
    owner_internal_update: 'Owner/Internal Update',
    accounting_claim_handoff: 'Accounting/Claims Handoff',
  }[actionType] || actionType || 'Workflow Action';
}

function workflowStageLabel(stage) {
  return {
    arrival_prep: 'Arrival Prep',
    in_stay_active: 'In Stay',
    checkout_prep: 'Checkout Prep',
    turnover_in_progress: 'Turnover Active',
    post_stay_followup: 'Post Stay',
    issue_active: 'Issue Active',
    archived: 'Archived',
    completed: 'Completed',
  }[stage] || stage || 'Workflow';
}

function workOrderStatusLabel(status) {
  return {
    opened: 'Opened',
    contacting_vendor: 'Contacting Vendor',
    accepted: 'Accepted',
    scheduled: 'Scheduled',
    en_route: 'En Route',
    on_site: 'On Site',
    work_completed: 'Work Completed',
    awaiting_verification: 'Awaiting Verification',
    verified: 'Verified',
    closed: 'Closed',
    failed: 'Failed',
    reassigned: 'Reassigned',
    cancelled: 'Cancelled',
  }[status] || status || 'Work Order';
}

function workOrderTone(status) {
  const value = String(status || '').toLowerCase();
  if (['verified', 'closed'].includes(value)) return 'badge-green';
  if (['failed', 'reassigned', 'cancelled'].includes(value)) return 'badge-red';
  if (['scheduled', 'en_route', 'on_site', 'work_completed', 'awaiting_verification'].includes(value)) return 'badge-amber';
  return 'badge-dim';
}

function filterToPhase(filter) {
  if (filter === 'arriving') return 'pre_arrival';
  if (filter === 'in_stay') return 'in_stay';
  if (filter === 'post_stay') return 'post_stay';
  return null;
}

function buildSummary(items) {
  const list = Array.isArray(items) ? items : [];
  return list.reduce((acc, item) => {
    acc.total += 1;
    if (item.phase === 'in_stay') acc.inStay += 1;
    if (item.phase === 'pre_arrival' || item.phase === 'arrival_day') acc.arriving += 1;
    if (item.phase === 'post_stay') acc.postStay += 1;
    acc.openEscalations += Number(item.openEscalations || 0);
    return acc;
  }, {
    total: 0,
    inStay: 0,
    arriving: 0,
    postStay: 0,
    openEscalations: 0,
  });
}

function isIssueActive(item) {
  return Number(item?.openEscalations || 0) > 0
    || String(item?.workflow?.stage || '').toLowerCase() === 'issue_active';
}

function needsArrivalAttention(item) {
  return ['pre_arrival', 'arrival_day'].includes(String(item?.phase || '').toLowerCase())
    && (!item?.welcomeSent || !item?.checkinReminderSent);
}

function needsProactiveAttention(item) {
  const detectors = item?.workflow?.detectors || {};
  return !!detectors.proactive_outreach_recommended
    || (!!item?.hasBookingContext && !item?.proactiveTriggeredAt && String(item?.phase || '').toLowerCase() === 'in_stay');
}

function isBackoffActive(item) {
  const detectors = item?.workflow?.detectors || {};
  return !!detectors.proactive_backoff_active;
}

function hasDirectReachability(item) {
  return !!(item?.guestPhone || item?.guestEmail);
}

function isAutonomyException(item) {
  const detectors = item?.workflow?.detectors || {};
  return isIssueActive(item)
    || !!detectors.vendor_dispatch_needed
    || !!detectors.accounting_claim_handoff_needed
    || !!detectors.turnover_coordination_needed
    || !item?.hasBookingContext;
}

function workViewLabel(view) {
  return {
    live_sessions: 'Live sessions',
    arrival_team: 'Arrival team',
    issue_desk: 'Issue desk',
    proactive_desk: 'Proactive desk',
    autonomy_exceptions: 'Autonomy exceptions',
    post_stay: 'Post-stay',
  }[view] || 'Live sessions';
}

function visibleItems() {
  const items = state.items || [];
  if (state.workView === 'arrival_team') {
    return items.filter((item) => ['pre_arrival', 'arrival_day'].includes(String(item.phase || '').toLowerCase()));
  }
  if (state.workView === 'issue_desk') {
    return items.filter((item) => isIssueActive(item));
  }
  if (state.workView === 'proactive_desk') {
    return items.filter((item) => needsProactiveAttention(item) || isBackoffActive(item));
  }
  if (state.workView === 'autonomy_exceptions') {
    return items.filter((item) => isAutonomyException(item));
  }
  if (state.workView === 'post_stay') {
    return items.filter((item) => ['post_stay', 'departure_day'].includes(String(item.phase || '').toLowerCase()));
  }
  return items;
}

function effectiveMode() {
  if (state.mode !== 'auto') return state.mode;
  const operator = appState.get('operator') || {};
  const propertyCount = Number(operator.properties || 0);
  return propertyCount >= 250 ? 'manager' : 'simple';
}

function defaultWorkView() {
  return effectiveMode() === 'manager' ? 'autonomy_exceptions' : 'live_sessions';
}

function isSimpleSafeWorkView(view) {
  return ['live_sessions', 'arrival_team', 'issue_desk', 'proactive_desk', 'post_stay'].includes(view);
}

function modeCopy(mode) {
  return {
    simple: 'Simple keeps stay operations centered on the live queue, with only the highest-signal task markers visible.',
    manager: 'Manager opens the operating lanes a lead or director needs: arrivals, issues, post-stay, and exception control.',
    auto: 'Auto keeps the shell calm for smaller teams and expands the task desk as stay operations get busier.',
  }[mode] || '';
}

function renderCommandMetrics() {
  const items = state.items || [];
  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = String(value);
  };
  setText('sess-metric-arriving', items.filter((item) => item.phase === 'pre_arrival' || item.phase === 'arrival_day').length);
  setText('sess-metric-instay', items.filter((item) => item.phase === 'in_stay').length);
  setText('sess-metric-escalations', items.reduce((sum, item) => sum + Number(item.openEscalations || 0), 0));
  setText('sess-metric-poststay', items.filter((item) => item.phase === 'post_stay' || item.phase === 'departure_day').length);
}

function renderAutonomyPosture() {
  const host = document.getElementById('sess-autonomy-posture');
  if (!host) return;
  const items = state.items || [];
  const directReachable = items.filter((item) => hasDirectReachability(item)).length;
  const proactiveDue = items.filter((item) => needsProactiveAttention(item)).length;
  const backoffActive = items.filter((item) => isBackoffActive(item)).length;
  const exceptions = items.filter((item) => isAutonomyException(item)).length;
  const bookingReady = items.filter((item) => item.hasBookingContext).length;
  const mode = effectiveMode();
  const policy = state.proactivePolicy || {};
  const cadence = Number(policy.min_hours_between_proactive_touches || 18);
  const serviceCadence = Number(policy.min_hours_between_service_updates || 4);
  const maxTouches = Number(policy.max_notifications_per_stay_window || 6);
  host.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:12px">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap">
        <div>
          <div style="font-size:13px;color:var(--white);font-weight:600">${mode === 'manager' ? 'Autonomy-first stay operations' : 'Stay operations posture'}</div>
          <div style="font-size:12px;color:var(--dim);line-height:1.6;margin-top:4px">
            ${mode === 'manager'
              ? 'For larger portfolios, this desk should mostly surface proactive touches due, escalation-worthy issues, and operator-adjustment moments. Normal guest messaging should stay quiet.'
              : 'For smaller portfolios, this desk can still be hands-on, but the proactive layer should steadily reduce how often you need to intervene.'}
          </div>
        </div>
        <span class="badge ${exceptions ? 'badge-amber' : 'badge-green'}" style="font-size:10px">${escapeHtml(String(exceptions))} exceptions</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px">
        <div style="padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Booking ready</div>
          <div style="font-size:18px;color:var(--white);font-family:'Cormorant Garamond',serif">${escapeHtml(String(bookingReady))}</div>
        </div>
        <div style="padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Direct reach</div>
          <div style="font-size:18px;color:var(--green);font-family:'Cormorant Garamond',serif">${escapeHtml(String(directReachable))}</div>
        </div>
        <div style="padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Proactive due</div>
          <div style="font-size:18px;color:var(--amber);font-family:'Cormorant Garamond',serif">${escapeHtml(String(proactiveDue))}</div>
        </div>
        <div style="padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Backoff active</div>
          <div style="font-size:18px;color:var(--white);font-family:'Cormorant Garamond',serif">${escapeHtml(String(backoffActive))}</div>
        </div>
        <div style="padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Touch policy</div>
          <div style="font-size:11px;color:var(--white);line-height:1.5">${escapeHtml(`${cadence}h proactive · ${serviceCadence}h service · ${maxTouches}/stay`)}</div>
        </div>
      </div>
    </div>
  `;
}

function renderTaskStrip() {
  const el = document.getElementById('sess-task-strip');
  if (!el) return;
  const mode = effectiveMode();
  el.classList.toggle('ops-hidden-when-simple', mode === 'simple');
  const items = state.items || [];
  const cards = [
    {
      label: 'Arrival touches due',
      value: items.filter((item) => needsArrivalAttention(item)).length,
      tone: 'amber',
      note: 'Welcome and check-in coverage before guest friction starts.',
    },
    {
      label: 'Issue desk',
      value: items.filter((item) => isIssueActive(item)).length,
      tone: 'red',
      note: 'Escalations and active operational incidents.',
    },
    {
      label: 'Autonomy exceptions',
      value: items.filter((item) => isAutonomyException(item)).length,
      tone: 'amber',
      note: 'Sessions the system should not quietly absorb alone.',
    },
    {
      label: 'Proactive due',
      value: items.filter((item) => needsProactiveAttention(item)).length,
      tone: 'green',
      note: 'Guests who should receive a nudge or reassurance next.',
    },
    {
      label: 'Backoff active',
      value: items.filter((item) => isBackoffActive(item)).length,
      tone: 'dim',
      note: 'Guests the system should intentionally leave alone right now.',
    },
  ];
  el.innerHTML = cards.map((card) => `
    <div class="ops-task-card">
      <div class="ops-task-kicker">${escapeHtml(card.label)}</div>
      <div class="ops-task-value ${escapeHtml(card.tone)}">${escapeHtml(String(card.value))}</div>
      <div class="ops-task-note">${escapeHtml(card.note)}</div>
    </div>
  `).join('');
}

function renderWorkViewChips() {
  document.querySelectorAll('#sess-workviews [data-sess-view]').forEach((btn) => {
    btn.classList.toggle('ops-chip-active', btn.getAttribute('data-sess-view') === state.workView);
  });
  const select = document.getElementById('sess-view-select');
  if (select) select.value = state.workView;
}

function renderScopeOptions() {
  const sel = document.getElementById('sess-scope-filter');
  if (!sel) return;
  const current = state.scopeFilter || 'all';
  const options = [
    { value: 'all', label: 'All live work' },
    { value: 'mine', label: 'My handoffs' },
    ...(state.portfolios || []).map((portfolio) => ({
      value: `portfolio:${portfolio.portfolio_key}`,
      label: `Portfolio · ${portfolio.display_name || portfolio.portfolio_key}`,
    })),
  ];
  sel.innerHTML = options
    .map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`)
    .join('');
  sel.value = current;
}

function renderModeChips() {
  const mode = state.mode;
  const effective = effectiveMode();
  document.querySelectorAll('#sess-modes [data-sess-mode]').forEach((btn) => {
    btn.classList.toggle('ops-chip-active', btn.getAttribute('data-sess-mode') === mode);
  });
  const copy = document.getElementById('sess-mode-copy');
  if (copy) {
    copy.textContent = mode === 'auto'
      ? `${modeCopy('auto')} ${effective === 'manager' ? 'Current portfolio size is using the manager lens.' : 'Current portfolio size is using the simple lens.'}`
      : modeCopy(mode);
  }
  const workviews = document.getElementById('sess-workviews');
  const scopebar = document.getElementById('sess-scopebar');
  if (workviews) workviews.classList.toggle('ops-hidden-when-simple', effective === 'simple');
  if (scopebar) scopebar.style.marginBottom = effective === 'simple' ? '8px' : '14px';
}

function renderStatusLine(extra) {
  const el = document.getElementById('sess-status-line');
  if (!el) return;
  if (extra) {
    el.textContent = extra;
    el.style.color = 'var(--dim)';
    return;
  }
  const summary = state.summary || {};
  const parts = [
    `${summary.total || 0} sessions`,
    `${summary.inStay || 0} in-stay`,
    `${summary.arriving || 0} arriving`,
  ];
  if (summary.postStay) parts.push(`${summary.postStay} post-stay`);
  if (summary.archived) parts.push(`${summary.archived} archived`);
  if (summary.openEscalations) parts.push(`${summary.openEscalations} open escalations`);
  parts.push(`mode ${effectiveMode()}`);
  parts.push(`view ${workViewLabel(state.workView)}`);
  parts.push(`scope ${state.scopeFilter.replace(':', ' · ')}`);
  if (state.workView !== 'post_stay') parts.push('history in audit');
  if (summary.withBookingContext) parts.push(`${summary.withBookingContext} with booking context`);
  if (summary.proactiveEvaluated) parts.push(`${summary.proactiveEvaluated} proactive evaluated`);
  if (summary.notificationsSent) parts.push(`${summary.notificationsSent} guest notifications`);
  if (state.proactivePolicy?.min_hours_between_proactive_touches) parts.push(`${state.proactivePolicy.min_hours_between_proactive_touches}h proactive cadence`);
  if (state.lastLoadedAt) parts.push(`refreshed ${fmtTime(state.lastLoadedAt)}`);
  el.textContent = parts.join(' · ');
  el.style.color = 'var(--dim)';
}

function isSessionsView() {
  const root = document.getElementById('view-sessions');
  return !!root && root.style.display !== 'none';
}

async function fetchSessions() {
  const params = {};
  const phase = filterToPhase(state.filter);
  if (phase) params.phase = phase;
  if (state.scopeFilter === 'mine') params.assigned_to_me = true;
  else if (state.scopeFilter.startsWith('portfolio:')) params.portfolio_key = state.scopeFilter.slice('portfolio:'.length);
  params.limit = 100;
  return normalizeSessionsList(await api.sessions.list(params));
}

async function fetchSessionDetail(id) {
  return normalizeSessionDetail(await api.sessions.detail(id));
}

function renderList() {
  const pane = document.getElementById('sess-list');
  if (!pane) return;
  const items = visibleItems();
  if (!items.length) {
    pane.innerHTML = `
      <div class="empty" style="padding:48px 20px">
        <div class="empty-title">No guest sessions here yet</div>
        <div class="empty-sub">Booked and active guest conversations appear here after PMS/session creation. Pre-booking inbox traffic and escalation-only workflows can still be active elsewhere in the dashboard.</div>
      </div>`;
    return;
  }
  const renderRow = (item) => {
    const active = item.sessionId === state.activeId ? 'msg-row-active' : '';
    const laneLabel = isIssueActive(item)
      ? 'Issue desk'
      : (['pre_arrival', 'arrival_day'].includes(String(item.phase || '').toLowerCase()) ? 'Arrival team' : (['post_stay', 'departure_day'].includes(String(item.phase || '').toLowerCase()) ? 'Post-stay' : 'Guest ops'));
    const stayWindow = item.checkIn || item.checkOut
      ? `${item.checkIn || 'TBD'} → ${item.checkOut || 'TBD'}`
      : '';
    return `
      <div class="sess-row queue-row ${active}" data-session-id="${escapeHtml(item.sessionId)}">
        <div class="queue-row-meta">
          <span class="queue-row-title">${escapeHtml(item.guestName || 'Guest')}</span>
          <span class="badge ${phaseClass(item.phase)}" style="font-size:9px">${escapeHtml(phaseLabel(item.phase))}</span>
          ${item.openEscalations ? `<span class="badge badge-red" style="font-size:9px">${escapeHtml(String(item.openEscalations))} open escalation${item.openEscalations === 1 ? '' : 's'}</span>` : ''}
          ${item.assignmentStatus === 'assigned' ? `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(item.assignedOperatorLabel || 'Assigned handoff')}</span>` : ''}
          ${item.workflow?.stage ? `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(workflowStageLabel(item.workflow.stage))}</span>` : ''}
          ${item.workflow?.turnover?.readyForNextGuest ? `<span class="badge badge-green" style="font-size:9px">Ready for next guest</span>` : ''}
          ${item.hasBookingContext ? `<span class="badge badge-green" style="font-size:9px">Booking context</span>` : ''}
          ${item.proactiveTriggeredAt ? `<span class="badge badge-amber" style="font-size:9px">Proactive evaluated</span>` : ''}
          ${item.journeyTracked ? `<span class="badge badge-dim" style="font-size:9px">Journey tracked</span>` : ''}
          <span style="flex:1"></span>
          <span class="queue-row-mono">${escapeHtml(fmtTime(item.lastMessageAt))}</span>
        </div>
        <div class="queue-row-sub">${escapeHtml(item.propertyName || item.propertyCode || 'Unknown property')}${stayWindow ? ` · ${escapeHtml(stayWindow)}` : ''} · ${escapeHtml(laneLabel)}</div>
        <div class="queue-row-preview">
          ${escapeHtml(item.guestPhone || item.guestEmail || 'No guest contact on file')}
        </div>
        <div class="queue-row-foot">
          <div class="queue-row-tags">
          ${item.reservationId ? `<span class="badge badge-dim" style="font-size:9px">Res ${escapeHtml(item.reservationId)}</span>` : ''}
          ${item.welcomeSent ? `<span class="badge badge-green" style="font-size:9px">Welcome sent</span>` : ''}
          ${item.checkinReminderSent ? `<span class="badge badge-green" style="font-size:9px">Check-in sent</span>` : ''}
          ${item.checkoutReminderSent ? `<span class="badge badge-green" style="font-size:9px">Checkout sent</span>` : ''}
          ${item.extendOfferSent ? `<span class="badge badge-amber" style="font-size:9px">Extend sent</span>` : ''}
          ${item.poolHeatAccepted ? `<span class="badge badge-green" style="font-size:9px">Pool heat accepted</span>` : item.poolHeatOffered ? `<span class="badge badge-amber" style="font-size:9px">Pool heat offered</span>` : ''}
          ${item.notificationsSent ? `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(String(item.notificationsSent))} guest notifications</span>` : ''}
          ${needsProactiveAttention(item) ? `<span class="badge badge-amber" style="font-size:9px">Proactive due</span>` : ''}
          ${isBackoffActive(item) ? `<span class="badge badge-dim" style="font-size:9px">Backoff active</span>` : ''}
          ${hasDirectReachability(item) ? `<span class="badge badge-green" style="font-size:9px">Direct reach</span>` : ''}
          </div>
          ${item.token ? `<span class="queue-row-mono">${escapeHtml(item.token)}</span>` : ''}
        </div>
      </div>`;
  };
  let groups = [];
  const mode = effectiveMode();
  if (state.workView === 'arrival_team') {
    groups = [
      { title: 'Arrival touches due', items: items.filter((item) => needsArrivalAttention(item)) },
      { title: 'Arrival covered', items: items.filter((item) => !needsArrivalAttention(item)) },
    ].filter((group) => group.items.length);
  } else if (state.workView === 'issue_desk') {
    groups = [
      { title: 'Escalation open', items: items.filter((item) => Number(item.openEscalations || 0) > 0) },
      { title: 'Operational issue active', items: items.filter((item) => Number(item.openEscalations || 0) === 0 && isIssueActive(item)) },
    ].filter((group) => group.items.length);
  } else if (state.workView === 'proactive_desk') {
    groups = [
      { title: 'Proactive touch due', items: items.filter((item) => needsProactiveAttention(item) && !isBackoffActive(item)) },
      { title: 'Backoff active', items: items.filter((item) => isBackoffActive(item)) },
    ].filter((group) => group.items.length);
  } else if (state.workView === 'autonomy_exceptions') {
    groups = [
      {
        title: 'Owner attention',
        items: items.filter((item) => {
          const detectors = item?.workflow?.detectors || {};
          return !!detectors.accounting_claim_handoff_needed || !item?.hasBookingContext;
        }),
      },
      {
        title: 'Vendor / turnover exceptions',
        items: items.filter((item) => {
          const detectors = item?.workflow?.detectors || {};
          return !(!item?.hasBookingContext || detectors.accounting_claim_handoff_needed)
            && (detectors.vendor_dispatch_needed || detectors.turnover_coordination_needed || isIssueActive(item));
        }),
      },
    ].filter((group) => group.items.length);
  } else if (state.workView === 'post_stay') {
    groups = [{ title: 'Post-stay follow-up', items }].filter((group) => group.items.length);
  } else {
    groups = mode === 'simple'
      ? [
          {
            title: 'Live sessions',
            items: items.filter((item) => item.phase !== 'post_stay' && item.phase !== 'departure_day'),
          },
        ].filter((group) => group.items.length)
      : [
          {
            title: 'Arrivals / prep',
            items: items.filter((item) => item.phase === 'pre_arrival' || item.phase === 'arrival_day'),
          },
          {
            title: 'Issue active',
            items: items.filter((item) => isIssueActive(item) && item.phase !== 'post_stay'),
          },
          {
            title: 'In stay active',
            items: items.filter((item) => item.phase === 'in_stay' && !isIssueActive(item)),
          },
        ].filter((group) => group.items.length);
  }
  const postStayCount = (state.items || []).filter((item) => item.phase === 'post_stay' || item.phase === 'departure_day').length;
  pane.innerHTML = groups.map((group) => `
    <section class="queue-group">
      <div class="queue-group-label">
        <div class="queue-group-title">${escapeHtml(group.title)}</div>
        <div class="queue-group-count">${escapeHtml(String(group.items.length))}</div>
      </div>
      <div class="queue-group-body">
        ${group.items.map(renderRow).join('')}
      </div>
    </section>
  `).join('') + (
    state.workView !== 'post_stay' && postStayCount
      ? `
      <section class="queue-group">
        <div class="queue-group-label">
          <div class="queue-group-title">Retained stay history</div>
          <div class="queue-group-count">${escapeHtml(String(postStayCount))}</div>
        </div>
        <div class="queue-group-body">
          <div style="padding:14px 14px 16px;font-size:11px;color:rgba(240,235,227,0.62);line-height:1.55">
            Checked-out stays and closed guest history are kept for learning, reporting, and audits, but they stay out of the live operations desk by default.
            <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
              <button class="btn btn-sm" id="sess-open-poststay-view">View post-stay</button>
              <button class="btn btn-sm" id="sess-open-audit-view">Open audit</button>
            </div>
          </div>
        </div>
      </section>`
      : ''
  );

  pane.querySelectorAll('.sess-row').forEach(row => {
    row.addEventListener('click', () => {
      selectSession(row.getAttribute('data-session-id'));
    });
  });
  const postStayBtn = document.getElementById('sess-open-poststay-view');
  if (postStayBtn) {
    postStayBtn.addEventListener('click', () => {
      state.workView = 'post_stay';
      savePreference('workView', state.workView);
      renderModeChips();
      renderWorkViewChips();
      renderTaskStrip();
      renderStatusLine();
      renderList();
    });
  }
  const auditBtn = document.getElementById('sess-open-audit-view');
  if (auditBtn && typeof window.navigate === 'function') {
    auditBtn.addEventListener('click', () => window.navigate('audit'));
  }
}

function renderThread() {
  const pane = document.getElementById('sess-thread');
  if (!pane) return;
  const detail = state.detail;
  if (!detail || !detail.session) {
    pane.innerHTML = `
      <div class="empty" style="padding:48px 20px">
        <div class="empty-sub">Select a session to view the conversation.</div>
      </div>`;
    return;
  }
  const msgs = detail.messages || [];
  const intentBadges = Object.entries(detail.intentMix || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([intent, count]) => `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(intent.replace(/_/g, ' '))} · ${escapeHtml(String(count))}</span>`)
    .join('');
  pane.innerHTML = `
    <div style="display:flex;flex-direction:column;height:100%">
      <div style="padding:14px 16px;border-bottom:1px solid var(--border);display:flex;flex-direction:column;gap:4px">
        <div style="font-size:15px;color:var(--white);font-weight:600">${escapeHtml(detail.session.guestName || 'Guest')}</div>
        <div style="font-size:11px;color:rgba(240,235,227,0.65)">
          ${escapeHtml(detail.session.propertyName || detail.session.propertyCode || 'Unknown property')} · ${escapeHtml(phaseLabel(detail.session.phase))}
        </div>
        ${intentBadges ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px">${intentBadges}</div>` : ''}
      </div>
      <div style="padding:14px;display:flex;flex-direction:column;gap:10px;overflow:auto;flex:1">
        ${msgs.length ? msgs.map(msg => `
          <div style="display:flex;justify-content:${msg.direction === 'outbound' ? 'flex-end' : 'flex-start'}">
            <div style="max-width:78%;padding:10px 12px;border-radius:10px;border:1px solid var(--border);background:${msg.direction === 'outbound' ? 'rgba(200,120,50,0.14)' : 'rgba(255,255,255,0.03)'}">
              <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">
                ${msg.direction === 'outbound' ? 'Outgoing to guest' : 'Guest message'} · ${escapeHtml(fmtTime(msg.createdAt))}
              </div>
              <div style="font-size:12px;color:var(--white);line-height:1.6;white-space:pre-wrap">${escapeHtml(msg.content || '')}</div>
              <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px;font-size:10px;color:rgba(240,235,227,0.45)">
                ${msg.intent ? `<span>Intent: ${escapeHtml(msg.intent.replace(/_/g, ' '))}</span>` : ''}
                ${msg.contentType && msg.contentType !== 'text' ? `<span>Type: ${escapeHtml(msg.contentType)}</span>` : ''}
                ${msg.wasQuickAnswer ? `<span>AI quick answer</span>` : ''}
                ${msg.responseTimeMs != null ? `<span>${escapeHtml(String(msg.responseTimeMs))}ms</span>` : ''}
              </div>
            </div>
          </div>
        `).join('') : `<div class="empty" style="padding:32px 20px"><div class="empty-sub">No messages recorded in this session yet.</div></div>`}
      </div>
    </div>`;
}

function renderMeta() {
  const pane = document.getElementById('sess-meta');
  if (!pane) return;
  const detail = state.detail;
  if (!detail || !detail.session) {
    pane.innerHTML = `<div style="font-size:12px;color:var(--dim);font-weight:300">No session selected.</div>`;
    return;
  }
  const s = detail.session;
  const booking = detail.bookingContext || {};
  const journey = detail.journey || {};
  const workflow = detail.workflow || {};
  const workflowActions = Array.isArray(workflow.actions) ? workflow.actions : [];
  const workflowDetectors = workflow.detectors || {};
  const proactive = workflow.proactive || {};
  const workOrders = Array.isArray(detail.workOrders) ? detail.workOrders : [];
  const notifications = Array.isArray(detail.notifications) ? detail.notifications : [];
  const openEsc = detail.openEscalations || [];
  const pendingEsc = state.pendingEscalation && state.pendingEscalation.session_id === s.sessionId
    ? state.pendingEscalation
    : null;
  pane.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px">
      <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:12px">
        <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Autonomy posture</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px">
          <span class="badge ${hasDirectReachability(s) ? 'badge-green' : 'badge-red'}" style="font-size:9px">${hasDirectReachability(s) ? 'Direct guest channel ready' : 'No direct guest channel'}</span>
          <span class="badge ${booking.available ? 'badge-green' : 'badge-red'}" style="font-size:9px">${booking.available ? 'Booking context loaded' : 'Booking context missing'}</span>
          ${needsProactiveAttention(s) ? `<span class="badge badge-amber" style="font-size:9px">Proactive due</span>` : ''}
          ${isBackoffActive(s) ? `<span class="badge badge-dim" style="font-size:9px">Backoff active</span>` : ''}
          ${isAutonomyException(s) ? `<span class="badge badge-red" style="font-size:9px">Operator review lane</span>` : `<span class="badge badge-green" style="font-size:9px">Autonomy-safe lane</span>`}
        </div>
        <div style="display:flex;flex-direction:column;gap:6px;font-size:12px;color:rgba(240,235,227,0.78)">
          <div><span style="color:rgba(240,235,227,0.45)">Messaging posture:</span> ${escapeHtml(isAutonomyException(s) ? 'Exception / review oriented' : 'Normal stay automation can stay quiet')}</div>
          <div><span style="color:rgba(240,235,227,0.45)">Proactive family:</span> ${escapeHtml(String(proactive.allowed_touch_family || 'standard').replace(/_/g, ' '))}</div>
          <div><span style="color:rgba(240,235,227,0.45)">Suggested touch:</span> ${escapeHtml(String(workflowDetectors.proactive_touch_type || proactive.touch_type || 'none').replace(/_/g, ' '))}</div>
          <div><span style="color:rgba(240,235,227,0.45)">Receptiveness:</span> ${proactive.receptiveness_score != null ? escapeHtml(String(proactive.receptiveness_score)) : '—'}</div>
          ${proactive.message ? `<div style="margin-top:4px;color:rgba(240,235,227,0.62);line-height:1.55"><span style="color:rgba(240,235,227,0.45)">Suggested proactive note:</span> ${escapeHtml(proactive.message)}</div>` : ''}
        </div>
      </div>
      <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:12px">
        <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Stay workflow</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">
          ${workflow.stage ? `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(workflowStageLabel(workflow.stage))}</span>` : ''}
          ${workflow.phase ? `<span class="badge ${phaseClass(workflow.phase)}" style="font-size:9px">${escapeHtml(phaseLabel(workflow.phase))}</span>` : ''}
          ${workflow.escalation_state === 'open' ? `<span class="badge badge-red" style="font-size:9px">Escalation open</span>` : ''}
          ${workflowDetectors.workflow_domain ? `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(String(workflowDetectors.workflow_domain).replace(/_/g, ' '))}</span>` : ''}
          ${workflowDetectors.proactive_outreach_recommended ? `<span class="badge badge-green" style="font-size:9px">Proactive touch</span>` : ''}
          ${workflowDetectors.proactive_backoff_active ? `<span class="badge badge-dim" style="font-size:9px">Backoff active</span>` : ''}
          ${workflowDetectors.knowledge_response_candidate ? `<span class="badge badge-green" style="font-size:9px">Knowledge path</span>` : ''}
          ${workflowDetectors.vendor_dispatch_needed ? `<span class="badge badge-amber" style="font-size:9px">Vendor needed</span>` : ''}
          ${workflowDetectors.turnover_coordination_needed ? `<span class="badge badge-amber" style="font-size:9px">Turnover needed</span>` : ''}
          ${workflowDetectors.accounting_claim_handoff_needed ? `<span class="badge badge-red" style="font-size:9px">Claims/Billing</span>` : ''}
        </div>
        <div style="display:flex;flex-direction:column;gap:8px">
          ${(workflow.timeline || []).map(step => `
            <div style="display:flex;align-items:center;gap:8px;font-size:12px;color:${step.done ? 'rgba(240,235,227,0.82)' : 'rgba(240,235,227,0.52)'}">
              <span class="badge ${step.done ? 'badge-green' : 'badge-dim'}" style="font-size:9px">${step.done ? 'done' : 'open'}</span>
              <span>${escapeHtml(step.label || step.key || 'Step')}</span>
            </div>
          `).join('')}
          ${workflowActions.length ? `
            <div style="display:flex;flex-direction:column;gap:8px;margin-top:4px">
              ${workflowActions.map(action => `
                <div style="border-top:1px solid rgba(255,255,255,0.05);padding-top:8px">
                  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">
                    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                      <span style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(workflowActionLabel(action.action_type))}</span>
                      <span class="badge badge-dim" style="font-size:9px">${escapeHtml(String(action.status || 'ready').replace(/_/g, ' '))}</span>
                    </div>
                    ${['ready', 'failed', 'blocked'].includes(String(action.status || '').toLowerCase()) ? `<button class="btn btn-sm" data-sess-action="${escapeHtml(action.action_type)}">Run Action</button>` : ''}
                  </div>
                </div>
              `).join('')}
            </div>
          ` : '<div style="font-size:12px;color:var(--dim)">No stay workflow actions queued yet.</div>'}
        </div>
      </div>
      <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:12px">
        <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Work orders</div>
        ${workOrders.length ? `
          <div style="display:flex;flex-direction:column;gap:10px">
            ${workOrders.map(order => `
              <div style="padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.03);display:flex;flex-direction:column;gap:6px">
                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                  <span style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(order.summary || order.issueCategory || 'Work order')}</span>
                  <span class="badge ${workOrderTone(order.status)}" style="font-size:9px">${escapeHtml(workOrderStatusLabel(order.status))}</span>
                  ${order.dispatchState ? `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(String(order.dispatchState).replace(/_/g, ' '))}</span>` : ''}
                </div>
                <div style="font-size:11px;color:rgba(240,235,227,0.7);line-height:1.55">
                  ${escapeHtml(order.vendorName || 'Vendor pending')}
                  ${order.vendorPhone ? ` · ${escapeHtml(order.vendorPhone)}` : ''}
                  ${order.etaMinutes != null ? ` · ETA ${escapeHtml(String(order.etaMinutes))}m` : ''}
                </div>
                <div style="display:flex;gap:6px;flex-wrap:wrap;font-size:10px;color:rgba(240,235,227,0.5);font-family:'DM Mono',monospace">
                  <span>Verification ${escapeHtml((order.verificationState || 'pending').replace(/_/g, ' '))}</span>
                  <span>Invoice ${escapeHtml((order.invoiceState || 'not_received').replace(/_/g, ' '))}</span>
                  ${order.assetId ? `<span>Asset linked</span>` : ''}
                </div>
                ${order.etaVisibilityMode === 'live_tracking' && (order.trackingUrl || order.lastKnownDistanceText) ? `
                  <div style="font-size:11px;color:rgba(240,235,227,0.68);line-height:1.5">
                    ${order.lastKnownDistanceText ? `Tracking: ${escapeHtml(order.lastKnownDistanceText)}` : 'Live vendor tracking available'}
                    ${order.trackingUrl ? ` · <a href="${escapeHtml(order.trackingUrl)}" target="_blank" rel="noreferrer" style="color:var(--amber)">open tracking</a>` : ''}
                  </div>
                ` : ''}
                ${order.details ? `<div style="font-size:11px;color:rgba(240,235,227,0.58);line-height:1.5">${escapeHtml(order.details)}</div>` : ''}
              </div>
            `).join('')}
          </div>
        ` : '<div style="font-size:12px;color:var(--dim)">No work orders tied to this stay yet.</div>'}
      </div>
      ${booking.available && booking.property ? `
        <div class="card">
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--dim);margin-bottom:10px">Booking context</div>
          <div style="display:flex;flex-direction:column;gap:6px;font-size:12px;color:rgba(240,235,227,0.8)">
            <div><strong style="color:var(--white)">Match:</strong> ${escapeHtml((booking.matchStrategy || 'canonical').replace(/_/g, ' '))}</div>
            <div><strong style="color:var(--white)">PMS:</strong> ${escapeHtml(booking.provider || 'canonical cache')}</div>
            <div><strong style="color:var(--white)">Property:</strong> ${escapeHtml(booking.property.property_name || booking.property.property_code || 'Property')}</div>
            <div><strong style="color:var(--white)">Reservation:</strong> ${escapeHtml(booking.booking?.reservation_id || 'Unknown')}</div>
            <div><strong style="color:var(--white)">Channel:</strong> ${escapeHtml((booking.booking?.booking_channel || 'direct').replace(/_/g, ' '))}</div>
            <div><strong style="color:var(--white)">Stay:</strong> ${escapeHtml(booking.booking?.check_in || 'TBD')} → ${escapeHtml(booking.booking?.check_out || 'TBD')}</div>
            <div><strong style="color:var(--white)">Guests:</strong> ${escapeHtml(String(booking.booking?.guest_count || 0))}</div>
            ${booking.nextBooking ? `<div><strong style="color:var(--white)">Next booking:</strong> ${escapeHtml(booking.nextBooking.check_in || '')} → ${escapeHtml(booking.nextBooking.check_out || '')}</div>` : ''}
            ${booking.guestIdentityAvailable && (booking.booking?.guest_email || booking.booking?.guest_phone) ? `<div><strong style="color:var(--white)">PMS guest identity:</strong> ${escapeHtml(booking.booking?.guest_email || booking.booking?.guest_phone || '')}</div>` : ''}
          </div>
        </div>
      ` : ''}
      ${pendingEsc ? `
        <div class="card" style="background:rgba(200,120,50,0.05);border:1px solid rgba(200,120,50,0.22);padding:12px">
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Escalation handoff</div>
          <div style="font-size:13px;color:var(--white);font-weight:600;line-height:1.45">${escapeHtml(pendingEsc.summary || pendingEsc.reason || 'Escalation')}</div>
          ${pendingEsc.guest_update_status ? `<div style="font-size:11px;color:rgba(240,235,227,0.68);margin-top:6px">Guest update state: ${escapeHtml(String(pendingEsc.guest_update_status).replace(/_/g, ' '))}</div>` : ''}
          ${pendingEsc.guest_update_due_at ? `<div style="font-size:11px;color:rgba(240,235,227,0.58);margin-top:4px">Next guest update due ${escapeHtml(fmtAbsolute(pendingEsc.guest_update_due_at))}</div>` : ''}
          <div style="margin-top:10px;display:flex;flex-direction:column;gap:8px">
            <select class="form-select" id="sess-escalation-status">
              ${[
                ['draft_needed', 'Draft needed'],
                ['ready_to_send', 'Draft ready to send'],
                ['sent_to_guest', 'Sent to guest'],
                ['awaiting_guest_reply', 'Awaiting guest reply'],
                ['vendor_eta_shared', 'Vendor ETA shared'],
                ['resolved_with_guest', 'Resolved with guest'],
              ].map(([value, label]) => `
                <option value="${value}" ${pendingEsc.guest_update_status === value ? 'selected' : ''}>${label}</option>
              `).join('')}
            </select>
            <textarea class="form-textarea" id="sess-escalation-note" rows="4" placeholder="What did we tell the guest, and what do they need next?">${escapeHtml(pendingEsc.guest_update_note || '')}</textarea>
            <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">
              <div id="sess-escalation-save-status" style="font-size:11px;color:rgba(240,235,227,0.5)">Use this session timeline to verify what the guest last received before recording the next update.</div>
              <button class="btn btn-sm btn-primary" id="sess-escalation-save-btn">Record guest update</button>
            </div>
          </div>
        </div>` : ''}
      <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:12px">
        <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Session summary</div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px">
          <span class="badge ${phaseClass(s.phase)}" style="font-size:9px">${escapeHtml(phaseLabel(s.phase))}</span>
          ${openEsc.length ? `<span class="badge badge-red" style="font-size:9px">${escapeHtml(String(openEsc.length))} linked escalation${openEsc.length === 1 ? '' : 's'}</span>` : '<span class="badge badge-dim" style="font-size:9px">No linked escalations</span>'}
        </div>
        <div style="display:flex;flex-direction:column;gap:6px;font-size:12px;color:rgba(240,235,227,0.78)">
          <div><span style="color:rgba(240,235,227,0.45)">Guest:</span> ${escapeHtml(s.guestName || 'Guest')}</div>
          <div><span style="color:rgba(240,235,227,0.45)">Property:</span> ${escapeHtml(s.propertyName || s.propertyCode || 'Unknown property')}</div>
          ${s.reservationId ? `<div><span style="color:rgba(240,235,227,0.45)">Reservation:</span> ${escapeHtml(s.reservationId)}</div>` : ''}
          <div><span style="color:rgba(240,235,227,0.45)">Stay:</span> ${escapeHtml(s.checkIn || '—')} → ${escapeHtml(s.checkOut || '—')}</div>
          <div><span style="color:rgba(240,235,227,0.45)">Contact:</span> ${escapeHtml(s.guestPhone || s.guestEmail || 'No guest contact')}</div>
          <div><span style="color:rgba(240,235,227,0.45)">Messages:</span> ${escapeHtml(String(s.conversationCount || 0))}</div>
          ${detail.messages?.length ? `<div><span style="color:rgba(240,235,227,0.45)">Latest touch:</span> ${escapeHtml(fmtAbsolute(detail.messages[detail.messages.length - 1].createdAt))}</div>` : ''}
          ${s.pmsSyncedAt ? `<div><span style="color:rgba(240,235,227,0.45)">PMS synced:</span> ${escapeHtml(fmtAbsolute(s.pmsSyncedAt))}</div>` : ''}
          ${s.proactiveTriggeredAt ? `<div><span style="color:rgba(240,235,227,0.45)">Proactive evaluated:</span> ${escapeHtml(fmtAbsolute(s.proactiveTriggeredAt))}</div>` : ''}
        </div>
      </div>
      <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:12px">
        <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Journey state</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px">
          <span class="badge ${journey.welcomeSent ? 'badge-green' : 'badge-dim'}" style="font-size:9px">Welcome ${journey.welcomeSent ? 'sent' : 'pending'}</span>
          <span class="badge ${journey.checkinReminderSent ? 'badge-green' : 'badge-dim'}" style="font-size:9px">Check-in reminder ${journey.checkinReminderSent ? 'sent' : 'pending'}</span>
          <span class="badge ${journey.checkoutReminderSent ? 'badge-green' : 'badge-dim'}" style="font-size:9px">Checkout reminder ${journey.checkoutReminderSent ? 'sent' : 'pending'}</span>
          <span class="badge ${journey.extendOfferSent ? 'badge-amber' : 'badge-dim'}" style="font-size:9px">Extend offer ${journey.extendOfferSent ? 'sent' : 'not sent'}</span>
        </div>
        <div style="display:flex;flex-direction:column;gap:6px;font-size:12px;color:rgba(240,235,227,0.78)">
          ${journey.welcomeSentAt ? `<div><span style="color:rgba(240,235,227,0.45)">Welcome at:</span> ${escapeHtml(fmtAbsolute(journey.welcomeSentAt))}</div>` : ''}
          ${journey.checkinReminderSentAt ? `<div><span style="color:rgba(240,235,227,0.45)">Check-in reminder:</span> ${escapeHtml(fmtAbsolute(journey.checkinReminderSentAt))}</div>` : ''}
          ${journey.checkoutReminderSentAt ? `<div><span style="color:rgba(240,235,227,0.45)">Checkout reminder:</span> ${escapeHtml(fmtAbsolute(journey.checkoutReminderSentAt))}</div>` : ''}
          ${journey.extendOfferSentAt ? `<div><span style="color:rgba(240,235,227,0.45)">Extend offer:</span> ${escapeHtml(fmtAbsolute(journey.extendOfferSentAt))}</div>` : ''}
          ${journey.extendOfferResponse ? `<div><span style="color:rgba(240,235,227,0.45)">Extend response:</span> ${escapeHtml(journey.extendOfferResponse.replace(/_/g, ' '))}</div>` : ''}
          ${journey.poolHeatOffered || journey.poolHeatAccepted ? `<div><span style="color:rgba(240,235,227,0.45)">Pool heat:</span> ${escapeHtml(journey.poolHeatAccepted ? 'accepted' : 'offered')}</div>` : ''}
        </div>
        ${journey.activities?.length ? `
          <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:6px">
            ${journey.activities.map(activity => `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(activity.activityType.replace(/_/g, ' '))}: ${escapeHtml(activity.status.replace(/_/g, ' '))}</span>`).join('')}
          </div>
        ` : '<div style="font-size:12px;color:var(--dim)">No activity journey state recorded yet.</div>'}
      </div>
      <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:12px">
        <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Guest notifications</div>
        ${notifications.length ? notifications.slice(0, 6).map(note => `
          <div style="padding:8px 0;border-top:1px solid rgba(255,255,255,0.05);font-size:12px;color:rgba(240,235,227,0.78)">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <span class="badge ${note.status === 'delivered' || note.status === 'sent' ? 'badge-green' : 'badge-dim'}" style="font-size:9px">${escapeHtml(note.status.toUpperCase())}</span>
              <span class="badge badge-dim" style="font-size:9px">${escapeHtml(note.notificationType.replace(/_/g, ' '))}</span>
              <span class="badge badge-dim" style="font-size:9px">${escapeHtml(note.channel.toUpperCase())}</span>
            </div>
            <div style="margin-top:4px">${escapeHtml(note.recipient || 'Recipient unavailable')}</div>
            ${note.sentAt ? `<div style="font-size:11px;color:rgba(240,235,227,0.5);margin-top:4px">Sent ${escapeHtml(fmtAbsolute(note.sentAt))}</div>` : ''}
            ${note.errorMessage ? `<div style="font-size:11px;color:var(--red);margin-top:4px">${escapeHtml(note.errorMessage)}</div>` : ''}
          </div>
        `).join('') : '<div style="font-size:12px;color:var(--dim)">No guest notifications logged yet.</div>'}
      </div>
      <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:12px">
        <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Operator guest update</div>
        <div style="font-size:11px;color:rgba(240,235,227,0.58);line-height:1.6;margin-bottom:8px">
          Sends directly to the guest’s phone through the normal guest messaging channel and logs the outbound message in this session timeline.
        </div>
        <textarea class="form-textarea" id="sess-send-text" rows="5" placeholder="Type the next guest update here...">${escapeHtml(
          pendingEsc && pendingEsc.guest_update_note
            ? pendingEsc.guest_update_note
            : ''
        )}</textarea>
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-top:10px">
          <div id="sess-send-status" style="font-size:11px;color:rgba(240,235,227,0.5)">
            ${s.guestPhone ? `Will send to ${escapeHtml(s.guestPhone)}` : 'No guest phone on this session yet'}
          </div>
          <button class="btn btn-primary btn-sm" id="sess-send-btn" ${s.guestPhone ? '' : 'disabled'}>Send guest update</button>
        </div>
      </div>
      <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:12px">
        <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Open escalations</div>
        ${openEsc.length ? openEsc.map(esc => `
          <div style="padding:10px 0;border-top:1px solid rgba(255,255,255,0.05)">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <span class="badge ${esc.status === 'resolved' ? 'badge-green' : 'badge-red'}" style="font-size:9px">${escapeHtml(String(esc.status || 'pending').toUpperCase())}</span>
              <span class="badge badge-dim" style="font-size:9px">${escapeHtml(String(esc.priority || 'medium').toUpperCase())}</span>
              <span style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(esc.summary || esc.reason || 'Escalation')}</span>
            </div>
            <div style="font-size:11px;color:rgba(240,235,227,0.58);margin-top:4px">${escapeHtml(fmtAbsolute(esc.createdAt))}</div>
          </div>
        `).join('') : '<div style="font-size:12px;color:var(--dim)">No open escalations tied to this session.</div>'}
      </div>
    </div>`;

  const saveBtn = document.getElementById('sess-escalation-save-btn');
  if (saveBtn && pendingEsc) {
    saveBtn.addEventListener('click', handleRecordEscalationGuestUpdate);
  }
  pane.querySelectorAll('[data-sess-action]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const actionType = btn.getAttribute('data-sess-action');
      if (!actionType || !detail?.session?.sessionId) return;
      try {
        btn.disabled = true;
        await api.sessions.executeAction(detail.session.sessionId, actionType);
        await selectSession(detail.session.sessionId);
      } catch (e) {
        console.warn('[Sessions] workflow action failed', e);
      } finally {
        btn.disabled = false;
      }
    });
  });
  const sendBtn = document.getElementById('sess-send-btn');
  if (sendBtn) {
    sendBtn.addEventListener('click', handleSendGuestUpdate);
  }
}

async function handleRecordEscalationGuestUpdate() {
  const pendingEsc = state.pendingEscalation;
  if (!pendingEsc || !pendingEsc.ticket_id) return;
  const statusEl = document.getElementById('sess-escalation-save-status');
  const note = ((document.getElementById('sess-escalation-note') || {}).value || '').trim();
  const guestUpdateStatus = ((document.getElementById('sess-escalation-status') || {}).value || 'sent_to_guest').trim();
  try {
    if (statusEl) {
      statusEl.textContent = 'Recording guest update…';
      statusEl.style.color = 'var(--amber)';
    }
    await api.escalations.coordination(pendingEsc.ticket_id, {
      watchers: Array.isArray(pendingEsc.watchers) ? pendingEsc.watchers : [],
      guest_update_note: note,
      guest_update_status: guestUpdateStatus,
      guest_update_due_at: pendingEsc.guest_update_due_at || null,
      mark_guest_updated: true,
      notify_watchers: false,
    });
    state.pendingEscalation = {
      ...pendingEsc,
      guest_update_note: note,
      guest_update_status: guestUpdateStatus,
    };
    renderMeta();
    const refreshed = document.getElementById('sess-escalation-save-status');
    if (refreshed) {
      refreshed.textContent = 'Guest update recorded on the escalation.';
      refreshed.style.color = 'var(--green)';
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = e.message || 'Could not record guest update.';
      statusEl.style.color = 'var(--red)';
    }
  }
}

async function handleSendGuestUpdate() {
  const detail = state.detail;
  if (!detail || !detail.session) return;
  const statusEl = document.getElementById('sess-send-status');
  const textEl = document.getElementById('sess-send-text');
  const sendBtn = document.getElementById('sess-send-btn');
  const messageText = ((textEl || {}).value || '').trim();
  if (!messageText) {
    if (statusEl) {
      statusEl.textContent = 'Add a guest-facing message first.';
      statusEl.style.color = 'var(--red)';
    }
    return;
  }
  try {
    if (sendBtn) sendBtn.disabled = true;
    if (statusEl) {
      statusEl.textContent = 'Sending guest update…';
      statusEl.style.color = 'var(--amber)';
    }
    await api.sessions.sendUpdate(detail.session.sessionId, {
      message_text: messageText,
      escalation_ticket_id: state.pendingEscalation ? state.pendingEscalation.ticket_id : null,
    });
    if (state.pendingEscalation) {
      state.pendingEscalation = {
        ...state.pendingEscalation,
        guest_update_note: messageText,
        guest_update_status: 'sent_to_guest',
      };
    }
    await selectSession(detail.session.sessionId);
    const refreshed = document.getElementById('sess-send-status');
    if (refreshed) {
      refreshed.textContent = 'Guest update sent and logged.';
      refreshed.style.color = 'var(--green)';
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = e.message || 'Could not send guest update.';
      statusEl.style.color = 'var(--red)';
    }
  } finally {
    const btn = document.getElementById('sess-send-btn');
    if (btn && detail.session.guestPhone) btn.disabled = false;
  }
}

async function selectSession(id) {
  if (!id) return;
  state.activeId = id;
  renderList();
  const pane = document.getElementById('sess-thread');
  if (pane) {
    pane.innerHTML = `<div class="empty" style="padding:48px 20px"><div class="empty-sub">Loading conversation…</div></div>`;
  }
  try {
    state.detail = await fetchSessionDetail(id);
    renderThread();
    renderMeta();
  } catch (e) {
    console.warn('[Sessions] detail load failed', e);
    if (pane) {
      pane.innerHTML = `<div class="empty" style="padding:48px 20px"><div class="empty-title">Couldn't load session</div><div class="empty-sub">${escapeHtml(String(e.message || e))}</div></div>`;
    }
  }
}

async function loadSessions(opts = {}) {
  if (state.loading && !opts.force) return;
  state.loading = true;
  const previousItems = Array.isArray(state.items) ? [...state.items] : [];
  const previousDetail = state.detail ? { ...state.detail } : null;
  try {
    const data = await fetchSessions();
    state.items = data.sessions || [];
    state.summary = buildSummary(state.items);
    state.lastLoadedAt = new Date().toISOString();
    renderStatusLine();
    renderCommandMetrics();
    renderAutonomyPosture();
    renderTaskStrip();
    renderWorkViewChips();
    renderList();
    const nextId = state.pendingSessionId || state.activeId || (state.items[0] && state.items[0].sessionId);
    if (nextId) {
      state.pendingSessionId = null;
      await selectSession(nextId);
    } else {
      state.detail = null;
      renderThread();
      renderMeta();
    }
  } catch (e) {
    console.warn('[Sessions] list load failed', e);
    state.items = previousItems;
    state.detail = previousDetail;
    renderStatusLine(`Could not refresh sessions · ${String(e.message || e)}`);
    const pane = document.getElementById('sess-list');
    if (pane) {
      if (previousItems.length) {
        renderAutonomyPosture();
        renderTaskStrip();
        renderList();
      } else {
        pane.innerHTML = `
          <div class="empty" style="padding:48px 20px">
            <div class="empty-title">Couldn't load sessions</div>
            <div class="empty-sub">${escapeHtml(String(e.message || e))}</div>
            <button class="btn btn-sm" id="sess-retry-btn" style="margin-top:12px">Retry</button>
          </div>`;
        const retryBtn = document.getElementById('sess-retry-btn');
        if (retryBtn) retryBtn.addEventListener('click', () => loadSessions({ force: true }));
      }
    }
    if (previousDetail) {
      renderThread();
      renderMeta();
    }
  } finally {
    state.loading = false;
  }
}

async function loadPortfolios() {
  try {
    const payload = await api.portfolios.list();
    if (Array.isArray(payload)) {
      state.portfolios = payload;
    } else if (Array.isArray(payload?.portfolios)) {
      state.portfolios = payload.portfolios;
    } else if (Array.isArray(payload?.items)) {
      state.portfolios = payload.items;
    } else {
      state.portfolios = [];
    }
  } catch (_) {
    state.portfolios = [];
  }
  renderScopeOptions();
}

async function loadSettingsContext() {
  try {
    const settings = await api.settings.get();
    state.proactivePolicy = settings?.proactive_policy || null;
  } catch (_) {
    state.proactivePolicy = null;
  }
  renderAutonomyPosture();
}

function wireTabs() {
  document.querySelectorAll('#sess-tabs .tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#sess-tabs .tab').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      state.filter = btn.getAttribute('data-sess-filter') || 'all';
      loadSessions({ force: true });
    });
  });
}

function wireWorkViews() {
  document.querySelectorAll('#sess-workviews [data-sess-view]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.workView = btn.getAttribute('data-sess-view') || 'live_sessions';
      savePreference('workView', state.workView);
      renderWorkViewChips();
      renderTaskStrip();
      renderStatusLine();
      renderList();
    });
  });
  const select = document.getElementById('sess-view-select');
  if (select) {
    select.addEventListener('change', () => {
      state.workView = select.value || 'live_sessions';
      savePreference('workView', state.workView);
      renderModeChips();
      renderWorkViewChips();
      renderTaskStrip();
      renderStatusLine();
      renderList();
    });
  }
  const scopeSel = document.getElementById('sess-scope-filter');
  if (scopeSel) {
    scopeSel.addEventListener('change', () => {
      state.scopeFilter = scopeSel.value || 'all';
      savePreference('scopeFilter', state.scopeFilter);
      loadSessions({ force: true });
    });
  }
}

function wireModes() {
  document.querySelectorAll('#sess-modes [data-sess-mode]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.mode = btn.getAttribute('data-sess-mode') || 'auto';
      savePreference('mode', state.mode);
      if (effectiveMode() === 'simple' && !isSimpleSafeWorkView(state.workView)) {
        state.workView = 'live_sessions';
      }
      renderModeChips();
      renderAutonomyPosture();
      renderWorkViewChips();
      renderTaskStrip();
      renderStatusLine();
      renderList();
    });
  });
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(() => {
    if (document.hidden) return;
    loadSessions();
  }, 30000);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function wireViewChange() {
  window.addEventListener('oyvoda:view-changed', (e) => {
    const view = e && e.detail && e.detail.view;
    if (view === 'instay' || view === 'sessions') {
      loadSessions({ force: true });
      startPolling();
    } else {
      stopPolling();
    }
  });
}

function openSession(sessionId, escalationContext) {
  state.pendingSessionId = sessionId || null;
  state.pendingEscalation = escalationContext || null;
  if (typeof window.navigate === 'function') {
    window.navigate('instay');
  }
  if (document.getElementById('view-sessions')?.style.display !== 'none') {
    loadSessions({ force: true });
  }
}

function inlineStyles() {
  if (document.getElementById('sess-inline-css')) return;
  const s = document.createElement('style');
  s.id = 'sess-inline-css';
  s.textContent = `
    #sess-list .sess-row:hover {
      background: rgba(255,255,255,0.04);
    }
    #sess-list .sess-row.msg-row-active {
      background: rgba(200,120,50,0.08);
      border-left: 3px solid var(--amber);
      padding-left: 13px !important;
    }
    #sess-workviews button,
    #sess-modes button {
      font: inherit;
    }
  `;
  document.head.appendChild(s);
}

export function init() {
  state.mode = loadPreference('mode', 'auto');
  state.workView = loadPreference('workView', defaultWorkView());
  state.scopeFilter = loadPreference('scopeFilter', 'all');
  inlineStyles();
  wireTabs();
  wireWorkViews();
  wireModes();
  wireViewChange();
  window.oyvodaOpenSession = openSession;
  renderScopeOptions();
  loadPortfolios();
  loadSettingsContext();
  appState.subscribe('operator', () => {
    state.mode = loadPreference('mode', state.mode);
    state.workView = loadPreference('workView', defaultWorkView());
    state.scopeFilter = loadPreference('scopeFilter', state.scopeFilter);
    if (effectiveMode() === 'simple' && !isSimpleSafeWorkView(state.workView)) state.workView = 'live_sessions';
    renderScopeOptions();
    loadSettingsContext();
    renderModeChips();
    renderAutonomyPosture();
    renderWorkViewChips();
    renderTaskStrip();
    renderStatusLine();
    renderList();
  });
  if (isSessionsView()) {
    loadSessions({ force: true });
  }
  renderStatusLine('Guest session queue wakes up when this view is active.');
  renderAutonomyPosture();
  renderTaskStrip();
  renderWorkViewChips();
  renderModeChips();
}
