import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const root = process.cwd();

function moduleUrl(relPath, query = '') {
  return pathToFileURL(path.join(root, relPath)).href + query;
}

const elements = new Map();

function makeElement(id = '') {
  return {
    id,
    style: {},
    dataset: {},
    value: '',
    textContent: '',
    innerHTML: '',
    href: '',
    onclick: null,
    checked: false,
    disabled: false,
    className: '',
    children: [],
    _classes: new Set(),
    classList: {
      add(...names) { names.forEach((name) => this._owner._classes.add(name)); },
      remove(...names) { names.forEach((name) => this._owner._classes.delete(name)); },
      toggle(name, force) {
        if (force === true) return this._owner._classes.add(name);
        if (force === false) return this._owner._classes.delete(name);
        if (this._owner._classes.has(name)) this._owner._classes.delete(name);
        else this._owner._classes.add(name);
      },
      contains(name) { return this._owner._classes.has(name); },
      _owner: null,
    },
    addEventListener() {},
    removeAttribute() {},
    closest() { return { querySelectorAll: () => [] }; },
    querySelectorAll() { return []; },
  };
}

function ensureElement(id) {
  if (!elements.has(id)) {
    const el = makeElement(id);
    el.classList._owner = el;
    elements.set(id, el);
  }
  return elements.get(id);
}

const navItems = ['overview', 'prebooking', 'sessions'].map((view) => ({
  getAttribute(name) {
    if (name === 'onclick') return `navigate('${view}')`;
    return null;
  },
  classList: {
    toggle() {},
  },
}));

globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};

const windowListeners = new Map();
globalThis.window = {
  location: { href: '', origin: 'http://localhost' },
  addEventListener(type, fn) {
    if (!windowListeners.has(type)) windowListeners.set(type, []);
    windowListeners.get(type).push(fn);
  },
  dispatchEvent(event) {
    (windowListeners.get(event.type) || []).forEach((fn) => fn(event));
  },
};

globalThis.document = {
  body: {
    classList: { add() {}, remove() {} },
  },
  getElementById(id) {
    return ensureElement(id);
  },
  querySelector(selector) {
    if (selector === '.main') return { scrollTop: 0 };
    return null;
  },
  querySelectorAll(selector) {
    if (selector === '.nav-item') return navItems;
    return [];
  },
  addEventListener() {},
};

const sessionStorageData = new Map();
globalThis.sessionStorage = {
  getItem(key) { return sessionStorageData.has(key) ? sessionStorageData.get(key) : null; },
  setItem(key, value) { sessionStorageData.set(key, String(value)); },
  removeItem(key) { sessionStorageData.delete(key); },
};

const fetchLog = [];
globalThis.fetch = async (url, options = {}) => {
  fetchLog.push({ url, options });
  if (url === '/app/auth/session') {
    return {
      ok: true,
      json: async () => ({
        operator: {
          name: 'Lanier Example',
          company: 'Beach Habitats',
          email: 'lanier@example.com',
          pms: 'escapia',
          properties: 5,
          is_super_admin: false,
          impersonating: false,
        },
      }),
    };
  }
  throw new Error(`Unexpected fetch: ${url}`);
};

const { state } = await import(moduleUrl('app/static/dashboard/js/state.js', '?v=2026-04-21-b'));
const router = await import(moduleUrl('app/static/dashboard/js/router.js'));
const auth = await import(moduleUrl('app/static/dashboard/js/auth.js'));
const adapters = await import(moduleUrl('app/static/dashboard/js/adapters.js', '?v=2026-04-21-d'));

state.set('smoke', { ok: true });
assert.deepEqual(state.get('smoke'), { ok: true });

const snapshots = [];
const stop = state.subscribeMany(['operator', 'currentView'], (next) => {
  snapshots.push(next);
});

router.navigate('prebooking');
assert.equal(state.get('currentView'), 'prebooking');
assert.equal(ensureElement('breadcrumb').textContent, 'Pre-Booking');

await auth.loadSession();
assert.equal(state.get('operator').company, 'Beach Habitats');
assert.equal(sessionStorage.getItem('oyvoda_op') !== null, true);
assert.equal(ensureElement('op-name').textContent, 'Lanier Example');

const normalizedFeed = adapters.normalizeMessageFeed({
  items: [{
    id: 'inq_1',
    guest_name: 'Robin Small',
    source_provider: 'vrbo',
    latest_guest_turn: 'Is your home part of Seagrove and do we get pool access?',
    prior_thread_context: 'Older quoted thread',
    asks: ['neighborhood', 'pool_access'],
    parser_source: 'ota_parser_vrbo',
    property_binding_candidates: [{ match_type: 'listing_id', property_code: 'BH-101' }],
    prior_operator_commitments: ['Confirmed beach access'],
    route_outcome: 'manual_review',
    fallback_reason: 'missing_pool_fact',
    latest_turn_extracted: true,
    draft_source: 'kb_gap_required',
    draft_ready: false,
  }],
});
assert.equal(normalizedFeed.items[0].parserSource, 'ota_parser_vrbo');
assert.equal(normalizedFeed.items[0].asks.length, 2);
assert.equal(normalizedFeed.items[0].propertyBindingCandidates[0].property_code, 'BH-101');
assert.equal(normalizedFeed.items[0].draftSource, 'kb_gap_required');

const normalizedSession = adapters.normalizeSessionDetail({
  session: {
    session_id: 'sess_1',
    guest_name: 'Robin Small',
  },
  intent_mix: { question: 2 },
  messages: [{
    message_id: 'msg_1',
    content: 'Can we check in early?',
    intent: 'check_in_process',
    content_type: 'text',
    was_quick_answer: false,
    response_time_ms: 3200,
  }],
  open_escalations: [{ ticket_id: 'esc_1', priority: 'high' }],
});
assert.equal(normalizedSession.messages[0].intent, 'check_in_process');
assert.equal(normalizedSession.intentMix.question, 2);
assert.equal(normalizedSession.openEscalations[0].priority, 'high');

const normalizedEvents = adapters.normalizeMessagingEvents({
  events: [{
    event_id: 'evt_1',
    severity: 'warning',
    title: 'Draft used fallback path',
    body: 'A recent message required manual review.',
    link_target: 'prebooking',
    link_label: 'Open Pre-Booking',
    created_at: '2026-04-21T12:00:00Z',
  }],
  count: 1,
  available: true,
});
assert.equal(normalizedEvents.available, true);
assert.equal(normalizedEvents.events[0].linkTarget, 'prebooking');
assert.equal(normalizedEvents.events[0].severity, 'warning');

state.clear('smoke');
assert.equal(state.has('smoke'), false);

stop();
assert.ok(snapshots.length >= 2, 'expected shared-state subscriptions to fire');

console.log('dashboard smoke passed');
