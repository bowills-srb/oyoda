/**
 * state.js — Tiny pub/sub store.
 *
 * Shared mutable state for the dashboard. Sections subscribe to keys they
 * care about and re-render when the value changes. No framework needed.
 *
 * Usage:
 *   import { state } from './state.js';
 *   state.set('operator', { id, name, ... });
 *   const op = state.get('operator');
 *   const unsub = state.subscribe('operator', (next, prev) => { ... });
 *   unsub();  // stop listening
 */

const store = new Map();
const listeners = new Map(); // key → Set<fn>

function emit(key, value, prev) {
  const fns = listeners.get(key);
  if (!fns) return;
  for (const fn of fns) {
    try { fn(value, prev); }
    catch (e) { console.error(`[state] listener for "${key}" threw:`, e); }
  }
}

export const state = {
  get(key) {
    return store.get(key);
  },
  has(key) {
    return store.has(key);
  },
  set(key, value) {
    const prev = store.get(key);
    if (Object.is(prev, value)) return;
    store.set(key, value);
    emit(key, value, prev);
  },
  update(key, updater, fallback = {}) {
    const prev = store.has(key) ? store.get(key) : fallback;
    const next = updater(prev);
    this.set(key, next);
    return next;
  },
  setMany(entries) {
    Object.entries(entries || {}).forEach(([key, value]) => {
      this.set(key, value);
    });
  },
  snapshot(keys) {
    if (!Array.isArray(keys) || keys.length === 0) {
      return Object.fromEntries(store.entries());
    }
    return keys.reduce((acc, key) => {
      acc[key] = store.get(key);
      return acc;
    }, {});
  },
  subscribe(key, fn) {
    if (!listeners.has(key)) listeners.set(key, new Set());
    listeners.get(key).add(fn);
    return () => listeners.get(key)?.delete(fn);
  },
  subscribeMany(keys, fn) {
    const watched = Array.isArray(keys) ? keys : [];
    const invoke = () => fn(this.snapshot(watched));
    const unsubs = watched.map((key) => this.subscribe(key, invoke));
    return () => unsubs.forEach((unsub) => unsub());
  },
  clear(key) {
    if (!store.has(key)) return;
    const prev = store.get(key);
    store.delete(key);
    emit(key, undefined, prev);
  },
};
