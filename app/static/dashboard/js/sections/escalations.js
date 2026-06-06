/**
 * escalations.js — Escalations workspace
 *
 * Live operator queue for human handoff. Uses the existing escalation API and
 * layers in dispatch-vendor suggestions without mixing this workspace with
 * guest-experience vendor referrals.
 */

import api from '../api.js?v=2026-04-23-a';

const state = {
  status: 'open',
  items: [],
  summary: {},
  selectedId: null,
  dispatchVendors: [],
  routingPreviewById: {},
  workOrdersById: {},
  teamMembers: [],
  loading: false,
  lastLoadedAt: null,
};

let pollTimer = null;

function escapeHtml(s) {
  return String(s || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function fmtWhen(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = Math.max(0, (now - d) / 1000);
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

function isoToDatetimeLocal(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const offsetMs = d.getTimezoneOffset() * 60000;
    return new Date(d.getTime() - offsetMs).toISOString().slice(0, 16);
  } catch (_) {
    return '';
  }
}

function priorityClass(priority) {
  const p = String(priority || '').toLowerCase();
  if (p === 'urgent' || p === 'high') return 'badge-red';
  if (p === 'medium') return 'badge-amber';
  return 'badge-dim';
}

function statusClass(status) {
  const s = String(status || '').toLowerCase();
  if (s === 'resolved') return 'badge-green';
  if (s === 'acknowledged') return 'badge-amber';
  return 'badge-red';
}

function humanizeToken(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}

function workflowActionLabel(actionType) {
  const map = {
    vendor_coordination: 'Vendor Coordination',
    guest_eta_update: 'Guest ETA Update',
    owner_internal_update: 'Owner/Internal Update',
    accounting_claim_handoff: 'Accounting/Claims Handoff',
  };
  return map[actionType] || humanizeToken(actionType);
}

function workflowActionSummary(action) {
  const payload = action && action.payload ? action.payload : {};
  if (action.action_type === 'vendor_coordination') {
    const vendors = Array.isArray(payload.recommended_vendors) ? payload.recommended_vendors : [];
    return vendors.length ? `${vendors.length} recommended vendor${vendors.length === 1 ? '' : 's'} ready` : 'Vendor handoff task ready';
  }
  if (action.action_type === 'guest_eta_update') {
    const eta = payload.eta_minutes;
    return eta != null ? `Ready to send ${eta}m ETA update` : 'Waiting on guest phone/vendor ETA';
  }
  if (action.action_type === 'owner_internal_update') {
    const contacts = (((payload.routing_snapshot || {}).available_contacts) || []).length;
    return contacts ? `${contacts} internal contact${contacts === 1 ? '' : 's'} available` : 'Internal visibility update queued';
  }
  if (action.action_type === 'accounting_claim_handoff') {
    return payload.safety_or_claims_risk ? 'Claims/safety review required' : 'Billing/claims follow-up queued';
  }
  return humanizeToken(action.status || 'ready');
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
  }[status] || humanizeToken(status || 'opened');
}

function workOrderTone(status) {
  const value = String(status || '').toLowerCase();
  if (['verified', 'closed'].includes(value)) return 'badge-green';
  if (['failed', 'reassigned', 'cancelled'].includes(value)) return 'badge-red';
  if (['scheduled', 'en_route', 'on_site', 'work_completed', 'awaiting_verification'].includes(value)) return 'badge-amber';
  return 'badge-dim';
}

function normalizeStatusFilter(status) {
  return status === 'open' ? null : (status === 'all' ? 'all' : status);
}

function isOpenStatus(status) {
  return status === 'pending' || status === 'acknowledged';
}

function scoreVendorForEscalation(vendor, text) {
  const slug = String(vendor.category_slug || '').toLowerCase();
  let score = 0;
  if (slug === 'maintenance') score += 10;
  if (slug === 'transportation') score += 4;
  if (/leak|broken|repair|not working|maintenance|plumb|electric|ac\b|hvac|lock|clean/i.test(text) && slug === 'maintenance') score += 10;
  if (/airport|ride|shuttle|transport|pickup|dropoff|car/i.test(text) && slug === 'transportation') score += 8;
  if (vendor.apply_scope === 'property_specific') score += 2;
  score += Math.max(0, 5 - Number(vendor.priority || 99));
  return score;
}

function vendorMatchesProperty(vendor, item) {
  if (!vendor) return false;
  if (!item) return true;
  if (vendor.apply_scope === 'all' || !vendor.apply_scope) return true;
  const ids = Array.isArray(vendor.property_ids) ? vendor.property_ids : [];
  const prop = item.property_code || item.property_name || '';
  return ids.includes(prop);
}

function recommendedDispatchVendors(item) {
  const text = `${item.reason || ''} ${item.summary || ''} ${item.last_message || ''}`.toLowerCase();
  return (state.dispatchVendors || [])
    .filter(v => vendorMatchesProperty(v, item))
    .map(v => ({ ...v, _score: scoreVendorForEscalation(v, text) }))
    .filter(v => v._score > 0)
    .sort((a, b) => b._score - a._score || Number(a.priority || 99) - Number(b.priority || 99))
    .slice(0, 5);
}

async function fetchEscalations() {
  const filter = normalizeStatusFilter(state.status);
  const data = await api.escalations.list(filter);
  const allItems = data.escalations || [];
  if (state.status === 'open') {
    state.items = allItems.filter(item => isOpenStatus(item.status));
  } else {
    state.items = allItems;
  }
  state.summary = data.summary || {};
}

async function ensureDispatchVendors() {
  if ((state.dispatchVendors || []).length > 0) return;
  try {
    const data = await api.vendors.dispatch();
    state.dispatchVendors = data.vendors || [];
  } catch (e) {
    console.warn('[Escalations] dispatch vendors failed:', e);
    state.dispatchVendors = [];
  }
}

async function ensureTeamMembers() {
  if ((state.teamMembers || []).length > 0) return;
  try {
    const data = await api.team.list();
    state.teamMembers = data.members || [];
  } catch (e) {
    console.warn('[Escalations] team list failed:', e);
    state.teamMembers = [];
  }
}

async function ensureRoutingPreview(ticketId) {
  if (!ticketId || state.routingPreviewById[ticketId]) return;
  try {
    state.routingPreviewById[ticketId] = await api.escalations.routingPreview(ticketId);
    renderDetail();
  } catch (e) {
    console.warn('[Escalations] routing preview failed:', e);
    state.routingPreviewById[ticketId] = {
      error: String(e.message || e),
      available_contacts: [],
      skipped_contacts: [],
      coverage_gap: false,
      timeout_minutes: null,
      alert_type: null,
    };
    renderDetail();
  }
}

async function ensureWorkOrders(ticketId) {
  if (!ticketId || state.workOrdersById[ticketId]) return;
  try {
    const payload = await api.escalations.workOrders(ticketId);
    state.workOrdersById[ticketId] = Array.isArray(payload.work_orders) ? payload.work_orders : [];
    renderDetail();
  } catch (e) {
    console.warn('[Escalations] work orders failed:', e);
    state.workOrdersById[ticketId] = [];
  }
}

function renderStats() {
  const summary = state.summary || {};
  const open = Number(summary.open || 0);
  const ack = Number(summary.acknowledged || 0);
  const resolved = Number(summary.resolved || 0);
  const countBadge = document.getElementById('esc-count-badge');
  const openEl = document.getElementById('esc-stat-open');
  const ackEl = document.getElementById('esc-stat-ack');
  const resolvedEl = document.getElementById('esc-stat-resolved');
  if (countBadge) countBadge.textContent = `${open} open`;
  if (openEl) openEl.textContent = open;
  if (ackEl) ackEl.textContent = ack;
  if (resolvedEl) resolvedEl.textContent = resolved;
}

function renderStatusLine(extra) {
  const el = document.getElementById('esc-status-line');
  if (!el) return;
  if (extra) {
    el.textContent = extra;
    el.style.color = 'var(--dim)';
    return;
  }
  const summary = state.summary || {};
  const parts = [
    `${Number(summary.open || 0)} open`,
    `${Number(summary.acknowledged || 0)} acknowledged`,
    `${Number(summary.resolved || 0)} resolved`,
  ];
  if (state.lastLoadedAt) parts.push(`refreshed ${fmtWhen(state.lastLoadedAt)}`);
  el.textContent = parts.join(' · ');
  el.style.color = 'var(--dim)';
}

function renderList() {
  const pane = document.getElementById('esc-list-pane');
  if (!pane) return;
  const items = state.items || [];
  if (items.length === 0) {
    pane.innerHTML = `
      <div class="empty" style="padding:40px 18px">
        <div class="empty-title">No escalations in this view</div>
        <div class="empty-sub">When urgent guest issues need human follow-up, they will appear here.</div>
      </div>`;
    return;
  }
  pane.innerHTML = items.map(item => {
    const selected = item.ticket_id === state.selectedId ? 'esc-row-active' : '';
    const assignee = item.assigned_to ? escapeHtml(item.assigned_to) : 'Unassigned';
    return `
      <div class="esc-row ${selected}" data-ticket-id="${escapeHtml(item.ticket_id)}" style="padding:14px 16px;border-bottom:1px solid var(--border);cursor:pointer;display:flex;flex-direction:column;gap:7px">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span class="badge ${priorityClass(item.priority)}" style="font-size:9px">${escapeHtml(String(item.priority || 'normal').toUpperCase())}</span>
          <span class="badge ${statusClass(item.status)}" style="font-size:9px">${escapeHtml(String(item.status || 'pending').toUpperCase())}</span>
          <span style="flex:1"></span>
          <span style="font-size:10px;color:rgba(240,235,227,0.55);font-family:'DM Mono',monospace">${escapeHtml(fmtWhen(item.created_at))}</span>
        </div>
        <div style="font-size:13px;color:var(--white);font-weight:600;line-height:1.35">${escapeHtml(item.summary || item.reason || 'Escalation')}</div>
        <div style="font-size:11px;color:rgba(240,235,227,0.78)">${escapeHtml(item.property_name || 'Unknown property')} · ${escapeHtml(item.guest_name || 'Guest')}</div>
        <div style="font-size:11px;color:rgba(240,235,227,0.6);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escapeHtml(item.last_message || 'No recent guest message saved')}</div>
        <div style="display:flex;align-items:center;gap:6px;font-size:10px;color:rgba(240,235,227,0.55);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.08em">
          <span>Owner</span>
          <span style="color:var(--ghost)">${assignee}</span>
        </div>
      </div>`;
  }).join('');

  pane.querySelectorAll('.esc-row').forEach(row => {
    row.addEventListener('click', () => {
      state.selectedId = row.getAttribute('data-ticket-id');
      renderList();
      renderDetail();
    });
  });
}

function renderDetail() {
  const pane = document.getElementById('esc-detail-pane');
  if (!pane) return;
  const item = (state.items || []).find(x => x.ticket_id === state.selectedId);
  if (!item) {
    pane.innerHTML = `
      <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(240,235,227,0.5)">Select an escalation</div>
      <div class="card" style="flex:1;background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:18px;display:flex;align-items:center;justify-content:center">
        <div class="empty">
          <div class="empty-title">No escalation selected</div>
          <div class="empty-sub">Choose a ticket on the left to review guest context, assign ownership, and see dispatch vendors.</div>
        </div>
      </div>`;
    return;
  }

  const vendors = recommendedDispatchVendors(item);
  const routing = state.routingPreviewById[item.ticket_id];
  const selectedVendorName = item.vendor_name || '';
  const selectedVendorPhone = item.vendor_phone || '';
  const selectedVendorEta = item.vendor_eta_minutes != null ? String(item.vendor_eta_minutes) : '';
  const selectedVendorStatus = item.vendor_status || 'contacted';
  const guestUpdated = !!item.guest_updated_at;
  const guestUpdateStatus = item.guest_update_status || 'draft_needed';
  const guestUpdateDueAt = item.guest_update_due_at || '';
  const latestOutboundAt = item.latest_outbound_at || '';
  const latestOutboundMessage = item.latest_outbound_message || '';
  const watchers = Array.isArray(item.watchers) ? item.watchers : [];
  const watchersNotified = !!item.watchers_notified_at;
  const guestUpdateNote = item.guest_update_note || '';
  const teamSuggestions = (state.teamMembers || []).slice(0, 8);
  const routingAvailableCount = routing && Array.isArray(routing.available_contacts)
    ? routing.available_contacts.length
    : 0;
  const routingSkippedCount = routing && Array.isArray(routing.skipped_contacts)
    ? routing.skipped_contacts.length
    : 0;
  const dispatchSummary = selectedVendorName
    ? `${selectedVendorName} · ${humanizeToken(selectedVendorStatus)}${selectedVendorEta ? ` · ETA ${selectedVendorEta}m` : ''}`
    : 'No dispatch vendor saved yet';
  const guestUpdateSummary = guestUpdated
    ? `Updated ${fmtWhen(item.guest_updated_at)}`
    : `State: ${humanizeToken(guestUpdateStatus)}`;
  const timeline = [
    item.created_at ? { at: item.created_at, label: 'Escalation created', note: item.summary || item.reason || 'New escalation' } : null,
    item.acknowledged_at ? { at: item.acknowledged_at, label: 'Acknowledged', note: item.assigned_to || 'Owner assigned' } : null,
    item.watchers_notified_at ? { at: item.watchers_notified_at, label: 'Watchers notified', note: watchers.length ? watchers.join(', ') : 'Internal feed update sent' } : null,
    item.guest_updated_at ? { at: item.guest_updated_at, label: 'Guest update recorded', note: guestUpdateNote || humanizeToken(guestUpdateStatus) } : null,
    latestOutboundAt ? { at: latestOutboundAt, label: 'Latest outbound message', note: latestOutboundMessage || 'Guest-facing message sent' } : null,
    item.resolved_at ? { at: item.resolved_at, label: 'Resolved', note: item.resolution_notes || 'Closed' } : null,
  ]
    .filter(Boolean)
    .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
  const routingHtml = routing
    ? (
      routing.error
        ? `<div style="font-size:12px;color:var(--red)">Could not load alert chain: ${escapeHtml(routing.error)}</div>`
        : `
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px">
            <span class="badge ${routing.coverage_gap ? 'badge-red' : 'badge-green'}" style="font-size:9px">${routing.coverage_gap ? 'COVERAGE GAP' : 'COVERED'}</span>
            ${routing.alert_type ? `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(String(routing.alert_type).toUpperCase())}</span>` : ''}
            ${routing.timeout_minutes ? `<span style="font-size:10px;color:rgba(240,235,227,0.55);font-family:'DM Mono',monospace">Ack timeout ${escapeHtml(String(routing.timeout_minutes))}m</span>` : ''}
            <span style="font-size:10px;color:rgba(240,235,227,0.55);font-family:'DM Mono',monospace">${routingAvailableCount} available · ${routingSkippedCount} unavailable</span>
          </div>
          <div style="font-size:11px;color:rgba(240,235,227,0.6);line-height:1.55;margin-bottom:8px">
            This is the live internal routing preview for this escalation type, including who is available now and who will be skipped.
          </div>
          <div style="display:flex;flex-direction:column;gap:8px">
            ${(routing.available_contacts || []).length
              ? routing.available_contacts.map(contact => `
                <div style="padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:rgba(255,255,255,0.03)">
                  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                    <span style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(contact.contact_name || 'Contact')}</span>
                    <span class="badge badge-green" style="font-size:9px">ORDER ${escapeHtml(String(contact.escalation_order || 1))}</span>
                    ${contact.is_primary ? `<span class="badge badge-dim" style="font-size:9px">PRIMARY</span>` : ''}
                  </div>
                  <div style="font-size:11px;color:rgba(240,235,227,0.68);margin-top:4px">${escapeHtml(contact.contact_phone || contact.contact_email || 'No phone or email saved')}</div>
                  <div style="font-size:10px;color:rgba(240,235,227,0.5);margin-top:4px">${escapeHtml(contact.availability_reason || 'Available')}</div>
                </div>`).join('')
              : `<div style="font-size:12px;color:rgba(240,235,227,0.65)">No available escalation contacts for this ticket right now.</div>`}
            ${(routing.skipped_contacts || []).length
              ? `<div style="padding-top:4px">
                   <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px">Skipped / unavailable</div>
                   <div style="display:flex;flex-direction:column;gap:6px">
                     ${routing.skipped_contacts.map(contact => `
                       <div style="font-size:11px;color:rgba(240,235,227,0.58)">
                         ${escapeHtml(contact.contact_name || 'Contact')} · ${escapeHtml(contact.availability_reason || 'Unavailable')}
                       </div>`).join('')}
                   </div>
                 </div>`
              : ''}
          </div>`
    )
    : `<div style="font-size:12px;color:rgba(240,235,227,0.6)">Loading alert chain...</div>`;
  const workflow = item.workflow || {};
  const workOrders = Array.isArray(state.workOrdersById[item.ticket_id]) ? state.workOrdersById[item.ticket_id] : [];
  const workflowActions = Array.isArray(workflow.actions) ? workflow.actions : [];
  const workflowDetectors = workflow.detectors || {};
  const detectorBadges = [
    workflowDetectors.primary_domain ? { label: humanizeToken(workflowDetectors.primary_domain), tone: 'badge-dim' } : null,
    workflowDetectors.vendor_dispatch_needed ? { label: 'Vendor Needed', tone: 'badge-amber' } : null,
    workflowDetectors.guest_eta_ready ? { label: 'ETA Ready', tone: 'badge-green' } : null,
    workflowDetectors.owner_internal_update_needed ? { label: 'Internal Update', tone: 'badge-dim' } : null,
    workflowDetectors.accounting_claim_handoff_needed ? { label: 'Claims Handoff', tone: 'badge-red' } : null,
  ].filter(Boolean);
  const workflowActionHtml = workflowActions.length
    ? workflowActions.map(action => `
        <div style="padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:rgba(255,255,255,0.03);display:flex;flex-direction:column;gap:6px">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <span style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(workflowActionLabel(action.action_type))}</span>
            <span class="badge ${action.status === 'completed' ? 'badge-green' : (action.status === 'in_progress' ? 'badge-amber' : (action.status === 'failed' ? 'badge-red' : 'badge-dim'))}" style="font-size:9px">${escapeHtml(humanizeToken(action.status || 'ready'))}</span>
            ${action.priority ? `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(String(action.priority).toUpperCase())}</span>` : ''}
          </div>
          <div style="font-size:11px;color:rgba(240,235,227,0.65);line-height:1.5">${escapeHtml(workflowActionSummary(action))}</div>
          ${action.result && action.result.message ? `<div style="font-size:11px;color:rgba(240,235,227,0.5);line-height:1.45">${escapeHtml(action.result.message)}</div>` : ''}
          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">
            <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace">
              ${action.due_at ? `Due ${escapeHtml(fmtAbsolute(action.due_at))}` : 'No due time'}
            </div>
            ${(action.status === 'ready' || action.status === 'failed' || action.status === 'blocked')
              ? `<button class="btn btn-sm esc-action-execute" data-action-type="${escapeHtml(action.action_type)}">Run Action</button>`
              : ''}
          </div>
        </div>
      `).join('')
    : '<div style="font-size:12px;color:rgba(240,235,227,0.6)">No workflow actions are queued for this escalation yet.</div>';
  const vendorHtml = vendors.length
    ? vendors.map(v => `
        <div style="padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:rgba(255,255,255,0.03);display:flex;flex-direction:column;gap:4px">
          <div style="display:flex;align-items:center;gap:8px">
            <span style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(v.name || 'Vendor')}</span>
            <span class="badge badge-dim" style="font-size:9px">${escapeHtml(v.category_slug || 'vendor')}</span>
          </div>
          <div style="font-size:11px;color:rgba(240,235,227,0.7)">${escapeHtml(v.phone || 'No phone saved')}${v.website ? ` · ${escapeHtml(v.website)}` : ''}</div>
          ${v.internal_notes ? `<div style="font-size:11px;color:rgba(240,235,227,0.55);line-height:1.45">${escapeHtml(v.internal_notes)}</div>` : ''}
        </div>`).join('')
    : `<div style="font-size:12px;color:rgba(240,235,227,0.65);line-height:1.6">
         No dispatch vendors are clearly matched yet for this escalation. Guest-experience vendors stay separate from this workspace unless they become an urgent operational issue.
       </div>`;

  const ownerValue = escapeHtml(item.assigned_to || '');
  const resolutionNotes = escapeHtml(item.resolution_notes || '');
  const openSessionButton = item.session_id
    ? `<button class="btn btn-sm" id="esc-open-session-btn">Open Guest Sessions</button>`
    : '';
  const actionButtons = item.status === 'resolved'
    ? `<div style="font-size:11px;color:rgba(240,235,227,0.55)">Resolved ${escapeHtml(fmtWhen(item.resolved_at))}</div>`
    : `
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn" id="esc-assign-btn">Acknowledge / Assign</button>
        <button class="btn btn-primary" id="esc-resolve-btn">Resolve</button>
        ${openSessionButton}
      </div>`;

  pane.innerHTML = `
    <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap">
      <div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px">
          <span class="badge ${priorityClass(item.priority)}" style="font-size:9px">${escapeHtml(String(item.priority || 'normal').toUpperCase())}</span>
          <span class="badge ${statusClass(item.status)}" style="font-size:9px">${escapeHtml(String(item.status || 'pending').toUpperCase())}</span>
          <span class="badge badge-dim" style="font-size:9px">${escapeHtml(String(item.reason || 'general').replace(/_/g, ' '))}</span>
          <span style="font-family:'DM Mono',monospace;font-size:10px;color:rgba(240,235,227,0.55)">${escapeHtml(fmtWhen(item.created_at))}</span>
        </div>
        <div style="font-size:18px;color:var(--white);font-weight:600;line-height:1.3">${escapeHtml(item.summary || 'Escalation')}</div>
        <div style="font-size:12px;color:rgba(240,235,227,0.75);margin-top:6px">${escapeHtml(item.property_name || 'Unknown property')} · ${escapeHtml(item.guest_name || 'Guest')}</div>
        ${(item.guest_phone || item.guest_email) ? `<div style="font-size:11px;color:rgba(240,235,227,0.55);font-family:'DM Mono',monospace;margin-top:4px">${escapeHtml(item.guest_phone || '')}${item.guest_phone && item.guest_email ? ' · ' : ''}${escapeHtml(item.guest_email || '')}</div>` : ''}
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:10px">
          <span class="badge badge-dim" style="font-size:9px">Ticket ${escapeHtml(item.ticket_id ? String(item.ticket_id).slice(0, 8) : '—')}</span>
          ${item.session_id ? '<span class="badge badge-green" style="font-size:9px">Linked guest session</span>' : '<span class="badge badge-dim" style="font-size:9px">No guest session linked yet</span>'}
          ${watchers.length ? `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(String(watchers.length))} watcher${watchers.length === 1 ? '' : 's'}</span>` : ''}
        </div>
      </div>
      <div style="min-width:220px;max-width:280px;display:flex;flex-direction:column;gap:8px">
        <div style="font-size:10px;color:rgba(240,235,227,0.5);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em">Primary owner</div>
        <input class="form-input" id="esc-assignee-input" value="${ownerValue}" placeholder="Name, role, or on-call owner" />
        <div style="font-size:11px;color:rgba(240,235,227,0.5);line-height:1.5">Primary owner drives the ticket. Watchers, alert-chain context, and dispatch coordination stay attached in the detail view below.</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px">
      <div class="card" style="padding:12px;background:rgba(255,255,255,0.02);border:1px solid var(--border)">
        <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px">Current state</div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span class="badge ${statusClass(item.status)}" style="font-size:9px">${escapeHtml(humanizeToken(item.status || 'pending'))}</span>
          <span class="badge ${priorityClass(item.priority)}" style="font-size:9px">${escapeHtml(humanizeToken(item.priority || 'normal'))}</span>
          ${workflow.stage ? `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(humanizeToken(workflow.stage))}</span>` : ''}
        </div>
        <div style="font-size:11px;color:rgba(240,235,227,0.65);margin-top:8px;line-height:1.5">${item.status === 'resolved' ? 'This issue is closed.' : (item.status === 'acknowledged' ? 'Human owner is actively working it.' : 'Waiting for human acknowledgement.')}</div>
      </div>
      <div class="card" style="padding:12px;background:rgba(255,255,255,0.02);border:1px solid var(--border)">
        <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px">Owner + watchers</div>
        <div style="font-size:13px;color:var(--white);font-weight:600">${escapeHtml(item.assigned_to || 'Unassigned')}</div>
        <div style="font-size:11px;color:rgba(240,235,227,0.65);margin-top:8px;line-height:1.5">
          ${watchers.length ? `${watchers.length} watcher${watchers.length === 1 ? '' : 's'}${watchersNotified ? ` · last notified ${escapeHtml(fmtWhen(item.watchers_notified_at))}` : ' · not notified yet'}` : 'No watchers added yet'}
        </div>
      </div>
      <div class="card" style="padding:12px;background:rgba(255,255,255,0.02);border:1px solid var(--border)">
        <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px">Alert routing</div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span class="badge ${(routing && !routing.error && !routing.coverage_gap) ? 'badge-green' : 'badge-red'}" style="font-size:9px">${routing ? ((routing.error || routing.coverage_gap) ? 'Needs attention' : 'Covered') : 'Loading'}</span>
        </div>
        <div style="font-size:11px;color:rgba(240,235,227,0.65);margin-top:8px;line-height:1.5">
          ${routing ? (routing.error ? escapeHtml(routing.error) : `${routingAvailableCount} available contact${routingAvailableCount === 1 ? '' : 's'}${routingSkippedCount ? ` · ${routingSkippedCount} unavailable` : ''}`) : 'Preparing routing preview…'}
        </div>
      </div>
      <div class="card" style="padding:12px;background:rgba(255,255,255,0.02);border:1px solid var(--border)">
        <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px">Dispatch + guest update</div>
        <div style="font-size:13px;color:var(--white);font-weight:600">${escapeHtml(dispatchSummary)}</div>
        <div style="font-size:11px;color:rgba(240,235,227,0.65);margin-top:8px;line-height:1.5">${escapeHtml(guestUpdateSummary)}</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1.2fr 0.8fr;gap:14px;align-items:start">
      <div style="display:flex;flex-direction:column;gap:14px">
        <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:14px">
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Situation</div>
          <div style="font-size:13px;color:var(--white);line-height:1.65">${escapeHtml(item.last_message || 'No guest message context saved on this escalation.')}</div>
          <div style="margin-top:10px;font-size:11px;color:rgba(240,235,227,0.6)">Reason: ${escapeHtml(item.reason || 'other')}</div>
        </div>

        <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:14px">
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Response plan</div>
          <textarea class="form-input" id="esc-resolution-notes" style="min-height:120px;resize:vertical">${resolutionNotes}</textarea>
          <div style="margin-top:10px">${actionButtons}</div>
        </div>
        <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:14px">
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Coordination</div>
          <div style="display:flex;flex-direction:column;gap:10px">
            <div>
              <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px">Watchers / keep in loop</div>
              <div id="esc-watchers-list" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">
                ${watchers.length ? watchers.map(w => `<span class="badge badge-dim" style="font-size:10px">${escapeHtml(w)}</span>`).join('') : '<span style="font-size:12px;color:rgba(240,235,227,0.55)">No watchers added yet</span>'}
              </div>
              <div style="display:flex;gap:8px;flex-wrap:wrap">
                <input class="form-input" id="esc-watchers-input" value="${escapeHtml(watchers.join(', '))}" placeholder="Comma-separated names or emails" />
                <button class="btn btn-sm" id="esc-save-coordination-btn">Save Coordination</button>
              </div>
              <label style="display:flex;align-items:center;gap:8px;font-size:12px;color:rgba(240,235,227,0.72);margin-top:8px">
                <input type="checkbox" id="esc-notify-watchers" />
                Notify watchers in the internal feed now
              </label>
              <div style="margin-top:6px;font-size:11px;color:rgba(240,235,227,0.5)">
                ${watchersNotified ? `Watchers last notified ${escapeHtml(fmtWhen(item.watchers_notified_at))}` : 'Watchers have not been notified yet'}
              </div>
              <div style="margin-top:6px;font-size:11px;color:rgba(240,235,227,0.55);line-height:1.55">
                Use watchers for people who need visibility but are not the primary owner. The checkbox below sends an internal notification into their feed.
              </div>
              ${teamSuggestions.length ? `<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:6px">
                ${teamSuggestions.map(member => `
                  <button class="btn btn-sm esc-team-suggestion" data-watch-label="${escapeHtml(member.name || member.email || '')}" style="padding:4px 8px">
                    ${escapeHtml(member.name || member.email || 'Team')}
                  </button>`).join('')}
              </div>` : ''}
            </div>
            <div>
              <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px">Guest update state</div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
                <select class="form-select" id="esc-guest-update-status">
                  ${[
                    ['draft_needed', 'Draft needed'],
                    ['ready_to_send', 'Draft ready to send'],
                    ['sent_to_guest', 'Sent to guest'],
                    ['awaiting_guest_reply', 'Awaiting guest reply'],
                    ['vendor_eta_shared', 'Vendor ETA shared'],
                    ['resolved_with_guest', 'Resolved with guest'],
                  ].map(([value, label]) => `
                    <option value="${value}" ${guestUpdateStatus === value ? 'selected' : ''}>${label}</option>
                  `).join('')}
                </select>
                <input class="form-input" id="esc-guest-update-due-at" type="datetime-local" value="${escapeHtml(isoToDatetimeLocal(guestUpdateDueAt))}" />
              </div>
              <div style="margin-top:8px;font-size:11px;color:rgba(240,235,227,0.5)">
                ${guestUpdateDueAt ? `Next guest update due ${escapeHtml(fmtAbsolute(guestUpdateDueAt))}` : 'No next-update deadline recorded'}
              </div>
            </div>
            <div>
              <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px">Guest update note</div>
              <textarea class="form-input" id="esc-guest-update-note" style="min-height:100px;resize:vertical" placeholder="What did we tell the guest, and what are we waiting on?">${escapeHtml(guestUpdateNote)}</textarea>
              <div style="margin-top:8px;font-size:11px;color:rgba(240,235,227,0.5)">
                ${guestUpdated ? `Last guest update recorded ${escapeHtml(fmtWhen(item.guest_updated_at))}` : 'No guest update note recorded yet'}
              </div>
            </div>
            <div>
              <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px">Latest outbound guest message</div>
              <div style="padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:rgba(255,255,255,0.03)">
                <div style="font-size:11px;color:rgba(240,235,227,0.5);margin-bottom:6px">
                  ${latestOutboundAt ? `Last outbound sent ${escapeHtml(fmtWhen(latestOutboundAt))}` : 'No outbound guest message recorded in this linked session yet'}
                </div>
                <div style="font-size:12px;color:rgba(240,235,227,0.78);line-height:1.55">
                  ${escapeHtml(latestOutboundMessage || 'When a guest-facing message is sent from the linked session, it will show up here for escalation context.')}
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:14px">
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Timeline</div>
          <div style="display:flex;flex-direction:column;gap:10px">
            ${timeline.length ? timeline.map(entry => `
              <div style="display:flex;gap:10px;align-items:flex-start">
                <div style="width:8px;height:8px;border-radius:50%;background:var(--amber);margin-top:6px;flex-shrink:0"></div>
                <div style="flex:1">
                  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                    <div style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(entry.label)}</div>
                    <div style="font-size:10px;color:rgba(240,235,227,0.5);font-family:'DM Mono',monospace">${escapeHtml(fmtAbsolute(entry.at))}</div>
                  </div>
                  <div style="font-size:11px;color:rgba(240,235,227,0.65);line-height:1.55;margin-top:4px">${escapeHtml(entry.note || '')}</div>
                </div>
              </div>
            `).join('') : '<div style="font-size:12px;color:rgba(240,235,227,0.6)">Timeline activity will appear as this ticket moves through acknowledgement, dispatch, guest updates, and resolution.</div>'}
          </div>
        </div>
      </div>

      <div style="display:flex;flex-direction:column;gap:14px">
        <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:14px">
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Alert routing visibility</div>
          <div style="display:flex;flex-direction:column;gap:10px">${routingHtml}</div>
        </div>
        <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:14px">
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Workflow actions</div>
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:10px">
            ${detectorBadges.length ? detectorBadges.map(badge => `<span class="badge ${badge.tone}" style="font-size:9px">${escapeHtml(badge.label)}</span>`).join('') : '<span style="font-size:11px;color:rgba(240,235,227,0.5)">No detector signals yet</span>'}
          </div>
          <div style="display:flex;flex-direction:column;gap:10px">${workflowActionHtml}</div>
        </div>
        <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:14px">
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Work orders</div>
          ${workOrders.length ? `
            <div style="display:flex;flex-direction:column;gap:10px">
              ${workOrders.map(order => `
                <div style="padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:rgba(255,255,255,0.03);display:flex;flex-direction:column;gap:6px">
                  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                    <span style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(order.summary || order.issue_category || 'Work order')}</span>
                    <span class="badge ${workOrderTone(order.status)}" style="font-size:9px">${escapeHtml(workOrderStatusLabel(order.status))}</span>
                    ${order.dispatch_state ? `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(humanizeToken(order.dispatch_state))}</span>` : ''}
                  </div>
                  <div style="font-size:11px;color:rgba(240,235,227,0.68);line-height:1.55">
                    ${escapeHtml(order.vendor_name || 'Vendor pending')}
                    ${order.vendor_phone ? ` · ${escapeHtml(order.vendor_phone)}` : ''}
                    ${order.eta_minutes != null ? ` · ETA ${escapeHtml(String(order.eta_minutes))}m` : ''}
                  </div>
                  <div style="display:flex;gap:6px;flex-wrap:wrap;font-size:10px;color:rgba(240,235,227,0.5);font-family:'DM Mono',monospace">
                    <span>Verification ${escapeHtml(humanizeToken(order.verification_state || 'pending'))}</span>
                    <span>Invoice ${escapeHtml(humanizeToken(order.invoice_state || 'not_received'))}</span>
                    ${order.asset_id ? '<span>Asset linked</span>' : ''}
                  </div>
                  ${order.eta_visibility_mode === 'live_tracking' && (order.tracking_url || order.last_known_distance_text) ? `
                    <div style="font-size:11px;color:rgba(240,235,227,0.62);line-height:1.5">
                      ${order.last_known_distance_text ? `Tracking: ${escapeHtml(order.last_known_distance_text)}` : 'Live tracking available'}
                      ${order.tracking_url ? ` · <a href="${escapeHtml(order.tracking_url)}" target="_blank" rel="noreferrer" style="color:var(--amber)">open tracking</a>` : ''}
                    </div>
                  ` : ''}
                </div>
              `).join('')}
            </div>
          ` : '<div style="font-size:12px;color:rgba(240,235,227,0.6)">No work orders tied to this escalation yet.</div>'}
        </div>
        <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:14px">
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Dispatch + vendor handoff</div>
          <div style="font-size:11px;color:rgba(240,235,227,0.6);line-height:1.55;margin-bottom:10px">
            Pick a dispatch vendor, record ETA, and capture whether the guest has been updated so the ticket does not drift between inboxes, texts, and phone calls.
          </div>
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px">
            <span class="badge ${selectedVendorName ? 'badge-amber' : 'badge-dim'}" style="font-size:9px">${selectedVendorName ? 'Vendor attached' : 'No vendor attached'}</span>
            <span class="badge ${guestUpdated ? 'badge-green' : 'badge-dim'}" style="font-size:9px">${guestUpdated ? 'Guest updated' : 'Guest not updated'}</span>
            <span class="badge badge-dim" style="font-size:9px">${escapeHtml(humanizeToken(selectedVendorStatus || 'contacted'))}</span>
          </div>
          <div style="display:flex;flex-direction:column;gap:10px">${vendorHtml}</div>
          <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border);display:flex;flex-direction:column;gap:10px">
            <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em">Vendor dispatch state</div>
            <select class="form-select" id="esc-vendor-select">
              <option value="">Select dispatch vendor</option>
              ${vendors.map(v => `
                <option value="${escapeHtml(v.name || '')}" data-phone="${escapeHtml(v.phone || '')}" ${selectedVendorName === (v.name || '') ? 'selected' : ''}>
                  ${escapeHtml(v.name || 'Vendor')} · ${escapeHtml(v.category_slug || 'vendor')}
                </option>`).join('')}
            </select>
            <input class="form-input" id="esc-vendor-name" value="${escapeHtml(selectedVendorName)}" placeholder="Vendor name" />
            <input class="form-input" id="esc-vendor-phone" value="${escapeHtml(selectedVendorPhone)}" placeholder="Vendor phone" />
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
              <input class="form-input" id="esc-vendor-eta" value="${escapeHtml(selectedVendorEta)}" placeholder="ETA minutes" inputmode="numeric" />
              <select class="form-select" id="esc-vendor-status">
                ${['recommended','contacted','dispatched','en_route','on_site','completed'].map(status => `
                  <option value="${status}" ${selectedVendorStatus === status ? 'selected' : ''}>${status.replace('_', ' ')}</option>
                `).join('')}
              </select>
            </div>
            <label style="display:flex;align-items:center;gap:8px;font-size:12px;color:rgba(240,235,227,0.72)">
              <input type="checkbox" id="esc-guest-updated" ${guestUpdated ? 'checked' : ''} />
              Guest has been updated
            </label>
            <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">
              <div style="font-size:11px;color:rgba(240,235,227,0.5)">${guestUpdated ? `Guest updated ${escapeHtml(fmtWhen(item.guest_updated_at))}` : 'Guest update not recorded yet'}</div>
              <button class="btn btn-sm" id="esc-save-dispatch-btn">Save Dispatch State</button>
            </div>
          </div>
        </div>
        <div class="card" style="background:rgba(255,255,255,0.02);border:1px solid var(--border);padding:14px">
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Escalation rules</div>
          <div style="font-size:12px;color:rgba(240,235,227,0.7);line-height:1.6">
            This workspace is for urgent human follow-up and dispatch coordination. Guest-experience vendors like crib rentals, beach chairs, chefs, or charters stay separate unless they become an urgent exception.
          </div>
        </div>
      </div>
    </div>`;

  const assignBtn = document.getElementById('esc-assign-btn');
  const resolveBtn = document.getElementById('esc-resolve-btn');
  const openSessionBtn = document.getElementById('esc-open-session-btn');
  const saveDispatchBtn = document.getElementById('esc-save-dispatch-btn');
  const vendorSelect = document.getElementById('esc-vendor-select');
  const saveCoordinationBtn = document.getElementById('esc-save-coordination-btn');
  if (assignBtn) assignBtn.addEventListener('click', handleAssign);
  if (resolveBtn) resolveBtn.addEventListener('click', handleResolve);
  if (openSessionBtn) {
    openSessionBtn.addEventListener('click', () => {
      if (typeof window.oyvodaOpenSession === 'function' && item.session_id) {
        window.oyvodaOpenSession(item.session_id, {
          ticket_id: item.ticket_id,
          session_id: item.session_id,
          summary: item.summary,
          reason: item.reason,
          priority: item.priority,
          status: item.status,
          watchers: Array.isArray(item.watchers) ? item.watchers : [],
          guest_update_status: item.guest_update_status,
          guest_update_due_at: item.guest_update_due_at,
          guest_update_note: item.guest_update_note,
        });
      } else if (typeof window.navigate === 'function') {
        window.navigate('instay');
      }
    });
  }
  if (vendorSelect) {
    vendorSelect.addEventListener('change', () => {
      const option = vendorSelect.options[vendorSelect.selectedIndex];
      const name = option ? option.value : '';
      const phone = option ? option.getAttribute('data-phone') || '' : '';
      const nameInput = document.getElementById('esc-vendor-name');
      const phoneInput = document.getElementById('esc-vendor-phone');
      if (nameInput) nameInput.value = name;
      if (phoneInput && !phoneInput.value) phoneInput.value = phone;
    });
  }
  if (saveDispatchBtn) saveDispatchBtn.addEventListener('click', handleSaveDispatchVendor);
  if (saveCoordinationBtn) saveCoordinationBtn.addEventListener('click', handleSaveCoordination);
  pane.querySelectorAll('.esc-team-suggestion').forEach(btn => {
    btn.addEventListener('click', () => {
      const label = btn.getAttribute('data-watch-label') || '';
      const input = document.getElementById('esc-watchers-input');
      if (!input || !label) return;
      const existing = input.value.split(',').map(v => v.trim()).filter(Boolean);
      if (!existing.includes(label)) existing.push(label);
      input.value = existing.join(', ');
    });
  });
  pane.querySelectorAll('.esc-action-execute').forEach(btn => {
    btn.addEventListener('click', () => handleExecuteWorkflowAction(btn.getAttribute('data-action-type') || ''));
  });
  ensureRoutingPreview(item.ticket_id);
  ensureWorkOrders(item.ticket_id);
}

async function handleAssign() {
  const item = (state.items || []).find(x => x.ticket_id === state.selectedId);
  if (!item) return;
  const input = document.getElementById('esc-assignee-input');
  const assignedTo = (input && input.value || '').trim();
  if (!assignedTo) {
    flash('Add a primary owner before acknowledging.', 'err');
    return;
  }
  try {
    await api.escalations.assign(item.ticket_id, assignedTo);
    flash('Escalation acknowledged.', 'ok');
    await loadEscalations({ force: true });
  } catch (e) {
    flash(`Assign failed: ${e.message || e}`, 'err');
  }
}

async function handleResolve() {
  const item = (state.items || []).find(x => x.ticket_id === state.selectedId);
  if (!item) return;
  const notes = (document.getElementById('esc-resolution-notes') || {}).value || '';
  try {
    await api.escalations.resolve(item.ticket_id, notes.trim());
    flash('Escalation resolved.', 'ok');
    await loadEscalations({ force: true });
  } catch (e) {
    flash(`Resolve failed: ${e.message || e}`, 'err');
  }
}

async function handleSaveDispatchVendor() {
  const item = (state.items || []).find(x => x.ticket_id === state.selectedId);
  if (!item) return;
  const vendorName = ((document.getElementById('esc-vendor-name') || {}).value || '').trim();
  const vendorPhone = ((document.getElementById('esc-vendor-phone') || {}).value || '').trim();
  const vendorEtaRaw = ((document.getElementById('esc-vendor-eta') || {}).value || '').trim();
  const vendorStatus = ((document.getElementById('esc-vendor-status') || {}).value || 'contacted').trim();
  const guestUpdated = !!((document.getElementById('esc-guest-updated') || {}).checked);
  const vendorEta = vendorEtaRaw ? Number(vendorEtaRaw) : null;
  if (vendorEtaRaw && Number.isNaN(vendorEta)) {
    flash('ETA must be a number.', 'err');
    return;
  }
  if (!vendorName) {
    flash('Choose or enter a dispatch vendor first.', 'err');
    return;
  }
  try {
    await api.escalations.dispatchVendor(item.ticket_id, {
      vendor_name: vendorName,
      vendor_phone: vendorPhone,
      vendor_eta_minutes: vendorEta,
      vendor_status: vendorStatus,
      eta_visibility_mode: 'estimated',
      guest_updated: guestUpdated,
    });
    flash('Dispatch state saved.', 'ok');
    await loadEscalations({ force: true });
  } catch (e) {
    flash(`Dispatch save failed: ${e.message || e}`, 'err');
  }
}

async function handleSaveCoordination() {
  const item = (state.items || []).find(x => x.ticket_id === state.selectedId);
  if (!item) return;
  const watcherInput = ((document.getElementById('esc-watchers-input') || {}).value || '').trim();
  const guestUpdateNote = ((document.getElementById('esc-guest-update-note') || {}).value || '').trim();
  const guestUpdateStatus = ((document.getElementById('esc-guest-update-status') || {}).value || 'draft_needed').trim();
  const guestUpdateDueAt = ((document.getElementById('esc-guest-update-due-at') || {}).value || '').trim();
  const notifyWatchers = !!((document.getElementById('esc-notify-watchers') || {}).checked);
  const watchers = watcherInput
    ? watcherInput.split(',').map(v => v.trim()).filter(Boolean)
    : [];
  if (notifyWatchers && !watchers.length) {
    flash('Add at least one watcher before sending an internal notification.', 'err');
    return;
  }
  try {
    await api.escalations.coordination(item.ticket_id, {
      watchers,
      guest_update_note: guestUpdateNote,
      guest_update_status: guestUpdateStatus,
      guest_update_due_at: guestUpdateDueAt ? new Date(guestUpdateDueAt).toISOString() : null,
      mark_guest_updated: !!guestUpdateNote,
      notify_watchers: notifyWatchers,
    });
    flash(notifyWatchers ? 'Coordination saved and watchers notified.' : 'Coordination saved.', 'ok');
    await loadEscalations({ force: true });
  } catch (e) {
    flash(`Coordination save failed: ${e.message || e}`, 'err');
  }
}

async function handleExecuteWorkflowAction(actionType) {
  const item = (state.items || []).find(x => x.ticket_id === state.selectedId);
  if (!item || !actionType) return;
  try {
    const result = await api.escalations.executeAction(item.ticket_id, actionType);
    flash(result.message || `${workflowActionLabel(actionType)} executed.`, 'ok');
    await loadEscalations({ force: true });
  } catch (e) {
    flash(`${workflowActionLabel(actionType)} failed: ${e.message || e}`, 'err');
  }
}

function flash(text, kind) {
  const host = document.getElementById('esc-detail-pane');
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

async function loadEscalations(opts = {}) {
  if (state.loading && !opts.force) return;
  state.loading = true;
  const previousItems = Array.isArray(state.items) ? [...state.items] : [];
  const previousSummary = state.summary ? { ...state.summary } : {};
  try {
    await Promise.all([fetchEscalations(), ensureDispatchVendors(), ensureTeamMembers()]);
    state.lastLoadedAt = new Date().toISOString();
    renderStats();
    renderStatusLine();
    if (state.selectedId && !state.items.some(x => x.ticket_id === state.selectedId)) {
      state.selectedId = state.items[0] ? state.items[0].ticket_id : null;
    }
    if (!state.selectedId && state.items[0]) state.selectedId = state.items[0].ticket_id;
    renderList();
    renderDetail();
  } catch (e) {
    console.warn('[Escalations] load failed', e);
    renderStatusLine(`Could not refresh escalations · ${String(e.message || e)}`);
    const pane = document.getElementById('esc-list-pane');
    if (pane) {
      const detail = String(e.message || e || 'Unknown error');
      pane.innerHTML = `
        <div class="empty" style="padding:40px 18px">
          <div class="empty-title">Could not load escalations</div>
          <div class="empty-sub" style="max-width:440px;margin:0 auto 14px">${escapeHtml(detail)}</div>
          <button class="btn btn-sm" id="esc-retry-load-btn">Retry</button>
        </div>`;
      const retryBtn = document.getElementById('esc-retry-load-btn');
      if (retryBtn) retryBtn.addEventListener('click', () => loadEscalations({ force: true }));
    }
    if (previousItems.length) {
      state.items = previousItems;
      state.summary = previousSummary;
      renderStats();
      renderStatusLine();
      renderDetail();
    }
  } finally {
    state.loading = false;
  }
}

function wireStatusTabs() {
  document.querySelectorAll('#esc-status-tabs .tab').forEach(btn => {
    btn.addEventListener('click', () => {
      setStatusFilter(btn.getAttribute('data-esc-status') || 'open', btn);
    });
  });
}

function setStatusFilter(status, sourceBtn) {
  document.querySelectorAll('#esc-status-tabs .tab').forEach(t => t.classList.remove('active'));
  const targetBtn = sourceBtn || document.querySelector(`#esc-status-tabs .tab[data-esc-status="${status}"]`);
  if (targetBtn) targetBtn.classList.add('active');
  state.status = status || 'open';
  state.selectedId = null;
  renderStatusLine(`Refreshing ${state.status === 'all' ? 'all escalations' : state.status + ' escalations'}…`);
  loadEscalations({ force: true });
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(() => {
    if (document.hidden) return;
    loadEscalations();
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
    if (view === 'escalations') {
      loadEscalations({ force: true });
      startPolling();
    } else {
      stopPolling();
    }
  });
}

function inlineStyles() {
  if (document.getElementById('esc-inline-css')) return;
  const s = document.createElement('style');
  s.id = 'esc-inline-css';
  s.textContent = `
    #esc-list-pane .esc-row:hover {
      background: rgba(255,255,255,0.04);
    }
    #esc-list-pane .esc-row.esc-row-active {
      background: rgba(239,68,68,0.08);
      border-left: 3px solid var(--red);
      padding-left: 13px !important;
    }
  `;
  document.head.appendChild(s);
}

function isEscalationsView() {
  const el = document.getElementById('view-escalations');
  return el && el.style.display !== 'none';
}

export function init() {
  inlineStyles();
  wireStatusTabs();
  wireViewChange();
  if (isEscalationsView()) {
    loadEscalations({ force: true });
    startPolling();
  }
  renderStatusLine('Escalation queue wakes up when this view is active.');
}

window.reloadEscalations = () => loadEscalations({ force: true });
window.setEscalationStatusFilter = (status, sourceBtn) => setStatusFilter(status, sourceBtn || null);
