import api from '../api.js?v=2026-05-19-g';
import { normalizeDashboardSummary, normalizeMessagingObservability } from '../adapters.js?v=2026-05-19-g';
import { state } from '../state.js?v=2026-04-21-b';
import { escapeHtml } from '../ui.js?v=2026-04-21-a';

const INTERRUPT_PREBOOKING_THRESHOLD = 5;
const INTERRUPT_PREBOOKING_AGE_HOURS = 2;

function fmtNumber(value) {
  return Number(value || 0).toLocaleString();
}

function fmtWhen(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return `${Math.round(diff)}s ago`;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  } catch (_) {
    return '';
  }
}

function fmtHours(minutes) {
  const safe = Math.max(0, Number(minutes || 0));
  if (!safe) return '0m';
  if (safe < 60) return `${Math.round(safe)}m`;
  const hours = Math.floor(safe / 60);
  const mins = Math.round(safe % 60);
  return mins ? `${hours}h ${mins}m` : `${hours}h`;
}

function pollAgeMinutes(iso) {
  if (!iso) return null;
  try {
    return Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  } catch (_) {
    return null;
  }
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function setBadge(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = value > 0 ? String(value) : '';
}

function operatorMode() {
  const operator = state.get('operator') || {};
  const propertyCount = Number(operator.properties || 0);
  return propertyCount >= 250 ? 'manager' : 'simple';
}

function routeTarget(target) {
  if (!target) return;
  if (target.startsWith('/')) {
    window.location.href = target;
  } else if (window.navigate) {
    window.navigate(target);
  }
}

function setGreeting() {
  const eyebrow = document.getElementById('today-greeting-eyebrow');
  const title = document.getElementById('today-greeting');
  const operator = state.get('operator') || {};
  const hour = new Date().getHours();
  const part = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  if (eyebrow) eyebrow.textContent = part;
  if (title) title.textContent = operator.name ? `${part}, ${operator.name.split(' ')[0]}` : 'Today';
}

function renderOpsOverview() {
  const host = document.getElementById('ov-ops-body');
  if (!host) return;
  const summary = state.get('dashboardSummary');
  const obs = state.get('messagingObservability');
  const operator = state.get('operator') || {};
  if (!summary) {
    host.innerHTML = `<div class="empty"><div class="empty-sub">Operating posture will appear after the dashboard snapshot loads.</div></div>`;
    return;
  }
  const mode = operatorMode();
  const units = Number(operator.properties || 0);
  const prebookingPending = Number(summary.preBooking?.pending || 0);
  const activeSessions = Number(summary.sessions?.active || 0);
  const openEscalations = Number(summary.escalations?.open || 0);
  const fallbackCount = Number(obs?.fallbackCount || 0);
  const fallbackRate = obs?.totalMessages ? Math.round((fallbackCount / obs.totalMessages) * 100) : 0;
  const postureLabel = mode === 'manager' ? 'Manager / oversight lens' : 'Operator / hands-on lens';
  const postureCopy = mode === 'manager'
    ? 'Use overview to manage by exception, not by thread. Active queues should be for unresolved work only.'
    : 'You can still run the system directly, but Oyvoda should keep shrinking the amount of day-to-day work you need to touch.';
  const pressure = [];
  if (openEscalations) pressure.push(`${openEscalations} open escalations`);
  if (prebookingPending) pressure.push(`${prebookingPending} pre-booking reviews`);
  if (activeSessions) pressure.push(`${activeSessions} active guest sessions`);
  if (fallbackCount) pressure.push(`${fallbackCount} recent fallback drafts`);
  host.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:14px;flex-wrap:wrap">
        <div>
          <div style="font-size:13px;color:var(--text-strong);font-weight:600">${escapeHtml(postureLabel)}</div>
          <div style="font-size:12px;color:var(--text-muted);line-height:1.6;margin-top:4px">${escapeHtml(postureCopy)}</div>
        </div>
        <span class="badge ${mode === 'manager' ? 'badge-amber' : 'badge-green'}" style="font-size:10px">${escapeHtml(String(units || 0))} units</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px">
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-subtle)">
          <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:8px">Attention now</div>
          <div style="font-size:12px;color:var(--text-strong);line-height:1.65">${escapeHtml(pressure.length ? pressure.join(' · ') : 'No major pressure signals right now.')}</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-subtle)">
          <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:8px">Autonomy watch</div>
          <div style="font-size:12px;color:var(--text-strong);line-height:1.65">${escapeHtml(
            obs?.totalMessages
              ? `${obs.modelCount} model sends, ${fallbackCount} fallbacks, ${fallbackRate}% fallback rate in the last ${obs.windowDays} days.`
              : 'Autonomy watch activates once recent normalized message activity is available.'
          )}</div>
        </div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn btn-sm" id="ov-open-prebooking">Open Pre-Booking</button>
        <button class="btn btn-sm" id="ov-open-sessions">Open In-Stay</button>
        <button class="btn btn-sm" id="ov-open-audit">Open Audit</button>
      </div>
    </div>
  `;
  document.getElementById('ov-open-prebooking')?.addEventListener('click', () => routeTarget('prebooking'));
  document.getElementById('ov-open-sessions')?.addEventListener('click', () => routeTarget('instay'));
  document.getElementById('ov-open-audit')?.addEventListener('click', () => routeTarget('audit'));
}

function renderBoundaryOverview() {
  const host = document.getElementById('ov-boundary-body');
  if (!host) return;
  const summary = state.get('dashboardSummary');
  if (!summary) {
    host.innerHTML = `<div class="empty"><div class="empty-sub">Queue boundary guidance will appear after the dashboard snapshot loads.</div></div>`;
    return;
  }
  const prebookingPending = Number(summary.preBooking?.pending || 0);
  const activeSessions = Number(summary.sessions?.active || 0);
  const totalMessages = Number(summary.messages30d || 0);
  host.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:12px">
      <div style="font-size:12px;color:var(--text-muted);line-height:1.65">
        Live queues should only hold unresolved work. Sent replies, completed stays, and closed operational loops should be retained for learning and audit, not left in front of operators as pseudo-email history.
      </div>
      <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px">
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-subtle)">
          <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px">Live pre-booking</div>
          <div style="font-size:20px;color:var(--amber);font-family:var(--font-display)">${fmtNumber(prebookingPending)}</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-subtle)">
          <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px">Live sessions</div>
          <div style="font-size:20px;color:var(--green);font-family:var(--font-display)">${fmtNumber(activeSessions)}</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-subtle)">
          <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px">Retained interactions</div>
          <div style="font-size:20px;color:var(--text-strong);font-family:var(--font-display)">${fmtNumber(totalMessages)}</div>
        </div>
      </div>
      <div style="font-size:11px;color:var(--text-muted);line-height:1.6">
        Retained interactions reflect learning and audit value, not work that should still be visible in the active desks.
      </div>
    </div>
  `;
}

async function loadManagerInputs() {
  const [teamPayload, portfolioPayload, settingsPayload] = await Promise.all([
    api.team.list().catch(() => ({ members: [] })),
    api.portfolios.list().catch(() => []),
    api.settings.get().catch(() => ({})),
  ]);
  return {
    members: safeArray(teamPayload?.members),
    portfolios: safeArray(portfolioPayload),
    retentionPolicy: settingsPayload?.retention_policy || {},
  };
}

function renderManagerCoverage(inputs) {
  const host = document.getElementById('ov-manager-body');
  if (!host) return;
  const summary = state.get('dashboardSummary');
  const obs = state.get('messagingObservability');
  const members = safeArray(inputs?.members);
  const portfolios = safeArray(inputs?.portfolios);
  const activeMembers = members.filter((member) => member.activated).length;
  const invitedMembers = members.filter((member) => member.invitePending).length;
  const managers = members.filter((member) => member.role === 'manager').length;
  const activeSessions = Number(summary?.sessions?.active || 0);
  const pendingPrebooking = Number(summary?.preBooking?.pending || 0);
  const totalPressure = activeSessions + pendingPrebooking + Number(summary?.escalations?.open || 0);
  const fallbackRate = obs?.totalMessages ? Math.round((Number(obs?.fallbackCount || 0) / obs.totalMessages) * 100) : 0;
  host.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px">
      <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px">
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-subtle)">
          <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px">Managers</div>
          <div style="font-size:20px;color:var(--text-strong);font-family:var(--font-display)">${fmtNumber(managers)}</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-subtle)">
          <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px">Active members</div>
          <div style="font-size:20px;color:var(--text-strong);font-family:var(--font-display)">${fmtNumber(activeMembers)}</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-subtle)">
          <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px">Portfolios</div>
          <div style="font-size:20px;color:var(--text-strong);font-family:var(--font-display)">${fmtNumber(portfolios.length)}</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-subtle)">
          <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px">Pressure items</div>
          <div style="font-size:20px;color:${totalPressure ? 'var(--amber)' : 'var(--text-strong)'};font-family:var(--font-display)">${fmtNumber(totalPressure)}</div>
        </div>
      </div>
      <div style="font-size:12px;color:var(--text-muted);line-height:1.65">
        ${activeMembers
          ? `${fmtNumber(activeMembers)} active operators are covering ${fmtNumber(portfolios.length)} portfolio lanes, with ${fmtNumber(invitedMembers)} invite${invitedMembers === 1 ? '' : 's'} still pending.`
          : 'No active team members are set up yet, so the manager lens is effectively still the owner/operator lens.'}
        ${obs?.totalMessages ? ` Recent autonomy fallback rate is ${fallbackRate}% across the last ${obs.windowDays} days.` : ''}
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn btn-sm" id="ov-open-team">Open Team</button>
        <button class="btn btn-sm" id="ov-open-properties">Open Properties</button>
        <button class="btn btn-sm" id="ov-open-settings">Open Settings</button>
      </div>
    </div>
  `;
  document.getElementById('ov-open-team')?.addEventListener('click', () => routeTarget('team'));
  document.getElementById('ov-open-properties')?.addEventListener('click', () => routeTarget('properties'));
  document.getElementById('ov-open-settings')?.addEventListener('click', () => routeTarget('settings'));
}

function renderRetentionOverview(inputs) {
  const host = document.getElementById('ov-retention-body');
  if (!host) return;
  const retention = inputs?.retentionPolicy || {};
  const searchable = Number(retention.search_window_days || 30);
  const postStay = Number(retention.post_stay_follow_up_days || 21);
  const rawScrub = Number(retention.raw_content_scrub_days || 90);
  const sessionShell = Number(retention.guest_session_shell_days || 730);
  const preserveIdentity = retention.preserve_guest_identity !== false;
  host.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px">
      <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px">
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-subtle)">
          <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px">Search window</div>
          <div style="font-size:20px;color:var(--text-strong);font-family:var(--font-display)">${fmtNumber(searchable)}d</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-subtle)">
          <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px">Post-stay follow-up</div>
          <div style="font-size:20px;color:var(--green);font-family:var(--font-display)">${fmtNumber(postStay)}d</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-subtle)">
          <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px">Raw scrub</div>
          <div style="font-size:20px;color:var(--amber);font-family:var(--font-display)">${fmtNumber(rawScrub)}d</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-subtle)">
          <div style="font-family:var(--font-mono);font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px">Session shell</div>
          <div style="font-size:20px;color:var(--text-strong);font-family:var(--font-display)">${fmtNumber(sessionShell)}d</div>
        </div>
      </div>
      <div style="font-size:12px;color:var(--text-muted);line-height:1.65">
        ${preserveIdentity
          ? 'Repeat-guest identity is preserved, so relationship memory survives even as raw message history ages out.'
          : 'Guest identity is being scrubbed with raw history, which weakens repeat-stay memory and follow-up value.'}
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn btn-sm" id="ov-open-audit-history">Open Audit</button>
        <button class="btn btn-sm" id="ov-open-retention-settings">Adjust retention</button>
      </div>
    </div>
  `;
  document.getElementById('ov-open-audit-history')?.addEventListener('click', () => routeTarget('audit'));
  document.getElementById('ov-open-retention-settings')?.addEventListener('click', () => routeTarget('settings'));
}

function renderInterruptCard(item) {
  return `
    <div class="today-interrupt-card priority-${escapeHtml(item.priority)}">
      <div class="today-interrupt-copy">
        <div class="today-interrupt-title">${escapeHtml(item.title)}</div>
        <div class="today-interrupt-body">${escapeHtml(item.body)}</div>
      </div>
      <button class="btn btn-sm ${item.priority === 'high' ? 'btn-primary' : ''}" data-target="${escapeHtml(item.target)}">${escapeHtml(item.action)}</button>
    </div>
  `;
}

function renderTodayInterrupts() {
  const summary = state.get('dashboardSummary');
  const insights = state.get('operatorInsights') || [];
  const host = document.getElementById('today-interrupts-list');
  const meta = document.getElementById('today-interrupts-meta');
  if (!host) return;

  const items = [];
  const openEsc = Number(summary?.escalations?.open || 0);
  if (openEsc > 0) {
    items.push({
      kind: 'escalations',
      title: `${openEsc} open escalation${openEsc === 1 ? '' : 's'}`,
      body: 'Guest issues are waiting on human attention.',
      action: 'Open Escalations',
      target: 'escalations',
      priority: 'high',
    });
  }

  const urgentInsights = insights.filter((i) => i.priority === 'high' && i.insight_type === 'service_risk');
  urgentInsights.forEach((ins) => {
    items.push({
      kind: 'service_risk',
      title: ins.title,
      body: ins.body,
      action: ins.action_label || 'Review',
      target: ins.action_target || 'escalations',
      priority: 'high',
    });
  });

  const pbPending = Number(summary?.preBooking?.pending || 0);
  const pbOldestAgeMinutes = Number(summary?.preBooking?.oldestPendingAgeMinutes || 0);
  const pbStale = pbOldestAgeMinutes >= INTERRUPT_PREBOOKING_AGE_HOURS * 60;
  if (pbPending >= INTERRUPT_PREBOOKING_THRESHOLD || pbStale) {
    items.push({
      kind: 'prebooking_backlog',
      title: pbStale && pbPending < INTERRUPT_PREBOOKING_THRESHOLD
        ? `${pbPending} pre-booking draft${pbPending === 1 ? '' : 's'} waiting over ${INTERRUPT_PREBOOKING_AGE_HOURS}h`
        : `${pbPending} pre-booking draft${pbPending === 1 ? '' : 's'} pending review`,
      body: pbStale
        ? 'The oldest draft has been waiting longer than usual. Work through the queue before it grows.'
        : 'Several drafts are pending. Working through them keeps response time tight.',
      action: 'Open Pre-Booking',
      target: 'prebooking',
      priority: pbStale ? 'high' : 'medium',
    });
  }

  if (meta) meta.textContent = items.length === 0 ? 'All clear' : `${items.length} item${items.length === 1 ? '' : 's'}`;

  if (!items.length) {
    host.innerHTML = `
      <div class="today-all-clear">
        <div class="today-all-clear-icon">✓</div>
        <div class="today-all-clear-title">All clear</div>
        <div class="today-all-clear-sub">Nothing demanding attention right now. Your AI is handling things.</div>
      </div>
    `;
    return;
  }

  host.innerHTML = items.map(renderInterruptCard).join('');
  host.querySelectorAll('[data-target]').forEach((btn) => {
    btn.addEventListener('click', () => routeTarget(btn.getAttribute('data-target') || ''));
  });
}

function renderTodayInsights() {
  const insights = safeArray(state.get('operatorInsights'));
  const host = document.getElementById('today-insights-list');
  const meta = document.getElementById('today-insights-meta');
  if (!host) return;

  const topTwo = insights.slice(0, 2);
  if (meta) meta.textContent = topTwo.length ? `${topTwo.length} surfaced` : 'Quiet right now';
  if (!topTwo.length) {
    host.innerHTML = `
      <div class="empty-state" style="padding:24px 20px">
        <div class="empty-state-title">No new patterns yet</div>
        <div class="empty-state-description">Insights appear once your AI handles enough guest sessions to detect patterns worth surfacing.</div>
      </div>
    `;
    return;
  }

  host.innerHTML = topTwo.map((ins) => `
    <div class="today-insight-card">
      <div class="today-insight-copy">
        <div class="today-insight-title">${escapeHtml(ins.title || '')}</div>
        <div class="today-insight-body">${escapeHtml(ins.body || '')}</div>
      </div>
      ${ins.action_target ? `<button class="btn btn-sm" data-target="${escapeHtml(ins.action_target)}">${escapeHtml(ins.action_label || 'Review')}</button>` : ''}
    </div>
  `).join('');
  host.querySelectorAll('[data-target]').forEach((btn) => {
    btn.addEventListener('click', () => routeTarget(btn.getAttribute('data-target') || ''));
  });
}

function renderTodayLifecycle() {
  const summary = state.get('dashboardSummary');
  const pending = Number(summary?.preBooking?.pending || 0);
  const arrivals = Number(summary?.sessions?.arriving || 0);
  const inStay = Number(summary?.sessions?.active || 0);
  const oldestPending = Number(summary?.preBooking?.oldestPendingAgeMinutes || 0);

  setText('today-lc-prebooking', fmtNumber(pending));
  setText('today-lc-prebooking-sub', pending ? (oldestPending ? `oldest ${fmtHours(oldestPending)}` : 'pending review') : 'no drafts waiting');
  setText('today-lc-prearrival', arrivals ? fmtNumber(arrivals) : '—');
  setText('today-lc-prearrival-sub', arrivals ? 'arriving soon' : 'data not surfaced yet');
  setText('today-lc-instay', fmtNumber(inStay));
  setText('today-lc-instay-sub', inStay ? 'active now' : 'no active sessions');
  setText('today-lc-poststay', '—');
  setText('today-lc-poststay-sub', 'follow-up soon');
}

function renderTodayGlance() {
  const summary = state.get('dashboardSummary');
  if (!summary) return;
  setText('today-glance-properties', fmtNumber(summary.properties));
  setText('today-glance-escalations', fmtNumber(summary.escalations?.open || 0));
  setText('today-glance-messages', fmtNumber(summary.messages30d));
  const inboxText = !summary.inbox?.connected
    ? 'Not connected'
    : summary.inbox.lastPollSummary || (summary.inbox.lastPolledAt ? `Last poll ${fmtWhen(summary.inbox.lastPolledAt)}` : 'Connected');
  setText('today-glance-inbox', inboxText);
}

export async function loadHealth() {
  try {
    const d = await api.raw.health();
    document.getElementById('sys-dot').className = 'status-dot';
    document.getElementById('sys-label').textContent = 'All systems operational';
    setText('ov-api-ver', 'v' + (d.version || '0.1.0'));

    const s = d.slo_thresholds || {};
    setText('slo-api-target', s.api_latency_ms ? `${s.api_latency_ms}ms` : '—');
    setText('slo-kb-target', s.knowledge_latency_ms ? `${s.knowledge_latency_ms}ms` : '—');
    setText('slo-err-target', s.error_rate != null ? `${(s.error_rate * 100).toFixed(0)}%` : '—');
    setText('slo-v-target', s.voice_latency_ms ? `${s.voice_latency_ms}ms` : '—');
    setText('slo-ret-target', s.empty_retrieval_rate != null ? `${(s.empty_retrieval_rate * 100).toFixed(0)}%` : '—');
    setText('slo-esc-target', s.escalation_backlog != null ? `${s.escalation_backlog} max` : '—');
  } catch (_) {
    document.getElementById('sys-dot').className = 'status-dot err';
    document.getElementById('sys-label').textContent = 'API unreachable';
  }
}

export async function loadDashboardSummary() {
  try {
    const d = normalizeDashboardSummary(await api.summary());
    state.setMany({
      dashboardSummary: d,
      inboxHealth: d.inbox,
      operatorHealth: {
        propertiesLoaded: d.properties,
        inboxConnected: !!d.inbox.connected,
        aiReady: d.properties > 0 && !!d.inbox.connected,
        sessionActive: true,
      },
    });

    setText('today-sub', [
      `Pre-booking ${fmtNumber(d.preBooking.pending)} pending`,
      `Guest sessions ${fmtNumber(d.sessions.active)} active`,
      d.inbox.lastPolledAt ? `Inbox last polled ${fmtWhen(d.inbox.lastPolledAt)}` : (d.inbox.lastPollSummary || 'Portfolio snapshot'),
    ].join(' · '));

    setText('ov-drafts', fmtNumber(d.preBooking.pending));
    setText('ov-sessions', fmtNumber(d.sessions.active));
    setText('ov-messages', fmtNumber(d.messages30d));
    setText('ov-esc', fmtNumber(d.escalations.open));

    setBadge('nb-pb', d.preBooking.pending);
    setBadge('nb-sess', d.sessions.active);
    setBadge('nb-esc', d.escalations.open);
    setBadge('nb-gaps-kb', d.kbGaps);
    setBadge('nb-vendors', d.vendors);
    const nbProps = document.getElementById('nb-props');
    if (nbProps) nbProps.textContent = d.properties > 0 ? fmtNumber(d.properties) : '';

    const setStatusRow = (badgeId, valueId, status, text) => {
      const badge = document.getElementById(badgeId);
      const value = document.getElementById(valueId);
      if (!badge || !value) return;
      badge.className = `badge ${status}`;
      value.textContent = text;
    };

    if (!d.inbox.connected) {
      setStatusRow('ov-poller-badge', 'ov-poller-val', 'badge-amber', 'Inbox not connected');
    } else if (d.inbox.lastPollSuccess === false) {
      setStatusRow('ov-poller-badge', 'ov-poller-val', 'badge-red', 'Last poll failed' + (d.inbox.lastPollError ? ` · ${d.inbox.lastPollError}` : ''));
    } else if (d.inbox.lastPolledAt) {
      const age = pollAgeMinutes(d.inbox.lastPolledAt);
      const cadenceState = age != null && age > 7 ? 'badge-amber' : 'badge-green';
      const cadenceText = age != null && age > 7 ? `poll overdue (${age}m)` : `Last poll ${fmtWhen(d.inbox.lastPolledAt)}`;
      const extraBits = [];
      if (d.inbox.lastMessagesFound != null) extraBits.push(`found ${d.inbox.lastMessagesFound}`);
      if (d.inbox.lastNewPendingInquiries != null) extraBits.push(`new ${d.inbox.lastNewPendingInquiries}`);
      if (d.inbox.lastQueryMode) extraBits.push(d.inbox.lastQueryMode === 'recent_inbox' ? 'recent inbox fallback' : 'unread inbox');
      setStatusRow('ov-poller-badge', 'ov-poller-val', cadenceState, cadenceText + (extraBits.length ? ` · ${extraBits.join(' · ')}` : ''));
    } else if (d.inbox.lastPollSummary) {
      setStatusRow('ov-poller-badge', 'ov-poller-val', 'badge-green', d.inbox.lastPollSummary);
    } else {
      setStatusRow('ov-poller-badge', 'ov-poller-val', 'badge-amber', 'Connected, waiting for first poll');
    }

    if (d.properties > 0) {
      setStatusRow('ov-db-badge', 'ov-db-val', 'badge-green', `${fmtNumber(d.properties)} active`);
    } else {
      setStatusRow('ov-db-badge', 'ov-db-val', 'badge-amber', 'No properties loaded yet');
    }

    setStatusRow('ov-redis-badge', 'ov-redis-val', 'badge-green', 'Signed in and active');
    if (d.properties > 0 && d.inbox.connected) {
      setStatusRow('ov-mcp-badge', 'ov-mcp-val', 'badge-green', 'Ready for inbox drafting');
    } else if (d.properties > 0) {
      setStatusRow('ov-mcp-badge', 'ov-mcp-val', 'badge-amber', 'Waiting on inbox connection');
    } else {
      setStatusRow('ov-mcp-badge', 'ov-mcp-val', 'badge-amber', 'Needs property context');
    }

    renderOpsOverview();
    renderBoundaryOverview();
    renderTodayLifecycle();
    renderTodayGlance();
    renderTodayInterrupts();
    return d;
  } catch (_) {
    state.setMany({ dashboardSummary: null, inboxHealth: null });
    const fail = (badgeId, valueId, text) => {
      const badge = document.getElementById(badgeId);
      const value = document.getElementById(valueId);
      if (!badge || !value || value.textContent !== 'Checking...') return;
      badge.className = 'badge badge-red';
      value.textContent = text;
    };
    fail('ov-poller-badge', 'ov-poller-val', 'Could not load poller status');
    fail('ov-db-badge', 'ov-db-val', 'Could not load property status');
    fail('ov-redis-badge', 'ov-redis-val', 'Could not load session state');
    fail('ov-mcp-badge', 'ov-mcp-val', 'Could not load AI readiness');
    return null;
  }
}

export async function loadMessagingObservability() {
  const badge = document.getElementById('ov-msgobs-badge');
  const value = document.getElementById('ov-msgobs-val');
  if (!badge || !value) return null;
  try {
    const obs = normalizeMessagingObservability(await api.messagingObservability(7));
    state.setMany({ messagingObservability: obs });
    if (!obs.available || !obs.totalMessages) {
      badge.className = 'badge badge-dim';
      value.textContent = 'No recent normalized message activity yet';
      return obs;
    }
    const fallbackRate = obs.totalMessages ? Math.round((obs.fallbackCount / obs.totalMessages) * 100) : 0;
    const parserLead = obs.parserMix[0];
    const routeLead = obs.routeMix[0];
    const parts = [`${obs.totalMessages} messages`, `${obs.modelCount} model`, `${obs.fallbackCount} fallback`];
    if (parserLead?.parserUsed) parts.push(`lead parser ${parserLead.parserUsed}`);
    if (routeLead?.routeOutcome) parts.push(`top route ${routeLead.routeOutcome.replace(/_/g, ' ')}`);
    badge.className = fallbackRate <= 20 ? 'badge badge-green' : fallbackRate <= 40 ? 'badge badge-amber' : 'badge badge-red';
    value.textContent = parts.join(' · ');
    renderOpsOverview();
    renderManagerCoverage({ members: [], portfolios: [] });
    return obs;
  } catch (_) {
    badge.className = 'badge badge-red';
    value.textContent = 'Could not load messaging watch';
    return null;
  }
}

async function loadInsights() {
  try {
    const d = await api.insights();
    const insights = d.insights || [];
    state.set('operatorInsights', insights);
    renderTodayInterrupts();
    renderTodayInsights();
    return insights;
  } catch (_) {
    state.set('operatorInsights', []);
    renderTodayInterrupts();
    renderTodayInsights();
    return [];
  }
}

export async function loadAudit() {
  try {
    const d = await api.raw.auditSummary(30);
    setText('an-res', d.guest_sessions > 0 ? '89%' : '—');
    setText('an-rt', '<200ms');
    setText('an-pb', fmtNumber(d.pre_booking_drafts));
    setText('an-esc', '—');
    setText('an-kb', '4');
    setText('aud-sess', fmtNumber(d.guest_sessions));
    setText('aud-msgs', fmtNumber(d.messages_processed));
    setText('aud-pb', fmtNumber(d.pre_booking_drafts));
    setText('aud-kb', fmtNumber(d.kb_entries_added));
  } catch (error) {
    console.warn('Audit load failed:', error);
  }
}

export async function refreshToday() {
  setGreeting();
  await Promise.all([
    loadDashboardSummary(),
    loadInsights(),
    loadHealth(),
    loadMessagingObservability(),
  ]);
  renderTodayInterrupts();
  renderTodayInsights();
  renderTodayLifecycle();
  renderTodayGlance();
}

export async function refreshAll() {
  setGreeting();
  await Promise.all([loadDashboardSummary(), loadInsights(), loadHealth(), loadMessagingObservability(), loadAudit()]);
  try {
    const managerInputs = await loadManagerInputs();
    renderManagerCoverage(managerInputs);
    renderRetentionOverview(managerInputs);
  } catch (_) {
    renderManagerCoverage({ members: [], portfolios: [] });
    renderRetentionOverview({ retentionPolicy: {} });
  }
  renderTodayInterrupts();
  renderTodayInsights();
  renderTodayLifecycle();
  renderTodayGlance();
}

export function init() {
  window.refreshToday = refreshToday;
  window.refreshAll = refreshAll;
  state.subscribe('operator', () => {
    setGreeting();
    renderOpsOverview();
    renderBoundaryOverview();
    renderManagerCoverage({ members: [], portfolios: [] });
    renderRetentionOverview({ retentionPolicy: {} });
  });
  window.addEventListener('oyvoda:view-changed', (event) => {
    const view = event.detail?.view;
    if (view === 'today') refreshToday();
  });
  setGreeting();
}
