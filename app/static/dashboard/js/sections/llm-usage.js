import api from '../api.js?v=2026-04-21-c';
import { state } from '../state.js?v=2026-04-21-b';

function el(id) {
  return document.getElementById(id);
}

function fmtUsd(value) {
  const amount = Number(value || 0);
  return `$${amount.toFixed(4)}`;
}

function fmtInt(value) {
  return Number(value || 0).toLocaleString();
}

function fmtPct(value) {
  return `${Math.round((Number(value || 0) * 100))}%`;
}

function fmtWhen(value) {
  if (!value) return '—';
  const date = new Date(value);
  return date.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function hasAdminDashboardAccess() {
  const operator = state.get('operator') || {};
  return Boolean(
    operator.is_super_admin || ['company_admin', 'ops_admin'].includes(operator.role)
  );
}

function setLoading(message = 'Loading…') {
  const loadingRow = `<tr><td colspan="7" style="text-align:center;color:var(--dim);padding:24px;font-size:12px">${message}</td></tr>`;
  const serviceBody = el('llm-usage-service-body');
  const providerBody = el('llm-usage-provider-body');
  const tenantBody = el('llm-usage-tenant-body');
  const recentBody = el('llm-usage-recent-body');
  if (serviceBody) serviceBody.innerHTML = loadingRow.replace('colspan="7"', 'colspan="5"');
  if (providerBody) providerBody.innerHTML = loadingRow.replace('colspan="7"', 'colspan="4"');
  if (tenantBody) tenantBody.innerHTML = loadingRow.replace('colspan="7"', 'colspan="4"');
  if (recentBody) recentBody.innerHTML = loadingRow;
}

function renderSummary(summary) {
  el('llm-usage-24h').textContent = fmtUsd(summary?.last_24h?.total_cost_usd);
  el('llm-usage-24h-sub').textContent = `${fmtInt(summary?.last_24h?.call_count)} calls`;
  el('llm-usage-7d').textContent = fmtUsd(summary?.last_7d?.total_cost_usd);
  el('llm-usage-7d-sub').textContent = `${fmtInt(summary?.last_7d?.call_count)} calls`;
  el('llm-usage-burn').textContent = fmtUsd(summary?.current_hourly_burn_usd);
  el('llm-usage-burn-sub').textContent = `${fmtInt(summary?.selected_window?.failed_calls)} failed calls in selected window`;
}

function renderServiceRows(rows) {
  const body = el('llm-usage-service-body');
  if (!body) return;
  if (!rows?.length) {
    body.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--dim);padding:24px;font-size:12px">No usage yet.</td></tr>';
    return;
  }
  body.innerHTML = rows.map((row) => `
    <tr>
      <td><strong>${row.service_name}</strong></td>
      <td>${fmtInt(row.call_count)}</td>
      <td>${fmtUsd(row.total_cost_usd)}</td>
      <td>${fmtInt(row.avg_latency_ms)} ms</td>
      <td>${fmtPct(row.success_ratio)}</td>
    </tr>
  `).join('');
}

function renderProviderRows(rows) {
  const body = el('llm-usage-provider-body');
  if (!body) return;
  if (!rows?.length) {
    body.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--dim);padding:24px;font-size:12px">No usage yet.</td></tr>';
    return;
  }
  body.innerHTML = rows.map((row) => `
    <tr>
      <td><strong>${row.provider}</strong></td>
      <td>${row.model_id}</td>
      <td>${fmtInt(row.call_count)}</td>
      <td>${fmtUsd(row.total_cost_usd)}</td>
    </tr>
  `).join('');
}

function renderTenantRows(rows) {
  const body = el('llm-usage-tenant-body');
  if (!body) return;
  if (!rows?.length) {
    body.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--dim);padding:24px;font-size:12px">No tenant data yet.</td></tr>';
    return;
  }
  body.innerHTML = rows.map((row) => `
    <tr>
      <td><strong>${row.tenant_id || 'Unattributed'}</strong></td>
      <td>${fmtInt(row.call_count)}</td>
      <td>${fmtUsd(row.total_cost_usd)}</td>
      <td>${fmtInt(row.failed_calls)}</td>
    </tr>
  `).join('');
}

function renderRecentRows(rows) {
  const body = el('llm-usage-recent-body');
  if (!body) return;
  if (!rows?.length) {
    body.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--dim);padding:24px;font-size:12px">No recent calls yet.</td></tr>';
    return;
  }
  body.innerHTML = rows.map((row) => `
    <tr>
      <td>${fmtWhen(row.created_at)}</td>
      <td><strong>${row.service_name}</strong></td>
      <td>${row.provider}</td>
      <td>${row.model_id}</td>
      <td>${fmtUsd(row.estimated_cost_usd)}</td>
      <td>${row.success ? 'Success' : `Failed${row.error_type ? ` · ${row.error_type}` : ''}`}</td>
      <td>${row.tenant_id || '—'}</td>
    </tr>
  `).join('');
}

async function loadLlmUsage() {
  if (!hasAdminDashboardAccess()) return;
  const windowValue = el('llm-usage-window')?.value || '24h';
  setLoading();
  try {
    const [summary, byService, byProvider, byTenant, recent] = await Promise.all([
      api.admin.llmUsage.summary(windowValue),
      api.admin.llmUsage.byService(windowValue),
      api.admin.llmUsage.byProvider(windowValue),
      api.admin.llmUsage.byTenant(windowValue),
      api.admin.llmUsage.recent({ window: windowValue, limit: 50 }),
    ]);
    renderSummary(summary);
    renderServiceRows(byService?.rows || []);
    renderProviderRows(byProvider?.rows || []);
    renderTenantRows(byTenant?.rows || []);
    renderRecentRows(recent?.rows || []);
  } catch (error) {
    console.warn('[LLMUsage] load failed:', error);
    setLoading(error?.message || 'Could not load LLM usage');
  }
}

export function init() {
  const refreshButton = el('llm-usage-refresh');
  const windowSelect = el('llm-usage-window');
  if (refreshButton) refreshButton.addEventListener('click', loadLlmUsage);
  if (windowSelect) windowSelect.addEventListener('change', loadLlmUsage);
  window.addEventListener('oyvoda:view-changed', (event) => {
    if (event.detail?.view === 'llm-usage') {
      loadLlmUsage();
    }
  });
  window.refreshLlmUsage = loadLlmUsage;
}
