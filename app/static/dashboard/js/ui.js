/**
 * ui.js — Shared UI primitives.
 *
 * showModal(html)        — show modal with injected HTML content
 * closeModal()           — hide and clear modal
 * toggleNotifs()         — open/close notifications panel
 * escapeHtml(str)        — safe HTML escaping for user content
 * safeUrl(str)           — validate URLs before using in hrefs
 */

function showModal(id) {
  document.getElementById(id).style.display = 'flex';
}

function closeModal(id) {
  document.getElementById(id).style.display = 'none';
}

function toggleNotifs() {
  document.getElementById('notif-panel').classList.toggle('open');
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function safeUrl(value) {
  if (!value) return '';
  try {
    const parsed = new URL(String(value), window.location.origin);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.href;
    }
  } catch (e) {}
  return '';
}

window.showModal = showModal;
window.closeModal = closeModal;
window.toggleNotifs = toggleNotifs;

export { showModal, closeModal, toggleNotifs, escapeHtml, safeUrl };
