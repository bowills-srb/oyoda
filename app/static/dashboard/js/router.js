/**
 * router.js — Section switching.
 *
 * navigate(view)       — show requested section, hide others, update breadcrumb
 * setFilter(_, btn)    — highlight a filter tab within current section
 * setKbTab(tab, btn)   — Knowledge Base sub-tabs (entries vs gaps)
 *
 * When the view changes, router dispatches a CustomEvent:
 *   window.dispatchEvent(new CustomEvent('oyvoda:view-changed', { detail: { view } }));
 * Any section module can listen:
 *   window.addEventListener('oyvoda:view-changed', (e) => { if (e.detail.view === 'market') loadMarket(30); });
 */

import { state } from './state.js?v=2026-04-21-b';

const VIEW_IDS = {
  today: ['view-today'],
  prebooking: ['view-prebooking'],
  prearrival: ['view-pre-arrival'],
  instay: ['view-sessions'],
  poststay: ['view-post-stay'],
  escalations: ['view-escalations'],
  knowledge: ['view-knowledge'],
  vendors: ['view-vendors'],
  properties: ['view-properties'],
  analytics: ['view-analytics'],
  audit: ['view-audit'],
  settings: ['view-settings'],
  market: ['view-market'],
  team: ['view-team'],
  gaps: ['view-gaps'],
  'llm-usage': ['view-llm-usage'],
};

const PRIMARY_VIEWS = [
  'today',
  'prebooking',
  'prearrival',
  'instay',
  'poststay',
  'properties',
  'vendors',
  'knowledge',
  'escalations',
  'analytics',
  'audit',
  'settings',
];

const LEGACY_ALIASES = {
  overview: 'today',
  sessions: 'instay',
};

const BREADCRUMBS = {
  today: 'Today',
  prebooking: 'Pre-Booking',
  prearrival: 'Pre-Arrival',
  instay: 'In-Stay',
  poststay: 'Post-Stay',
  properties: 'Properties',
  vendors: 'Vendors',
  knowledge: 'Knowledge',
  escalations: 'Escalations',
  analytics: 'Analytics',
  audit: 'Audit',
  settings: 'Settings',
  market: 'Market Intelligence',
  team: 'Team',
  gaps: 'KB Gaps',
  'llm-usage': 'LLM Usage',
};

function canonicalView(view) {
  return LEGACY_ALIASES[view] || view;
}

function allDomViewIds() {
  const ids = new Set();
  Object.values(VIEW_IDS).forEach((group) => {
    group.forEach((id) => ids.add(id));
  });
  return Array.from(ids);
}

let currentView = 'today';
state.set('currentView', currentView);

function navigate(view) {
  const resolvedView = canonicalView(view);
  currentView = resolvedView;
  state.set('currentView', currentView);
  if (document.body) document.body.setAttribute('data-current-view', resolvedView);

  const visibleIds = new Set(VIEW_IDS[resolvedView] || []);
  allDomViewIds().forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = visibleIds.has(id) ? '' : 'none';
  });

  document.querySelectorAll('.nav-item[data-view]').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-view') === resolvedView);
  });

  const bc = document.getElementById('breadcrumb');
  if (bc) bc.textContent = BREADCRUMBS[resolvedView] || resolvedView;

  const mn = document.querySelector('.main');
  if (mn) mn.scrollTop = 0;

  window.dispatchEvent(new CustomEvent('oyvoda:view-changed', { detail: { view: resolvedView } }));
}

function setFilter(val, btn) {
  if (!btn) return;
  btn.closest('.tab-bar').querySelectorAll('.tab').forEach(function(t){ t.classList.remove('active'); });
  btn.classList.add('active');
}

function setKbTab(tab, btn) {
  if (!btn) return;
  btn.closest('.tab-bar').querySelectorAll('.tab').forEach(function(t){ t.classList.remove('active'); });
  btn.classList.add('active');
  var kbEntries = document.getElementById('kb-entries-section');
  var kbGaps = document.getElementById('kb-gaps-section');
  if (tab === 'gaps') {
    if (kbEntries) kbEntries.style.display = 'none';
    if (kbGaps) {
      kbGaps.style.display = '';
      var inline = document.getElementById('kb-gaps-inline');
      var src = document.getElementById('view-gaps');
      if (inline && src && inline.querySelector('.empty-title')) {
        var content = '';
        Array.from(src.children).forEach(function(el) {
          if (!el.classList.contains('page-header')) content += el.outerHTML;
        });
        inline.innerHTML = content || src.innerHTML;
      }
    }
  } else {
    if (kbEntries) kbEntries.style.display = '';
    if (kbGaps) kbGaps.style.display = 'none';
  }
}

window.navigate = navigate;
window.setFilter = setFilter;
window.setKbTab = setKbTab;

export { PRIMARY_VIEWS, BREADCRUMBS, navigate, setFilter, setKbTab, canonicalView };
