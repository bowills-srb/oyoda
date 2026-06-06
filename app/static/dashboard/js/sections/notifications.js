import api from '../api.js?v=2026-04-21-d';
import { normalizeMessagingEvents, normalizeNotifications } from '../adapters.js?v=2026-04-21-d';
import { escapeHtml } from '../ui.js?v=2026-04-21-a';

let pollTimer = null;

function fmtWhen(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return `${Math.round(diff)}s ago`;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  } catch (_) {
    return '';
  }
}

function severityBadge(severity) {
  const s = String(severity || '').toLowerCase();
  if (s === 'critical' || s === 'high') return 'badge-red';
  if (s === 'warning' || s === 'medium') return 'badge-amber';
  return 'badge-dim';
}

function renderMessagingEvents(events) {
  if (!events.length) return '';
  return `
    <div style="padding:12px 14px;border-bottom:1px solid var(--border);background:rgba(255,255,255,0.02)">
      <div style="font-size:10px;color:rgba(240,235,227,0.5);font-family:'DM Mono',monospace;letter-spacing:0.12em;text-transform:uppercase">Messaging Watch</div>
      <div style="font-size:11px;color:rgba(240,235,227,0.62);line-height:1.5;margin-top:6px">Recent parser, routing, and fallback events from the canonical messaging layer.</div>
    </div>
    ${events.map((item) => `
      <div style="padding:12px 14px;border-bottom:1px solid var(--border);display:flex;flex-direction:column;gap:6px;background:rgba(255,255,255,0.015)">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span class="badge ${severityBadge(item.severity)}" style="font-size:9px">${escapeHtml(String(item.severity || 'info').toUpperCase())}</span>
          <span style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(item.title)}</span>
          <span style="flex:1"></span>
          <span style="font-size:10px;color:rgba(240,235,227,0.5);font-family:'DM Mono',monospace">${escapeHtml(fmtWhen(item.createdAt))}</span>
        </div>
        <div style="font-size:11px;color:rgba(240,235,227,0.68);line-height:1.55">${escapeHtml(item.body)}</div>
        ${item.linkTarget && item.linkLabel ? `<div><button class="btn btn-sm notif-link-btn" data-target="${escapeHtml(item.linkTarget)}">${escapeHtml(item.linkLabel)}</button></div>` : ''}
      </div>
    `).join('')}`;
}

function renderPanel(feed, messagingEvents = { events: [] }) {
  const list = document.getElementById('notif-list');
  const badge = document.getElementById('notif-badge');
  const markRead = document.getElementById('notif-mark-read');
  if (!list || !badge || !markRead) return;

  const unread = Number(feed.unreadCount || 0);
  if (unread > 0) {
    badge.textContent = String(unread);
    badge.style.display = 'inline-flex';
    markRead.style.display = 'inline';
  } else {
    badge.textContent = '';
    badge.style.display = 'none';
    markRead.style.display = 'none';
  }

  if (!feed.notifications.length && !(messagingEvents.events || []).length) {
    list.innerHTML = `
      <div class="empty" style="padding:32px 20px">
        <div class="empty-title">No notifications</div>
        <div class="empty-sub">Escalations, watcher alerts, knowledge events, and messaging watch items will show up here.</div>
      </div>`;
    return;
  }

  const realNotifications = feed.notifications.map((item) => `
    <div style="padding:12px 14px;border-bottom:1px solid var(--border);display:flex;flex-direction:column;gap:6px;background:${item.readAt ? 'transparent' : 'rgba(200,120,50,0.06)'}">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <span class="badge ${severityBadge(item.severity)}" style="font-size:9px">${escapeHtml(String(item.severity || 'info').toUpperCase())}</span>
        <span style="font-size:12px;color:var(--white);font-weight:600">${escapeHtml(item.title)}</span>
        <span style="flex:1"></span>
        <span style="font-size:10px;color:rgba(240,235,227,0.5);font-family:'DM Mono',monospace">${escapeHtml(fmtWhen(item.createdAt))}</span>
      </div>
      <div style="font-size:11px;color:rgba(240,235,227,0.72);line-height:1.55">${escapeHtml(item.body)}</div>
      ${item.linkTarget && item.linkLabel ? `<div><button class="btn btn-sm notif-link-btn" data-target="${escapeHtml(item.linkTarget)}">${escapeHtml(item.linkLabel)}</button></div>` : ''}
    </div>
  `).join('');
  list.innerHTML = realNotifications + renderMessagingEvents(messagingEvents.events || []);

  list.querySelectorAll('.notif-link-btn').forEach((button) => {
    button.addEventListener('click', () => {
      const target = button.getAttribute('data-target');
      if (target && window.navigate) {
        window.navigate(target);
        document.getElementById('notif-panel')?.classList.remove('open');
      }
    });
  });
}

async function loadNotifications() {
  try {
    const [feed, messagingEvents] = await Promise.all([
      api.notifications.list().then(normalizeNotifications),
      api.messagingEvents(10).then(normalizeMessagingEvents).catch(() => ({ events: [], count: 0, available: false })),
    ]);
    renderPanel(feed, messagingEvents);
  } catch (error) {
    const list = document.getElementById('notif-list');
    if (list) {
      list.innerHTML = `
        <div class="empty" style="padding:32px 20px">
          <div class="empty-title">Could not load notifications</div>
          <div class="empty-sub">${escapeHtml(error.message || String(error))}</div>
        </div>`;
    }
  }
}

function isNotificationsRelevantView() {
  const overview = document.getElementById('view-today');
  const settings = document.getElementById('view-settings');
  return (overview && overview.style.display !== 'none') || (settings && settings.style.display !== 'none');
}

async function markNotifsRead() {
  try {
    await api.notifications.markAllRead();
    await loadNotifications();
  } catch (error) {
    console.warn('[Notifications] mark read failed:', error);
  }
}

export function init() {
  window.markNotifsRead = markNotifsRead;
  if (isNotificationsRelevantView()) {
    loadNotifications();
  }
  window.addEventListener('oyvoda:view-changed', (event) => {
    const view = event.detail?.view;
    if (view === 'today' || view === 'settings') {
      loadNotifications();
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(loadNotifications, 30000);
    } else if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  });
  if (isNotificationsRelevantView()) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(loadNotifications, 30000);
  }
}
