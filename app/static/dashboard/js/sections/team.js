import api from '../api.js?v=2026-04-23-a';
import { normalizeTeamMembers, renderInlineError } from '../adapters.js?v=2026-04-21-b';
import { closeModal, escapeHtml } from '../ui.js?v=2026-04-21-a';

const state = {
  members: [],
  portfolios: [],
  properties: [],
  memberScopes: {},
  loadingScopesFor: '',
};

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function slugify(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 50);
}

function fmtWhen(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' });
  } catch (_) {
    return '';
  }
}

function propertyLabelByCode(code) {
  const match = state.properties.find((property) => String(property.propertyCode || property.external_id || property.id) === String(code));
  return match ? (match.propertyName || match.addressStreet || code) : String(code || '');
}

function summarizeMemberCoverage(memberId) {
  const scopes = safeArray(state.memberScopes[memberId]);
  const summary = {
    tenantWide: false,
    portfolios: new Set(),
    properties: new Set(),
    canAssign: false,
    canManageVendors: false,
    canManageSettings: false,
  };
  scopes.forEach((scope) => {
    if (scope.scope_type === 'tenant') summary.tenantWide = true;
    if (scope.scope_type === 'portfolio' && scope.portfolio_id) summary.portfolios.add(scope.portfolio_id);
    if (scope.scope_type === 'property' && scope.property_external_id) summary.properties.add(scope.property_external_id);
    if (scope.can_assign) summary.canAssign = true;
    if (scope.can_manage_vendors) summary.canManageVendors = true;
    if (scope.can_manage_settings) summary.canManageSettings = true;
  });
  return summary;
}

function portfolioCoverage(portfolioId) {
  const memberIds = state.members
    .filter((member) => safeArray(state.memberScopes[member.id]).some((scope) => scope.scope_type === 'tenant' || (scope.scope_type === 'portfolio' && scope.portfolio_id === portfolioId)))
    .map((member) => member.id);
  return {
    memberCount: memberIds.length,
    managerCount: state.members.filter((member) => memberIds.includes(member.id) && member.role === 'manager').length,
  };
}

function renderTeamSummary() {
  const activeMembers = state.members.filter((member) => member.activated).length;
  const invitedMembers = state.members.filter((member) => member.invitePending).length;
  const scopedMembers = state.members.filter((member) => safeArray(state.memberScopes[member.id]).length > 0).length;
  const coveredProperties = new Set(
    Object.values(state.memberScopes)
      .flatMap((scopes) => safeArray(scopes))
      .filter((scope) => scope.scope_type === 'property' && scope.property_external_id)
      .map((scope) => scope.property_external_id)
  ).size;
  return `
    <div class="card" style="grid-column:1/-1">
      <div class="card-body" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px">
        <div class="team-card">
          <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;letter-spacing:0.1em;text-transform:uppercase">Active members</div>
          <div style="font-size:24px;color:var(--white);font-weight:600;margin-top:4px">${escapeHtml(String(activeMembers))}</div>
          <div style="font-size:12px;color:rgba(240,235,227,0.58)">Currently activated in the operator workspace.</div>
        </div>
        <div class="team-card">
          <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;letter-spacing:0.1em;text-transform:uppercase">Invites pending</div>
          <div style="font-size:24px;color:var(--white);font-weight:600;margin-top:4px">${escapeHtml(String(invitedMembers))}</div>
          <div style="font-size:12px;color:rgba(240,235,227,0.58)">People who still need to accept access.</div>
        </div>
        <div class="team-card">
          <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;letter-spacing:0.1em;text-transform:uppercase">Portfolios</div>
          <div style="font-size:24px;color:var(--white);font-weight:600;margin-top:4px">${escapeHtml(String(state.portfolios.length))}</div>
          <div style="font-size:12px;color:rgba(240,235,227,0.58)">Operating areas that can own visibility and routing.</div>
        </div>
        <div class="team-card">
          <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;letter-spacing:0.1em;text-transform:uppercase">Scoped coverage</div>
          <div style="font-size:24px;color:var(--white);font-weight:600;margin-top:4px">${escapeHtml(String(scopedMembers))}</div>
          <div style="font-size:12px;color:rgba(240,235,227,0.58)">${escapeHtml(String(coveredProperties))} properties explicitly assigned across the team.</div>
        </div>
      </div>
    </div>
  `;
}

function renderTeam() {
  const grid = document.getElementById('team-grid');
  if (!grid) return;
  if (!state.members.length) {
    grid.innerHTML = `
      <div class="empty" style="padding:48px;grid-column:1/-1">
        <div class="empty-title">No team members yet</div>
        <div class="empty-sub">Invite managers or staff so escalation ownership and watcher delivery stay targeted.</div>
      </div>`;
    return;
  }

  const teamSummary = renderTeamSummary();
  const portfolioPanel = `
    <div class="card" style="grid-column:1/-1">
      <div class="card-body" style="display:flex;flex-direction:column;gap:16px">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap">
          <div>
            <div class="card-title">Portfolios</div>
            <div class="card-sub">Group properties into operating areas so visibility, assignments, vendors, and alert routing can follow the same boundary.</div>
          </div>
          <button class="btn btn-sm" id="team-add-portfolio-btn">+ Add Portfolio</button>
        </div>
        ${renderPortfolioList()}
      </div>
    </div>
  `;

  grid.innerHTML = teamSummary + portfolioPanel + state.members.map((member) => `
    <div class="card">
      <div class="card-body" style="display:flex;flex-direction:column;gap:10px">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <div style="font-size:14px;color:var(--white);font-weight:600">${escapeHtml(member.name)}</div>
          <span class="badge ${member.activated ? 'badge-green' : 'badge-amber'}" style="font-size:9px">${member.activated ? 'ACTIVE' : 'INVITED'}</span>
          <span style="flex:1"></span>
          <span class="badge badge-dim" style="font-size:9px">${escapeHtml(String(member.role).toUpperCase())}</span>
        </div>
        <div style="font-size:12px;color:rgba(240,235,227,0.72)">${escapeHtml(member.email)}</div>
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:10px;color:rgba(240,235,227,0.5);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.08em">
          ${member.joinedAt ? `<span>joined ${escapeHtml(fmtWhen(member.joinedAt))}</span>` : ''}
          ${member.lastLoginAt ? `<span>last login ${escapeHtml(fmtWhen(member.lastLoginAt))}</span>` : ''}
          ${member.invitePending && member.inviteExpires ? `<span>invite expires ${escapeHtml(fmtWhen(member.inviteExpires))}</span>` : ''}
        </div>
        ${renderCoverageChips(member.id)}
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <select class="form-select team-role-select" data-member-id="${escapeHtml(member.id)}" style="max-width:180px">
            <option value="manager" ${member.role === 'manager' ? 'selected' : ''}>Manager</option>
            <option value="staff" ${member.role === 'staff' ? 'selected' : ''}>Staff</option>
          </select>
          <button class="btn btn-sm team-scope-btn" data-member-id="${escapeHtml(member.id)}">Manage Scope</button>
          <button class="btn btn-sm team-remove-btn" data-member-id="${escapeHtml(member.id)}">Remove</button>
        </div>
        ${renderScopeSummary(member.id)}
      </div>
    </div>
  `).join('');

  const addPortfolioBtn = document.getElementById('team-add-portfolio-btn');
  if (addPortfolioBtn) addPortfolioBtn.addEventListener('click', openPortfolioModal);
}

function renderPortfolioList() {
  if (!state.portfolios.length) {
    return `
      <div class="empty" style="padding:28px 18px">
        <div class="empty-title">No portfolios yet</div>
        <div class="empty-sub">Start with a geography, brand, or operating team, then map properties into it.</div>
      </div>
    `;
  }
  return `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px">
      ${state.portfolios.map((portfolio) => `
        <div class="team-card" style="display:flex;flex-direction:column;gap:10px">
          ${renderPortfolioCoverageMeta(portfolio)}
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <div style="font-size:13px;font-weight:600;color:var(--white)">${escapeHtml(portfolio.display_name || portfolio.portfolio_key)}</div>
            <span class="badge ${portfolio.active ? 'badge-green' : 'badge-dim'}" style="font-size:9px">${portfolio.active ? 'ACTIVE' : 'INACTIVE'}</span>
          </div>
          <div style="font-size:11px;color:rgba(240,235,227,0.5);font-family:'DM Mono',monospace;letter-spacing:0.08em;text-transform:uppercase">${escapeHtml(portfolio.portfolio_key || '')}</div>
          <div style="font-size:12px;color:rgba(240,235,227,0.72)">${escapeHtml(portfolio.description || 'No description yet.')}</div>
          <div style="font-size:11px;color:rgba(240,235,227,0.52)">${escapeHtml(String(portfolio.property_count || 0))} properties</div>
          ${renderPortfolioPropertyPreview(portfolio)}
          <div>
            <button class="btn btn-sm team-portfolio-edit-btn" data-portfolio-id="${escapeHtml(portfolio.portfolio_id)}">Map Properties</button>
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function renderPortfolioCoverageMeta(portfolio) {
  const coverage = portfolioCoverage(portfolio.portfolio_id);
  return `
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <span class="badge badge-dim" style="font-size:9px">${escapeHtml(String(coverage.memberCount))} members</span>
      <span class="badge badge-dim" style="font-size:9px">${escapeHtml(String(coverage.managerCount))} managers</span>
    </div>
  `;
}

function renderPortfolioPropertyPreview(portfolio) {
  const propertyCodes = safeArray(portfolio.property_external_ids || portfolio.property_codes || []);
  if (!propertyCodes.length) {
    return `<div style="font-size:12px;color:rgba(240,235,227,0.45)">No properties mapped yet.</div>`;
  }
  return `
    <div style="display:flex;flex-wrap:wrap;gap:6px">
      ${propertyCodes.slice(0, 4).map((code) => `
        <span class="badge badge-dim" style="font-size:9px">${escapeHtml(propertyLabelByCode(code))}</span>
      `).join('')}
      ${propertyCodes.length > 4 ? `<span class="badge badge-dim" style="font-size:9px">+${escapeHtml(String(propertyCodes.length - 4))} more</span>` : ''}
    </div>
  `;
}

function renderCoverageChips(memberId) {
  const coverage = summarizeMemberCoverage(memberId);
  const chips = [];
  if (coverage.tenantWide) chips.push('Entire operator');
  if (coverage.portfolios.size) chips.push(`${coverage.portfolios.size} portfolios`);
  if (coverage.properties.size) chips.push(`${coverage.properties.size} properties`);
  if (coverage.canAssign) chips.push('Can assign');
  if (coverage.canManageVendors) chips.push('Vendor access');
  if (coverage.canManageSettings) chips.push('Settings access');
  if (!chips.length) {
    return `<div style="font-size:12px;color:rgba(240,235,227,0.5)">No explicit coverage yet. This member will only see what the role defaults and backend fallbacks allow.</div>`;
  }
  return `
    <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
      ${chips.map((chip) => `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(chip)}</span>`).join('')}
    </div>
  `;
}

function renderScopeSummary(memberId) {
  const scopes = safeArray(state.memberScopes[memberId]);
  if (!scopes.length) {
    return `<div style="font-size:12px;color:rgba(240,235,227,0.5)">No explicit scope set yet. Role defaults apply until portfolios or property scopes are assigned.</div>`;
  }
  return `
    <div style="display:flex;flex-direction:column;gap:6px">
      <div style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.1em">Scope</div>
      ${scopes.map((scope) => {
        const label = scope.scope_type === 'tenant'
          ? 'Entire operator'
          : scope.scope_type === 'portfolio'
            ? (portfolioLabel(scope.portfolio_id) || 'Portfolio')
            : (scope.property_external_id || 'Property');
        const perms = [
          scope.can_view ? 'view' : '',
          scope.can_assign ? 'assign' : '',
          scope.can_manage_vendors ? 'vendors' : '',
          scope.can_manage_settings ? 'settings' : '',
        ].filter(Boolean).join(' · ');
        return `
          <div style="font-size:12px;color:rgba(240,235,227,0.72)">
            <span style="color:var(--white)">${escapeHtml(label)}</span>
            <span style="color:rgba(240,235,227,0.45)">(${escapeHtml(scope.scope_type)})</span>
            ${perms ? `<div style="font-size:11px;color:rgba(240,235,227,0.5);margin-top:2px">${escapeHtml(perms)}</div>` : ''}
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function portfolioLabel(portfolioId) {
  const match = state.portfolios.find((portfolio) => portfolio.portfolio_id === portfolioId);
  return match ? (match.display_name || match.portfolio_key) : '';
}

function propertyOptionsHtml(selected = []) {
  const selectedSet = new Set(selected.map(String));
  return state.properties.map((property) => {
    const code = property.propertyCode || property.external_id || property.id;
    const label = property.propertyName || property.addressStreet || code;
    return `<label style="display:flex;align-items:flex-start;gap:8px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.04)">
      <input type="checkbox" class="portfolio-property-checkbox" value="${escapeHtml(String(code))}" ${selectedSet.has(String(code)) ? 'checked' : ''} />
      <span style="display:flex;flex-direction:column;gap:2px">
        <span style="font-size:12px;color:var(--white)">${escapeHtml(label)}</span>
        <span style="font-size:10px;color:rgba(240,235,227,0.45);font-family:'DM Mono',monospace">${escapeHtml(String(code))}</span>
      </span>
    </label>`;
  }).join('');
}

function portfolioSelectOptions(selectedId = '') {
  return `<option value="">Select portfolio</option>` + state.portfolios.map((portfolio) => `
    <option value="${escapeHtml(portfolio.portfolio_id)}" ${portfolio.portfolio_id === selectedId ? 'selected' : ''}>${escapeHtml(portfolio.display_name || portfolio.portfolio_key)}</option>
  `).join('');
}

function propertySelectOptions(selectedCode = '') {
  return `<option value="">Select property</option>` + state.properties.map((property) => {
    const code = property.propertyCode || property.external_id || property.id;
    const label = property.propertyName || property.addressStreet || code;
    return `<option value="${escapeHtml(String(code))}" ${String(code) === String(selectedCode) ? 'selected' : ''}>${escapeHtml(label)} (${escapeHtml(String(code))})</option>`;
  }).join('');
}

async function loadTeam() {
  const grid = document.getElementById('team-grid');
  if (grid) grid.innerHTML = renderInlineError('Loading team…', 'Pulling members and roles.');
  try {
    const [teamPayload, portfoliosPayload, propertiesPayload] = await Promise.all([
      api.team.list(),
      api.portfolios.list(),
      api.properties(),
    ]);
    const normalized = normalizeTeamMembers(teamPayload);
    state.members = normalized.members;
    state.portfolios = safeArray(portfoliosPayload.portfolios);
    state.properties = safeArray(propertiesPayload.properties).map((property) => ({
      id: property.id || property.property_id || null,
      propertyCode: property.property_code || property.external_id || '',
      propertyName: property.address_street || property.name || property.property_code || '',
      addressStreet: property.address_street || '',
      external_id: property.external_id || '',
    }));
    await Promise.all(state.members.map(async (member) => {
      try {
        const payload = await api.team.scopes(member.id);
        state.memberScopes[member.id] = safeArray(payload.scopes);
      } catch (_) {
        state.memberScopes[member.id] = [];
      }
    }));
    renderTeam();
  } catch (error) {
    if (grid) {
      grid.innerHTML = renderInlineError('Could not load team', error.message || String(error), 'team-retry');
      const btn = document.getElementById('team-retry');
      if (btn) btn.addEventListener('click', loadTeam);
    }
  }
}

async function sendInvite() {
  const nameEl = document.getElementById('inv-name');
  const emailEl = document.getElementById('inv-email');
  const roleEl = document.getElementById('inv-role');
  const name = (nameEl?.value || '').trim();
  const email = (emailEl?.value || '').trim();
  const role = roleEl?.value || 'staff';
  if (!name || !email) {
    alert('Add a name and email address.');
    return;
  }
  try {
    await api.team.invite({ name, email, role });
    if (nameEl) nameEl.value = '';
    if (emailEl) emailEl.value = '';
    if (roleEl) roleEl.value = 'manager';
    closeModal('invite-modal');
    await loadTeam();
  } catch (error) {
    alert(error.message || 'Could not send invite.');
  }
}

async function updateRole(memberId, role) {
  try {
    await api.team.updateRole(memberId, role);
    await loadTeam();
  } catch (error) {
    alert(error.message || 'Could not update role.');
  }
}

async function removeMember(memberId) {
  if (!window.confirm('Remove this team member?')) return;
  try {
    await api.team.remove(memberId);
    await loadTeam();
  } catch (error) {
    alert(error.message || 'Could not remove team member.');
  }
}

function openPortfolioModal(portfolioId = '') {
  const modal = document.getElementById('team-portfolio-modal');
  const title = document.getElementById('team-portfolio-title');
  const keyEl = document.getElementById('team-portfolio-key');
  const nameEl = document.getElementById('team-portfolio-name');
  const descEl = document.getElementById('team-portfolio-description');
  const propsEl = document.getElementById('team-portfolio-properties');
  if (!modal || !title || !keyEl || !nameEl || !descEl || !propsEl) return;
  const portfolio = state.portfolios.find((item) => item.portfolio_id === portfolioId);
  modal.dataset.portfolioId = portfolioId || '';
  title.textContent = portfolio ? 'Update Portfolio Properties' : 'Create Portfolio';
  keyEl.value = portfolio?.portfolio_key || '';
  keyEl.disabled = !!portfolio;
  nameEl.value = portfolio?.display_name || '';
  descEl.value = portfolio?.description || '';
  const selectedPropertyCodes = safeArray(portfolio?.property_external_ids || portfolio?.property_codes || []);
  propsEl.innerHTML = propertyOptionsHtml(selectedPropertyCodes);
  modal.style.display = 'flex';
}

async function savePortfolio() {
  const modal = document.getElementById('team-portfolio-modal');
  if (!modal) return;
  const portfolioId = modal.dataset.portfolioId || '';
  const keyEl = document.getElementById('team-portfolio-key');
  const nameEl = document.getElementById('team-portfolio-name');
  const descEl = document.getElementById('team-portfolio-description');
  const selectedPropertyIds = Array.from(document.querySelectorAll('#team-portfolio-properties .portfolio-property-checkbox:checked')).map((el) => el.value);
  const portfolioKey = slugify(keyEl?.value || '');
  const displayName = (nameEl?.value || '').trim();
  const description = (descEl?.value || '').trim();
  if (!portfolioId && (!portfolioKey || !displayName)) {
    alert('Add a portfolio key and display name.');
    return;
  }
  try {
    let finalPortfolioId = portfolioId;
    if (!finalPortfolioId) {
      const created = await api.portfolios.create({
        portfolio_key: portfolioKey,
        display_name: displayName,
        description,
      });
      finalPortfolioId = created.portfolio_id;
    }
    await api.portfolios.updateProperties(finalPortfolioId, selectedPropertyIds);
    closeModal('team-portfolio-modal');
    await loadTeam();
  } catch (error) {
    alert(error.message || 'Could not save portfolio.');
  }
}

async function openScopeModal(memberId) {
  state.loadingScopesFor = memberId;
  const modal = document.getElementById('team-scope-modal');
  const title = document.getElementById('team-scope-title');
  const rows = document.getElementById('team-scope-rows');
  if (!modal || !title || !rows) return;
  const member = state.members.find((item) => item.id === memberId);
  title.textContent = `Manage Scope • ${member?.name || 'Team member'}`;
  modal.dataset.memberId = memberId;
  let scopes = safeArray(state.memberScopes[memberId]);
  if (!scopes.length) {
    try {
      const payload = await api.team.scopes(memberId);
      scopes = safeArray(payload.scopes);
      state.memberScopes[memberId] = scopes;
    } catch (_) {
      scopes = [];
    }
  }
  rows.innerHTML = scopes.length ? scopes.map(renderScopeRow).join('') : renderScopeRow({
    scope_type: 'property',
    portfolio_id: '',
    property_external_id: '',
    can_view: true,
    can_assign: false,
    can_manage_vendors: false,
    can_manage_settings: false,
  });
  modal.style.display = 'flex';
}

function renderScopeRow(scope = {}) {
  return `
    <div class="team-scope-row" style="border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:12px;display:flex;flex-direction:column;gap:12px">
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px;align-items:end">
        <label style="display:flex;flex-direction:column;gap:6px">
          <span class="form-label">Scope type</span>
          <select class="form-select team-scope-type">
            <option value="property" ${(scope.scope_type || 'property') === 'property' ? 'selected' : ''}>Property</option>
            <option value="portfolio" ${(scope.scope_type || '') === 'portfolio' ? 'selected' : ''}>Portfolio</option>
            <option value="tenant" ${(scope.scope_type || '') === 'tenant' ? 'selected' : ''}>Entire operator</option>
          </select>
        </label>
        <label style="display:flex;flex-direction:column;gap:6px">
          <span class="form-label">Portfolio</span>
          <select class="form-select team-scope-portfolio">${portfolioSelectOptions(scope.portfolio_id || '')}</select>
        </label>
        <label style="display:flex;flex-direction:column;gap:6px">
          <span class="form-label">Property</span>
          <select class="form-select team-scope-property">${propertySelectOptions(scope.property_external_id || '')}</select>
        </label>
        <button class="btn btn-sm team-scope-remove-btn">Remove</button>
      </div>
      <div style="display:flex;gap:14px;flex-wrap:wrap">
        <label style="display:flex;align-items:center;gap:6px;font-size:12px"><input type="checkbox" class="team-scope-can-view" ${scope.can_view !== false ? 'checked' : ''} /> View</label>
        <label style="display:flex;align-items:center;gap:6px;font-size:12px"><input type="checkbox" class="team-scope-can-assign" ${scope.can_assign ? 'checked' : ''} /> Assign</label>
        <label style="display:flex;align-items:center;gap:6px;font-size:12px"><input type="checkbox" class="team-scope-can-manage-vendors" ${scope.can_manage_vendors ? 'checked' : ''} /> Vendors</label>
        <label style="display:flex;align-items:center;gap:6px;font-size:12px"><input type="checkbox" class="team-scope-can-manage-settings" ${scope.can_manage_settings ? 'checked' : ''} /> Settings</label>
      </div>
    </div>
  `;
}

function addScopeRow() {
  const rows = document.getElementById('team-scope-rows');
  if (!rows) return;
  rows.insertAdjacentHTML('beforeend', renderScopeRow({
    scope_type: 'property',
    portfolio_id: '',
    property_external_id: '',
    can_view: true,
    can_assign: false,
    can_manage_vendors: false,
    can_manage_settings: false,
  }));
}

async function saveScopeModal() {
  const modal = document.getElementById('team-scope-modal');
  const memberId = modal?.dataset.memberId || '';
  if (!memberId) return;
  const scopes = Array.from(document.querySelectorAll('#team-scope-rows .team-scope-row')).map((row) => ({
    scope_type: row.querySelector('.team-scope-type')?.value || 'property',
    portfolio_id: row.querySelector('.team-scope-portfolio')?.value || '',
    property_external_id: row.querySelector('.team-scope-property')?.value || '',
    can_view: !!row.querySelector('.team-scope-can-view')?.checked,
    can_assign: !!row.querySelector('.team-scope-can-assign')?.checked,
    can_manage_vendors: !!row.querySelector('.team-scope-can-manage-vendors')?.checked,
    can_manage_settings: !!row.querySelector('.team-scope-can-manage-settings')?.checked,
  })).filter((scope) => {
    if (scope.scope_type === 'tenant') return true;
    if (scope.scope_type === 'portfolio') return !!scope.portfolio_id;
    return !!scope.property_external_id;
  });
  try {
    await api.team.updateScopes(memberId, scopes);
    state.memberScopes[memberId] = scopes;
    closeModal('team-scope-modal');
    renderTeam();
  } catch (error) {
    alert(error.message || 'Could not update member scope.');
  }
}

function wireDom() {
  const grid = document.getElementById('team-grid');
  if (grid && grid.dataset.wired !== '1') {
    grid.dataset.wired = '1';
    grid.addEventListener('change', (event) => {
      const select = event.target.closest('.team-role-select');
      if (!select) return;
      updateRole(select.getAttribute('data-member-id'), select.value);
    });
    grid.addEventListener('click', (event) => {
      const btn = event.target.closest('.team-remove-btn');
      if (btn) {
        removeMember(btn.getAttribute('data-member-id'));
        return;
      }
      const scopeBtn = event.target.closest('.team-scope-btn');
      if (scopeBtn) {
        openScopeModal(scopeBtn.getAttribute('data-member-id'));
        return;
      }
      const portfolioBtn = event.target.closest('.team-portfolio-edit-btn');
      if (portfolioBtn) {
        openPortfolioModal(portfolioBtn.getAttribute('data-portfolio-id'));
      }
    });
  }

  const scopeRows = document.getElementById('team-scope-rows');
  if (scopeRows && scopeRows.dataset.wired !== '1') {
    scopeRows.dataset.wired = '1';
    scopeRows.addEventListener('click', (event) => {
      const removeBtn = event.target.closest('.team-scope-remove-btn');
      if (!removeBtn) return;
      removeBtn.closest('.team-scope-row')?.remove();
    });
  }
}

function isTeamView() {
  const root = document.getElementById('view-team');
  return !!root && root.style.display !== 'none';
}

export function init() {
  wireDom();
  window.sendInvite = sendInvite;
  window.savePortfolio = savePortfolio;
  window.addScopeRow = addScopeRow;
  window.saveScopeModal = saveScopeModal;
  window.addEventListener('oyvoda:view-changed', (event) => {
    if (event.detail?.view === 'team') {
      loadTeam();
    }
  });
  if (isTeamView()) {
    loadTeam();
  }
}
