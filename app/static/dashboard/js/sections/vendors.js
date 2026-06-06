import api from '../api.js?v=2026-04-23-a';
import { closeModal, escapeHtml, safeUrl } from '../ui.js?v=2026-04-21-a';
import { normalizeVendorCategories, normalizeVendors, renderInlineError } from '../adapters.js?v=2026-04-23-a';

const state = {
  categories: [],
  vendors: [],
  properties: [],
  loaded: false,
};

function splitTags(value) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

function joinTags(values) {
  return Array.isArray(values) ? values.join(', ') : '';
}

function groupVendors() {
  const grouped = new Map();
  state.categories.forEach((category) => grouped.set(category.slug, { category, vendors: [] }));
  state.vendors.forEach((vendor) => {
    if (!grouped.has(vendor.categorySlug)) {
      grouped.set(vendor.categorySlug, {
        category: {
          slug: vendor.categorySlug,
          displayName: vendor.categorySlug || 'Uncategorized',
          icon: '',
          workflowGroup: vendor.workflowGroup,
          vendorCount: 0,
        },
        vendors: [],
      });
    }
    grouped.get(vendor.categorySlug).vendors.push(vendor);
  });
  return Array.from(grouped.values()).sort((a, b) => {
    return (a.category.sortOrder || 999) - (b.category.sortOrder || 999) || a.category.displayName.localeCompare(b.category.displayName);
  });
}

function renderStats() {
  const groups = groupVendors();
  const total = state.vendors.length;
  const categoriesWithVendors = groups.filter((group) => group.vendors.length > 0).length;
  const fallbacks = groups.filter((group) => group.vendors.length > 1).length;
  const referrals = state.vendors.reduce((sum, vendor) => sum + Number(vendor.referralCount || 0), 0);

  const set = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = String(value);
  };
  set('vnd-stat-total', total);
  set('vnd-stat-cats', categoriesWithVendors);
  set('vnd-stat-fallbacks', fallbacks);
  set('vnd-stat-referrals', referrals);
}

function renderVendorOperationalMeta(vendor) {
  const meta = vendor.operationalMetadata || {};
  const chips = [];
  if (vendor.applyScope === 'all' || !vendor.applyScope) chips.push('All properties');
  if (vendor.applyScope === 'property_specific' && vendor.propertyIds?.length) chips.push(`${vendor.propertyIds.length} scoped properties`);
  if (meta.warrantyCapable) chips.push('Warranty safe');
  if (meta.warrantyOnly) chips.push('Warranty only');
  if (meta.emergencyCapable) chips.push('Emergency capable');
  if (meta.emergencyOverrideOnly) chips.push('Emergency override only');
  if (meta.afterHoursAvailable) chips.push('After hours');
  if (meta.responseSlaMinutes) chips.push(`SLA ${meta.responseSlaMinutes}m`);
  if (meta.backupRank) chips.push(`Backup tier ${meta.backupRank}`);
  if (meta.costTier && meta.costTier !== 'standard') chips.push(`Cost ${meta.costTier}`);
  if (meta.approvalMode && meta.approvalMode !== 'standard') chips.push(`Approval ${meta.approvalMode}`);
  return `
    <div style="display:flex;flex-direction:column;gap:8px">
      ${chips.length ? `<div style="display:flex;gap:6px;flex-wrap:wrap">${chips.map((chip) => `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(chip)}</span>`).join('')}</div>` : ''}
      ${(meta.supportedIssueTags?.length || meta.manufacturerTags?.length || meta.preferredPropertyCodes?.length)
        ? `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;font-size:11px;color:rgba(240,235,227,0.58)">
            ${meta.supportedIssueTags?.length ? `<div><span style="color:var(--white)">Issues:</span> ${escapeHtml(meta.supportedIssueTags.join(', '))}</div>` : ''}
            ${meta.manufacturerTags?.length ? `<div><span style="color:var(--white)">Systems:</span> ${escapeHtml(meta.manufacturerTags.join(', '))}</div>` : ''}
            ${meta.preferredPropertyCodes?.length ? `<div><span style="color:var(--white)">Preferred properties:</span> ${escapeHtml(meta.preferredPropertyCodes.join(', '))}</div>` : ''}
          </div>`
        : ''}
    </div>
  `;
}

function renderGrid() {
  const grid = document.getElementById('vendor-categories-grid');
  if (!grid) return;
  const groups = groupVendors();
  if (!groups.length) {
    grid.innerHTML = `
      <div class="empty" style="padding:48px">
        <div class="empty-title">No vendors configured yet</div>
        <div class="empty-sub">Add local partners and fallback options so the concierge can make grounded recommendations.</div>
      </div>`;
    return;
  }
  grid.innerHTML = groups.map(({ category, vendors }) => `
    <div class="card" style="margin-bottom:14px">
      <div class="card-header">
        <div>
          <div class="card-title">${escapeHtml(category.displayName)}</div>
          <div class="card-sub">${vendors.length} vendor${vendors.length === 1 ? '' : 's'} · ${escapeHtml(category.workflowGroup === 'dispatch' ? 'Dispatch workflow' : 'Guest experience workflow')}</div>
        </div>
      </div>
      <div class="card-body" style="display:flex;flex-direction:column;gap:10px">
        ${vendors.length ? vendors.map((vendor) => `
          <div style="padding:12px;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.03);display:flex;flex-direction:column;gap:8px">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <span style="font-size:13px;color:var(--white);font-weight:600">${escapeHtml(vendor.name)}</span>
              <span class="badge ${vendor.active ? 'badge-green' : 'badge-dim'}" style="font-size:9px">${vendor.active ? 'ACTIVE' : 'INACTIVE'}</span>
              <span class="badge badge-dim" style="font-size:9px">Priority ${vendor.priority}</span>
              <span style="flex:1"></span>
              <button class="btn btn-sm vendor-edit-btn" data-vendor-id="${escapeHtml(vendor.id)}">Edit</button>
              <button class="btn btn-sm vendor-delete-btn" data-vendor-id="${escapeHtml(vendor.id)}">Delete</button>
            </div>
            <div style="font-size:11px;color:rgba(240,235,227,0.7)">${escapeHtml(vendor.phone || vendor.website || 'No contact details saved')}</div>
            ${vendor.aiScript ? `<div style="font-size:12px;color:rgba(240,235,227,0.82);line-height:1.6">${escapeHtml(vendor.aiScript)}</div>` : ''}
            ${renderVendorOperationalMeta(vendor)}
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:10px;color:rgba(240,235,227,0.5);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.08em">
              <span>${vendor.workflowGroup}</span>
              <span>${vendor.referralCount} referrals</span>
              ${vendor.website ? `<a href="${escapeHtml(safeUrl(vendor.website))}" target="_blank" rel="noopener noreferrer" style="color:var(--amber);text-decoration:none">Website ↗</a>` : ''}
            </div>
          </div>
        `).join('') : `
          <div class="empty" style="padding:20px 12px">
            <div class="empty-sub">No vendors in this category yet.</div>
          </div>
        `}
      </div>
    </div>
  `).join('');
}

function populateCategoryOptions() {
  const select = document.getElementById('new-vendor-category');
  if (!select) return;
  const current = select.value || '';
  select.innerHTML = state.categories.map((category) => `
    <option value="${escapeHtml(category.slug)}">${escapeHtml(category.displayName)}</option>
  `).join('');
  if (current) select.value = current;
}

async function loadVendors() {
  const grid = document.getElementById('vendor-categories-grid');
  if (grid) grid.innerHTML = renderInlineError('Loading vendors…', 'Pulling vendor categories and recommendation partners.');
  try {
    const [categoriesPayload, vendorsPayload, propertiesPayload] = await Promise.all([
      api.vendors.categories(),
      api.vendors.list(),
      api.properties(),
    ]);
    state.categories = normalizeVendorCategories(categoriesPayload).categories;
    state.vendors = normalizeVendors(vendorsPayload).vendors;
    state.properties = Array.isArray(propertiesPayload?.properties) ? propertiesPayload.properties : [];
    state.loaded = true;
    populateCategoryOptions();
    renderStats();
    renderGrid();
  } catch (error) {
    if (grid) {
      grid.innerHTML = renderInlineError('Could not load vendors', error.message || String(error), 'vendors-retry');
      const btn = document.getElementById('vendors-retry');
      if (btn) btn.addEventListener('click', loadVendors);
    }
  }
}

function populateVendorForm(vendor) {
  const meta = vendor?.operationalMetadata || {};
  const fields = {
    'new-vendor-id': vendor?.id || '',
    'new-vendor-name': vendor?.name || '',
    'new-vendor-phone': vendor?.phone || '',
    'new-vendor-website': vendor?.website || '',
    'new-vendor-script': vendor?.aiScript || '',
    'new-vendor-priority': String(vendor?.priority || 1),
    'new-vendor-notes': vendor?.internalNotes || '',
    'new-vendor-property-ids': joinTags(vendor?.propertyIds || []),
    'new-vendor-supported-issues': joinTags(meta.supportedIssueTags),
    'new-vendor-manufacturers': joinTags(meta.manufacturerTags),
    'new-vendor-warranty-providers': joinTags(meta.warrantyProviderTags),
    'new-vendor-preferred-properties': joinTags(meta.preferredPropertyCodes),
    'new-vendor-backup-rank': String(meta.backupRank || 0),
    'new-vendor-response-sla': String(meta.responseSlaMinutes || 0),
  };
  Object.entries(fields).forEach(([id, value]) => {
    const el = document.getElementById(id);
    if (el) el.value = value;
  });
  const category = document.getElementById('new-vendor-category');
  const active = document.getElementById('new-vendor-active');
  const scope = document.getElementById('new-vendor-apply-scope');
  const warrantyCapable = document.getElementById('new-vendor-warranty-capable');
  const warrantyOnly = document.getElementById('new-vendor-warranty-only');
  const emergencyCapable = document.getElementById('new-vendor-emergency-capable');
  const emergencyOverrideOnly = document.getElementById('new-vendor-emergency-override-only');
  const afterHours = document.getElementById('new-vendor-after-hours');
  const approvalMode = document.getElementById('new-vendor-approval-mode');
  const costTier = document.getElementById('new-vendor-cost-tier');
  const title = document.getElementById('vendor-modal-title');
  if (category) category.value = vendor?.categorySlug || (state.categories[0]?.slug || '');
  if (active) active.value = vendor?.active === false ? 'false' : 'true';
  if (scope) scope.value = vendor?.applyScope || 'all';
  if (warrantyCapable) warrantyCapable.checked = !!meta.warrantyCapable;
  if (warrantyOnly) warrantyOnly.checked = !!meta.warrantyOnly;
  if (emergencyCapable) emergencyCapable.checked = !!meta.emergencyCapable;
  if (emergencyOverrideOnly) emergencyOverrideOnly.checked = !!meta.emergencyOverrideOnly;
  if (afterHours) afterHours.checked = !!meta.afterHoursAvailable;
  if (approvalMode) approvalMode.value = meta.approvalMode || 'standard';
  if (costTier) costTier.value = meta.costTier || 'standard';
  if (title) title.textContent = vendor ? 'Edit Vendor' : 'Add Vendor';
}

async function saveVendor() {
  const operationalMetadata = {
    supported_issue_tags: splitTags(document.getElementById('new-vendor-supported-issues')?.value || ''),
    manufacturer_tags: splitTags(document.getElementById('new-vendor-manufacturers')?.value || ''),
    warranty_provider_tags: splitTags(document.getElementById('new-vendor-warranty-providers')?.value || ''),
    preferred_property_codes: splitTags(document.getElementById('new-vendor-preferred-properties')?.value || ''),
    warranty_capable: !!document.getElementById('new-vendor-warranty-capable')?.checked,
    warranty_only: !!document.getElementById('new-vendor-warranty-only')?.checked,
    emergency_capable: !!document.getElementById('new-vendor-emergency-capable')?.checked,
    emergency_override_only: !!document.getElementById('new-vendor-emergency-override-only')?.checked,
    after_hours_available: !!document.getElementById('new-vendor-after-hours')?.checked,
    backup_rank: parseInt(document.getElementById('new-vendor-backup-rank')?.value || '0', 10) || 0,
    response_sla_minutes: parseInt(document.getElementById('new-vendor-response-sla')?.value || '0', 10) || 0,
    approval_mode: document.getElementById('new-vendor-approval-mode')?.value || 'standard',
    cost_tier: document.getElementById('new-vendor-cost-tier')?.value || 'standard',
  };
  const payload = {
    name: (document.getElementById('new-vendor-name')?.value || '').trim(),
    category_slug: document.getElementById('new-vendor-category')?.value || '',
    phone: (document.getElementById('new-vendor-phone')?.value || '').trim(),
    website: (document.getElementById('new-vendor-website')?.value || '').trim(),
    ai_script: (document.getElementById('new-vendor-script')?.value || '').trim(),
    priority: parseInt(document.getElementById('new-vendor-priority')?.value || '1', 10),
    active: (document.getElementById('new-vendor-active')?.value || 'true') === 'true',
    internal_notes: (document.getElementById('new-vendor-notes')?.value || '').trim(),
    apply_scope: document.getElementById('new-vendor-apply-scope')?.value || 'all',
    property_ids: splitTags(document.getElementById('new-vendor-property-ids')?.value || ''),
    operational_metadata: operationalMetadata,
  };
  const vendorId = document.getElementById('new-vendor-id')?.value || '';
  if (!payload.name || !payload.category_slug) {
    alert('Add a business name and category.');
    return;
  }
  try {
    if (vendorId) {
      await api.vendors.update(vendorId, payload);
    } else {
      await api.vendors.create(payload);
    }
    populateVendorForm(null);
    closeModal('add-vendor-modal');
    await loadVendors();
  } catch (error) {
    alert(error.message || 'Could not save vendor.');
  }
}

function wireDom() {
  const grid = document.getElementById('vendor-categories-grid');
  if (grid && grid.dataset.wired !== '1') {
    grid.dataset.wired = '1';
    grid.addEventListener('click', async (event) => {
      const editBtn = event.target.closest('.vendor-edit-btn');
      const deleteBtn = event.target.closest('.vendor-delete-btn');
      if (editBtn) {
        const vendor = state.vendors.find((item) => item.id === editBtn.getAttribute('data-vendor-id'));
        if (!vendor) return;
        populateVendorForm(vendor);
        window.showModal('add-vendor-modal');
      }
      if (deleteBtn) {
        const vendorId = deleteBtn.getAttribute('data-vendor-id');
        if (!window.confirm('Delete this vendor?')) return;
        try {
          await api.vendors.delete(vendorId);
          await loadVendors();
        } catch (error) {
          alert(error.message || 'Could not delete vendor.');
        }
      }
    });
  }
}

function isVendorsView() {
  const root = document.getElementById('view-vendors');
  return !!root && root.style.display !== 'none';
}

export function init() {
  wireDom();
  window.saveVendor = saveVendor;
  window.addEventListener('oyvoda:view-changed', (event) => {
    if (event.detail?.view === 'vendors') {
      loadVendors();
    }
  });
  if (isVendorsView()) {
    loadVendors();
  }
}
