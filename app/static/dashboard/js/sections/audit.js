import api from '../api.js?v=2026-05-05-a';
import { normalizeDashboardSummary, normalizeMessagingEvents } from '../adapters.js?v=2026-05-05-a';

const state = {
  days: 30,
};

let composerPollTimer = null;

function fmtNumber(value) {
  return Number(value || 0).toLocaleString();
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

// ── Composer compare-mode helpers ────────────────────────────────────────
// These format raw normalized values from normalizeMessagingEvents() into
// human-readable cells. They are deliberately tolerant of nulls and missing
// fields because compare-mode rows arrive partially populated until the
// composer fully runs against an inbound message.

function fmtLatency(ms) {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function fmtTimestamp(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch (_) {
    return iso;
  }
}

function escapeText(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function updateExportLinks() {
  const days = state.days || 30;
  document.querySelectorAll('[data-audit-export]').forEach((link) => {
    const href = link.getAttribute('href') || '';
    if (!href.includes('/api/v1/audit/export')) return;
    const url = new URL(href, window.location.origin);
    url.searchParams.set('days', String(days));
    link.setAttribute('href', `${url.pathname}?${url.searchParams.toString()}`);
  });
}

function renderAuditPosture(summary, audit) {
  const host = document.getElementById('audit-posture-body');
  if (!host) return;
  const livePrebooking = Number(summary?.preBooking?.pending || 0);
  const liveSessions = Number(summary?.sessions?.active || 0);
  const openEscalations = Number(summary?.escalations?.open || 0);
  const retained = Number(audit?.messages_processed || 0);
  host.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px">
      <div style="font-size:12px;color:var(--dim);line-height:1.65">
        The live desks should only reflect unresolved work. Everything else should move here into a bounded audit/search posture so operators are not staring at a giant sent-mail archive.
      </div>
      <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px">
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Live pre-booking</div>
          <div style="font-size:20px;color:var(--amber);font-family:'Cormorant Garamond',serif">${fmtNumber(livePrebooking)}</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Live sessions</div>
          <div style="font-size:20px;color:var(--green);font-family:'Cormorant Garamond',serif">${fmtNumber(liveSessions)}</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Escalations</div>
          <div style="font-size:20px;color:${openEscalations ? 'var(--red)' : 'var(--white)'};font-family:'Cormorant Garamond',serif">${fmtNumber(openEscalations)}</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Retained signals</div>
          <div style="font-size:20px;color:var(--white);font-family:'Cormorant Garamond',serif">${fmtNumber(retained)}</div>
        </div>
      </div>
    </div>
  `;
}

function renderAuditRetention(policy) {
  const host = document.getElementById('audit-retention-body');
  if (!host) return;
  const searchable = Number(policy?.search_window_days || 30);
  const postStay = Number(policy?.post_stay_follow_up_days || 21);
  const rawScrub = Number(policy?.raw_content_scrub_days || 90);
  const prebookingDelete = Number(policy?.pre_booking_delete_days || 120);
  const preserveIdentity = policy?.preserve_guest_identity !== false;
  host.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px">
      <div style="font-size:12px;color:var(--dim);line-height:1.65">
        Raw history stays searchable for a bounded window, post-stay follow-up stays available long enough to drive repeat bookings, and identity stays preserved so guest relationship value is not lost.
      </div>
      <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px">
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Search window</div>
          <div style="font-size:20px;color:var(--white);font-family:'Cormorant Garamond',serif">${fmtNumber(searchable)}d</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Post-stay follow-up</div>
          <div style="font-size:20px;color:var(--green);font-family:'Cormorant Garamond',serif">${fmtNumber(postStay)}d</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Raw scrub</div>
          <div style="font-size:20px;color:var(--amber);font-family:'Cormorant Garamond',serif">${fmtNumber(rawScrub)}d</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Pre-booking delete</div>
          <div style="font-size:20px;color:var(--white);font-family:'Cormorant Garamond',serif">${fmtNumber(prebookingDelete)}d</div>
        </div>
      </div>
      <div style="font-size:11px;color:rgba(240,235,227,0.56);line-height:1.6">
        ${preserveIdentity ? 'Repeat-guest memory is preserved for rebook context.' : 'Repeat-guest memory is not being preserved.'}
      </div>
    </div>
  `;
}

function renderCoverage(teamPayload, portfolios) {
  const host = document.getElementById('audit-coverage-body');
  if (!host) return;
  const members = safeArray(teamPayload?.members);
  const activeMembers = members.filter((member) => member.activated).length;
  const managers = members.filter((member) => member.role === 'manager').length;
  const staff = members.filter((member) => member.role === 'staff').length;
  host.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px">
      <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px">
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Managers</div>
          <div style="font-size:20px;color:var(--white);font-family:'Cormorant Garamond',serif">${fmtNumber(managers)}</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Staff</div>
          <div style="font-size:20px;color:var(--white);font-family:'Cormorant Garamond',serif">${fmtNumber(staff)}</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Active members</div>
          <div style="font-size:20px;color:var(--white);font-family:'Cormorant Garamond',serif">${fmtNumber(activeMembers)}</div>
        </div>
        <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.02)">
          <div style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);margin-bottom:6px">Portfolios</div>
          <div style="font-size:20px;color:var(--white);font-family:'Cormorant Garamond',serif">${fmtNumber(safeArray(portfolios).length)}</div>
        </div>
      </div>
      <div style="font-size:12px;color:var(--dim);line-height:1.65">
        Managers should mostly review exceptions and portfolio health here, while staff should stay inside scoped live desks instead of browsing full retained history every day.
      </div>
    </div>
  `;
}

// ── Composer Compare Mode ────────────────────────────────────────────────
// Renders a table of recent message_normalizations rows where the LLM
// composer ran. Each row shows the guest's latest turn alongside the
// composer's candidate output, plus source / latency / tokens / notes.
// Polls every 30 seconds while the audit view is active. Polling is
// stopped by init() when the operator navigates away from audit.

function renderComposerCompareMode(payload) {
  const host = document.getElementById('audit-composer-body');
  if (!host) return;
  const rows = safeArray(payload?.composerRows);
  if (!rows.length) {
    host.innerHTML = `
      <div style="font-size:12px;color:var(--dim);line-height:1.65">
        No composer rows yet. Compare-mode populates as soon as the LLM composer runs alongside the live drafting path. Each inbound guest message under compare-mode produces one row showing what the composer would have said versus what was actually sent.
      </div>
    `;
    return;
  }

  const tableRows = rows.map((row) => {
    const tokens = (row.composerInputTokens != null && row.composerOutputTokens != null)
      ? `${row.composerInputTokens}→${row.composerOutputTokens}`
      : '—';
    const noteCount = safeArray(row.composerNotes).length;
    const noteBadge = noteCount
      ? `<span style="background:rgba(200,120,50,0.12);color:var(--amber);font-size:10px;padding:2px 8px;border-radius:10px;margin-left:6px">${noteCount} note${noteCount === 1 ? '' : 's'}</span>`
      : '';
    const composerPreview = escapeText(row.composerResponseText || '');
    const composerEllipsis = row.composerTextTruncated ? '…' : '';
    const guestPreview = escapeText(row.latestGuestTurn || '');
    const guestEllipsis = row.guestTurnTruncated ? '…' : '';
    return `
      <tr>
        <td style="padding:10px 12px;font-size:11px;color:var(--dim);font-family:'DM Mono',monospace;white-space:nowrap;vertical-align:top">${escapeText(fmtTimestamp(row.sentAt))}</td>
        <td style="padding:10px 12px;font-size:12px;color:var(--white);vertical-align:top">${escapeText(row.guestName || 'Guest')}</td>
        <td style="padding:10px 12px;font-size:11px;color:var(--dim);font-family:'DM Mono',monospace;vertical-align:top">${escapeText(row.propertyCode || '—')}</td>
        <td style="padding:10px 12px;font-size:11px;color:var(--white);font-family:'DM Mono',monospace;vertical-align:top">${escapeText(row.composerSource || '—')}</td>
        <td style="padding:10px 12px;font-size:11px;color:var(--dim);font-family:'DM Mono',monospace;white-space:nowrap;vertical-align:top">${escapeText(fmtLatency(row.composerLatencyMs))}</td>
        <td style="padding:10px 12px;font-size:11px;color:var(--dim);font-family:'DM Mono',monospace;white-space:nowrap;vertical-align:top">${tokens}</td>
        <td style="padding:10px 12px;font-size:12px;color:rgba(240,235,227,0.78);max-width:360px;vertical-align:top">
          <div style="display:flex;flex-direction:column;gap:6px">
            <div style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:0.08em;font-family:'DM Mono',monospace">Guest</div>
            <div style="line-height:1.5">${guestPreview}${guestEllipsis}</div>
            <div style="font-size:10px;color:var(--amber);text-transform:uppercase;letter-spacing:0.08em;font-family:'DM Mono',monospace;margin-top:4px">Composer ${noteBadge}</div>
            <div style="line-height:1.5">${composerPreview}${composerEllipsis}</div>
          </div>
        </td>
      </tr>
    `;
  }).join('');

  host.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px">
      <div style="font-size:12px;color:var(--dim);line-height:1.65">
        Each row shows the LLM composer's candidate output alongside the guest message that triggered it. Use this to validate composer behavior before promoting it past compare-mode. Polls every 30 seconds.
      </div>
      <div style="border:1px solid var(--border);border-radius:10px;overflow:auto">
        <table style="width:100%;border-collapse:collapse">
          <thead>
            <tr style="background:rgba(255,255,255,0.02)">
              <th style="text-align:left;padding:10px 12px;font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);font-weight:500">Sent</th>
              <th style="text-align:left;padding:10px 12px;font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);font-weight:500">Guest</th>
              <th style="text-align:left;padding:10px 12px;font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);font-weight:500">Property</th>
              <th style="text-align:left;padding:10px 12px;font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);font-weight:500">Source</th>
              <th style="text-align:left;padding:10px 12px;font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);font-weight:500">Latency</th>
              <th style="text-align:left;padding:10px 12px;font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);font-weight:500">Tokens</th>
              <th style="text-align:left;padding:10px 12px;font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.48);font-weight:500">Comparison</th>
            </tr>
          </thead>
          <tbody>${tableRows}</tbody>
        </table>
      </div>
      <div style="font-size:11px;color:rgba(240,235,227,0.48);font-family:'DM Mono',monospace">${rows.length} row${rows.length === 1 ? '' : 's'}</div>
    </div>
  `;
}

async function loadComposerCompareMode() {
  try {
    const payload = await api.messagingComposerEvents(20);
    renderComposerCompareMode(normalizeMessagingEvents(payload));
  } catch (error) {
    console.warn('[Audit] composer compare-mode load failed:', error);
    const host = document.getElementById('audit-composer-body');
    // Only overwrite if there's nothing rendered yet — otherwise a transient
    // poll error would clobber the last successful render.
    if (host && !host.innerHTML.trim()) {
      host.innerHTML = `
        <div style="font-size:12px;color:var(--dim);line-height:1.65">
          Composer compare-mode data is temporarily unavailable.
        </div>
      `;
    }
  }
}

function startComposerPolling() {
  stopComposerPolling();
  composerPollTimer = setInterval(loadComposerCompareMode, 30000);
}

function stopComposerPolling() {
  if (composerPollTimer) {
    clearInterval(composerPollTimer);
    composerPollTimer = null;
  }
}

async function loadAuditWorkspace() {
  const days = state.days || 30;
  try {
    const [summaryPayload, audit, settings, teamPayload, portfolios] = await Promise.all([
      api.summary(),
      api.raw.auditSummary(days),
      api.settings.get().catch(() => ({})),
      api.team.list().catch(() => ({ members: [] })),
      api.portfolios.list().catch(() => []),
    ]);
    const summary = normalizeDashboardSummary(summaryPayload);
    setText('aud-sess', fmtNumber(audit.guest_sessions));
    setText('aud-msgs', fmtNumber(audit.messages_processed));
    setText('aud-pb', fmtNumber(audit.pre_booking_drafts));
    setText('aud-kb', fmtNumber(audit.kb_entries_added));
    renderAuditPosture(summary, audit);
    renderAuditRetention(settings?.retention_policy || {});
    renderCoverage(teamPayload, portfolios);
    updateExportLinks();
  } catch (error) {
    console.warn('[Audit] load failed:', error);
  }
  // Composer compare-mode is loaded independently of the rest of the audit
  // workspace so a failure here doesn't take down the posture/retention/
  // coverage cards, and vice versa.
  loadComposerCompareMode();
}

function wireControls() {
  const daysSel = document.getElementById('audit-days-select');
  if (daysSel) {
    daysSel.addEventListener('change', () => {
      state.days = parseInt(daysSel.value || '30', 10) || 30;
      loadAuditWorkspace();
    });
  }
}

export function init() {
  wireControls();
  window.addEventListener('oyvoda:view-changed', (event) => {
    if (event.detail?.view === 'audit') {
      loadAuditWorkspace();
      startComposerPolling();
    } else {
      // Stop polling when the operator navigates away from audit. Otherwise
      // every operator who ever opened audit would keep polling forever.
      stopComposerPolling();
    }
  });
  const audit = document.getElementById('view-audit');
  if (audit && audit.style.display !== 'none') {
    loadAuditWorkspace();
    startComposerPolling();
  }
}
