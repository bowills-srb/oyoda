import api from '../api.js?v=2026-04-21-e';
import { state } from '../state.js?v=2026-04-21-b';
import { escapeHtml } from '../ui.js?v=2026-04-21-a';

function fmtWhen(iso) {
  if (!iso) return 'never';
  try {
    const dt = new Date(iso);
    return dt.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  } catch (_) {
    return iso;
  }
}

function setBannerCta(button, step) {
  if (!button || !step?.cta_target) return;
  button.textContent = (step.cta_label || 'Set it up') + ' →';
  if (step.cta_target.startsWith('/')) {
    button.href = step.cta_target;
    button.onclick = null;
    return;
  }
  button.href = 'javascript:void(0)';
  button.onclick = function(ev) {
    ev.preventDefault();
    if (window.navigate) window.navigate(step.cta_target);
  };
}

export async function loadOnboardingStatus() {
  try {
    const d = await api.onboarding.status();
    state.set('onboardingStatus', d);
    const visibleSteps = (d.steps || []).filter((step) => !step.done || step.visible_when_complete !== false);
    const incompleteSteps = (d.steps || []).filter((step) => !step.done);

    const inboxStatus = d.inbox_status || {};
    const banner = document.getElementById('onboarding-banner');
    const bannerTitle = document.getElementById('onboarding-banner-title');
    const bannerDetail = document.getElementById('onboarding-banner-detail');
    const bannerCta = document.getElementById('onboarding-banner-cta');
    const dismissed = sessionStorage.getItem('oyvoda_onboarding_banner_dismissed') === '1';

    if (banner && d.critical_incomplete && !dismissed) {
      const step = d.critical_incomplete;
      if (bannerTitle) bannerTitle.textContent = step.title;
      if (bannerDetail) bannerDetail.textContent = step.detail || '';
      setBannerCta(bannerCta, step);
      banner.style.display = 'flex';
    } else if (banner) {
      banner.style.display = 'none';
    }

    const card = document.getElementById('onboarding-card');
    const sub = document.getElementById('onboarding-card-sub');
    const pct = document.getElementById('onboarding-percent');
    const bar = document.getElementById('onboarding-progress-bar');
    const list = document.getElementById('onboarding-steps-list');
    if (!card) return d;

    // Hide the Setup Checklist entirely once onboarding is 100% complete.
    // The visibleSteps filter keeps `done` steps in view by default (so an
    // operator partway through can see what they've already done), but once
    // everything is finished the card is no longer actionable and should
    // get out of the way of the morning worklist.
    const fullyComplete = incompleteSteps.length === 0
      || (d.percent_complete === 100)
      || (d.total && d.completed >= d.total);

    if (!visibleSteps.length || fullyComplete) {
      card.style.display = 'none';
    } else {
      card.style.display = '';
      if (pct) pct.textContent = (d.percent_complete || 0) + '%';
      if (bar) bar.style.width = (d.percent_complete || 0) + '%';
      if (sub) sub.textContent = `${d.completed} of ${d.total} steps complete. Pick up where you left off.`;
      if (list) {
        list.innerHTML = visibleSteps.map((step) => {
          const done = !!step.done;
          const checkIcon = done
            ? '<div style="width:20px;height:20px;border-radius:50%;background:rgba(34,197,94,0.18);border:1px solid rgba(34,197,94,0.4);display:flex;align-items:center;justify-content:center;color:#22c55e;font-size:11px;flex-shrink:0">✓</div>'
            : (step.critical
              ? '<div style="width:20px;height:20px;border-radius:50%;background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.4);flex-shrink:0"></div>'
              : '<div style="width:20px;height:20px;border-radius:50%;border:1px solid rgba(255,255,255,0.2);flex-shrink:0"></div>');
          const titleStyle = done
            ? 'color:rgba(240,235,227,0.5);text-decoration:line-through;font-size:13px;font-weight:500'
            : 'color:var(--white);font-size:13px;font-weight:500';
          let ctaHtml = '';
          if (step.cta_label && step.cta_target) {
            const isUrl = step.cta_target.startsWith('/');
            const click = isUrl
              ? `window.location.href='${step.cta_target}'`
              : `window.navigate && window.navigate('${step.cta_target}')`;
            ctaHtml = `<button class="btn btn-sm" onclick="${click}" style="font-size:11px;padding:5px 10px;flex-shrink:0;${done ? 'opacity:0.6' : ''}">${escapeHtml(step.cta_label)}${done ? '' : ' →'}</button>`;
          }
          return `
            <div style="display:flex;align-items:flex-start;gap:12px;padding:14px 20px;border-bottom:1px solid rgba(255,255,255,0.04)">
              ${checkIcon}
              <div style="flex:1;min-width:0">
                <div style="${titleStyle}">${escapeHtml(step.title)}</div>
                ${step.detail ? `<div style="font-size:11px;color:var(--dim);margin-top:3px;line-height:1.5">${escapeHtml(step.detail)}</div>` : ''}
              </div>
              ${ctaHtml}
            </div>
          `;
        }).join('') || '<div class="empty" style="padding:24px"><div class="empty-sub">No setup steps available.</div></div>';
      }
    }

    const gmailStatus = document.getElementById('gmail-status');
    if (gmailStatus) {
      if (d.inbox_connected) {
        let txt = inboxStatus.email || 'Inbox connected';
        if (inboxStatus.last_polled_at) txt += ` · last polled ${fmtWhen(inboxStatus.last_polled_at)}`;
        if (inboxStatus.last_poll_summary) txt += ` · ${inboxStatus.last_poll_summary}`;
        if (inboxStatus.last_poll_success === false && inboxStatus.last_poll_error) txt += ` · error: ${inboxStatus.last_poll_error}`;
        gmailStatus.textContent = txt;
      } else {
        gmailStatus.textContent = 'Inbox not connected yet';
      }
    }
    return d;
  } catch (error) {
    console.warn('[Oyvoda] onboarding status failed:', error);
    return null;
  }
}

export function dismissOnboardingBanner() {
  sessionStorage.setItem('oyvoda_onboarding_banner_dismissed', '1');
  const banner = document.getElementById('onboarding-banner');
  if (banner) banner.style.display = 'none';
}

export function openCommandPaletteStub() {
  const modal = document.getElementById('command-modal');
  if (!modal) return;
  modal.style.display = 'flex';
}

export function closeCommandPaletteStub() {
  const modal = document.getElementById('command-modal');
  if (!modal) return;
  modal.style.display = 'none';
}

export function openDetailPanel(title = 'Context panel', html = '') {
  const panel = document.getElementById('detail-panel');
  const titleEl = document.getElementById('detail-panel-title');
  const body = document.getElementById('detail-panel-body');
  if (!panel || !titleEl || !body) return;
  titleEl.textContent = title;
  body.innerHTML = html || `
    <div class="detail-panel-section">
      <div class="empty-state" style="padding:32px 20px">
        <div class="empty-state-title">No item selected</div>
        <div class="empty-state-description">Sections will begin using this contextual detail rail in later ships.</div>
      </div>
    </div>
  `;
  panel.classList.add('is-open');
  panel.setAttribute('aria-hidden', 'false');
  document.body.setAttribute('data-detail-open', 'true');
}

export function closeDetailPanel() {
  const panel = document.getElementById('detail-panel');
  if (!panel) return;
  panel.classList.remove('is-open');
  panel.setAttribute('aria-hidden', 'true');
  document.body.setAttribute('data-detail-open', 'false');
}

export function init() {
  window.dismissOnboardingBanner = dismissOnboardingBanner;
  window.loadOnboardingStatus = loadOnboardingStatus;
  window.openCommandPaletteStub = openCommandPaletteStub;
  window.closeCommandPaletteStub = closeCommandPaletteStub;
  window.openDetailPanel = openDetailPanel;
  window.closeDetailPanel = closeDetailPanel;

  window.addEventListener('oyvoda:view-changed', function(e) {
    const view = e.detail && e.detail.view;
    if (view === 'today') {
      loadOnboardingStatus();
    }
  });
}
