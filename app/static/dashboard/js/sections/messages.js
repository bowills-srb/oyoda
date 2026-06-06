/**
 * messages.js — Pre-Booking review section
 *
 * Renders the Pre-Booking view as a focused operator review queue for
 * inbound booking inquiries only.
 *
 * Plus a property filter dropdown that narrows to a single property (populated
 * from whichever properties had any activity in the last 60 days).
 *
 * Data source: GET /app/api/messages?stage=pre_booking&status=&property=
 * Actions:
 *   POST /app/api/inquiries/{id}/approve
 *   POST /app/api/inquiries/{id}/edit       body: {reply_text}
 *   POST /app/api/inquiries/{id}/reject
 *   POST /app/api/inquiries/{id}/regenerate
 *
 * The router dispatches `oyvoda:view-changed` whenever the operator
 * navigates; this module auto-refreshes when that view is "prebooking"
 * (kept for compatibility — the view id is historical, the label is
 * "Pre-Booking"). We also auto-poll every 30s while the tab is focused.
 */

import api from '../api.js?v=2026-05-19-g';
import { normalizeMessageFeed } from '../adapters.js?v=2026-05-20-h';
import { state as appState } from '../state.js?v=2026-04-21-b';

const PREF_NS = 'oyvoda.dashboard.prebooking';

const state = {
  stage:      'pre_booking', // fixed to pre-booking for this view
  status:     'all',         // current status tab
  property:   '',            // current property filter
  scopeFilter:'all',
  workView:   'action_queue',
  metricFilter: 'all',
  unboundOnly: false,
  mode:       'auto',
  queueDepth: 25,
  confidenceWindow: '7d',
  items:      [],            // last-loaded items
  properties: [],            // dropdown options
  assignmentCandidates: [],
  summary:    {
    total: 0,
    pending: 0,
    sent: 0,
    rejected: 0,
    draftReady: 0,
    manualReview: 0,
    unbound: 0,
  },
  counters: {
    awaitingYou: 0,
    waitingOnKnowledge: 0,
  },
  tabCounts: {
    action_queue: 0,
    sent: 0,
    held: 0,
    closed: 0,
  },
  shipIKbRetryEnabled: false,
  activeId:   null,          // id of the item in the detail pane
  activeKind: null,          // inquiry
  activeSnapshot: null,      // preserves the selected inquiry during transient feed churn
  editId: null,
  queueInfoId: null,
  draftEdits: {},
  pendingSelectId: null,
  loading:    false,
  lastLoadedAt: null,
  loadSeq: 0,
};

let pollTimer = null;
const HELD_DRAFT_PLACEHOLDERS = new Set([
  '(no ai draft generated yet)',
  'held for review before sending.',
]);

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

function inboxHealth() {
  return appState.get('inboxHealth') || null;
}

function dashboardSummary() {
  return appState.get('dashboardSummary') || null;
}

function fmtTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = (now - d) / 1000;
    if (diff < 60)     return `${Math.round(diff)}s ago`;
    if (diff < 3600)   return `${Math.round(diff/60)}m ago`;
    if (diff < 86400)  return `${Math.round(diff/3600)}h ago`;
    if (diff < 604800) return `${Math.round(diff/86400)}d ago`;
    return d.toLocaleDateString();
  } catch (_) { return ''; }
}

function stageLabel(stage) {
  return {
    pre_booking: 'Pre-Booking',
    booked:      'Booked',
    in_stay:     'In-Stay',
    post_stay:   'Post-Stay',
    escalations: 'Escalation',
  }[stage] || stage;
}

function stageClass(stage) {
  return {
    pre_booking: 'badge-amber',
    booked:      'badge-dim',
    in_stay:     'badge-green',
    post_stay:   'badge-dim',
    escalations: 'badge-red',
  }[stage] || 'badge-dim';
}

function assignmentLabel(item) {
  if (!item) return '';
  if (item.assignedOperatorId) return 'Assigned operator';
  if (item.assignedTeamKey) return `Team ${item.assignedTeamKey}`;
  if (item.portfolioKey) return `Portfolio ${item.portfolioKey}`;
  return item.assignmentStatus === 'assigned' ? 'Assigned' : 'Unassigned';
}

function channelLabel(channel) {
  const c = (channel || '').toLowerCase();
  if (c.includes('vrbo')) return 'Vrbo';
  if (c.includes('airbnb')) return 'Airbnb';
  if (c.includes('booking')) return 'Booking';
  if (c.includes('escapia')) return 'Escapia';
  if (c === 'sms' || c === 'rcs') return 'SMS';
  if (c === 'email') return 'Email';
  return humanizeToken(channel) || 'Message';
}

function statusLabel(status) {
  return {
    pending_review: 'Pending',
    replied: 'Sent',
    rejected: 'Rejected',
    closed: 'Closed',
  }[String(status || '').toLowerCase()] || humanizeToken(status) || 'Open';
}

function statusTone(status) {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'pending_review') return 'badge-amber';
  if (normalized === 'replied') return 'badge-green';
  if (normalized === 'rejected') return 'badge-red';
  return 'badge-dim';
}

function confidenceTier(item) {
  const label = String(item?.confidenceLabel || '').toLowerCase();
  if (label.includes('high')) return 'high';
  if (label.includes('medium')) return 'medium';
  if (label.includes('low')) return 'low';
  const value = Number(item?.confidence || 0);
  if (value >= 0.9) return 'high';
  if (value >= 0.7) return 'medium';
  return 'low';
}

function confidencePct(item) {
  return Math.max(0, Math.min(100, Math.round(Number(item?.confidence || 0) * 100)));
}

function propertyIdentity(item) {
  return String(item?.propertyId || '').trim() || String(item?.propertyName || '').trim();
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/"/g, '&quot;');
}

function escapeHtml(s) {
  return String(s || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function humanizeToken(value) {
  return String(value || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function operatorVisibleWarningText(value) {
  const text = humanizeToken(value || '').trim();
  if (!text) return '';
  if (/draft source/i.test(text)) return '';
  if (/parser/i.test(text)) return '';
  if (/route outcome/i.test(text)) return '';
  if (/messaging brain/i.test(text)) return '';
  if (/adversarial review/i.test(text)) return '';
  if (/revenue sensitive/i.test(text)) return '';
  if (/missing property knowledge/i.test(text)) return '';
  return text;
}

function draftPreviewText(item) {
  const draft = String(rowDraftText(item) || '').trim();
  if (draft) return draft;
  if (wasHeldForReview(item)) return 'Held for review before sending.';
  return '(no AI draft generated yet)';
}

function formatBindingCandidate(candidate) {
  if (!candidate) return '';
  if (typeof candidate === 'string') return candidate.trim();
  if (typeof candidate !== 'object') return String(candidate);
  const bits = [];
  if (candidate.match_type) bits.push(humanizeToken(candidate.match_type));
  if (candidate.property_name) bits.push(candidate.property_name);
  if (candidate.property_code) bits.push(candidate.property_code);
  if (candidate.external_id) bits.push(`external ${candidate.external_id}`);
  if (candidate.listing_id) bits.push(`listing ${candidate.listing_id}`);
  if (candidate.unit_id) bits.push(`unit ${candidate.unit_id}`);
  return bits.filter(Boolean).join(' · ');
}

function rowDraftText(item) {
  if (state.editId === item.id && Object.prototype.hasOwnProperty.call(state.draftEdits, item.id)) {
    return state.draftEdits[item.id];
  }
  return item.draftText || '';
}

function normalizedDraftText(item) {
  return String(item?.draftText || '').trim();
}

function hasMeaningfulDraft(item) {
  const draft = normalizedDraftText(item);
  if (!draft) return false;
  return !HELD_DRAFT_PLACEHOLDERS.has(draft.toLowerCase());
}

function categorizeNonActive(item) {
  const status = String(item?.status || '').toLowerCase();
  if (status === 'replied') return 'sent';
  if (status === 'pending_review') return 'action_queue';
  return hasMeaningfulDraft(item) ? 'held' : 'closed';
}

function buildSummary(items, feed = {}) {
  const list = Array.isArray(items) ? items : [];
  const summary = list.reduce((acc, item) => {
    if (routesToKnowledge(item)) return acc;
    acc.total += 1;
    if (item.status === 'pending_review') acc.pending += 1;
    if (item.status === 'replied') acc.sent += 1;
    if (item.status === 'rejected') acc.rejected += 1;
    if (!String(item.propertyId || '').trim()) acc.unbound += 1;
    if (item.kind === 'inquiry') {
      if (item.draftReady) acc.draftReady += 1;
      else acc.manualReview += 1;
    }
    return acc;
  }, {
    total: 0,
    pending: 0,
    sent: 0,
    rejected: 0,
    draftReady: 0,
    manualReview: 0,
    unbound: 0,
  });
  if (feed && Number.isFinite(Number(feed.unboundCount))) {
    summary.unbound = Number(feed.unboundCount);
  }
  return summary;
}

function buildCounters(items) {
  return (Array.isArray(items) ? items : []).reduce((acc, item) => {
    if (routesToKnowledge(item)) {
      acc.waitingOnKnowledge += 1;
      return acc;
    }
    if (String(item?.status || '').toLowerCase() === 'pending_review') {
      acc.awaitingYou += 1;
    }
    return acc;
  }, { awaitingYou: 0, waitingOnKnowledge: 0 });
}

function buildTabCounts(items) {
  return (Array.isArray(items) ? items : []).reduce((acc, item) => {
    if (routesToKnowledge(item)) return acc;
    const bucket = categorizeNonActive(item);
    if (bucket === 'action_queue') acc.action_queue += 1;
    if (bucket === 'sent') acc.sent += 1;
    if (bucket === 'held') acc.held += 1;
    if (bucket === 'closed') acc.closed += 1;
    return acc;
  }, { action_queue: 0, sent: 0, held: 0, closed: 0 });
}

function isRevenueSensitive(item) {
  const intent = String(item?.intent || '').toLowerCase();
  const asks = (item?.asks || []).map((ask) => String(ask).toLowerCase());
  const warnings = (item?.policyWarnings || []).map((warn) => String(warn).toLowerCase());
  const preview = String(item?.messagePreview || item?.messageText || '').toLowerCase();
  return (
    intent === 'pricing' ||
    asks.includes('pricing') ||
    asks.includes('group_or_event') ||
    asks.includes('accessibility') ||
    warnings.some((warn) => warn.includes('pricing') || warn.includes('missing_property_knowledge')) ||
    ['discount', 'bachelorette', 'anniversary', 'birthday', 'honeymoon', 'early check', 'pet'].some((token) => preview.includes(token))
  );
}

function isKnowledgeGap(item) {
  return String(item?.draftSource || '').toLowerCase() === 'kb_gap_required'
    || String(item?.confidenceSource || '').toLowerCase() === 'knowledge_gap_required'
    || (item?.policyWarnings || []).some((warn) => String(warn).startsWith('missing_property_knowledge:'));
}

function routesToKnowledge(item) {
  if (state.shipIKbRetryEnabled) return false;
  return isKnowledgeGap(item);
}

function gapTopics(item) {
  const direct = (item?.blockedByGapTopics || []).map((topic) => String(topic || '').trim()).filter(Boolean);
  if (direct.length) return direct;
  const warning = (item?.policyWarnings || []).find((warn) => String(warn).startsWith('missing_property_knowledge:'));
  if (!warning) return [];
  return String(warning).split(':').slice(1).join(':').split(',').map((topic) => topic.trim()).filter(Boolean);
}

function primaryGapTopic(item) {
  return gapTopics(item)[0] || '';
}

function isAutonomyException(item) {
  return item?.status === 'pending_review' && (
    isKnowledgeGap(item)
    || !item?.draftReady
    || String(item?.confidenceSource || '').toLowerCase() === 'fallback_placeholder'
    || String(item?.fallbackReason || '').trim().length > 0
    || String(item?.routeOutcome || '').toLowerCase().includes('review')
    || (item?.propertyBindingCandidates || []).length > 1
  );
}

function wasHeldForReview(item) {
  const status = String(item?.status || '').toLowerCase();
  if (!['pending_review', 'replied', 'rejected', 'closed', 'approved', 'edited'].includes(status)) return false;
  return isKnowledgeGap(item)
    || String(item?.confidenceSource || '').toLowerCase() === 'fallback_placeholder'
    || String(item?.fallbackReason || '').trim().length > 0
    || String(item?.routeOutcome || '').toLowerCase().includes('review');
}

function workViewLabel(view) {
  return {
    action_queue: 'Action queue',
    ownership_lanes: 'Ownership lanes',
    autonomy_exceptions: 'Autonomy exceptions',
    sent: 'Sent',
    held: 'Held',
    closed: 'Closed',
  }[view] || 'Action queue';
}

function describeAssignmentLane(item) {
  if (item?.assignedOperatorId) return 'Owner / operator';
  if (item?.assignedTeamKey) return `Team · ${humanizeToken(item.assignedTeamKey)}`;
  if (item?.portfolioKey) return `Portfolio · ${humanizeToken(item.portfolioKey)}`;
  return 'Unassigned';
}

function activeItems() {
  return (state.items || []).filter((item) => item.status === 'pending_review');
}

function filteredItems() {
  const items = state.items || [];
  const scopeFiltered = items.filter((item) => {
    if (routesToKnowledge(item)) return false;
    if (state.scopeFilter === 'unassigned') return item.assignmentStatus !== 'assigned';
    return true;
  });
  let workviewFiltered = scopeFiltered;
  if (state.workView === 'action_queue') {
    workviewFiltered = scopeFiltered.filter((item) => item.status === 'pending_review');
  } else if (['sent', 'held', 'closed'].includes(state.workView)) {
    workviewFiltered = scopeFiltered.filter((item) => categorizeNonActive(item) === state.workView);
  } else if (state.workView === 'autonomy_exceptions') {
    workviewFiltered = scopeFiltered.filter((item) => isAutonomyException(item));
  }
  if (state.metricFilter === 'needs_action') {
    return workviewFiltered.filter((item) => item.status === 'pending_review');
  }
  if (state.metricFilter === 'revenue') {
    return workviewFiltered.filter((item) => item.status === 'pending_review' && isRevenueSensitive(item));
  }
  if (state.metricFilter === 'knowledge_gaps') {
    return [];
  }
  if (state.metricFilter === 'draft_ready') {
    return workviewFiltered.filter((item) => item.status === 'pending_review' && item.draftReady);
  }
  if (state.metricFilter === 'unbound' || state.unboundOnly) {
    return workviewFiltered.filter((item) => item.status === 'pending_review' && !String(item.propertyId || '').trim());
  }
  return workviewFiltered;
}

function visibleItems() {
  const items = filteredItems();
  if (state.queueDepth === 'all') return items;
  const depth = Number(state.queueDepth || 25);
  if (!Number.isFinite(depth) || depth <= 0) return items;
  return items.slice(0, depth);
}

function canInlineSend(item) {
  if (!item || item.kind !== 'inquiry') return false;
  if (String(item.status).toLowerCase() !== 'pending_review') return false;
  if (!String(item.propertyId || '').trim()) return false;
  if (wasHeldForReview(item)) return false;
  return confidenceTier(item) !== 'low';
}

function queueDepthLabel() {
  return state.queueDepth === 'all' ? 'all' : String(state.queueDepth || 25);
}

function confidenceWindowDays() {
  if (state.confidenceWindow === '24h') return 1;
  if (state.confidenceWindow === '30d') return 30;
  return 7;
}

function itemTimestamp(item) {
  return item?.repliedAt || item?.occurredAt || null;
}

function itemsForConfidenceWindow() {
  const days = confidenceWindowDays();
  const cutoff = Date.now() - (days * 24 * 60 * 60 * 1000);
  return (state.items || []).filter((item) => {
    const stamp = itemTimestamp(item);
    if (!stamp) return false;
    const parsed = new Date(stamp).getTime();
    return Number.isFinite(parsed) && parsed >= cutoff;
  });
}

function effectiveMode() {
  if (state.mode !== 'auto') return state.mode;
  const operator = appState.get('operator') || {};
  const propertyCount = Number(operator.properties || 0);
  return propertyCount >= 250 ? 'manager' : 'simple';
}

function modeCopy(mode) {
  return {
    simple: 'Simple keeps the queue calm: one primary lane, minimal decision clutter, still enough signal to move quickly.',
    manager: 'Manager opens ownership lanes, exception handling, and broader queue oversight for large portfolios and lead operators.',
    auto: 'Auto keeps the workflow lightweight for smaller operators and opens more controls as portfolio volume grows.',
  }[mode] || '';
}

function renderCommandMetrics() {
  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = String(value);
  };
  const counters = state.counters || {};
  setText('msg-metric-awaiting', counters.awaitingYou || 0);
  setText('msg-metric-knowledge', counters.waitingOnKnowledge || 0);
}

function renderMomentumLine() {
  const summary = dashboardSummary();
  const segments = [
    {
      id: 'pb-momentum-awaiting',
      value: state.counters?.awaitingYou,
      title: 'Action queue count computed from the rendered queue.',
    },
    {
      id: 'pb-momentum-replied',
      value: summary?.preBooking?.replied30d,
      title: 'Pulled from dashboard summary: replied in last 30 days.',
    },
    {
      id: 'pb-momentum-total',
      value: summary?.preBooking?.total30d,
      title: 'Pulled from dashboard summary: total in last 30 days.',
    },
  ];
  segments.forEach(({ id, value, title }) => {
    const segment = document.getElementById(id);
    const strong = segment?.querySelector('strong');
    if (!strong) return;
    if (value == null || value === '') {
      strong.textContent = '—';
      strong.title = 'Unavailable on this load.';
      return;
    }
    strong.textContent = String(value);
    strong.title = title;
  });
}

function renderResolutionHeader() {
  const summary = dashboardSummary();
  const inbox = summary?.inbox || inboxHealth() || {};
  const resolved = document.getElementById('pb-rh-resolved');
  const pending = document.getElementById('pb-rh-pending');
  const escalations = document.getElementById('pb-rh-escalations');
  const inboxEl = document.getElementById('pb-rh-inbox');
  if (resolved) resolved.textContent = String(state.summary?.sent || 0);
  if (pending) pending.textContent = String(state.summary?.pending || 0);
  if (escalations) escalations.textContent = String(summary?.escalations?.open ?? '—');
  if (inboxEl) {
    let text = 'inbox status unknown';
    if (inbox.lastPollError) {
      text = String(inbox.lastPollError).includes('gmail_reauth_required')
        ? 'inbox auth expired'
        : 'inbox polling warning';
      inboxEl.classList.add('pb-rh-inbox-error');
    } else {
      inboxEl.classList.remove('pb-rh-inbox-error');
      if (inbox.lastPollSummary) {
        text = inbox.lastPollSummary;
      } else if (inbox.lastPolledAt) {
        text = `last polled ${fmtTime(inbox.lastPolledAt)}`;
      }
    }
    inboxEl.textContent = text;
  }
}

function renderTaskStrip() {
  renderResolutionHeader();
  renderConfidenceBand();
  renderAnalyticsBand();
  renderMomentumLine();
}

function renderFilterIndicator() {
  const el = document.getElementById('msg-filter-indicator');
  if (!el) return;
  el.hidden = !state.unboundOnly;
}

function averageConfidence(items) {
  const values = items
    .map((item) => Number(item?.confidence))
    .filter((value) => Number.isFinite(value) && value > 0);
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function statTone(value) {
  if (!Number.isFinite(value)) return 'medium';
  if (value >= 0.9) return 'high';
  if (value >= 0.7) return 'medium';
  return 'low';
}

function renderConfidenceBand() {
  const body = document.getElementById('pb-band-confidence-body');
  const sel = document.getElementById('pb-confidence-window');
  if (!body) return;
  if (sel && sel.value !== state.confidenceWindow) sel.value = state.confidenceWindow;
  const windowItems = itemsForConfidenceWindow();
  if (windowItems.length < 10) {
    body.innerHTML = `<div class="pb-band-empty">Not enough activity to compute reliable signals — try a longer window.</div>`;
    return;
  }
  const sentItems = windowItems.filter((item) => String(item.status).toLowerCase() === 'replied');
  const heldItems = windowItems.filter((item) => String(item.status).toLowerCase() === 'pending_review' && wasHeldForReview(item));
  const sentAvg = averageConfidence(sentItems);
  const heldAvg = averageConfidence(heldItems);
  const resolvedHeld = windowItems.filter((item) => ['replied', 'rejected'].includes(String(item.status).toLowerCase()) && wasHeldForReview(item));
  const correctHold = resolvedHeld.length
    ? `${Math.round((resolvedHeld.filter((item) => String(item.status).toLowerCase() === 'replied').length / resolvedHeld.length) * 100)}%`
    : '—';
  const correctTitle = resolvedHeld.length ? 'Share of held drafts that were later approved and sent.' : 'Will populate once enough held drafts resolve in the selected window.';
  body.innerHTML = `
    <div class="pb-conf-compact-line">
      <span class="pb-conf-stat pb-conf-stat-${escapeAttr(statTone(sentAvg ?? 0))}">
        <span class="pb-conf-stat-value">${sentAvg == null ? '—' : `${Math.round(sentAvg * 100)}%`}</span>
        <span class="pb-conf-stat-label">avg confidence on sent · ${sentItems.length} drafts</span>
      </span>
      <span class="pb-conf-divider"></span>
      <span class="pb-conf-stat pb-conf-stat-${escapeAttr(statTone(heldAvg ?? 0))}">
        <span class="pb-conf-stat-value">${heldAvg == null ? '—' : `${Math.round(heldAvg * 100)}%`}</span>
        <span class="pb-conf-stat-label">held for review · ${heldItems.length} drafts · <span title="${escapeAttr(correctTitle)}">${escapeHtml(correctHold)}</span> correct holds</span>
      </span>
    </div>
  `;
}

function extractKnowledgeTopic(item) {
  const warning = (item?.policyWarnings || []).find((warn) => String(warn).startsWith('missing_property_knowledge:'));
  if (!warning) return 'recurring questions';
  return humanizeToken(String(warning).replace('missing_property_knowledge:', '')) || 'recurring questions';
}

function computeKnowledgeGapGroups(items = []) {
  const pendingGaps = items.filter((item) => String(item.status).toLowerCase() === 'pending_review' && isKnowledgeGap(item));
  const byProperty = new Map();
  pendingGaps.forEach((item) => {
    const key = propertyIdentity(item) || 'unknown';
    const existing = byProperty.get(key) || {
      propertyId: item.propertyId || '',
      propertyName: item.propertyName || 'Unknown property',
      count: 0,
      topics: new Map(),
    };
    existing.count += 1;
    const topic = extractKnowledgeTopic(item);
    existing.topics.set(topic, (existing.topics.get(topic) || 0) + 1);
    byProperty.set(key, existing);
  });
  const groups = Array.from(byProperty.values())
    .map((group) => {
      const [topGapTopic] = Array.from(group.topics.entries()).sort((a, b) => b[1] - a[1])[0] || ['recurring questions'];
      return {
        propertyId: group.propertyId,
        propertyName: group.propertyName,
        count: group.count,
        topGapTopic,
      };
    })
    .sort((a, b) => b.count - a.count)
    .slice(0, 5);
  return { total: pendingGaps.length, byProperty: groups };
}

function computeAnalyticsAggregates(items = []) {
  const windowItems = itemsForConfidenceWindow();
  const topicCounts = new Map();
  const propertyCounts = new Map();
  const gapGroups = computeKnowledgeGapGroups(windowItems);
  windowItems.forEach((item) => {
    const intent = humanizeToken(item.intent || 'general') || 'General';
    topicCounts.set(intent, (topicCounts.get(intent) || 0) + 1);
    (item.asks || []).forEach((ask) => {
      const label = humanizeToken(ask);
      if (label) topicCounts.set(label, (topicCounts.get(label) || 0) + 1);
    });
    const propertyName = item.propertyName || 'Unknown property';
    propertyCounts.set(propertyName, (propertyCounts.get(propertyName) || 0) + 1);
  });
  return {
    topTopics: Array.from(topicCounts.entries()).sort((a, b) => b[1] - a[1]).slice(0, 5),
    topProperties: Array.from(propertyCounts.entries()).sort((a, b) => b[1] - a[1]).slice(0, 5),
    gapGroups,
  };
}

function renderAnalyticsBand() {
  const el = document.getElementById('pb-band-analytics-body');
  const windowEl = document.getElementById('pb-analytics-window');
  if (!el) return;
  if (windowEl) windowEl.textContent = String(confidenceWindowDays());
  const data = computeAnalyticsAggregates(state.items || []);
  el.innerHTML = `
    <div class="pb-analytics-grid">
      <div class="pb-analytics-card">
        <div class="pb-analytics-title">Top recurring topics</div>
        <div class="pb-analytics-list">${data.topTopics.length ? data.topTopics.map(([label, count]) => `<span>${escapeHtml(label)} <strong>${escapeHtml(String(count))}</strong></span>`).join('') : '<span>No clear topic pattern yet.</span>'}</div>
      </div>
      <div class="pb-analytics-card">
        <div class="pb-analytics-title">Top inquiry-generating properties</div>
        <div class="pb-analytics-list">${data.topProperties.length ? data.topProperties.map(([label, count]) => `<span>${escapeHtml(label)} <strong>${escapeHtml(String(count))}</strong></span>`).join('') : '<span>No property trend yet.</span>'}</div>
      </div>
      <div class="pb-analytics-card">
        <div class="pb-analytics-title">Knowledge gap recurrence</div>
        <div class="pb-analytics-copy">${data.gapGroups.total ? `${data.gapGroups.total} active knowledge-gap inquiries across ${data.gapGroups.byProperty.length} properties in this window.` : 'No recurring knowledge-gap cluster in the selected window.'}</div>
        <div class="pb-analytics-note">Conversion correlation will appear once inquiry-to-booking attribution is live.</div>
      </div>
    </div>
  `;
}

function renderWorkViewChips() {
  document.querySelectorAll('#msg-status-tabs [data-msg-viewfilter]').forEach((btn) => {
    const view = btn.getAttribute('data-msg-viewfilter') || 'pending';
    const active =
      (view === 'pending' && state.workView === 'action_queue') ||
      (view === 'sent' && state.workView === 'sent') ||
      (view === 'held' && state.workView === 'held') ||
      (view === 'closed' && state.workView === 'closed');
    btn.classList.toggle('active', active);
    const label = view === 'pending' ? 'Action queue' : workViewLabel(view);
    const count = view === 'pending'
      ? (state.tabCounts?.action_queue || 0)
      : (state.tabCounts?.[view] || 0);
    btn.textContent = `${label} · ${count}`;
  });
}

function renderModeChips() {
  return;
}

function renderStatusLine(extra) {
  const el = document.getElementById('msg-status-line');
  if (!el) return;
  if (extra) {
    el.textContent = extra;
    el.style.color = 'rgba(240,235,227,0.52)';
    return;
  }
  const counters = state.counters || {};
  const currentCount = state.workView === 'action_queue'
    ? (state.tabCounts?.action_queue || 0)
    : (state.tabCounts?.[state.workView] || 0);
  const parts = [
    `${counters.awaitingYou || 0} awaiting you`,
    `${counters.waitingOnKnowledge || 0} waiting on knowledge`,
    `${currentCount} in ${workViewLabel(state.workView).toLowerCase()}`,
  ];
  const inbox = inboxHealth();
  if (inbox?.lastPollError) {
    if (String(inbox.lastPollError).includes('gmail_reauth_required')) {
      parts.push('inbox auth expired — reconnect Gmail');
    } else {
      parts.push('inbox polling warning');
    }
  }
  if (inbox?.lastPolledAt) {
    const pollBits = [`poll ${fmtTime(inbox.lastPolledAt)}`];
    if (inbox.lastMessagesFound != null) pollBits.push(`found ${inbox.lastMessagesFound}`);
    if (inbox.lastNewPendingInquiries != null) pollBits.push(`new ${inbox.lastNewPendingInquiries}`);
    parts.push(pollBits.join(' · '));
  }
  if (state.lastLoadedAt) parts.push(`refreshed ${fmtTime(state.lastLoadedAt)}`);
  el.textContent = parts.join(' · ');
  el.style.color = 'rgba(240,235,227,0.42)';
}

// ── API ──────────────────────────────────────────────────────────────────

async function fetchMessages() {
  const params = {
    stage: state.stage,
    status: state.status,
    property: state.property,
    limit: 200,
  };
  if (state.unboundOnly) params.unbound_only = true;
  if (state.scopeFilter === 'mine') params.assigned_to_me = true;
  else if (state.scopeFilter.startsWith('team:')) params.team_key = state.scopeFilter.slice('team:'.length);
  else if (state.scopeFilter.startsWith('portfolio:')) params.portfolio_key = state.scopeFilter.slice('portfolio:'.length);
  return normalizeMessageFeed(await api.messages.list(params));
}

async function fetchAssignmentCandidates() {
  const payload = await api.inquiries.assignmentCandidates();
  return Array.isArray(payload?.items) ? payload.items : [];
}

async function approveInquiry(id) {
  try {
    const data = await api.inquiries.approve(id);
    return { ok: true, data };
  } catch (error) {
    return { ok: false, data: error.data || { error: error.message } };
  }
}

async function editInquiry(id, reply_text) {
  try {
    const data = await api.inquiries.edit(id, { reply_text });
    return { ok: true, data };
  } catch (error) {
    return { ok: false, data: error.data || { error: error.message } };
  }
}

// ── Render ──────────────────────────────────────────────────────────────

function renderPropertyDropdown() {
  const sel = document.getElementById('msg-property-filter');
  if (!sel) return;
  const current = state.property || '';
  sel.innerHTML = '';
  const all = document.createElement('option');
  all.value = ''; all.textContent = 'All properties';
  sel.appendChild(all);
  (state.properties || []).forEach(p => {
    if (!p.id) return;
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = `${p.name || p.id} (${p.count})`;
    sel.appendChild(opt);
  });
  sel.value = current;
}

function renderScopeDropdown() {
  const sel = document.getElementById('msg-scope-filter');
  if (!sel) return;
  const current = state.scopeFilter || 'all';
  const teamKeys = Array.from(new Set((state.assignmentCandidates || []).map((item) => item.team_key).filter(Boolean)));
  const portfolioKeys = Array.from(new Set((state.items || []).map((item) => item.portfolioKey).filter(Boolean)));
  const options = [
    { value: 'all', label: 'All live work' },
    { value: 'mine', label: 'My assignments' },
    { value: 'unassigned', label: 'Unassigned only' },
    ...teamKeys.map((key) => ({ value: `team:${key}`, label: `Team · ${key}` })),
    ...portfolioKeys.map((key) => ({ value: `portfolio:${key}`, label: `Portfolio · ${key}` })),
  ];
  sel.innerHTML = options.map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`).join('');
  sel.value = options.some((option) => option.value === current) ? current : 'all';
}

function renderStatusTabVisibility() {
  const bar = document.getElementById('msg-status-tabs');
  if (!bar) return;
  bar.style.display = '';
}

function renderList() {
  const pane = document.getElementById('msg-list-pane');
  if (!pane) return;
  const allFiltered = filteredItems();
  const items = visibleItems();
  if (items.length === 0) {
    const queueName = workViewLabel(state.workView).toLowerCase();
    const summaryState = dashboardSummary();
    const backendPending = summaryState?.preBooking?.pending ?? null;
    const inbox = inboxHealth();
    const pollSummary = inbox?.lastPollSummary ? escapeHtml(inbox.lastPollSummary) : '';
    const pollError = inbox?.lastPollError ? escapeHtml(inbox.lastPollError) : '';
    const pollHint = inbox?.lastPolledAt
      ? `Inbox last polled ${escapeHtml(fmtTime(inbox.lastPolledAt))}.`
      : '';
    const reauthHint = inbox?.lastPollError && String(inbox.lastPollError).includes('gmail_reauth_required')
      ? ' Gmail authorization has expired, so no new mail can be fetched until the inbox is reconnected in Settings.'
      : '';
    const noNewHint = inbox && inbox.lastMessagesFound && inbox.lastNewPendingInquiries === 0
      ? ' The poller processed inbox traffic, but none of those messages became new pre-booking queue items. They may have been duplicates, filtered operational emails, or routed outside pre-booking.'
      : '';
    const waitingOnKnowledge = state.counters?.waitingOnKnowledge || 0;
    const backendHint = backendPending && backendPending > 0
      ? waitingOnKnowledge > 0 && state.workView === 'action_queue'
        ? ` The backend currently reports ${escapeHtml(String(backendPending))} pending review item${backendPending === 1 ? '' : 's'}, and ${escapeHtml(String(waitingOnKnowledge))} of them are currently routed to Knowledge instead of this queue.`
        : ` The backend currently reports ${escapeHtml(String(backendPending))} pending review item${backendPending === 1 ? '' : 's'}, so if the list is still blank this is likely a rendering/filter/cache problem rather than no queue data.`
      : '';
    // Brightened empty-state text so it's legible against the dark card.
    pane.innerHTML = `
      <div class="empty-state" style="padding:48px 20px">
        <div class="empty-state-title">No items in the ${queueName}</div>
        <div class="empty-state-description">When inbound booking inquiries arrive, they'll show up here.${pollHint}${reauthHint}${noNewHint}${backendHint}</div>
        ${pollSummary ? `<div style="margin-top:12px;font-size:11px;color:rgba(92,103,117,0.9);font-family:'JetBrains Mono',monospace">${pollSummary}</div>` : ''}
        ${pollError ? `<div style="margin-top:8px;font-size:11px;color:var(--status-urgent-text);font-family:'JetBrains Mono',monospace">${pollError}</div>` : ''}
      </div>`;
    return;
  }
  const queueHeading = workViewLabel(state.workView);
  const formatAge = (item) => fmtTime(item.occurredAt) || 'now';
  const draftText = (item) => draftPreviewText(item);
  const guestText = (item) => item.latestGuestTurn || item.messageText || item.messagePreview || '(no guest message captured)';
  const propertyText = (item) => String(item.propertyId || '').trim() ? (item.propertyName || 'Unknown property') : 'Unbound';
  const confidenceText = (item) => `${confidencePct(item)}%`;
  const propertyIdentityText = (item) => {
    const bits = [];
    if (item.propertyName) bits.push(item.propertyName);
    if (item.propertyId) bits.push(item.propertyId);
    if (item.propertyAddress) bits.push(item.propertyAddress);
    return bits.filter(Boolean).join(' · ');
  };
  const renderPolicyWarnings = (item) => {
    const warnings = (item.policyWarnings || [])
      .map((flag) => operatorVisibleWarningText(flag))
      .filter(Boolean);
    if (!warnings.length) return '';
    return `
      <div class="pb-row-popout-section">
        <div class="pb-row-popout-label">Policy warnings</div>
        <div class="pb-row-popout-list">
          ${warnings.map((flag) => `<span>${escapeHtml(flag)}</span>`).join('')}
        </div>
      </div>
    `;
  };
  const renderRow = (it) => {
    const active = it.id === state.activeId;
    const openInfo = state.queueInfoId === it.id;
    const editing = state.editId === it.id;
    const actionable = String(it.status).toLowerCase() === 'pending_review' && it.kind === 'inquiry';
    const gapRow = state.shipIKbRetryEnabled && isKnowledgeGap(it);
    const allowSend = canInlineSend(it);
    const metaBits = [it.guestName || 'Guest', propertyText(it), formatAge(it)].filter(Boolean);
    const popoutMetaBits = [channelLabel(it.channel)];
    if (it.platformListingId) popoutMetaBits.push(`listing ${it.platformListingId}`);
    if (it.checkIn || it.checkOut) popoutMetaBits.push(`${it.checkIn || 'TBD'} → ${it.checkOut || 'TBD'}`);
    if (it.guestCount != null) popoutMetaBits.push(`${it.guestCount} guest${Number(it.guestCount) === 1 ? '' : 's'}`);
    const candidateList = (it.propertyBindingCandidates || [])
      .map(formatBindingCandidate)
      .filter(Boolean);
    const priorThread = String(it.priorThreadContext || '').trim();
    return `
      <div class="msg-row pb-queue-row ${active ? 'msg-row-active' : ''}"
           data-id="${escapeHtml(it.id)}" data-kind="${escapeHtml(it.kind)}">
        <div class="pb-queue-row-meta-strip">
          <div class="pb-queue-row-meta-line">${escapeHtml(metaBits.join(' · '))}</div>
          <div class="pb-queue-row-meta-actions">
            <button class="pb-icon-btn" type="button" data-row-info="${escapeAttr(it.id)}" aria-label="Show inquiry details" title="Show inquiry details">?</button>
          </div>
        </div>
        <div class="pb-queue-row-message">${escapeHtml(guestText(it))}</div>
        <div class="pb-queue-row-draftline">
          <div class="pb-queue-row-draftlabel">${gapRow ? `Needs KB${primaryGapTopic(it) ? ` · missing: ${escapeHtml(primaryGapTopic(it).replace(/_/g, ' '))}` : ''}` : (hasMeaningfulDraft(it) ? `Draft · ${escapeHtml(confidenceText(it))}` : 'Draft')}</div>
          <div class="pb-queue-row-draftcontent">
            ${gapRow ? `
              <div class="pb-queue-row-drafttext">${escapeHtml(primaryGapTopic(it) ? primaryGapTopic(it).replace(/_/g, ' ') : 'Missing property knowledge')}</div>
            ` : editing ? `
              <textarea class="pb-inline-editor" data-row-editor="${escapeAttr(it.id)}">${escapeHtml(rowDraftText(it))}</textarea>
            ` : `
              <div class="pb-queue-row-drafttext">${escapeHtml(draftText(it))}</div>
            `}
          </div>
          <div class="pb-queue-row-draftactions">
            ${gapRow ? `
              <button class="btn btn-sm" type="button" data-row-fill-kb="${escapeAttr(it.id)}">Fill KB</button>
            ` : editing ? `
              <button class="btn btn-primary btn-sm" type="button" data-row-save="${escapeAttr(it.id)}">Save</button>
              <button class="btn btn-sm" type="button" data-row-cancel="${escapeAttr(it.id)}">Cancel</button>
            ` : actionable ? `
              <button class="btn btn-primary btn-sm" type="button" data-row-send="${escapeAttr(it.id)}"${allowSend ? '' : ' disabled'}>Send</button>
              <button class="btn btn-sm" type="button" data-row-edit="${escapeAttr(it.id)}">Edit</button>
            ` : ''}
          </div>
        </div>
        ${openInfo ? `
          <div class="pb-row-popout" data-row-popout="${escapeAttr(it.id)}">
            <div class="pb-row-popout-head">
              <span class="pb-row-popout-title">Guest inquiry</span>
              <button class="pb-icon-btn" type="button" data-row-info-close="${escapeAttr(it.id)}" aria-label="Close details">×</button>
            </div>
            <div class="pb-row-popout-meta">${escapeHtml(popoutMetaBits.filter(Boolean).join(' · '))}</div>
            <div class="pb-row-popout-section">
              <div class="pb-row-popout-label">Full guest message</div>
              <div class="pb-row-popout-body">${escapeHtml(guestText(it))}</div>
            </div>
            ${gapTopics(it).length ? `
              <div class="pb-row-popout-section">
                <div class="pb-row-popout-label">Missing topics</div>
                <div class="pb-row-popout-list">
                  ${gapTopics(it).map((topic) => `<span>${escapeHtml(topic.replace(/_/g, ' '))}</span>`).join('')}
                </div>
              </div>
            ` : ''}
            ${propertyIdentityText(it) ? `
              <div class="pb-row-popout-section">
                <div class="pb-row-popout-label">Property</div>
                <div class="pb-row-popout-body">${escapeHtml(propertyIdentityText(it))}</div>
              </div>
            ` : ''}
            ${candidateList.length ? `
              <div class="pb-row-popout-section">
                <div class="pb-row-popout-label">Binding candidates</div>
                <div class="pb-row-popout-list">
                  ${candidateList.map((candidate) => `<span>${escapeHtml(candidate)}</span>`).join('')}
                </div>
              </div>
            ` : ''}
            <div class="pb-row-popout-section">
              <div class="pb-row-popout-label">Confidence</div>
              <div class="pb-row-popout-body">${escapeHtml(confidenceText(it))} · ${escapeHtml(humanizeToken(confidenceTier(it)))} confidence</div>
            </div>
            ${renderPolicyWarnings(it)}
            ${priorThread ? `
              <details class="pb-row-popout-thread">
                <summary>Prior thread context</summary>
                <div class="pb-row-popout-thread-body">${escapeHtml(priorThread)}</div>
              </details>
            ` : ''}
            <div class="pb-row-popout-actions">
              ${gapRow ? `<button class="btn" type="button" data-row-fill-kb="${escapeAttr(it.id)}">Fill KB</button>` : ''}
              ${actionable && !gapRow ? `<button class="btn btn-primary" type="button" data-row-send="${escapeAttr(it.id)}"${allowSend ? '' : ' disabled'}>Send</button>` : ''}
              ${actionable && !gapRow ? `<button class="btn" type="button" data-row-edit="${escapeAttr(it.id)}">Edit</button>` : ''}
            </div>
          </div>
        ` : ''}
      </div>`;
  };
  pane.innerHTML = `
    <section class="pb-queue-group">
      <div class="pb-queue-group-head">
        <div>
          <div class="pb-queue-group-eyebrow">${escapeHtml(queueHeading)}</div>
          <div class="pb-queue-group-title">${state.workView === 'action_queue' ? 'Pending operator review' : `${escapeHtml(queueHeading)} inquiries`}</div>
        </div>
        <div class="pb-queue-group-side">
          <label class="pb-queue-depth-control">
            <span>Show</span>
            <select id="pb-queue-depth">
              <option value="5">5</option>
              <option value="10">10</option>
              <option value="25">25</option>
              <option value="all">All</option>
            </select>
          </label>
          <div class="pb-queue-group-count">${state.queueDepth === 'all' ? escapeHtml(String(allFiltered.length)) : `${escapeHtml(String(items.length))}<span class="pb-queue-group-count-sub">of ${escapeHtml(String(allFiltered.length))}</span>`}</div>
        </div>
      </div>
      <div class="pb-queue-group-body">
        ${items.map(renderRow).join('')}
      </div>
    </section>`;
  const depthSel = document.getElementById('pb-queue-depth');
  if (depthSel) {
    depthSel.value = queueDepthLabel();
    depthSel.addEventListener('change', () => {
      state.queueDepth = depthSel.value === 'all' ? 'all' : Number(depthSel.value || 25);
      savePreference('queueDepth', state.queueDepth);
      renderList();
    });
  }
  pane.querySelectorAll('.msg-row').forEach(row => {
    row.addEventListener('click', () => {
      const id = row.getAttribute('data-id');
      const kind = row.getAttribute('data-kind');
      selectItem(id, kind);
    });
  });
  positionOpenPopout();
}

function positionOpenPopout() {
  const popout = document.querySelector('[data-row-popout]');
  if (!popout) return;
  popout.classList.remove('is-left');
  popout.style.maxHeight = '';
  const rect = popout.getBoundingClientRect();
  if (rect.right > window.innerWidth - 16) {
    popout.classList.add('is-left');
  }
  const adjusted = popout.getBoundingClientRect();
  const availableHeight = Math.max(220, window.innerHeight - adjusted.top - 24);
  popout.style.maxHeight = `${availableHeight}px`;
}

function wireWorkViews() {
  document.querySelectorAll('#msg-workviews [data-msg-view]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.workView = btn.getAttribute('data-msg-view') || 'action_queue';
      savePreference('workView', state.workView);
      if (['sent', 'held', 'closed'].includes(state.workView)) state.metricFilter = 'all';
      renderWorkViewChips();
      renderCommandMetrics();
      renderStatusLine();
      renderTaskStrip();
      renderList();
    });
  });
}

function wireModes() {
  document.querySelectorAll('#msg-modes [data-msg-mode]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.mode = btn.getAttribute('data-msg-mode') || 'auto';
      savePreference('mode', state.mode);
      if (effectiveMode() === 'simple' && state.workView !== 'action_queue') {
        state.workView = 'action_queue';
      }
      renderModeChips();
      renderWorkViewChips();
      renderCommandMetrics();
      renderStatusLine();
      renderTaskStrip();
      renderList();
    });
  });
}

function wireMetricCards() {
  document.querySelectorAll('[data-msg-counter]').forEach((card) => {
    card.addEventListener('click', () => {
      const next = card.getAttribute('data-msg-counter') || 'awaiting';
      if (next === 'knowledge') {
        if (typeof window.navigate === 'function') window.navigate('knowledge');
        if (typeof window.setKbTab === 'function') window.setKbTab('gaps');
        return;
      }
      state.workView = 'action_queue';
      savePreference('workView', state.workView);
      renderWorkViewChips();
      renderCommandMetrics();
      renderStatusLine();
      renderTaskStrip();
      renderFilterIndicator();
      renderList();
    });
  });
  const clear = document.getElementById('msg-filter-clear');
  if (clear) {
    clear.addEventListener('click', () => {
      state.unboundOnly = false;
      if (state.metricFilter === 'unbound') state.metricFilter = 'all';
      loadMessages({ force: true });
    });
  }
}

function selectItem(id, kind) {
  const isSame = state.activeId === id;
  state.activeId = isSame ? null : id;
  state.activeKind = isSame ? null : kind;
  state.queueInfoId = null;
  if (isSame) {
    state.editId = null;
  }
  state.activeSnapshot = (state.items || []).find(x => x.id === id) || state.activeSnapshot;
  renderList();
}

function shouldAutoSelectDesktop() {
  return typeof window !== 'undefined' && window.innerWidth >= 1200;
}

function ensureDesktopSelection() {
  if (!shouldAutoSelectDesktop()) return;
  if (state.activeId) return;
  const items = visibleItems();
  if (!items.length) return;
  const first = items[0];
  state.activeId = first.id;
  state.activeKind = first.kind;
  state.activeSnapshot = first;
}

// ── Controller ──────────────────────────────────────────────────────────

async function loadMessages(opts = {}) {
  if (state.loading && !opts.force) return;
  state.loading = true;
  const loadSeq = ++state.loadSeq;
  const requestedUnboundOnly = !!state.unboundOnly;
  const previousItems = Array.isArray(state.items) ? [...state.items] : [];
  const previousProperties = Array.isArray(state.properties) ? [...state.properties] : [];
  try {
    const data = await fetchMessages();
    if (loadSeq !== state.loadSeq) return;
    state.items = data.items || [];
    state.shipIKbRetryEnabled = !!data.shipIKbRetryPrimary;
    state.properties = data.properties || [];
    const routedKnowledgeCount = state.items.filter((item) => routesToKnowledge(item)).length;
    const kbBadge = document.getElementById('nb-gaps-kb');
    if (kbBadge) {
      if (state.shipIKbRetryEnabled) {
        kbBadge.style.display = '';
        kbBadge.textContent = '';
        kbBadge.classList.remove('nb-red-dot');
        kbBadge.title = 'Knowledge backlog';
      } else {
        kbBadge.style.display = routedKnowledgeCount > 0 ? 'inline-flex' : 'none';
        kbBadge.textContent = '';
        kbBadge.classList.toggle('nb-red-dot', routedKnowledgeCount > 0);
        kbBadge.title = routedKnowledgeCount > 0 ? `${routedKnowledgeCount} inquiries waiting on knowledge` : '';
      }
    }
    state.summary = buildSummary(state.items, data);
    state.counters = buildCounters(state.items);
    state.tabCounts = buildTabCounts(state.items);
    state.unboundOnly = requestedUnboundOnly && data.unboundOnly === true;
    state.lastLoadedAt = new Date().toISOString();
    if (state.activeId) {
      const activeMatch = state.items.find(x => x.id === state.activeId);
      if (activeMatch) {
        if (routesToKnowledge(activeMatch)) {
          state.activeId = null;
          state.activeKind = null;
          state.activeSnapshot = null;
        } else {
          state.activeSnapshot = activeMatch;
        }
      } else if (state.activeKind === 'inquiry' && state.activeSnapshot) {
        state.items = [{ ...state.activeSnapshot, _syncing: true }, ...state.items.filter(x => x.id !== state.activeSnapshot.id)];
      }
    }
    if (state.pendingSelectId) {
      const pendingMatch = state.items.find((item) => item.id === state.pendingSelectId);
      if (pendingMatch) {
        state.activeId = pendingMatch.id;
        state.activeKind = pendingMatch.kind;
        state.activeSnapshot = pendingMatch;
      } else {
        state.activeId = null;
        state.activeKind = null;
        state.activeSnapshot = null;
      }
      state.pendingSelectId = null;
    }
    if (state.activeId && !state.items.some(x => x.id === state.activeId)) {
      if (!(state.activeKind === 'inquiry' && state.activeSnapshot)) {
        state.activeId = null;
        state.activeKind = null;
        state.activeSnapshot = null;
      }
    }
    ensureDesktopSelection();
    renderStatusLine();
    renderCommandMetrics();
    renderTaskStrip();
    renderWorkViewChips();
    renderFilterIndicator();
    renderPropertyDropdown();
    renderScopeDropdown();
    renderStatusTabVisibility();
    renderList();
  } catch (e) {
    if (loadSeq !== state.loadSeq) return;
    console.warn('[Messages] load failed', e);
    state.items = previousItems;
    state.properties = previousProperties;
    renderStatusLine(`Could not refresh pre-booking queue · ${String(e.message || e)}`);
    const pane = document.getElementById('msg-list-pane');
    if (pane) {
      if (previousItems.length) {
        renderCommandMetrics();
        renderTaskStrip();
        renderFilterIndicator();
        renderPropertyDropdown();
        renderScopeDropdown();
        renderList();
      } else {
        pane.innerHTML = `
          <div class="empty" style="padding:48px 20px">
            <div class="empty-title">Couldn't load pre-booking queue</div>
            <div class="empty-sub">${escapeHtml(String(e.message || e))}</div>
            <button class="btn btn-sm" id="msg-retry-btn" style="margin-top:12px">Retry</button>
          </div>`;
        const retryBtn = document.getElementById('msg-retry-btn');
        if (retryBtn) retryBtn.addEventListener('click', () => loadMessages({ force: true }));
      }
    }
  } finally {
    if (loadSeq === state.loadSeq) {
      state.loading = false;
    }
  }
}

function wireStageTabs() {
  // Stage tabs were intentionally removed to keep this screen focused on
  // inbound pre-booking work. We keep the helper for backward compatibility
  // with older cached HTML shells that may still render the tab bar briefly.
  document.querySelectorAll('#msg-stage-tabs .tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#msg-stage-tabs .tab').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      state.stage = 'pre_booking';
      loadMessages({ force: true });
    });
  });
}

function wireStatusTabs() {
  document.querySelectorAll('#msg-status-tabs .tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const view = btn.getAttribute('data-msg-viewfilter') || 'pending';
      state.workView = view === 'pending' ? 'action_queue' : view;
      state.status = 'all';
      savePreference('workView', state.workView);
      renderWorkViewChips();
      renderStatusLine();
      renderTaskStrip();
      renderList();
    });
  });
}

function wirePropertyFilter() {
  const sel = document.getElementById('msg-property-filter');
  if (!sel) return;
  sel.addEventListener('change', () => {
    state.property = sel.value || '';
    if (state.property) {
      state.unboundOnly = false;
      if (state.metricFilter === 'unbound') state.metricFilter = 'all';
    }
    loadMessages({ force: true });
  });
}

function wireScopeFilter() {
  const sel = document.getElementById('msg-scope-filter');
  if (!sel) return;
  sel.addEventListener('change', () => {
    state.scopeFilter = sel.value || 'all';
    savePreference('scopeFilter', state.scopeFilter);
    loadMessages({ force: true });
  });
}

function wireActions() {
  function activateItem(id, { openEditor = false } = {}) {
    const item = (state.items || []).find((entry) => entry.id === id);
    if (!item) return;
    state.activeId = item.id;
    state.activeKind = item.kind;
    state.activeSnapshot = item;
    state.queueInfoId = null;
    if (openEditor) {
      state.editId = item.id;
      if (!Object.prototype.hasOwnProperty.call(state.draftEdits, item.id)) {
        state.draftEdits[item.id] = item.draftText || '';
      }
    } else if (state.editId !== item.id) {
      state.editId = null;
    }
    renderList();
  }

  function rowEditorValue(targetId, fallback = '') {
    const textEl = document.querySelector(`[data-row-editor="${CSS.escape(String(targetId))}"]`);
    if (textEl instanceof HTMLTextAreaElement) return textEl.value.trim();
    return fallback;
  }

  async function handleSend(targetId = state.activeId) {
    if (!targetId) return;
    const item = (state.items || []).find(x => x.id === targetId);
    if (!item || item.kind !== 'inquiry') return;
    state.activeId = item.id;
    state.activeKind = item.kind;
    state.activeSnapshot = item;
    const queue = visibleItems();
    const idx = queue.findIndex((entry) => entry.id === item.id);
    const nextItem = idx >= 0 ? (queue[idx + 1] || queue[idx - 1] || null) : null;
    const originalDraft = (item.draftText || '').trim();
    const currentText = state.editId === item.id ? rowEditorValue(item.id, originalDraft) : originalDraft;
    const edited = currentText && currentText !== originalDraft;
    setBusy(true, targetId);
    try {
      const { ok, data } = edited
        ? await editInquiry(state.activeId, currentText)
        : await approveInquiry(state.activeId);
      if (!ok) throw new Error((data && data.error) || 'Send failed');
      state.pendingSelectId = nextItem ? nextItem.id : null;
      state.editId = null;
      await loadMessages({ force: true });
      flash('Sent', 'ok');
    } catch (e) {
      flash(`Send failed: ${e.message || e}`, 'err');
    } finally {
      setBusy(false, targetId);
    }
  }

  async function handleSave(targetId) {
    if (!targetId) return;
    const item = (state.items || []).find((entry) => entry.id === targetId);
    if (!item || item.kind !== 'inquiry') return;
    const currentText = rowEditorValue(targetId, item.draftText || '');
    if (!currentText) return;
    const queue = visibleItems();
    const idx = queue.findIndex((entry) => entry.id === item.id);
    const nextItem = idx >= 0 ? (queue[idx + 1] || queue[idx - 1] || null) : null;
    setBusy(true, targetId);
    try {
      const { ok, data } = await editInquiry(targetId, currentText);
      if (!ok) throw new Error((data && data.error) || 'Save failed');
      state.pendingSelectId = nextItem ? nextItem.id : null;
      state.editId = null;
      state.queueInfoId = null;
      await loadMessages({ force: true });
      flash('Saved', 'ok');
    } catch (e) {
      flash(`Save failed: ${e.message || e}`, 'err');
    } finally {
      setBusy(false, targetId);
    }
  }

  document.addEventListener('click', (event) => {
    const openPopout = document.querySelector('[data-row-popout]');
    if (openPopout && !event.target.closest('[data-row-popout]') && !event.target.closest('[data-row-info]')) {
      state.queueInfoId = null;
      renderList();
      return;
    }
    const rowSendBtn = event.target.closest('[data-row-send]');
    if (rowSendBtn) {
      event.stopPropagation();
      if (!rowSendBtn.disabled) handleSend(rowSendBtn.getAttribute('data-row-send'));
      return;
    }
    const rowSaveBtn = event.target.closest('[data-row-save]');
    if (rowSaveBtn) {
      event.stopPropagation();
      handleSave(rowSaveBtn.getAttribute('data-row-save'));
      return;
    }
    const rowEditBtn = event.target.closest('[data-row-edit]');
    if (rowEditBtn) {
      event.stopPropagation();
      activateItem(rowEditBtn.getAttribute('data-row-edit'), { openEditor: true });
      return;
    }
    const rowFillKbBtn = event.target.closest('[data-row-fill-kb]');
    if (rowFillKbBtn) {
      event.stopPropagation();
      const id = rowFillKbBtn.getAttribute('data-row-fill-kb');
      const item = (state.items || []).find((entry) => entry.id === id);
      if (item && typeof window.openKbResolveFlow === 'function') {
        window.openKbResolveFlow({
          source: 'queue',
          draftId: item.id,
          question: item.latestGuestTurn || item.messageText || item.messagePreview || '',
          answerHint: item.draftText || '',
          propertyId: item.propertyId || '',
          category: primaryGapTopic(item) || item.intent || 'General',
          retryTopic: primaryGapTopic(item) || '',
          retryCount: (state.items || []).filter((entry) => String(entry.status).toLowerCase() === 'pending_review' && gapTopics(entry).includes(primaryGapTopic(item))).length,
        });
      }
      return;
    }
    const rowInfoBtn = event.target.closest('[data-row-info]');
    if (rowInfoBtn) {
      event.stopPropagation();
      const id = rowInfoBtn.getAttribute('data-row-info');
      state.queueInfoId = state.queueInfoId === id ? null : id;
      state.activeId = id;
      state.activeKind = 'inquiry';
      state.activeSnapshot = (state.items || []).find((item) => item.id === id) || state.activeSnapshot;
      renderList();
      return;
    }
    const rowInfoCloseBtn = event.target.closest('[data-row-info-close]');
    if (rowInfoCloseBtn) {
      event.stopPropagation();
      state.queueInfoId = null;
      renderList();
      return;
    }
    const rowCancelBtn = event.target.closest('[data-row-cancel]');
    if (rowCancelBtn) {
      event.stopPropagation();
      const id = rowCancelBtn.getAttribute('data-row-cancel');
      state.editId = null;
      delete state.draftEdits[id];
      renderList();
    }
  });

  document.addEventListener('input', (event) => {
    const editor = event.target.closest('[data-row-editor]');
    if (!editor) return;
    const id = editor.getAttribute('data-row-editor');
    state.draftEdits[id] = editor.value;
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.queueInfoId) {
      state.queueInfoId = null;
      renderList();
    }
  });
}

function wireOperationalControls() {
  const windowSel = document.getElementById('pb-confidence-window');
  if (windowSel) {
    windowSel.value = state.confidenceWindow;
    windowSel.addEventListener('change', () => {
      state.confidenceWindow = windowSel.value || '7d';
      savePreference('confidenceWindow', state.confidenceWindow);
      renderConfidenceBand();
      renderAnalyticsBand();
    });
  }
}

function setBusy(busy, targetId) {
  if (!targetId) return;
  document.querySelectorAll(
    `[data-row-send="${CSS.escape(String(targetId))}"],` +
    `[data-row-edit="${CSS.escape(String(targetId))}"],` +
    `[data-row-save="${CSS.escape(String(targetId))}"],` +
    `[data-row-cancel="${CSS.escape(String(targetId))}"]`
  ).forEach((button) => {
    button.disabled = !!busy;
  });
}

function flash(text, kind) {
  const host = document.getElementById('msg-list-pane');
  if (!host) return;
  const el = document.createElement('div');
  el.textContent = text;
  el.style.cssText = `
    position:absolute;bottom:16px;right:16px;z-index:50;
    padding:8px 14px;border-radius:6px;font-size:12px;
    background:${kind === 'err' ? 'rgba(239,68,68,0.15)' : 'rgba(74,222,128,0.15)'};
    color:${kind === 'err' ? 'var(--red)' : 'var(--green)'};
    border:1px solid ${kind === 'err' ? 'rgba(239,68,68,0.3)' : 'rgba(74,222,128,0.3)'};
    font-family:'DM Mono',monospace;letter-spacing:0.08em;text-transform:uppercase`;
  host.style.position = 'relative';
  host.appendChild(el);
  setTimeout(() => el.remove(), 2400);
}

// ── Polling / lifecycle ─────────────────────────────────────────────────

function startPolling() {
  stopPolling();
  pollTimer = setInterval(() => {
    if (document.hidden) return;
    loadMessages({ background: true });
  }, 30000);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function isMessagesView() {
  const el = document.getElementById('view-prebooking');
  return el && el.style.display !== 'none';
}

function wireViewChange() {
  window.addEventListener('oyvoda:view-changed', (e) => {
    const view = e && e.detail && e.detail.view;
    if (view === 'prebooking') {
      if (state.unboundOnly) {
        state.unboundOnly = false;
        if (state.metricFilter === 'unbound') state.metricFilter = 'all';
        renderFilterIndicator();
      }
      loadMessages({ force: true });
      startPolling();
    } else {
      stopPolling();
    }
  });
}

function wireAttentionRefresh() {
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && isMessagesView()) {
      loadMessages({ force: true });
      startPolling();
    }
  });
  window.addEventListener('focus', () => {
    if (isMessagesView()) {
      loadMessages({ force: true });
      startPolling();
    }
  });
  window.addEventListener('resize', () => {
    if (!isMessagesView()) return;
    if (shouldAutoSelectDesktop() && !state.activeId) {
      ensureDesktopSelection();
      renderList();
    }
    positionOpenPopout();
  });
}

function inlineStyles() {
  if (document.getElementById('msg-inline-css')) return;
  const s = document.createElement('style');
  s.id = 'msg-inline-css';
  s.textContent = `
    #msg-property-filter {
      min-width: 220px;
    }
  `;
  document.head.appendChild(s);
}

function normalizeStoredWorkView(value) {
  return ['sent', 'held', 'closed'].includes(value) ? value : 'action_queue';
}

export function init() {
  state.mode = loadPreference('mode', 'auto');
  state.workView = normalizeStoredWorkView(loadPreference('workView', 'action_queue'));
  state.scopeFilter = loadPreference('scopeFilter', 'all');
  state.queueDepth = loadPreference('queueDepth', '25') === 'all' ? 'all' : Number(loadPreference('queueDepth', '25'));
  state.confidenceWindow = loadPreference('confidenceWindow', '7d');
  inlineStyles();
  wireStageTabs();
  wireStatusTabs();
  wireWorkViews();
  wireModes();
  wireMetricCards();
  wirePropertyFilter();
  wireScopeFilter();
  wireActions();
  wireViewChange();
  wireAttentionRefresh();
  wireOperationalControls();
  fetchAssignmentCandidates().then((items) => {
    state.assignmentCandidates = items;
    renderScopeDropdown();
  }).catch(() => {});
  appState.subscribe('inboxHealth', () => {
    renderResolutionHeader();
    renderStatusLine();
    if (!state.items.length) renderList();
  });
  appState.subscribe('dashboardSummary', () => {
    renderResolutionHeader();
    renderStatusLine();
    if (!state.items.length) renderList();
  });
  appState.subscribe('operator', () => {
    state.mode = loadPreference('mode', state.mode);
    state.workView = normalizeStoredWorkView(loadPreference('workView', state.workView));
    state.queueDepth = loadPreference('queueDepth', queueDepthLabel()) === 'all' ? 'all' : Number(loadPreference('queueDepth', queueDepthLabel()));
    state.confidenceWindow = loadPreference('confidenceWindow', state.confidenceWindow);
    if (effectiveMode() === 'simple' && state.workView !== 'action_queue') state.workView = 'action_queue';
    renderModeChips();
    renderWorkViewChips();
    renderScopeDropdown();
    renderStatusLine();
    renderTaskStrip();
    renderList();
  });
  if (isMessagesView()) {
    loadMessages({ force: true });
  }
  if (isMessagesView()) startPolling();
  renderStatusLine('Pre-booking queue wakes up when this view is active.');
  renderTaskStrip();
  renderCommandMetrics();
  renderFilterIndicator();
  renderWorkViewChips();
  renderModeChips();
}

// Expose a manual refresh for other parts of the UI to trigger a reload
// without reaching into module internals.
window.reloadMessages = () => loadMessages({ force: true });
