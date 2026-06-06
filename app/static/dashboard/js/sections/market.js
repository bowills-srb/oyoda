import api from '../api.js?v=2026-04-23-a';
import { escapeHtml, safeUrl } from '../ui.js?v=2026-04-21-a';

let loadedOnce = false;

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function renderMarket(data) {
  const d = data || {};
  const summary = d.demand_summary || {};
  const market = d.market || {};
  const events = Array.isArray(d.events) ? d.events : [];
  const categories = Array.isArray(d.categories) ? d.categories : [];
  const signals = Array.isArray(d.signals) ? d.signals : [];
  const peakDates = Array.isArray(summary.peak_dates) ? summary.peak_dates : [];

  setText('mkt-sub', `${market.name || '30A Beaches, FL'} · Next ${d.window_days || 30} days · as of ${d.as_of || 'now'}`);

  const level = summary.level || 'Unknown';
  const levelEl = document.getElementById('mkt-demand-level');
  if (levelEl) {
    levelEl.textContent = level;
    levelEl.className = 'stat-card-value' + (level === 'High' ? ' red' : level === 'Elevated' ? ' amber' : ' green');
  }
  setText('mkt-demand-sub', `${summary.high_impact_events || 0} major events driving demand`);
  setText('mkt-event-count', String(summary.total_events || 0));
  setText('mkt-high-impact', String(summary.high_impact_events || 0));
  setText('mkt-scraped', market.last_scraped ? new Date(market.last_scraped).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : 'Never');

  const peaks = document.getElementById('mkt-peaks');
  if (peaks) {
    peaks.innerHTML = peakDates.length
      ? `<table class="data-table"><thead><tr><th>Date</th><th>Events</th><th>Impact</th><th>What is On</th></tr></thead><tbody>${
          peakDates.map((item) => {
            const date = new Date(item.date).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
            return `<tr>
              <td style="font-weight:500;color:var(--white)">${escapeHtml(date)}</td>
              <td><span class="badge badge-amber">${Number(item.event_count || 0)}</span></td>
              <td>${Number(item.total_impact || 0).toFixed(1)}</td>
              <td style="font-size:11px;color:var(--dim);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(item.events || '')}</td>
            </tr>`;
          }).join('')
        }</tbody></table>`
      : '<div class="empty" style="padding:24px"><div class="empty-title">No peak date clusters found</div><div class="empty-sub">Market intelligence will populate here as event data arrives.</div></div>';
  }

  const eventsEl = document.getElementById('mkt-events');
  if (eventsEl) {
    const categoryLabelMap = { music: 'Music', festival: 'Festival', food: 'Food', sports: 'Sports', art: 'Arts', family: 'Family', holiday: 'Holiday', community: 'Community', other: 'Other' };
    const impactColors = { High: 'var(--red)', Medium: 'var(--amber)', Low: 'var(--dim)' };
    eventsEl.innerHTML = events.length
      ? events.map((event) => {
          const start = new Date(event.start_date).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
          const end = event.is_multi_day && event.end_date !== event.start_date
            ? ` – ${new Date(event.end_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
            : '';
          const ticketUrl = safeUrl(event.ticket_url);
          return `<div class="list-item" style="display:block;padding:14px">
            <div style="display:flex;align-items:flex-start;gap:10px">
              <div style="flex:1;min-width:0">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:3px">
                  <div style="font-size:13px;font-weight:500;color:var(--white)">${escapeHtml(event.title)}</div>
                  <span class="badge badge-dim" style="font-size:9px">${escapeHtml(categoryLabelMap[event.category] || 'Other')}</span>
                  <div style="width:8px;height:8px;border-radius:50%;background:${impactColors[event.demand_impact_label] || 'var(--dim)'};flex-shrink:0"></div>
                </div>
                <div style="font-size:11px;color:var(--dim);margin-bottom:4px">${escapeHtml(start + end)}${event.venue ? ` · ${escapeHtml(event.venue)}` : ''}</div>
                ${event.description ? `<div style="font-size:11px;color:rgba(240,235,227,0.4);line-height:1.4">${escapeHtml(event.description)}</div>` : ''}
              </div>
              ${ticketUrl ? `<a href="${escapeHtml(ticketUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-sm" style="margin-left:auto">Open details</a>` : ''}
            </div>
          </div>`;
        }).join('')
      : '<div class="empty" style="padding:48px"><div class="empty-title">No events found</div><div class="empty-sub">No current market events in this window.</div></div>';
  }

  const categoriesEl = document.getElementById('mkt-categories');
  if (categoriesEl) {
    const labels = { music: 'Music', festival: 'Festival', food: 'Food & Drink', sports: 'Sports', art: 'Arts', family: 'Family', holiday: 'Holiday', community: 'Community', other: 'Other' };
    const maxCount = categories.length ? Math.max(...categories.map((item) => Number(item.count || 0))) : 0;
    categoriesEl.innerHTML = categories.length
      ? categories.map((item) => {
          const pct = maxCount > 0 ? Math.round((Number(item.count || 0) / maxCount) * 100) : 0;
          return `<div style="margin-bottom:10px">
            <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:3px">
              <span style="color:var(--ghost)">${escapeHtml(labels[item.category] || item.category)}</span>
              <span style="color:var(--dim);font-family:monospace">${Number(item.count || 0)}</span>
            </div>
            <div style="background:rgba(255,255,255,0.05);border-radius:2px;height:4px"><div style="width:${pct}%;height:4px;border-radius:2px;background:var(--amber)"></div></div>
          </div>`;
        }).join('')
      : '<div style="font-size:12px;color:var(--dim);text-align:center;padding:16px">No data yet</div>';
  }

  const signalsEl = document.getElementById('mkt-signals');
  if (signalsEl) {
    signalsEl.innerHTML = signals.length
      ? signals.map((item) => {
          const pct = Math.round(Number(item.value || 0) * 100);
          const conf = Math.round(Number(item.confidence || 0) * 100);
          return `<div style="margin-bottom:12px">
            <div style="font-size:11px;color:var(--ghost);margin-bottom:4px">${escapeHtml(item.explanation || item.type || 'Signal')}</div>
            <div style="display:flex;align-items:center;gap:8px">
              <div style="flex:1;background:rgba(255,255,255,0.05);border-radius:2px;height:5px"><div style="width:${Math.min(pct, 100)}%;height:5px;border-radius:2px;background:var(--amber)"></div></div>
              <span style="font-size:10px;font-family:monospace;color:var(--dim);white-space:nowrap">${conf}% conf</span>
            </div>
          </div>`;
        }).join('')
      : '<div style="font-size:12px;color:var(--dim);text-align:center;padding:16px">Signals populate after the event scraper runs</div>';
  }

  const insightEl = document.getElementById('mkt-insight');
  if (insightEl) {
    if (!events.length) {
      insightEl.textContent = 'Market intelligence data will appear here once event coverage is available.';
    } else {
      const topEvent = events[0];
      const peak = peakDates[0];
      let insight = level === 'High'
        ? 'Demand is elevated in your market. '
        : level === 'Elevated'
          ? 'Demand is above normal. '
          : 'Demand is at normal seasonal levels. ';
      if (topEvent) {
        const date = new Date(topEvent.start_date).toLocaleDateString('en-US', { month: 'long', day: 'numeric' });
        insight += `The biggest driver is ${topEvent.title} on ${date}. `;
      }
      if (peak) {
        const date = new Date(peak.date).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
        insight += `Flag ${date} — ${peak.event_count} events that day. Consider staffing and cleaner scheduling ahead of time.`;
      }
      insightEl.textContent = insight;
    }
  }
}

async function loadMarket(days = 30, button) {
  if (button) {
    button.closest('.tab-bar')?.querySelectorAll('.tab').forEach((tab) => tab.classList.remove('active'));
    button.classList.add('active');
  }
  setText('mkt-sub', 'Loading...');
  try {
    renderMarket(await api.market.intelligence(days));
    loadedOnce = true;
  } catch (error) {
    setText('mkt-sub', 'Could not load market data');
    console.warn('[Market] load failed:', error);
  }
}

export function init() {
  window.__oyvodaMarketModule = true;
  window.loadMarket = loadMarket;
  window.addEventListener('oyvoda:view-changed', (event) => {
    if (event.detail?.view === 'market' && !loadedOnce) {
      loadMarket(30);
    }
  });
}
