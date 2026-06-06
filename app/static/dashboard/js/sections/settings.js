import api from '../api.js?v=2026-04-29-c';
import { normalizeSettings, renderInlineError } from '../adapters.js?v=2026-04-29-c';
import { escapeHtml } from '../ui.js?v=2026-04-21-a';

const state = {
  settings: null,
  loaded: false,
  alertRouting: null,
  providerCatalog: [],
  configuredIntegrations: [],
};

const TOGGLE_MAP = {
  'tog-emerg': 'notifyEmergency',
  'tog-maint': 'notifyMaintenance',
  'tog-pb': 'notifyPrebooking',
  'tog-gaps': 'notifyKbGaps',
  'tog-weekly': 'notifyWeeklyAnalytics',
};

let settingsSaveTimer = null;

function setStatus(text, kind = 'dim') {
  const el = document.getElementById('settings-save-status');
  if (!el) return;
  el.textContent = text;
  el.style.color =
    kind === 'ok' ? 'var(--green)' :
    kind === 'err' ? 'var(--red)' :
    kind === 'warn' ? 'var(--amber)' :
    'var(--dim)';
}

function renderPmsList(account) {
  const list = document.getElementById('settings-pms-list');
  if (!list) return;
  const provider = account?.pms || 'escapia';
  const propertyCount = Number(account?.propertyCount || 0);
  const configuredByProvider = new Map((state.configuredIntegrations || []).map((item) => [item.provider, item]));
  const preferredProviders = ['escapia', 'guesty', 'hostaway', 'track', 'ownerrez', 'streamline'];
  const providers = (state.providerCatalog || []).filter((item) => preferredProviders.includes(item.provider));
  if (!providers.length) {
    list.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;padding:12px;background:rgba(255,255,255,0.02);border:1px solid var(--border);border-radius:8px;gap:12px">
        <div>
          <div style="font-size:13px;font-weight:500;color:var(--white)">${provider.toUpperCase()} connection</div>
          <div style="font-size:11px;color:var(--dim)">${propertyCount} propert${propertyCount === 1 ? 'y' : 'ies'} currently linked</div>
        </div>
        <a href="/app/connect-gmail" class="btn btn-sm" style="text-decoration:none">Manage inbox</a>
      </div>
    `;
    return;
  }
  list.innerHTML = providers.map((item) => {
    const configured = configuredByProvider.get(item.provider);
    const fieldCount = (item.required_fields || []).length + (item.optional_fields || []).length;
    const readiness = String(item.readiness || 'planned').replace(/_/g, ' ');
    const transport = String(item.message_transport || 'none').replace(/_/g, ' ');
    const auth = String(item.auth_scheme || 'custom').replace(/_/g, ' ');
    const caps = item.capabilities || {};
    const capabilityBits = [
      caps.listings ? 'Listings' : '',
      caps.bookings ? 'Bookings' : '',
      caps.messages_pull ? 'Messages' : '',
      caps.message_webhooks ? 'Webhooks' : '',
      caps.direct_messaging ? 'Direct send' : '',
    ].filter(Boolean);
    const isInboxBridge = item.message_transport === 'email_bridge' || item.message_transport === 'hybrid';
    return `
      <div style="display:flex;flex-direction:column;gap:10px;padding:14px;background:rgba(255,255,255,0.02);border:1px solid ${item.provider === provider ? 'rgba(200,120,50,0.28)' : 'var(--border)'};border-radius:10px">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap">
          <div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
              <div style="font-size:13px;font-weight:600;color:var(--white)">${escapeHtml(item.name || item.provider)}</div>
              ${item.provider === provider ? `<span class="badge badge-amber" style="font-size:9px">Current PMS</span>` : ''}
              ${configured ? `<span class="badge badge-green" style="font-size:9px">Configured</span>` : `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(readiness)}</span>`}
            </div>
            <div style="font-size:11px;color:var(--dim);margin-top:4px">${propertyCount} propert${propertyCount === 1 ? 'y' : 'ies'} currently linked · ${escapeHtml(auth)} auth · ${escapeHtml(transport)}</div>
          </div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            ${isInboxBridge ? `<a href="/app/connect-gmail" class="btn btn-sm" style="text-decoration:none">Manage inbox</a>` : ''}
          </div>
        </div>
        <div style="font-size:11px;color:rgba(240,235,227,0.62);line-height:1.6">${escapeHtml(item.notes || 'Canonical PMS contract ready for this provider.')}</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          ${capabilityBits.length ? capabilityBits.map((bit) => `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(bit)}</span>`).join('') : `<span class="badge badge-dim" style="font-size:9px">Config only</span>`}
          <span class="badge badge-dim" style="font-size:9px">${escapeHtml(String(fieldCount))} credential fields</span>
        </div>
        ${configured ? `
          <div style="font-size:11px;color:rgba(240,235,227,0.58)">
            Stored credentials: ${escapeHtml((configured.credential_fields || []).join(', ') || 'configured')}
          </div>
        ` : `
          <div style="font-size:11px;color:rgba(240,235,227,0.52)">
            Required fields: ${escapeHtml((item.required_fields || []).join(', ') || 'none')}
          </div>
        `}
      </div>
    `;
  }).join('');
}

function renderAccount(data) {
  const account = data.account;
  const settings = data.settings;
  const company = document.getElementById('set-company');
  const email = document.getElementById('set-email');
  const aiName = document.getElementById('set-ai-name');
  const plan = document.getElementById('set-plan');
  if (company) company.value = account.companyName || 'Operator account';
  if (email) email.value = account.contactEmail || '—';
  if (aiName) aiName.value = settings.aiConciergeName || 'Your Concierge';
  if (plan) plan.value = account.plan || 'beta';
  renderPmsList(account);
}

function renderNotificationPrefs(settings) {
  Object.entries(TOGGLE_MAP).forEach(([id, key]) => {
    const toggle = document.getElementById(id);
    if (!toggle) return;
    toggle.classList.toggle('on', !!settings[key]);
  });
}

function renderPauseState(settings) {
  const btn = document.getElementById('ai-pause-btn');
  const status = document.getElementById('ai-pause-status');
  if (!btn || !status) return;
  if (settings.aiPaused) {
    btn.textContent = 'Resume AI';
    btn.classList.remove('btn-danger');
    status.textContent = settings.aiPausedAt
      ? `Paused since ${new Date(settings.aiPausedAt).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}`
      : 'AI is paused — operators are handling guest messages manually.';
  } else {
    btn.textContent = 'Pause AI';
    btn.classList.add('btn-danger');
    status.textContent = 'AI is live for drafting and guest workflow support.';
  }
}

const TOUCH_TYPE_MAP = {
  'pro-touch-welcome': 'pre_arrival_welcome',
  'pro-touch-arrival-info': 'arrival_info',
  'pro-touch-dinner': 'dinner_planning',
  'pro-touch-instay': 'in_stay_checkin',
  'pro-touch-checkout': 'checkout_prep',
  'pro-touch-extend': 'extend_offer',
};

function renderProactivePolicy(settings) {
  const proactive = settings.proactivePolicy || {};
  const escalation = settings.escalationGuestPolicy || {};
  const stayOps = settings.stayOperationsPolicy || {};
  const retention = settings.retentionPolicy || {};
  const enabled = new Set(proactive.enabledTouchTypes || []);
  Object.entries(TOUCH_TYPE_MAP).forEach(([id, touchType]) => {
    const el = document.getElementById(id);
    if (el) el.checked = enabled.has(touchType);
  });
  const cadence = document.getElementById('pro-cadence-hours');
  const serviceGap = document.getElementById('pro-service-update-hours');
  const maxNotifications = document.getElementById('pro-max-notifications');
  const allowEsc = document.getElementById('pro-allow-escalation-updates');
  const allowEta = document.getElementById('esc-allow-eta');
  const allowReassure = document.getElementById('esc-allow-reassure');
  const requireApproval = document.getElementById('esc-approval-required');
  const workflowProfile = document.getElementById('ops-workflow-profile');
  const accessFlows = document.getElementById('ops-enable-access');
  const rentalFlows = document.getElementById('ops-enable-rentals');
  const turnoverFlows = document.getElementById('ops-enable-turnover');
  const maintenanceFlows = document.getElementById('ops-enable-maintenance');
  const walkthrough = document.getElementById('ops-enable-walkthrough');
  const walkthroughRequired = document.getElementById('ops-walkthrough-required');
  const autoArchive = document.getElementById('ops-auto-archive');
  const activeSearch = document.getElementById('ret-active-search');
  const postStayFollowUp = document.getElementById('ret-post-stay-followup');
  const rawGuestRetention = document.getElementById('ret-raw-guest');
  const preBookingRetention = document.getElementById('ret-prebooking');
  const sessionShellRetention = document.getElementById('ret-session-shells');
  const signalRetention = document.getElementById('ret-signals');
  const cleanupEnabled = document.getElementById('ret-auto-cleanup');
  const preserveGuestIdentity = document.getElementById('ret-preserve-identity');
  if (cadence) cadence.value = String(proactive.minHoursBetweenProactiveTouches || 18);
  if (serviceGap) serviceGap.value = String(proactive.minHoursBetweenServiceUpdates || 4);
  if (maxNotifications) maxNotifications.value = String(proactive.maxNotificationsPerStayWindow || 6);
  if (allowEsc) allowEsc.checked = proactive.allowServiceUpdatesDuringEscalation !== false;
  if (allowEta) allowEta.checked = escalation.allowEtaUpdates !== false;
  if (allowReassure) allowReassure.checked = escalation.allowReassuranceWithoutEta !== false;
  if (requireApproval) requireApproval.checked = !!escalation.operatorApprovalRequiredForStatusUpdates;
  if (workflowProfile) workflowProfile.value = stayOps.workflowProfile || 'assisted_ops';
  if (accessFlows) accessFlows.checked = stayOps.enableAccessWorkflows !== false;
  if (rentalFlows) rentalFlows.checked = stayOps.enableRentalWorkflows !== false;
  if (turnoverFlows) turnoverFlows.checked = stayOps.enableTurnoverWorkflows !== false;
  if (maintenanceFlows) maintenanceFlows.checked = stayOps.enableMaintenanceWorkflows !== false;
  if (walkthrough) walkthrough.checked = !!stayOps.enablePostCheckoutWalkthrough;
  if (walkthroughRequired) walkthroughRequired.checked = !!stayOps.walkthroughRequiredBeforeReady;
  if (autoArchive) autoArchive.checked = stayOps.autoArchiveWhenTurnoverReady !== false;
  if (activeSearch) activeSearch.value = String(retention.activeSearchWindowDays || 30);
  if (postStayFollowUp) postStayFollowUp.value = String(retention.postStayFollowUpDays || 21);
  if (rawGuestRetention) rawGuestRetention.value = String(retention.rawGuestContentRetentionDays || 90);
  if (preBookingRetention) preBookingRetention.value = String(retention.preBookingRecordRetentionDays || 120);
  if (sessionShellRetention) sessionShellRetention.value = String(retention.guestSessionShellRetentionDays || 730);
  if (signalRetention) signalRetention.value = String(retention.structuredSignalRetentionDays || 365);
  if (cleanupEnabled) cleanupEnabled.checked = retention.autoCleanupEnabled !== false;
  if (preserveGuestIdentity) preserveGuestIdentity.checked = retention.preserveGuestIdentity !== false;
}

async function loadSettings() {
  try {
    const [settingsPayload, providerPayload, credentialPayload] = await Promise.all([
      api.settings.get(),
      api.gateway.providers().catch(() => ({ providers: [] })),
      api.gateway.credentials().catch(() => ({ configured_integrations: [] })),
    ]);
    const data = normalizeSettings(settingsPayload);
    state.settings = data;
    state.loaded = true;
    state.providerCatalog = Array.isArray(providerPayload?.providers) ? providerPayload.providers : [];
    state.configuredIntegrations = Array.isArray(credentialPayload?.configured_integrations) ? credentialPayload.configured_integrations : [];
    renderAccount(data);
    renderNotificationPrefs(data.settings);
    renderPauseState(data.settings);
    renderProactivePolicy(data.settings);
    setStatus('Settings synced', 'dim');
  } catch (error) {
    setStatus('Could not load settings', 'err');
    const pmsList = document.getElementById('settings-pms-list');
    if (pmsList) {
      pmsList.innerHTML = renderInlineError('Settings unavailable', error.message || String(error), 'settings-retry');
      const btn = document.getElementById('settings-retry');
      if (btn) btn.addEventListener('click', loadSettings);
    }
  }
}

function updateAiGuidanceCount() {
  const ta = document.getElementById('ai-guidance-text');
  const count = document.getElementById('ai-guidance-count');
  if (!ta || !count) return;
  const n = (ta.value || '').length;
  count.textContent = `${n.toLocaleString()} / 8,000`;
  count.style.color = n > 7500 ? 'var(--red)' : n > 6500 ? 'var(--amber)' : 'var(--dim)';
}

async function loadAiGuidance() {
  const ta = document.getElementById('ai-guidance-text');
  const status = document.getElementById('ai-guidance-status');
  if (!ta) return;
  try {
    const data = await api.settings.aiGuidance.get();
    ta.value = data.guidance_text || '';
    updateAiGuidanceCount();
    if (status) {
      if (data.updated_at) {
        const when = new Date(data.updated_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        const who = data.updated_by ? ` by ${data.updated_by}` : '';
        status.textContent = `Last saved ${when}${who}`;
      } else {
        status.textContent = 'Not set yet';
      }
      status.style.color = 'var(--dim)';
    }
  } catch (error) {
    if (status) {
      status.textContent = 'Could not load';
      status.style.color = 'var(--red)';
    }
    console.warn('[Settings] AI guidance load failed:', error);
  }
}

async function saveAiGuidance() {
  const ta = document.getElementById('ai-guidance-text');
  const btn = document.getElementById('ai-guidance-save');
  const status = document.getElementById('ai-guidance-status');
  if (!ta || !btn) return;
  const text = (ta.value || '').trim();
  if (text.length > 8000) {
    if (status) {
      status.textContent = 'Too long — trim to 8,000 chars';
      status.style.color = 'var(--red)';
    }
    return;
  }
  btn.disabled = true;
  btn.textContent = 'Saving...';
  try {
    const data = await api.settings.aiGuidance.put({ guidance_text: text });
    if (status) {
      status.textContent = `Saved — ${(data.char_count || 0).toLocaleString()} chars live`;
      status.style.color = 'var(--green)';
      setTimeout(() => {
        if (status) status.style.color = 'var(--dim)';
        loadAiGuidance();
      }, 2000);
    }
  } catch (error) {
    if (status) {
      status.textContent = 'Save failed — try again';
      status.style.color = 'var(--red)';
    }
    console.warn('[Settings] AI guidance save failed:', error);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save Rules';
  }
}

function updateThresholdSummary() {
  const pb = document.getElementById('set-pb-thr');
  const esc = document.getElementById('set-esc-thr');
  const gap = document.getElementById('set-gap-thr');
  const pbVal = document.getElementById('set-pb-thr-val');
  const escVal = document.getElementById('set-esc-thr-val');
  const gapVal = document.getElementById('set-gap-thr-val');
  const summary = document.getElementById('settings-threshold-summary');
  if (!pb || !esc || !gap) return;
  if (pbVal) pbVal.textContent = `${pb.value || '0'}%`;
  if (escVal) escVal.textContent = `${esc.value || '0'}%`;
  if (gapVal) gapVal.textContent = `${gap.value || '0'}%`;
  if (summary) {
    summary.textContent =
      `Current policy: auto-send only above ${pb.value}% for Auto-mode properties, escalate above ${esc.value}%, and flag knowledge gaps below ${gap.value}%.`;
  }
}

async function saveThresholdSettingsPatch(patch) {
  try {
    await api.settings.patch(patch);
    setStatus('Saved', 'ok');
    setTimeout(() => {
      const el = document.getElementById('settings-save-status');
      if (el && el.textContent === 'Saved') setStatus('Settings synced', 'dim');
    }, 1500);
  } catch (error) {
    setStatus('Save failed', 'err');
    console.warn('[Settings] threshold save failed:', error);
  }
}

function queueThresholdSave() {
  if (settingsSaveTimer) clearTimeout(settingsSaveTimer);
  setStatus('Saving…', 'warn');
  settingsSaveTimer = setTimeout(() => {
    const pb = document.getElementById('set-pb-thr');
    const esc = document.getElementById('set-esc-thr');
    const gap = document.getElementById('set-gap-thr');
    if (!pb || !esc || !gap) return;
    saveThresholdSettingsPatch({
      prebooking_autosend_threshold: parseInt(pb.value || '95', 10),
      escalation_urgency_threshold: parseInt(esc.value || '70', 10),
      kb_gap_detection_threshold: parseInt(gap.value || '40', 10),
    });
  }, 250);
}

function wireThresholdInputs() {
  ['set-pb-thr', 'set-esc-thr', 'set-gap-thr'].forEach((id) => {
    const el = document.getElementById(id);
    if (!el || el.dataset.thresholdWired === '1') return;
    el.dataset.thresholdWired = '1';
    el.addEventListener('input', updateThresholdSummary);
    el.addEventListener('change', () => {
      updateThresholdSummary();
      queueThresholdSave();
    });
  });
}

function isSettingsView() {
  const root = document.getElementById('view-settings');
  return !!root && root.style.display !== 'none';
}

async function loadOperatorSettings() {
  try {
    const data = await api.settings.get();
    const s = (data && data.settings) || {};
    const pb = document.getElementById('set-pb-thr');
    const esc = document.getElementById('set-esc-thr');
    const gap = document.getElementById('set-gap-thr');
    if (pb) pb.value = String(s.prebooking_autosend_threshold != null ? s.prebooking_autosend_threshold : 95);
    if (esc) esc.value = String(s.escalation_urgency_threshold != null ? s.escalation_urgency_threshold : 70);
    if (gap) gap.value = String(s.kb_gap_detection_threshold != null ? s.kb_gap_detection_threshold : 40);
    updateThresholdSummary();
    setStatus('Loaded saved settings', 'dim');
  } catch (error) {
    setStatus('Could not load settings', 'err');
    console.warn('[Settings] threshold load failed:', error);
  }
}

function fmtAlertRoutingWhen(iso) {
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

function isoToLocalInputValue(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const offsetMs = d.getTimezoneOffset() * 60000;
    return new Date(d.getTime() - offsetMs).toISOString().slice(0, 16);
  } catch (_) {
    return '';
  }
}

function setAlertRoutingStatus(text, kind = 'dim') {
  const status = document.getElementById('alert-routing-status');
  if (!status) return;
  status.textContent = text;
  status.style.color =
    kind === 'ok' ? 'var(--green)' :
    kind === 'err' ? 'var(--red)' :
    kind === 'warn' ? 'var(--amber)' :
    'var(--dim)';
}

function renderAlertRouting(data) {
  state.alertRouting = data || { contacts: [], coverage: [], properties: [], alert_types: [] };
  const coverageEl = document.getElementById('alert-routing-coverage');
  const listEl = document.getElementById('alert-routing-list');
  const typeEl = document.getElementById('alert-route-type');
  const propertyEl = document.getElementById('alert-route-property');
  if (!coverageEl || !listEl || !typeEl || !propertyEl) return;

  const coverage = state.alertRouting.coverage || [];
  const contacts = state.alertRouting.contacts || [];
  const properties = state.alertRouting.properties || [];
  const types = state.alertRouting.alert_types || [];

  const statusParts = [
    `${contacts.length} contact${contacts.length === 1 ? '' : 's'}`,
    `${coverage.length} routing lane${coverage.length === 1 ? '' : 's'}`,
  ];
  if (state.alertRouting.all_covered) {
    statusParts.push('all covered');
    setAlertRoutingStatus(statusParts.join(' · '), 'ok');
  } else {
    statusParts.push(`${state.alertRouting.gap_count || 0} coverage gap${(state.alertRouting.gap_count || 0) === 1 ? '' : 's'}`);
    setAlertRoutingStatus(statusParts.join(' · '), 'warn');
  }

  coverageEl.innerHTML = coverage.map((item) => `
    <div style="padding:12px;border:1px solid var(--border);border-radius:8px;background:rgba(255,255,255,0.03)">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px">
        <span class="badge ${item.has_coverage ? 'badge-green' : 'badge-red'}" style="font-size:9px">${item.has_coverage ? 'COVERED' : 'GAP'}</span>
        <span style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(String(item.alert_type || '').replace(/_/g, ' '))}</span>
      </div>
      <div style="font-size:11px;color:rgba(240,235,227,0.65);line-height:1.6">
        ${item.has_coverage
          ? `${item.available_count} active contact${item.available_count === 1 ? '' : 's'} · timeout ${item.escalation_timeout_minutes}m`
          : escapeHtml(item.gap_details || 'No active coverage')}
      </div>
    </div>`).join('') || '<div class="empty" style="padding:24px 18px"><div class="empty-sub">No coverage data yet. Add contacts below to build your internal response chain.</div></div>';

  if (!typeEl.dataset.loaded) {
    typeEl.innerHTML = types.map((type) => `<option value="${escapeHtml(type)}">${escapeHtml(String(type).replace(/_/g, ' '))}</option>`).join('');
    typeEl.dataset.loaded = '1';
  }

  propertyEl.innerHTML = '<option value="">All properties</option>' + properties.map((prop) => (
    `<option value="${escapeHtml(prop.property_code || '')}">${escapeHtml(prop.property_name || prop.property_code || 'Property')}</option>`
  )).join('');

  listEl.innerHTML = contacts.length ? contacts.map((contact) => {
    const redirectOptions = ['<option value="">Escalate to next in chain</option>']
      .concat(contacts.filter((other) => other.id !== contact.id).map((other) => (
        `<option value="${escapeHtml(other.id)}" ${contact.redirect_to_id === other.id ? 'selected' : ''}>${escapeHtml(other.contact_name || 'Contact')}</option>`
      ))).join('');
    const typeOptions = types.map((type) => (
      `<option value="${escapeHtml(type)}" ${contact.alert_type === type ? 'selected' : ''}>${escapeHtml(String(type).replace(/_/g, ' '))}</option>`
    )).join('');
    const propertyOptions = ['<option value="">All properties</option>']
      .concat(properties.map((prop) => {
        const value = prop.property_code || '';
        return `<option value="${escapeHtml(value)}" ${contact.property_code === value ? 'selected' : ''}>${escapeHtml(prop.property_name || value || 'Property')}</option>`;
      })).join('');
    return `
      <div class="alert-routing-contact" data-contact-id="${escapeHtml(contact.id)}" style="padding:12px;border:1px solid var(--border);border-radius:8px;background:rgba(255,255,255,0.03);display:flex;flex-direction:column;gap:10px">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap">
          <div>
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <span style="font-size:13px;color:var(--white);font-weight:600">${escapeHtml(contact.contact_name || 'Contact')}</span>
              <span class="badge ${contact.is_available ? 'badge-green' : 'badge-amber'}" style="font-size:9px">${contact.is_available ? 'AVAILABLE' : 'OOO'}</span>
              <span class="badge badge-dim" style="font-size:9px">${escapeHtml(String(contact.alert_type || '').toUpperCase())}</span>
              ${contact.property_code ? `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(contact.property_code)}</span>` : '<span class="badge badge-dim" style="font-size:9px">ALL PROPERTIES</span>'}
            </div>
            <div style="font-size:11px;color:rgba(240,235,227,0.68);margin-top:4px">${escapeHtml(contact.contact_phone || contact.contact_email || 'No phone or email saved')}</div>
            <div style="font-size:11px;color:rgba(240,235,227,0.5);margin-top:4px">${escapeHtml(contact.status_label || 'Available')}</div>
          </div>
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:10px;color:rgba(240,235,227,0.55);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.08em">
            <span>Order ${escapeHtml(String(contact.escalation_order || 1))}</span>
            <span>Timeout ${escapeHtml(String(contact.escalation_timeout_minutes || 30))}m</span>
            <span>${escapeHtml(contact.active_hours || '24/7')}</span>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:1.1fr 1fr 0.75fr 0.85fr;gap:8px;align-items:end">
          <div><div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">Name</div><input class="form-input alert-route-name" value="${escapeHtml(contact.contact_name || '')}" /></div>
          <div><div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">Alert type</div><select class="form-select alert-route-type-edit">${typeOptions}</select></div>
          <div><div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">Order</div><input class="form-input alert-route-order-edit" type="number" min="1" step="1" value="${escapeHtml(String(contact.escalation_order || 1))}" /></div>
          <div><div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">Timeout</div><input class="form-input alert-route-timeout-edit" type="number" min="1" step="1" value="${escapeHtml(String(contact.escalation_timeout_minutes || 30))}" /></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;align-items:end">
          <div><div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">Phone</div><input class="form-input alert-route-phone-edit" value="${escapeHtml(contact.contact_phone || '')}" /></div>
          <div><div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">Email</div><input class="form-input alert-route-email-edit" value="${escapeHtml(contact.contact_email || '')}" /></div>
          <div><div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">Hours start</div><input class="form-input alert-route-start-edit" type="time" value="${escapeHtml(contact.active_hours_start || '')}" /></div>
          <div><div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">Hours end</div><input class="form-input alert-route-end-edit" type="time" value="${escapeHtml(contact.active_hours_end || '')}" /></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr auto;gap:8px;align-items:end">
          <div><div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">Property scope</div><select class="form-select alert-route-property-edit">${propertyOptions}</select></div>
          <label style="display:flex;align-items:center;gap:8px;font-size:12px;color:rgba(240,235,227,0.72);padding-bottom:10px"><input type="checkbox" class="alert-route-primary-edit" ${contact.is_primary ? 'checked' : ''} />Primary</label>
        </div>
        <div><div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">Notes</div><textarea class="form-textarea alert-route-notes-edit" rows="2">${escapeHtml(contact.notes || '')}</textarea></div>
        <div style="display:grid;grid-template-columns:1fr 1fr auto auto;gap:8px;align-items:end">
          <div><div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">OOO until</div><input class="form-input alert-route-ooo-until" type="datetime-local" value="${escapeHtml(isoToLocalInputValue(contact.unavailable_until))}" /></div>
          <div><div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">Redirect to</div><select class="form-select alert-route-redirect">${redirectOptions}</select></div>
          ${contact.is_available ? `<button class="btn btn-sm alert-route-mark-ooo">Mark OOO</button>` : `<button class="btn btn-sm alert-route-mark-available">Restore</button>`}
          <button class="btn btn-sm alert-route-save">Save</button>
          <button class="btn btn-sm alert-route-delete">Remove</button>
        </div>
      </div>`;
  }).join('') : '<div class="empty" style="padding:28px 18px"><div class="empty-title">No alert contacts added yet</div><div class="empty-sub">Start with the people who should receive maintenance, emergency, or general escalation alerts first.</div></div>';
}

async function loadAlertRoutingSettings() {
  const coverageEl = document.getElementById('alert-routing-coverage');
  const listEl = document.getElementById('alert-routing-list');
  if (!coverageEl || !listEl) return;
  try {
    setAlertRoutingStatus('Loading alert routing…', 'dim');
    renderAlertRouting(await api.settings.alertRouting());
  } catch (error) {
    setAlertRoutingStatus('Could not load alert routing', 'err');
    coverageEl.innerHTML = `
      <div class="empty" style="padding:24px 18px">
        <div class="empty-title">Alert routing is unavailable right now</div>
        <div class="empty-sub">${escapeHtml(String(error.message || error))}</div>
        <button class="btn btn-sm" id="alert-routing-retry-btn" style="margin-top:12px">Retry</button>
      </div>`;
    listEl.innerHTML = '';
    const retryBtn = document.getElementById('alert-routing-retry-btn');
    if (retryBtn) retryBtn.addEventListener('click', loadAlertRoutingSettings);
    console.warn('[Settings] alert routing load failed:', error);
  }
}

async function createAlertRoutingContact() {
  const status = document.getElementById('alert-routing-form-status');
  const body = {
    alert_type: document.getElementById('alert-route-type')?.value || 'general',
    property_code: document.getElementById('alert-route-property')?.value || '',
    contact_name: (document.getElementById('alert-route-name')?.value || '').trim(),
    escalation_order: parseInt(document.getElementById('alert-route-order')?.value || '1', 10),
    contact_phone: (document.getElementById('alert-route-phone')?.value || '').trim(),
    contact_email: (document.getElementById('alert-route-email')?.value || '').trim(),
    escalation_timeout_minutes: parseInt(document.getElementById('alert-route-timeout')?.value || '30', 10),
    active_hours_start: document.getElementById('alert-route-start')?.value || null,
    active_hours_end: document.getElementById('alert-route-end')?.value || null,
    notes: (document.getElementById('alert-route-notes')?.value || '').trim(),
    is_primary: !!document.getElementById('alert-route-primary')?.checked,
  };
  if (!body.contact_name) {
    if (status) {
      status.textContent = 'Contact name is required';
      status.style.color = 'var(--red)';
    }
    return;
  }
  try {
    if (status) {
      status.textContent = 'Saving contact…';
      status.style.color = 'var(--amber)';
    }
    await api.settings.createAlertContact(body);
    ['alert-route-name', 'alert-route-phone', 'alert-route-email', 'alert-route-notes', 'alert-route-start', 'alert-route-end'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    const orderEl = document.getElementById('alert-route-order');
    if (orderEl) orderEl.value = '1';
    const primaryEl = document.getElementById('alert-route-primary');
    if (primaryEl) primaryEl.checked = true;
    if (status) {
      status.textContent = 'Contact added to the routing chain.';
      status.style.color = 'var(--green)';
    }
    await loadAlertRoutingSettings();
  } catch (error) {
    if (status) {
      status.textContent = error.message || 'Could not add contact';
      status.style.color = 'var(--red)';
    }
  }
}

async function changePassword() {
  const cur = document.getElementById('cp-current');
  const nw = document.getElementById('cp-new');
  const cf = document.getElementById('cp-confirm');
  const msg = document.getElementById('cp-msg');
  const btn = document.getElementById('cp-btn');
  if (!cur || !nw || !cf || !msg || !btn) return;

  const setMsg = (kind, text) => {
    msg.style.display = 'block';
    msg.textContent = text;
    msg.style.color = kind === 'ok' ? '#86efac' : '#fca5a5';
  };

  const current = cur.value;
  const next = nw.value;
  const confirmVal = cf.value;
  if (!current) return setMsg('err', 'Enter your current password.');
  if (next.length < 8) return setMsg('err', 'New password must be at least 8 characters.');
  if (next !== confirmVal) return setMsg('err', "New passwords don't match.");
  if (next === current) return setMsg('err', 'New password must be different from current.');

  btn.disabled = true;
  btn.textContent = 'Updating...';
  try {
    const data = await api.auth.changePassword({ current_password: current, new_password: next });
    setMsg('ok', data.message || 'Password updated.');
    cur.value = '';
    nw.value = '';
    cf.value = '';
  } catch (error) {
    setMsg('err', error.message || 'Could not update password.');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Update password';
  }
}

function collectPatch() {
  const enabledTouchTypes = Object.entries(TOUCH_TYPE_MAP)
    .filter(([id]) => document.getElementById(id)?.checked)
    .map(([, touchType]) => touchType);
  return {
    ai_concierge_name: (document.getElementById('set-ai-name')?.value || '').trim() || 'Your Concierge',
    notify_emergency: document.getElementById('tog-emerg')?.classList.contains('on'),
    notify_maintenance: document.getElementById('tog-maint')?.classList.contains('on'),
    notify_prebooking: document.getElementById('tog-pb')?.classList.contains('on'),
    notify_kb_gaps: document.getElementById('tog-gaps')?.classList.contains('on'),
    notify_weekly_analytics: document.getElementById('tog-weekly')?.classList.contains('on'),
    proactive_policy: {
      enabled_touch_types: enabledTouchTypes,
      min_hours_between_proactive_touches: parseInt(document.getElementById('pro-cadence-hours')?.value || '18', 10),
      min_hours_between_service_updates: parseInt(document.getElementById('pro-service-update-hours')?.value || '4', 10),
      max_notifications_per_stay_window: parseInt(document.getElementById('pro-max-notifications')?.value || '6', 10),
      allow_service_updates_during_escalation: !!document.getElementById('pro-allow-escalation-updates')?.checked,
    },
    escalation_guest_policy: {
      allow_eta_updates: !!document.getElementById('esc-allow-eta')?.checked,
      allow_reassurance_without_eta: !!document.getElementById('esc-allow-reassure')?.checked,
      operator_approval_required_for_status_updates: !!document.getElementById('esc-approval-required')?.checked,
    },
    stay_operations_policy: {
      workflow_profile: document.getElementById('ops-workflow-profile')?.value || 'assisted_ops',
      enable_access_workflows: !!document.getElementById('ops-enable-access')?.checked,
      enable_rental_workflows: !!document.getElementById('ops-enable-rentals')?.checked,
      enable_turnover_workflows: !!document.getElementById('ops-enable-turnover')?.checked,
      enable_maintenance_workflows: !!document.getElementById('ops-enable-maintenance')?.checked,
      enable_post_checkout_walkthrough: !!document.getElementById('ops-enable-walkthrough')?.checked,
      walkthrough_required_before_ready: !!document.getElementById('ops-walkthrough-required')?.checked,
      auto_archive_when_turnover_ready: !!document.getElementById('ops-auto-archive')?.checked,
    },
    retention_policy: {
      active_search_window_days: parseInt(document.getElementById('ret-active-search')?.value || '30', 10),
      post_stay_follow_up_days: parseInt(document.getElementById('ret-post-stay-followup')?.value || '21', 10),
      raw_guest_content_retention_days: parseInt(document.getElementById('ret-raw-guest')?.value || '90', 10),
      pre_booking_record_retention_days: parseInt(document.getElementById('ret-prebooking')?.value || '120', 10),
      guest_session_shell_retention_days: parseInt(document.getElementById('ret-session-shells')?.value || '730', 10),
      structured_signal_retention_days: parseInt(document.getElementById('ret-signals')?.value || '365', 10),
      auto_cleanup_enabled: !!document.getElementById('ret-auto-cleanup')?.checked,
      preserve_guest_identity: !!document.getElementById('ret-preserve-identity')?.checked,
    },
  };
}

async function saveAllSettings() {
  const btn = document.getElementById('settings-save-btn');
  const previous = btn?.textContent || 'Save All Changes';
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Saving…';
  }
  setStatus('Saving settings…', 'warn');
  try {
    await api.settings.patch(collectPatch());
    setStatus('Settings saved', 'ok');
    await loadSettings();
  } catch (error) {
    setStatus(error.message || 'Could not save settings', 'err');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = previous;
    }
  }
}

async function toggleAiPause() {
  const current = !!state.settings?.settings?.aiPaused;
  setStatus(current ? 'Resuming AI…' : 'Pausing AI…', 'warn');
  try {
    await api.settings.patch({ ai_paused: !current });
    await loadSettings();
    setStatus(!current ? 'AI paused' : 'AI resumed', !current ? 'warn' : 'ok');
  } catch (error) {
    setStatus(error.message || 'Could not update AI pause state', 'err');
  }
}

function wireDom() {
  Object.keys(TOGGLE_MAP).forEach((id) => {
    const toggle = document.getElementById(id);
    if (!toggle || toggle.dataset.settingsWired === '1') return;
    toggle.dataset.settingsWired = '1';
    toggle.removeAttribute('onclick');
    toggle.addEventListener('click', (event) => {
      event.preventDefault();
      toggle.classList.toggle('on');
    });
  });
  const aiGuidance = document.getElementById('ai-guidance-text');
  if (aiGuidance && aiGuidance.dataset.wired !== '1') {
    aiGuidance.dataset.wired = '1';
    aiGuidance.addEventListener('input', updateAiGuidanceCount);
  }
  wireThresholdInputs();
  const addBtn = document.getElementById('alert-routing-add-btn');
  if (addBtn && addBtn.dataset.wired !== '1') {
    addBtn.dataset.wired = '1';
    addBtn.addEventListener('click', createAlertRoutingContact);
  }
  const routingList = document.getElementById('alert-routing-list');
  if (routingList && routingList.dataset.wired !== '1') {
    routingList.dataset.wired = '1';
    routingList.addEventListener('click', async (event) => {
      const card = event.target.closest('.alert-routing-contact');
      if (!card) return;
      const contactId = card.getAttribute('data-contact-id');
      if (!contactId) return;
      try {
        if (event.target.classList.contains('alert-route-mark-ooo')) {
          const until = card.querySelector('.alert-route-ooo-until')?.value || '';
          const redirect = card.querySelector('.alert-route-redirect')?.value || '';
          if (!until) return window.alert('Choose when this contact returns.');
          await api.settings.markAlertOOO(contactId, {
            unavailable_until: new Date(until).toISOString(),
            redirect_to_id: redirect || null,
          });
          setAlertRoutingStatus('Contact marked out of office.', 'warn');
          return loadAlertRoutingSettings();
        }
        if (event.target.classList.contains('alert-route-mark-available')) {
          await api.settings.markAlertAvailable(contactId);
          setAlertRoutingStatus('Contact restored to the routing chain.', 'ok');
          return loadAlertRoutingSettings();
        }
        if (event.target.classList.contains('alert-route-save')) {
          await api.settings.updateAlertContact(contactId, {
            contact_name: (card.querySelector('.alert-route-name')?.value || '').trim(),
            alert_type: card.querySelector('.alert-route-type-edit')?.value || 'general',
            escalation_order: parseInt(card.querySelector('.alert-route-order-edit')?.value || '1', 10),
            escalation_timeout_minutes: parseInt(card.querySelector('.alert-route-timeout-edit')?.value || '30', 10),
            contact_phone: (card.querySelector('.alert-route-phone-edit')?.value || '').trim(),
            contact_email: (card.querySelector('.alert-route-email-edit')?.value || '').trim(),
            active_hours_start: card.querySelector('.alert-route-start-edit')?.value || null,
            active_hours_end: card.querySelector('.alert-route-end-edit')?.value || null,
            property_code: card.querySelector('.alert-route-property-edit')?.value || '',
            is_primary: !!card.querySelector('.alert-route-primary-edit')?.checked,
            notes: (card.querySelector('.alert-route-notes-edit')?.value || '').trim(),
          });
          setAlertRoutingStatus('Routing contact updated.', 'ok');
          return loadAlertRoutingSettings();
        }
        if (event.target.classList.contains('alert-route-delete')) {
          if (!window.confirm('Remove this alert contact from the routing chain?')) return;
          await api.settings.deleteAlertContact(contactId);
          setAlertRoutingStatus('Routing contact removed.', 'warn');
          return loadAlertRoutingSettings();
        }
      } catch (error) {
        setAlertRoutingStatus(error.message || 'Could not update alert routing.', 'err');
      }
    });
  }
}

export function init() {
  wireDom();
  window.saveAllSettings = saveAllSettings;
  window.toggleAiPause = toggleAiPause;
  window.saveAiGuidance = saveAiGuidance;
  window.loadAiGuidance = loadAiGuidance;
  window.changePassword = changePassword;
  window.addEventListener('oyvoda:view-changed', (event) => {
    if (event.detail?.view === 'settings') {
      loadSettings();
      loadAiGuidance();
      loadOperatorSettings();
      loadAlertRoutingSettings();
      wireThresholdInputs();
    }
  });
  if (isSettingsView()) {
    loadSettings();
    loadAiGuidance();
    loadOperatorSettings();
    loadAlertRoutingSettings();
  }
  wireThresholdInputs();
}
