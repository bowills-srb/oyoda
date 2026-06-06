import api from '../api.js?v=2026-04-28-b';
import { normalizeDashboardSummary, normalizePropertiesAutonomy, renderInlineError } from '../adapters.js?v=2026-04-29-a';
import { escapeHtml } from '../ui.js?v=2026-04-21-a';

const state = {
  properties: [],
  count: 0,
  summary: { autoCount: 0, reviewCount: 0 },
  portfolios: [],
  selectedPortfolioKey: '',
  autonomyStageScope: 'all',
  selectedPropertyCode: '',
  assetsByProperty: {},
  identityReport: null,
  identityReviews: [],
  importResult: null,
  documentImportResult: null,
  importProfiles: {},
};

function fmtDate(value) {
  if (!value) return '';
  try {
    return new Date(value).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
  } catch (_) {
    return String(value);
  }
}

function renderStats(dashboardSummary) {
  const set = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = String(value);
  };
  set('prop-total', state.count);
  set('prop-pms-count', state.identityReport?.summary?.withPmsPropertyId || 0);
  const pmsSub = document.getElementById('prop-pms-sub');
  if (pmsSub) {
    pmsSub.textContent = state.identityReport?.summary?.withPmsPropertyId
      ? 'Properties with PMS property IDs'
      : (state.count > 0 ? 'Properties linked' : 'Connect PMS to sync');
  }
  const autonomySummary = getAutonomySummary();
  set('autonomy-review-count', autonomySummary.reviewCount);
  set('autonomy-auto-count', autonomySummary.autoCount);
  set('autonomy-default-count', Math.max(autonomySummary.totalCount - autonomySummary.autoCount - autonomySummary.reviewCount, 0));
  const scopeLabel = document.getElementById('autonomy-scope-label');
  if (scopeLabel) scopeLabel.textContent = autonomySummary.scopeLabel;
  const reviewSub = document.getElementById('autonomy-review-sub');
  if (reviewSub) reviewSub.textContent = autonomySummary.reviewSub;
  const autoSub = document.getElementById('autonomy-auto-sub');
  if (autoSub) autoSub.textContent = autonomySummary.autoSub;
  const defaultSub = document.getElementById('autonomy-default-sub');
  if (defaultSub) defaultSub.textContent = autonomySummary.defaultSub;
  if (dashboardSummary) {
    set('prop-kb-count', dashboardSummary.kbEntries);
    set('prop-active-sess', dashboardSummary.sessions.active);
    const nbProps = document.getElementById('nb-props');
    if (nbProps) nbProps.textContent = state.count > 0 ? String(state.count) : '';
  }
  syncTopPortfolioFilter();
}

function getSearchQuery() {
  const primary = document.getElementById('prop-search-input');
  return (primary?.value || '').trim().toLowerCase();
}

function getVisibleProperties() {
  const search = getSearchQuery();
  let portfolioCodes = null;
  if (state.selectedPortfolioKey) {
    const portfolio = state.portfolios.find((item) => item.portfolioKey === state.selectedPortfolioKey);
    portfolioCodes = new Set((portfolio?.propertyExternalIds || []).map((value) => String(value || '').trim()).filter(Boolean));
  }
  return state.properties.filter((property) => {
    const code = String(property.propertyCode || '').trim();
    if (portfolioCodes && !portfolioCodes.has(code)) return false;
    if (!search) return true;
    const haystack = [
      property.propertyCode,
      property.propertyName,
      property.addressStreet,
      property.addressCity,
      property.addressState,
      property.community,
    ].filter(Boolean).join(' ').toLowerCase();
    return haystack.includes(search);
  });
}

function getAutonomyLane(property, stageScope) {
  if (stageScope === 'pre_booking') return property.autonomy?.preBooking || { approvalMode: property.approvalMode, minConfidenceForAuto: property.minConfidenceForAuto };
  if (stageScope === 'guest_sessions') return property.autonomy?.guestSessions || { approvalMode: property.approvalMode, minConfidenceForAuto: property.minConfidenceForAuto };
  return property.autonomy?.all || { approvalMode: property.approvalMode, minConfidenceForAuto: property.minConfidenceForAuto };
}

function getAutonomySummary() {
  if (state.autonomyStageScope === 'pre_booking') {
    return {
      autoCount: Number(state.summary.preBookingAutoCount || 0),
      reviewCount: Number(state.summary.preBookingReviewCount || 0),
      totalCount: state.count,
      scopeLabel: 'Pre-booking lane',
      reviewSub: 'Drafts wait before inquiry replies',
      autoSub: 'Inquiry replies can send when grounded',
      defaultSub: 'Unconfigured properties still review',
    };
  }
  if (state.autonomyStageScope === 'guest_sessions') {
    return {
      autoCount: Number(state.summary.guestSessionsAutoCount || 0),
      reviewCount: Number(state.summary.guestSessionsReviewCount || 0),
      totalCount: state.count,
      scopeLabel: 'Guest sessions lane',
      reviewSub: 'Stay messages wait for operator review',
      autoSub: 'Proactive and reactive stay replies can send',
      defaultSub: 'Unconfigured properties still review',
    };
  }
  return {
    autoCount: Number(state.summary.autoCount || 0),
    reviewCount: Number(state.summary.reviewCount || 0),
    totalCount: state.count,
    scopeLabel: 'All messaging',
    reviewSub: 'Everything waits for review',
    autoSub: 'All lanes can send automatically',
    defaultSub: 'Falls back to review',
  };
}

function syncTopPortfolioFilter() {
  const select = document.getElementById('prop-portfolio-filter');
  if (!select) return;
  const options = ['<option value="">All portfolios</option>']
    .concat(
      state.portfolios.map((portfolio) => (
        `<option value="${escapeHtml(portfolio.portfolioKey)}" ${portfolio.portfolioKey === state.selectedPortfolioKey ? 'selected' : ''}>${escapeHtml(portfolio.displayName)} (${escapeHtml(String(portfolio.propertyCount || 0))})</option>`
      ))
    );
  select.innerHTML = options.join('');
}

function renderLanePill(property, laneKey, label) {
  const lane = getAutonomyLane(property, laneKey);
  const isMixed = lane?.approvalMode === 'mixed';
  const isAuto = lane?.approvalMode === 'auto';
  const minConfPct = Math.round((lane?.minConfidenceForAuto || 0.95) * 100);
  return `
    <div class="autonomy-pill" data-prop-id="${escapeHtml(property.id)}" data-stage-scope="${escapeHtml(laneKey)}" style="display:inline-flex;align-items:center;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:999px;padding:2px;flex-shrink:0">
      <span style="font-size:10px;color:rgba(240,235,227,0.58);padding:0 7px 0 8px;text-transform:uppercase;letter-spacing:0.08em">${escapeHtml(label)}</span>
      <button class="autonomy-seg" data-mode="required" style="border:none;background:${!isAuto ? 'rgba(200,120,50,0.2)' : 'transparent'};color:${!isAuto ? '#c87832' : 'rgba(240,235,227,0.5)'};font-size:11px;font-weight:500;padding:4px 9px;border-radius:999px;cursor:pointer;font-family:inherit" title="Hold ${label.toLowerCase()} replies for operator review">Review</button>
      <button class="autonomy-seg" data-mode="auto" style="border:none;background:${isAuto ? 'rgba(34,197,94,0.2)' : 'transparent'};color:${isAuto ? '#22c55e' : 'rgba(240,235,227,0.5)'};font-size:11px;font-weight:500;padding:4px 9px;border-radius:999px;cursor:pointer;font-family:inherit" title="Auto-send ${label.toLowerCase()} when confidence ≥ ${minConfPct}%">Auto</button>
      ${isMixed ? `<span style="font-size:10px;color:var(--amber);padding:0 8px">Mixed</span>` : ''}
    </div>
  `;
}

function renderList() {
  const container = document.getElementById('prop-list-container');
  if (!container) return;
  if (!state.properties.length) {
    container.innerHTML = `
      <div class="empty">
        <div class="empty-title">No properties linked yet</div>
        <div class="empty-sub">Contact support to link your properties.</div>
        <button class="btn btn-primary" onclick="window.navigate && window.navigate('settings')">Go to Settings</button>
      </div>`;
    return;
  }
  const visibleProperties = getVisibleProperties();
  const identity = state.identityReport?.summary || {};
  const rows = visibleProperties.map((property) => {
    const addr = [property.addressStreet, property.addressCity, property.addressState].filter(Boolean).join(', ');
    const tags = [
      property.bedrooms ? `${property.bedrooms} bd` : '',
      property.bathrooms ? `${property.bathrooms} ba` : '',
      property.sleeps ? `sleeps ${property.sleeps}` : '',
    ].filter(Boolean).join(' · ');
    const amenities = [
      property.hasPool ? 'Pool' : '',
      property.hasHotTub ? 'Hot Tub' : '',
      property.petsAllowed ? 'Pet Friendly' : '',
    ].filter(Boolean).join(' · ');
    const selected = property.propertyCode === state.selectedPropertyCode;
    return `
      <div class="prop-row ${selected ? 'prop-row-active' : ''}" data-prop-id="${escapeHtml(property.id)}" data-prop-code="${escapeHtml(property.propertyCode)}" style="display:flex;align-items:center;padding:12px 12px;border-bottom:1px solid rgba(255,255,255,0.05);gap:12px;cursor:pointer;border-left:${selected ? '3px solid var(--amber)' : '3px solid transparent'};background:${selected ? 'rgba(200,120,50,0.08)' : 'transparent'}">
        <div style="width:36px;height:36px;border-radius:8px;background:rgba(200,120,50,0.12);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;letter-spacing:0.08em;color:var(--amber);flex-shrink:0">PR</div>
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:500;color:var(--white);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escapeHtml(addr || property.propertyCode || property.propertyName)}</div>
          ${property.community ? `<div style="margin-top:2px;font-size:11px;color:var(--amber)">${escapeHtml(property.community)}</div>` : ''}
          <div style="font-size:11px;color:var(--dim);margin-top:2px">${escapeHtml(tags)}${amenities ? ` · ${escapeHtml(amenities)}` : ''}</div>
        </div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end;flex-shrink:0;margin-left:auto">
          ${renderLanePill(property, 'pre_booking', 'PB')}
          ${renderLanePill(property, 'guest_sessions', 'Stay')}
          ${property.dataSource ? `<span style="font-size:10px;color:var(--dim)">${escapeHtml(property.dataSource)}</span>` : ''}
        </div>
      </div>`;
  }).join('');
  const visibleCount = visibleProperties.length;

  container.innerHTML = `
    ${renderIdentityOps(identity)}
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:16px;flex-wrap:wrap">
      <div style="font-size:12px;color:rgba(240,235,227,0.62)">
        Showing <strong style="color:var(--white)">${escapeHtml(String(visibleCount))}</strong> of <strong style="color:var(--white)">${escapeHtml(String(state.count))}</strong> properties
        ${state.selectedPortfolioKey ? ` in <span style="color:var(--amber)">${escapeHtml(state.portfolios.find((item) => item.portfolioKey === state.selectedPortfolioKey)?.displayName || state.selectedPortfolioKey)}</span>` : ''}
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <select id="prop-portfolio-inline" class="form-select" style="min-width:180px">
          <option value="">All portfolios</option>
          ${state.portfolios.map((portfolio) => `<option value="${escapeHtml(portfolio.portfolioKey)}" ${portfolio.portfolioKey === state.selectedPortfolioKey ? 'selected' : ''}>${escapeHtml(portfolio.displayName)} (${escapeHtml(String(portfolio.propertyCount || 0))})</option>`).join('')}
        </select>
        <input id="prop-search-inline" class="form-input" placeholder="Search properties..." value="${escapeHtml(getSearchQuery())}" style="width:220px;padding:6px 12px;font-size:12px">
      </div>
    </div>
    <div id="prop-rows">${rows || '<div class="empty"><div class="empty-title">No properties match this slice</div><div class="empty-sub">Try a different portfolio, lifecycle lane, or search query.</div></div>'}</div>
    <div id="prop-detail-panel" style="margin-top:16px">${renderPropertyDetail()}</div>
  `;

  const search = document.getElementById('prop-search-inline');
  if (search) {
    search.addEventListener('input', () => {
      const topSearch = document.getElementById('prop-search-input');
      if (topSearch && topSearch.value !== search.value) topSearch.value = search.value;
      renderList();
    });
  }
  const inlinePortfolio = document.getElementById('prop-portfolio-inline');
  if (inlinePortfolio) {
    inlinePortfolio.addEventListener('change', () => {
      state.selectedPortfolioKey = inlinePortfolio.value || '';
      const topPortfolio = document.getElementById('prop-portfolio-filter');
      if (topPortfolio && topPortfolio.value !== inlinePortfolio.value) topPortfolio.value = inlinePortfolio.value;
      renderList();
    });
  }

  container.querySelectorAll('.prop-row').forEach((row) => {
    row.addEventListener('click', () => {
      selectProperty(row.getAttribute('data-prop-code') || '');
    });
  });
}

function renderIdentityOps(identity) {
  const importResult = state.importResult;
  const documentResult = state.documentImportResult;
  const selectedPropertyCode = state.selectedPropertyCode || state.properties[0]?.propertyCode || '';
  const recentIngestEvents = Array.isArray(state.identityReport?.recent_ingest_events) ? state.identityReport.recent_ingest_events.slice(0, 3) : [];
  const importProfilesJson = JSON.stringify(state.importProfiles || {}, null, 2);
  return `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin-bottom:16px">
      <div class="card" style="padding:16px;background:rgba(255,255,255,0.03);border:1px solid var(--border);display:flex;flex-direction:column;gap:12px">
        <div>
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:6px">Property Uploads</div>
          <div style="font-size:14px;color:var(--white);font-weight:600">Upload property tables for future operators</div>
          <div style="font-size:12px;color:var(--dim);margin-top:4px;line-height:1.6">CSV, TSV, XLSX, XLS, and JSON uploads feed the same canonical property store used by PMS sync, property intelligence, and messaging.</div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <select id="property-upload-source" class="form-select" style="min-width:160px">
            <option value="dashboard_upload">Operator upload</option>
            <option value="owner_property_sheet">Owner property sheet</option>
            <option value="portfolio_reference">Portfolio reference</option>
          </select>
          <input id="property-upload-file" type="file" class="form-input" accept=".csv,.tsv,.xlsx,.xls,.json" style="flex:1;min-width:180px;padding:8px 10px">
          <button class="btn btn-primary" id="property-upload-btn">Upload</button>
        </div>
        <div style="font-size:11px;color:rgba(240,235,227,0.58);line-height:1.55">Best columns to include: <code>property_id</code>, <code>unit_code</code>, <code>name</code>, <code>address</code>, <code>community</code>, OTA ids, operational notes, and amenity fields.</div>
        ${importResult ? `
          <div style="padding:12px;border-radius:10px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);display:flex;flex-direction:column;gap:6px">
            <div style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(importResult.filename || 'Latest import')}</div>
            <div style="font-size:11px;color:rgba(240,235,227,0.68)">Rows ${escapeHtml(String(importResult.rowsReceived || 0))} · inserted ${escapeHtml(String(importResult.inserted || 0))} · updated ${escapeHtml(String(importResult.updated || 0))} · vector indexed ${escapeHtml(String(importResult.vectorIndexed || 0))}</div>
            ${importResult.ingestEventId ? `<div style="font-size:11px;color:rgba(240,235,227,0.58)">Ingest event ${escapeHtml(importResult.ingestEventId)}</div>` : ''}
            ${importResult.mappingProfilesUsed?.length ? `<div style="font-size:11px;color:rgba(240,235,227,0.58)">Mapping profile${importResult.mappingProfilesUsed.length > 1 ? 's' : ''}: ${escapeHtml(importResult.mappingProfilesUsed.join(', '))}</div>` : ''}
            <div style="font-size:11px;color:rgba(240,235,227,0.68)">Observed columns ${escapeHtml(String(importResult.observedColumns?.length || 0))} · preserved raw fields ${escapeHtml(String(importResult.preservedFieldCount || 0))}${(importResult.rowsWithUnmappedFields || 0) ? ` · ${escapeHtml(String(importResult.rowsWithUnmappedFields))} row(s) had unmapped fields` : ''}</div>
            ${importResult.unmappedColumns?.length ? `<div style="font-size:11px;color:var(--amber)">Unmapped columns preserved for review: ${escapeHtml(importResult.unmappedColumns.join(', '))}</div>` : '<div style="font-size:11px;color:#86efac">All non-empty columns mapped into canonical fields or known metadata.</div>'}
            ${importResult.warnings?.length ? `<div style="font-size:11px;color:var(--amber)">Warnings: ${escapeHtml(importResult.warnings.join(' | '))}</div>` : ''}
            ${importResult.errors?.length ? `<div style="font-size:11px;color:#f87171">Errors: ${escapeHtml(importResult.errors.join(' | '))}</div>` : '<div style="font-size:11px;color:#86efac">Import completed without row-level errors.</div>'}
          </div>
        ` : ''}
      </div>
      <div class="card" style="padding:16px;background:rgba(255,255,255,0.03);border:1px solid var(--border);display:flex;flex-direction:column;gap:12px">
        <div>
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:6px">Document Ingest</div>
          <div style="font-size:14px;color:var(--white);font-weight:600">Load manuals, rental docs, and warranty records</div>
          <div style="font-size:12px;color:var(--dim);margin-top:4px;line-height:1.6">Property-scoped uploads enrich unit knowledge and assets. Portfolio scope is for broad policies like rental agreement terms, discount rules, and portfolio-wide guidance.</div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px">
          <select id="property-document-type" class="form-select">
            <option value="house_manual">House manual / guidebook</option>
            <option value="amenities">Amenities sheet</option>
            <option value="guest_qa">Guest Q&A history</option>
            <option value="rental_agreement">Rental agreement</option>
            <option value="equipment_warranty">Equipment warranty</option>
            <option value="appliance_manual">Appliance manual</option>
            <option value="portfolio_policy">Portfolio policy</option>
            <option value="misc">Misc document</option>
          </select>
          <select id="property-document-target" class="form-select">
            <option value="knowledge">Knowledge</option>
            <option value="both">Knowledge + asset</option>
            <option value="asset">Asset only</option>
          </select>
          <select id="property-document-scope" class="form-select">
            <option value="property">Selected property</option>
            <option value="portfolio">Portfolio-wide</option>
          </select>
          <select id="property-document-asset-type" class="form-select">
            <option value="">Infer asset type</option>
            <option value="warranty">Warranty</option>
            <option value="hvac">HVAC</option>
            <option value="pool_equipment">Pool equipment</option>
            <option value="refrigerator">Refrigerator</option>
            <option value="appliance">Appliance</option>
            <option value="document">General document</option>
          </select>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <input id="property-document-asset-name" class="form-input" placeholder="Optional asset name (for warranty/manual docs)" style="flex:1;min-width:220px">
          <input id="property-document-file" type="file" class="form-input" accept=".pdf,.doc,.docx,.txt,.csv,.tsv,.xlsx,.xls,.json,.png,.jpg,.jpeg,.tiff" style="flex:1;min-width:220px;padding:8px 10px">
          <button class="btn btn-primary" id="property-document-upload-btn">Upload</button>
        </div>
        <div style="font-size:11px;color:rgba(240,235,227,0.58);line-height:1.55">Current selected property: <code>${escapeHtml(selectedPropertyCode || 'none')}</code>. Use portfolio scope for rules that should apply across the whole operator.</div>
        ${documentResult ? `
          <div style="padding:12px;border-radius:10px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);display:flex;flex-direction:column;gap:6px">
            <div style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(documentResult.filename || 'Latest document import')}</div>
            <div style="font-size:11px;color:rgba(240,235,227,0.68)">Type ${escapeHtml(documentResult.documentType || 'document')} · target ${escapeHtml(documentResult.target || 'knowledge')} · extracted ${escapeHtml(String(documentResult.fieldsExtracted || 0))} field(s)</div>
            ${documentResult.guestQaSummary ? `<div style="font-size:11px;color:#86efac">Guest Q&A imported: ${escapeHtml(documentResult.guestQaSummary)}</div>` : ''}
            ${documentResult.assetResult ? `<div style="font-size:11px;color:#86efac">Asset updated: ${escapeHtml(documentResult.assetResult)}</div>` : ''}
            ${documentResult.warnings?.length ? `<div style="font-size:11px;color:var(--amber)">Warnings: ${escapeHtml(documentResult.warnings.join(' | '))}</div>` : '<div style="font-size:11px;color:#86efac">Document processed successfully.</div>'}
          </div>
        ` : ''}
      </div>
      <div class="card" style="padding:16px;background:rgba(255,255,255,0.03);border:1px solid var(--border);display:flex;flex-direction:column;gap:10px">
        <div>
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:6px">Identity Coverage</div>
          <div style="font-size:14px;color:var(--white);font-weight:600">What PMS sync and uploads have populated</div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px">
          ${metricChip('Display names', identity.withDisplayName || 0, state.count)}
          ${metricChip('PMS property IDs', identity.withPmsPropertyId || 0, state.count)}
          ${metricChip('PMS unit codes', identity.withPmsUnitCode || 0, state.count)}
          ${metricChip('Any OTA refs', identity.withAnyOtaId || 0, state.count)}
          ${metricChip('Property KB', identity.withPropertyKnowledge || 0, state.count)}
          ${metricChip('Asset records', identity.withAssetRecords || 0, state.count)}
          ${metricChip('Portfolio KB', identity.portfolioKnowledgeRecords || 0, null)}
        </div>
        <div style="font-size:11px;color:rgba(240,235,227,0.58);line-height:1.6">Portfolio-wide rules like discounts or special offers should live in KB records scoped to <code>__all_properties__</code>. Property-specific facts stay attached to the unit’s property code and canonical property identity.</div>
        ${recentIngestEvents.length ? `
          <div style="margin-top:4px;display:flex;flex-direction:column;gap:8px">
            <div style="font-size:10px;color:rgba(240,235,227,0.55);font-family:'DM Mono',monospace;letter-spacing:0.08em;text-transform:uppercase">Recent Ingests</div>
            ${recentIngestEvents.map((event) => `
              <div style="padding:10px;border-radius:10px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.08)">
                <div style="font-size:11px;color:var(--white)">${escapeHtml(event.source_label || event.source_type || 'import')}</div>
                <div style="font-size:10px;color:rgba(240,235,227,0.58);margin-top:3px">
                  ${escapeHtml(String(event.row_count || 0))} row(s) · ${escapeHtml(String(event.inserted_count || 0))} inserted · ${escapeHtml(String(event.updated_count || 0))} updated
                  ${(event.rows_with_unmapped_fields || 0) ? ` · ${escapeHtml(String(event.rows_with_unmapped_fields))} row(s) preserved unmapped fields` : ''}
                </div>
                <div style="margin-top:8px;display:flex;justify-content:flex-end">
                  <button class="btn btn-sm property-ingest-replay" data-ingest-event-id="${escapeHtml(event.ingest_event_id || '')}">Replay</button>
                </div>
              </div>
            `).join('')}
          </div>
        ` : ''}
      </div>
      <div class="card" style="padding:16px;background:rgba(255,255,255,0.03);border:1px solid var(--border);display:flex;flex-direction:column;gap:12px">
        <div>
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:6px">Import Profiles</div>
          <div style="font-size:14px;color:var(--white);font-weight:600">Adjust upload mappings without a deploy</div>
          <div style="font-size:12px;color:var(--dim);margin-top:4px;line-height:1.6">Profiles extend the built-in alias system. Use normalized JSON to add operator-specific column mappings for recurring spreadsheets or exports.</div>
        </div>
        <textarea id="property-import-profiles-json" class="form-input" style="min-height:220px;font-family:'DM Mono',monospace;font-size:11px;line-height:1.5;white-space:pre;resize:vertical">${escapeHtml(importProfilesJson)}</textarea>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn-primary" id="property-import-profiles-save-btn">Save Profiles</button>
          <button class="btn" id="property-import-profiles-refresh-btn">Reload</button>
        </div>
      </div>
    </div>
    ${renderIdentityReviews()}
  `;
}

function metricChip(label, value, total) {
  const suffix = total != null ? ` / ${total}` : '';
  return `
    <div style="padding:12px;border-radius:10px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.08)">
      <div style="font-size:10px;color:rgba(240,235,227,0.55);font-family:'DM Mono',monospace;letter-spacing:0.08em;text-transform:uppercase">${escapeHtml(label)}</div>
      <div style="font-size:18px;color:var(--white);font-weight:600;margin-top:4px">${escapeHtml(String(value || 0))}<span style="font-size:12px;color:rgba(240,235,227,0.45)">${escapeHtml(suffix)}</span></div>
    </div>
  `;
}

function renderIdentityReviews() {
  const reviews = Array.isArray(state.identityReviews) ? state.identityReviews : [];
  return `
    <div class="card" style="padding:16px;background:rgba(255,255,255,0.02);border:1px solid var(--border);margin-bottom:16px;display:flex;flex-direction:column;gap:12px">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap">
        <div>
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:6px">Identity Reviews</div>
          <div style="font-size:14px;color:var(--white);font-weight:600">Approve uncertain PMS or OTA property mappings</div>
          <div style="font-size:12px;color:var(--dim);margin-top:4px;line-height:1.6">High-confidence mappings are learned automatically. Ambiguous names, IDs, or aliases land here for operator confirmation before they touch the canonical graph.</div>
        </div>
        <span class="badge badge-dim" style="font-size:10px">${escapeHtml(String(reviews.length))} pending</span>
      </div>
      ${reviews.length ? reviews.map((review) => `
        <div style="padding:12px;border-radius:10px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);display:flex;flex-direction:column;gap:8px">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <span class="badge badge-amber" style="font-size:9px">${escapeHtml(review.provider || 'unknown')}</span>
            <span class="badge badge-dim" style="font-size:9px">${escapeHtml(review.refKind || 'alias')}</span>
            ${review.propertyName ? `<span style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(review.propertyName)}</span>` : ''}
            <span style="margin-left:auto;font-size:11px;color:rgba(240,235,227,0.6)">confidence ${escapeHtml(String(Math.round((review.confidence || 0) * 100)))}%</span>
          </div>
          <div style="font-size:11px;color:rgba(240,235,227,0.68);line-height:1.6">
            ref ${escapeHtml(review.refValue || '')}
            ${review.platformListingId ? ` · listing ${escapeHtml(review.platformListingId)}` : ''}
            ${review.platformUnitId ? ` · unit ${escapeHtml(review.platformUnitId)}` : ''}
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <select class="form-select property-review-candidate" data-review-id="${escapeHtml(String(review.reviewId))}" style="min-width:260px;flex:1">
              ${(review.candidates || []).map((candidate) => `<option value="${escapeHtml(candidate.property_code || '')}">${escapeHtml(candidate.property_code || 'unknown')} · ${escapeHtml(candidate.display_name || candidate.address_street || candidate.property_name || 'property')}</option>`).join('')}
            </select>
            <button class="btn btn-sm property-review-approve" data-review-id="${escapeHtml(String(review.reviewId))}">Approve</button>
            <button class="btn btn-sm property-review-reject" data-review-id="${escapeHtml(String(review.reviewId))}">Reject</button>
          </div>
        </div>
      `).join('') : '<div style="font-size:12px;color:var(--dim)">No pending identity reviews right now.</div>'}
    </div>
  `;
}

function renderPropertyDetail() {
  const property = state.properties.find((item) => item.propertyCode === state.selectedPropertyCode);
  if (!property) {
    return `
      <div class="card" style="padding:16px;background:rgba(255,255,255,0.02);border:1px solid var(--border)">
        <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:8px">Property data</div>
        <div style="font-size:12px;color:var(--dim)">Select a property to review asset, warranty, and maintenance context.</div>
      </div>
    `;
  }
  const assets = Array.isArray(state.assetsByProperty[property.propertyCode]) ? state.assetsByProperty[property.propertyCode] : [];
  return `
    <div class="card" style="padding:16px;background:rgba(255,255,255,0.02);border:1px solid var(--border);display:flex;flex-direction:column;gap:12px">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap">
        <div>
          <div style="font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--amber);margin-bottom:6px">Property data</div>
          <div style="font-size:15px;color:var(--white);font-weight:600">${escapeHtml(property.propertyName || property.propertyCode)}</div>
          <div style="font-size:11px;color:rgba(240,235,227,0.58);margin-top:4px">${escapeHtml(property.propertyCode)}</div>
        </div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          ${property.assetCount ? `<span class="badge badge-dim" style="font-size:10px">${escapeHtml(String(property.assetCount))} asset records</span>` : ''}
          <button class="btn btn-sm" id="prop-refresh-assets-btn">Refresh assets</button>
        </div>
      </div>
      ${assets.length ? `
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px">
          ${assets.map((asset) => `
            <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.03);display:flex;flex-direction:column;gap:6px">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                <span style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(asset.asset_name || asset.asset_type || 'Asset')}</span>
                <span class="badge badge-dim" style="font-size:9px">${escapeHtml(asset.asset_type || 'asset')}</span>
                <span class="badge ${asset.status === 'active' ? 'badge-green' : 'badge-amber'}" style="font-size:9px">${escapeHtml(asset.status || 'active')}</span>
              </div>
              <div style="font-size:11px;color:rgba(240,235,227,0.7);line-height:1.5">
                ${escapeHtml(asset.manufacturer || 'Unknown manufacturer')}
                ${asset.model_number ? ` · ${escapeHtml(asset.model_number)}` : ''}
                ${asset.serial_number ? ` · S/N ${escapeHtml(asset.serial_number)}` : ''}
              </div>
              <div style="display:flex;gap:6px;flex-wrap:wrap;font-size:10px;color:rgba(240,235,227,0.5);font-family:'DM Mono',monospace">
                <span>Warranty ${escapeHtml(asset.warranty_scope || 'none')}</span>
                ${asset.warranty_provider ? `<span>${escapeHtml(asset.warranty_provider)}</span>` : ''}
                ${asset.install_vendor_name ? `<span>Installed by ${escapeHtml(asset.install_vendor_name)}</span>` : ''}
              </div>
              <div style="font-size:11px;color:rgba(240,235,227,0.6);line-height:1.5">
                ${asset.install_date ? `Installed ${escapeHtml(fmtDate(asset.install_date))}` : 'Install date not recorded'}
                ${asset.last_service_at ? ` · Last serviced ${escapeHtml(fmtDate(asset.last_service_at))}` : ''}
              </div>
              ${asset.warranty_end_date || asset.parts_warranty_end_date || asset.labor_warranty_end_date ? `
                <div style="font-size:11px;color:rgba(240,235,227,0.58);line-height:1.5">
                  ${asset.warranty_end_date ? `Warranty ends ${escapeHtml(fmtDate(asset.warranty_end_date))}` : ''}
                  ${asset.parts_warranty_end_date ? `${asset.warranty_end_date ? ' · ' : ''}Parts ${escapeHtml(fmtDate(asset.parts_warranty_end_date))}` : ''}
                  ${asset.labor_warranty_end_date ? `${asset.warranty_end_date || asset.parts_warranty_end_date ? ' · ' : ''}Labor ${escapeHtml(fmtDate(asset.labor_warranty_end_date))}` : ''}
                </div>
              ` : ''}
              ${asset.last_work_order_id ? `<div style="font-size:11px;color:rgba(240,235,227,0.5)">Last work order ${escapeHtml(asset.last_work_order_id.slice(0, 8))}</div>` : ''}
              ${asset.notes ? `<div style="font-size:11px;color:rgba(240,235,227,0.58);line-height:1.5">${escapeHtml(asset.notes)}</div>` : ''}
            </div>
          `).join('')}
        </div>
      ` : '<div style="font-size:12px;color:var(--dim)">No property assets recorded yet for this unit.</div>'}
    </div>
  `;
}

async function selectProperty(propertyCode) {
  if (!propertyCode) return;
  state.selectedPropertyCode = propertyCode;
  if (!state.assetsByProperty[propertyCode]) {
    try {
      const payload = await api.propertyAssets.list(propertyCode);
      state.assetsByProperty[propertyCode] = Array.isArray(payload.assets) ? payload.assets : [];
    } catch (error) {
      state.assetsByProperty[propertyCode] = [];
      window.alert(error.message || 'Could not load property assets.');
    }
  }
  renderList();
  const refreshBtn = document.getElementById('prop-refresh-assets-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', async () => {
      delete state.assetsByProperty[propertyCode];
      await selectProperty(propertyCode);
    });
  }
}

async function loadProperties() {
  const container = document.getElementById('prop-list-container');
  if (container) container.innerHTML = renderInlineError('Loading properties…', 'Pulling portfolio and AI autonomy state.');
  try {
    await loadImportProfiles();
    const [propertiesPayload, summaryPayload, identityPayload, reviewPayload, portfolioPayload] = await Promise.all([
      api.propertiesAutonomy.list(),
      api.summary(),
      api.propertyIdentity.report(),
      api.propertyLinks.reviews('pending'),
      api.portfolios.list(),
    ]);
    const normalized = normalizePropertiesAutonomy(propertiesPayload);
    const summary = normalizeDashboardSummary(summaryPayload);
    state.properties = normalized.properties;
    state.count = normalized.count;
    state.summary = normalized.summary;
    state.portfolios = Array.isArray(portfolioPayload?.portfolios) ? portfolioPayload.portfolios.map((item) => ({
      portfolioId: item.portfolio_id || '',
      portfolioKey: item.portfolio_key || '',
      displayName: item.display_name || item.portfolio_key || 'Portfolio',
      propertyCount: Number(item.property_count || 0),
      propertyExternalIds: Array.isArray(item.property_external_ids) ? item.property_external_ids : [],
    })) : [];
    state.identityReport = {
      summary: {
        ...(identityPayload?.summary || {}),
        withDisplayName: Number(identityPayload?.summary?.with_display_name || 0),
        withPmsPropertyId: Number(identityPayload?.summary?.with_pms_property_id || 0),
        withPmsUnitCode: Number(identityPayload?.summary?.with_pms_unit_code || 0),
        withAnyOtaId: Number(identityPayload?.summary?.with_any_ota_id || 0),
        withPropertyKnowledge: Number(identityPayload?.summary?.with_property_knowledge || 0),
        withAssetRecords: Number(identityPayload?.summary?.with_asset_records || 0),
        portfolioKnowledgeRecords: Number(identityPayload?.summary?.portfolio_knowledge_records || 0),
      },
      properties: Array.isArray(identityPayload?.properties) ? identityPayload.properties : [],
      recent_ingest_events: Array.isArray(identityPayload?.recent_ingest_events) ? identityPayload.recent_ingest_events : [],
    };
    const identityByCode = new Map(state.identityReport.properties.map((item) => [item.property_code, item]));
    state.properties = state.properties.map((property) => {
      const identityMeta = identityByCode.get(property.propertyCode) || {};
      return {
        ...property,
        assetCount: Number(identityMeta.asset_count || 0),
      };
    });
    state.identityReviews = Array.isArray(reviewPayload?.reviews) ? reviewPayload.reviews.map((review) => ({
      reviewId: review.review_id,
      provider: review.provider || '',
      refKind: review.ref_kind || '',
      refValue: review.ref_value || '',
      platformListingId: review.platform_listing_id || '',
      platformUnitId: review.platform_unit_id || '',
      propertyName: review.property_name || review.display_name || '',
      confidence: Number(review.confidence || 0),
      candidates: Array.isArray(review.candidates) ? review.candidates : [],
    })) : [];
    if (!state.selectedPropertyCode && state.properties[0]) {
      state.selectedPropertyCode = state.properties[0].propertyCode;
    }
    renderStats(summary);
    renderList();
    if (state.selectedPropertyCode) await selectProperty(state.selectedPropertyCode);
  } catch (error) {
    if (container) {
      container.innerHTML = renderInlineError('Could not load properties', error.message || String(error), 'properties-retry');
      const btn = document.getElementById('properties-retry');
      if (btn) btn.addEventListener('click', loadProperties);
    }
  }
}

async function setPropAutonomy(propertyId, mode, buttonEl) {
  const pill = buttonEl?.closest('.autonomy-pill');
  const stageScope = pill?.getAttribute('data-stage-scope') || 'all';
  if (pill) pill.style.opacity = '0.5';
  try {
    await api.propertiesAutonomy.update(propertyId, { approval_mode: mode, stage_scope: stageScope });
    await loadProperties();
    if (window.loadOnboardingStatus) window.loadOnboardingStatus();
  } catch (error) {
    if (pill) pill.style.opacity = '1';
    alert('Could not update: ' + (error.message || 'unknown error'));
  }
}

async function bulkSetAutonomy(mode) {
  const visibleProperties = getVisibleProperties();
  const stageScope = state.autonomyStageScope || 'all';
  const targetLabel = stageScope === 'pre_booking'
    ? 'pre-booking'
    : stageScope === 'guest_sessions'
      ? 'guest sessions'
      : 'all messaging';
  const label = mode === 'auto' ? 'Auto-send' : 'Review required';
  const targetCount = visibleProperties.length;
  if (!targetCount) {
    window.alert('There are no visible properties in this slice to update.');
    return;
  }
  const confirmMsg = mode === 'auto'
    ? `Switch ${targetCount} visible propert${targetCount === 1 ? 'y' : 'ies'} to Auto-send for ${targetLabel}?\n\nReplies with confidence ≥ 95% will send without your review.`
    : `Switch ${targetCount} visible propert${targetCount === 1 ? 'y' : 'ies'} back to Review mode for ${targetLabel}?\n\nEvery AI draft in that lane will wait for approval.`;
  if (!window.confirm(confirmMsg)) return;
  try {
    const result = await api.propertiesAutonomy.bulk({
      approval_mode: mode,
      property_ids: visibleProperties.map((property) => property.id),
      stage_scope: stageScope,
    });
    await loadProperties();
    if (window.loadOnboardingStatus) window.loadOnboardingStatus();
    window.alert(`${targetLabel} set to ${label}${result.updated ? ` (${result.updated} updated)` : ''}`);
  } catch (error) {
    window.alert('Bulk update failed: ' + (error.message || 'unknown error'));
  }
}

async function uploadPropertyTable() {
  const fileInput = document.getElementById('property-upload-file');
  const sourceSelect = document.getElementById('property-upload-source');
  const file = fileInput?.files?.[0];
  if (!file) {
    window.alert('Choose a property table to upload first.');
    return;
  }
  const sourceLabel = sourceSelect?.value || 'dashboard_upload';
  try {
    const payload = await api.propertyImports.upload(file, sourceLabel);
    state.importResult = {
      filename: payload.filename || file.name,
      ingestEventId: payload.ingest_event_id || '',
      rowsReceived: payload.rows_received || 0,
      inserted: payload.inserted || 0,
      updated: payload.updated || 0,
      vectorIndexed: payload.vector_indexed || 0,
      observedColumns: Array.isArray(payload.observed_columns) ? payload.observed_columns : [],
      unmappedColumns: Array.isArray(payload.unmapped_columns) ? payload.unmapped_columns : [],
      rowsWithUnmappedFields: payload.rows_with_unmapped_fields || 0,
      preservedFieldCount: payload.preserved_field_count || 0,
      mappingProfilesUsed: Array.isArray(payload.mapping_profiles_used) ? payload.mapping_profiles_used : [],
      warnings: Array.isArray(payload.warnings) ? payload.warnings : [],
      errors: Array.isArray(payload.errors) ? payload.errors : [],
    };
    if (fileInput) fileInput.value = '';
    await loadProperties();
  } catch (error) {
    window.alert(error.message || 'Property upload failed.');
  }
}

async function uploadPropertyDocument() {
  const fileInput = document.getElementById('property-document-file');
  const typeSelect = document.getElementById('property-document-type');
  const targetSelect = document.getElementById('property-document-target');
  const scopeSelect = document.getElementById('property-document-scope');
  const assetTypeSelect = document.getElementById('property-document-asset-type');
  const assetNameInput = document.getElementById('property-document-asset-name');
  const file = fileInput?.files?.[0];
  if (!file) {
    window.alert('Choose a document to upload first.');
    return;
  }
  const scope = scopeSelect?.value || 'property';
  const propertyCode = scope === 'portfolio' ? '' : (state.selectedPropertyCode || state.properties[0]?.propertyCode || '');
  try {
    const payload = await api.propertyDocuments.upload({
      file,
      documentType: typeSelect?.value || 'misc',
      target: targetSelect?.value || 'knowledge',
      scope,
      propertyCode,
      assetType: assetTypeSelect?.value || '',
      assetName: assetNameInput?.value || '',
      sourceLabel: 'dashboard_document_upload',
    });
    state.documentImportResult = {
      filename: payload.filename || file.name,
      documentType: payload.document_type || typeSelect?.value || 'document',
      target: payload.target || targetSelect?.value || 'knowledge',
      fieldsExtracted: payload.fields_extracted || 0,
      warnings: Array.isArray(payload.warnings) ? payload.warnings : [],
      guestQaSummary: payload.guest_qa_result
        ? `${payload.guest_qa_result.imported_answers || 0} answers, ${payload.guest_qa_result.imported_gaps || 0} gaps`
        : '',
      assetResult: payload.asset_result?.asset_id ? `saved ${String(payload.asset_result.asset_id).slice(0, 8)}` : '',
    };
    if (fileInput) fileInput.value = '';
    if (assetNameInput) assetNameInput.value = '';
    await loadProperties();
    if (propertyCode) {
      delete state.assetsByProperty[propertyCode];
      await selectProperty(propertyCode);
    }
  } catch (error) {
    window.alert(error.message || 'Document upload failed.');
  }
}

async function loadImportProfiles() {
  try {
    const payload = await api.propertyImports.profiles();
    state.importProfiles = payload?.profiles && typeof payload.profiles === 'object' ? payload.profiles : {};
  } catch (_) {
    state.importProfiles = {};
  }
}

async function saveImportProfiles() {
  const input = document.getElementById('property-import-profiles-json');
  const raw = input?.value || '{}';
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (_) {
    window.alert('Import profiles must be valid JSON.');
    return;
  }
  try {
    const payload = await api.propertyImports.saveProfiles(parsed);
    state.importProfiles = payload?.profiles && typeof payload.profiles === 'object' ? payload.profiles : {};
    renderList();
    window.alert('Import profiles saved.');
  } catch (error) {
    window.alert(error.message || 'Could not save import profiles.');
  }
}

async function replayIngestEvent(ingestEventId) {
  if (!ingestEventId) return;
  if (!window.confirm('Replay this ingest event through the current mapping profiles?')) return;
  try {
    const payload = await api.propertyImports.replay(ingestEventId);
    state.importResult = {
      filename: `Replay ${ingestEventId}`,
      ingestEventId: payload.new_ingest_event_id || '',
      rowsReceived: payload.count || 0,
      inserted: payload.inserted || 0,
      updated: payload.updated || 0,
      vectorIndexed: payload.vector_indexed || 0,
      observedColumns: Array.isArray(payload.observed_columns) ? payload.observed_columns : [],
      unmappedColumns: Array.isArray(payload.unmapped_columns) ? payload.unmapped_columns : [],
      rowsWithUnmappedFields: payload.rows_with_unmapped_fields || 0,
      preservedFieldCount: payload.preserved_field_count || 0,
      mappingProfilesUsed: Array.isArray(payload.mapping_profiles_used) ? payload.mapping_profiles_used : [],
      warnings: Array.isArray(payload.warnings) ? payload.warnings : [],
      errors: Array.isArray(payload.errors) ? payload.errors : [],
    };
    await loadProperties();
  } catch (error) {
    window.alert(error.message || 'Could not replay ingest event.');
  }
}

async function approveIdentityReview(reviewId) {
  const select = document.querySelector(`.property-review-candidate[data-review-id="${CSS.escape(String(reviewId))}"]`);
  const canonicalPropertyCode = select?.value || '';
  if (!canonicalPropertyCode) {
    window.alert('Select a property before approving this review.');
    return;
  }
  try {
    await api.propertyLinks.approveReview(reviewId, { canonical_property_code: canonicalPropertyCode });
    await loadProperties();
  } catch (error) {
    window.alert(error.message || 'Could not approve property review.');
  }
}

async function rejectIdentityReview(reviewId) {
  try {
    await api.propertyLinks.rejectReview(reviewId);
    await loadProperties();
  } catch (error) {
    window.alert(error.message || 'Could not reject property review.');
  }
}

function isPropertiesView() {
  const root = document.getElementById('view-properties');
  return !!root && root.style.display !== 'none';
}

function wireDom() {
  const container = document.getElementById('prop-list-container');
  if (container && container.dataset.wired !== '1') {
    container.dataset.wired = '1';
    container.addEventListener('click', (event) => {
      const uploadBtn = event.target.closest('#property-upload-btn');
      if (uploadBtn) {
        uploadPropertyTable();
        return;
      }
      const documentUploadBtn = event.target.closest('#property-document-upload-btn');
      if (documentUploadBtn) {
        uploadPropertyDocument();
        return;
      }
      const saveProfilesBtn = event.target.closest('#property-import-profiles-save-btn');
      if (saveProfilesBtn) {
        saveImportProfiles();
        return;
      }
      const reloadProfilesBtn = event.target.closest('#property-import-profiles-refresh-btn');
      if (reloadProfilesBtn) {
        loadProperties();
        return;
      }
      const replayBtn = event.target.closest('.property-ingest-replay');
      if (replayBtn) {
        replayIngestEvent(replayBtn.getAttribute('data-ingest-event-id') || '');
        return;
      }
      const approveBtn = event.target.closest('.property-review-approve');
      if (approveBtn) {
        approveIdentityReview(approveBtn.getAttribute('data-review-id') || '');
        return;
      }
      const rejectBtn = event.target.closest('.property-review-reject');
      if (rejectBtn) {
        rejectIdentityReview(rejectBtn.getAttribute('data-review-id') || '');
        return;
      }
      const button = event.target.closest('.autonomy-seg');
      if (!button) return;
      const pill = button.closest('.autonomy-pill');
      const propertyId = pill?.getAttribute('data-prop-id');
      const mode = button.getAttribute('data-mode');
      if (propertyId && mode) setPropAutonomy(propertyId, mode, button);
    });
  }
  const topSearch = document.getElementById('prop-search-input');
  if (topSearch && topSearch.dataset.wired !== '1') {
    topSearch.dataset.wired = '1';
    topSearch.addEventListener('input', () => {
      const inlineSearch = document.getElementById('prop-search-inline');
      if (inlineSearch && inlineSearch.value !== topSearch.value) inlineSearch.value = topSearch.value;
      renderList();
    });
  }
  const portfolioFilter = document.getElementById('prop-portfolio-filter');
  if (portfolioFilter && portfolioFilter.dataset.wired !== '1') {
    portfolioFilter.dataset.wired = '1';
    portfolioFilter.addEventListener('change', () => {
      state.selectedPortfolioKey = portfolioFilter.value || '';
      const inlinePortfolio = document.getElementById('prop-portfolio-inline');
      if (inlinePortfolio && inlinePortfolio.value !== portfolioFilter.value) inlinePortfolio.value = portfolioFilter.value;
      renderList();
    });
  }
  const stageScope = document.getElementById('prop-autonomy-stage-scope');
  if (stageScope && stageScope.dataset.wired !== '1') {
    stageScope.dataset.wired = '1';
    stageScope.addEventListener('change', () => {
      state.autonomyStageScope = stageScope.value || 'all';
      renderStats();
    });
  }
}

export function init() {
  window.__oyvodaPropertiesModule = true;
  wireDom();
  window.setPropAutonomy = setPropAutonomy;
  window.bulkSetAutonomy = bulkSetAutonomy;
  window.addEventListener('oyvoda:view-changed', (event) => {
    if (event.detail?.view === 'properties') {
      loadProperties();
    }
  });
  if (isPropertiesView()) {
    loadProperties();
  }
}
