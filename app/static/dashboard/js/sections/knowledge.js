import api from '../api.js?v=2026-05-19-g';
import { closeModal, escapeHtml } from '../ui.js?v=2026-04-21-a';
import { normalizeKbEntries, normalizeKbGaps, normalizeKbTestResult, normalizeMessageFeed, renderInlineError } from '../adapters.js?v=2026-05-20-h';

const state = {
  entries: [],
  gaps: [],
  waitingInquiries: [],
  properties: [],
  counts: { entries: 0, gaps: 0 },
  loaded: false,
  shipIKbRetryEnabled: false,
  pendingKbAction: null,
};

function fmtTime(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' });
  } catch (_) {
    return '';
  }
}

function renderCounts() {
  const entriesEl = document.getElementById('kb-entries-count');
  const gapsEl = document.getElementById('kb-gaps-count');
  if (entriesEl) entriesEl.textContent = String(state.counts.entries || 0);
  if (gapsEl) gapsEl.textContent = String(state.counts.gaps || 0);
}

function renderEntries() {
  const list = document.getElementById('kb-entries-list');
  if (!list) return;
  if (!state.entries.length) {
    list.innerHTML = `
      <div class="empty" style="padding:48px">
        <div class="empty-title">No knowledge entries yet</div>
        <div class="empty-sub">As operators answer questions and close gaps, reusable knowledge will show up here.</div>
      </div>`;
    return;
  }
  list.innerHTML = state.entries.map((entry) => `
    <div class="card" style="margin-bottom:12px">
      <div class="card-body" style="display:flex;flex-direction:column;gap:10px">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span class="badge badge-amber" style="font-size:9px">${escapeHtml(entry.category)}</span>
          <span class="badge badge-dim" style="font-size:9px">${escapeHtml(entry.propertyLabel)}</span>
          <span style="flex:1"></span>
          <span style="font-size:10px;color:rgba(240,235,227,0.55);font-family:'DM Mono',monospace">${Math.round(entry.confidence * 100)}% confidence</span>
        </div>
        <div style="font-size:13px;color:var(--white);font-weight:600;line-height:1.45">${escapeHtml(entry.question)}</div>
        <div style="font-size:12px;color:rgba(240,235,227,0.82);line-height:1.65;white-space:pre-wrap">${escapeHtml(entry.answer)}</div>
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:10px;color:rgba(240,235,227,0.5);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.08em">
          <span>${escapeHtml(entry.source || 'operator_dashboard')}</span>
          <span>${entry.usageCount} uses</span>
          ${entry.updatedAt ? `<span>updated ${escapeHtml(fmtTime(entry.updatedAt))}</span>` : ''}
          <span style="flex:1"></span>
          <button class="btn btn-sm kb-edit-btn" data-entry-id="${escapeHtml(entry.id)}">Edit</button>
          <button class="btn btn-sm kb-delete-btn" data-entry-id="${escapeHtml(entry.id)}">Delete</button>
        </div>
      </div>
    </div>
  `).join('');
}

function renderGaps() {
  const list = document.getElementById('kb-gaps-list');
  if (!list) return;
  if (!state.gaps.length) {
    list.innerHTML = `
      <div class="empty" style="padding:48px">
        <div class="empty-title">No open knowledge gaps</div>
        <div class="empty-sub">When guest questions expose missing property knowledge, they’ll appear here for cleanup.</div>
      </div>`;
    return;
  }
  list.innerHTML = state.gaps.map((gap) => `
    <div class="card" style="margin-bottom:12px">
      <div class="card-body" style="display:flex;flex-direction:column;gap:10px">
        <div style="font-size:10px;color:rgba(240,235,227,0.54);font-family:'DM Mono',monospace;letter-spacing:0.08em;text-transform:uppercase">Inquiries waiting on knowledge</div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span class="badge badge-red" style="font-size:9px">${escapeHtml(gap.category)}</span>
          <span class="badge badge-dim" style="font-size:9px">${escapeHtml(gap.property)}</span>
          ${gap.channel ? `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(gap.channel)}</span>` : ''}
          ${gap.parserSource ? `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(gap.parserSource)}</span>` : ''}
          <span style="flex:1"></span>
          <span style="font-size:10px;color:rgba(240,235,227,0.55);font-family:'DM Mono',monospace">${Math.round(gap.confidence * 100)}% confidence</span>
        </div>
        <div style="font-size:13px;color:var(--white);font-weight:600;line-height:1.45">${escapeHtml(gap.question)}</div>
        ${gap.aiAnswer ? `<div style="font-size:11px;color:rgba(240,235,227,0.62);line-height:1.6"><strong>Drafted answer:</strong> ${escapeHtml(gap.aiAnswer)}</div>` : ''}
        ${(gap.asks.length || gap.missingTopics.length || gap.reason || gap.intent) ? `
          <div style="display:flex;flex-direction:column;gap:6px;padding:10px 12px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:10px">
            ${(gap.asks.length || gap.missingTopics.length) ? `
              <div style="display:flex;gap:6px;flex-wrap:wrap">
                ${gap.asks.map((ask) => `<span class="badge badge-dim" style="font-size:9px">${escapeHtml(ask.replace(/_/g, ' '))}</span>`).join('')}
                ${gap.missingTopics.map((topic) => `<span class="badge badge-amber" style="font-size:9px">${escapeHtml(topic.replace(/_/g, ' '))}</span>`).join('')}
              </div>` : ''}
            ${(gap.reason || gap.intent) ? `<div style="font-size:11px;color:rgba(240,235,227,0.64);line-height:1.55"><strong style="color:rgba(240,235,227,0.78)">Why this gap exists:</strong> ${escapeHtml((gap.reason || 'unknown').replace(/_/g, ' '))}${gap.intent ? ` · intent ${escapeHtml(gap.intent.replace(/_/g, ' '))}` : ''}</div>` : ''}
            ${(gap.thresholdPct != null || gap.actualPct != null) ? `<div style="font-size:11px;color:rgba(240,235,227,0.58);line-height:1.55">${gap.actualPct != null ? `actual ${escapeHtml(String(gap.actualPct))}%` : ''}${gap.thresholdPct != null ? `${gap.actualPct != null ? ' · ' : ''}threshold ${escapeHtml(String(gap.thresholdPct))}%` : ''}</div>` : ''}
            ${(gap.platformListingId || gap.platformUnitId || gap.draftId) ? `<div style="font-size:11px;color:rgba(240,235,227,0.58);line-height:1.55">${gap.platformListingId ? `listing ${escapeHtml(gap.platformListingId)}` : ''}${gap.platformUnitId ? `${gap.platformListingId ? ' · ' : ''}unit ${escapeHtml(gap.platformUnitId)}` : ''}${gap.draftId ? `${(gap.platformListingId || gap.platformUnitId) ? ' · ' : ''}draft ${escapeHtml(gap.draftId)}` : ''}</div>` : ''}
            ${gap.linkContextSummary ? `<div style="font-size:11px;color:rgba(240,235,227,0.58);line-height:1.6"><strong style="color:rgba(240,235,227,0.72)">Linked page context:</strong> ${escapeHtml(gap.linkContextSummary)}</div>` : ''}
          </div>` : ''}
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:10px;color:rgba(240,235,227,0.5);font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.08em">
          <span>${gap.askCount} similar ask${gap.askCount === 1 ? '' : 's'}</span>
          ${gap.createdAt ? `<span>opened ${escapeHtml(fmtTime(gap.createdAt))}</span>` : ''}
          <span style="flex:1"></span>
          <button class="btn btn-sm kb-gap-resolve-btn" data-gap-id="${escapeHtml(gap.id)}">Resolve in KB</button>
          <button class="btn btn-sm kb-gap-dismiss-btn" data-gap-id="${escapeHtml(gap.id)}">Dismiss</button>
        </div>
      </div>
    </div>
  `).join('');
}

function isKnowledgeGap(item) {
  return String(item?.draftSource || '').toLowerCase() === 'kb_gap_required'
    || String(item?.confidenceSource || '').toLowerCase() === 'knowledge_gap_required'
    || (item?.policyWarnings || []).some((warn) => String(warn).startsWith('missing_property_knowledge:'));
}

function gapTopic(item) {
  const warning = (item?.policyWarnings || []).find((warn) => String(warn).startsWith('missing_property_knowledge:'));
  return warning ? String(warning).replace('missing_property_knowledge:', '').replace(/[_-]+/g, ' ').trim() : 'Recurring question';
}

function renderWaitingInquiries() {
  const list = document.getElementById('kb-inquiries-waiting-list');
  const shell = document.getElementById('kb-inquiries-waiting');
  if (!list || !shell) return;
  if (state.shipIKbRetryEnabled) {
    shell.style.display = 'none';
    list.innerHTML = '';
    return;
  }
  shell.style.display = '';
  if (!state.waitingInquiries.length) {
    list.innerHTML = `
      <div class="empty" style="padding:24px">
        <div class="empty-title">No inquiries are waiting on knowledge</div>
        <div class="empty-sub">When a guest question needs missing property knowledge, it will show up here until someone resolves it in the KB.</div>
      </div>`;
    return;
  }
  list.innerHTML = state.waitingInquiries.map((item) => {
    const guest = item.guestName || 'Guest';
    const property = item.propertyName || 'Unbound';
    const age = fmtTime(item.occurredAt) || 'Today';
    const question = item.latestGuestTurn || item.messageText || item.messagePreview || '(no guest message captured)';
    return `
      <div class="kb-waiting-row">
        <div class="kb-waiting-meta">${escapeHtml(`${guest} · ${property} · ${age}`)}</div>
        <div class="kb-waiting-topic">${escapeHtml(gapTopic(item))}</div>
        <div class="kb-waiting-question">${escapeHtml(question)}</div>
        <div class="kb-waiting-actions">
          <button class="btn btn-sm btn-primary kb-waiting-resolve-btn" data-waiting-id="${escapeHtml(item.id)}">Resolve in KB</button>
        </div>
      </div>
    `;
  }).join('');
}

function applyKnowledgeLayoutState() {
  const knowledge = document.getElementById('view-knowledge');
  if (knowledge) knowledge.classList.add('kb-shell');
}

async function loadKnowledge() {
  applyKnowledgeLayoutState();
  const entriesList = document.getElementById('kb-entries-list');
  const gapsList = document.getElementById('kb-gaps-list');
  if (entriesList) entriesList.innerHTML = renderInlineError('Loading knowledge base…', 'Pulling saved Q&A and property guidance.');
  if (gapsList) gapsList.innerHTML = renderInlineError('Loading gaps…', 'Checking unresolved guest questions.');
  const waitingList = document.getElementById('kb-inquiries-waiting-list');
  if (waitingList) waitingList.innerHTML = renderInlineError('Loading waiting inquiries…', 'Checking pre-booking questions that need knowledge.');
  try {
    const [entriesPayload, gapsPayload, propertiesPayload, waitingPayload] = await Promise.all([
      api.kb.list(),
      api.kbGaps.list(false),
      api.properties(),
      api.messages.list({ stage: 'pre_booking', status: 'all', limit: 200 }),
    ]);
    const entries = normalizeKbEntries(entriesPayload);
    const gaps = normalizeKbGaps(gapsPayload);
    const waitingFeed = normalizeMessageFeed(waitingPayload);
    state.entries = entries.entries;
    state.gaps = gaps.gaps;
    state.shipIKbRetryEnabled = !!waitingFeed.shipIKbRetryPrimary;
    state.waitingInquiries = state.shipIKbRetryEnabled
      ? []
      : (waitingFeed.items || []).filter((item) => isKnowledgeGap(item));
    state.properties = Array.isArray(propertiesPayload?.properties) ? propertiesPayload.properties : [];
    state.counts.entries = entries.count;
    state.counts.gaps = gaps.totalUnresolved || gaps.count;
    state.loaded = true;
    renderCounts();
    renderEntries();
    renderGaps();
    renderWaitingInquiries();
    populatePropertyOptions();
  } catch (error) {
    if (entriesList) {
      entriesList.innerHTML = renderInlineError('Could not load knowledge base', error.message || String(error), 'kb-entries-retry');
      const btn = document.getElementById('kb-entries-retry');
      if (btn) btn.addEventListener('click', loadKnowledge);
    }
    if (gapsList) gapsList.innerHTML = renderInlineError('Could not load gaps', error.message || String(error));
    if (waitingList) waitingList.innerHTML = renderInlineError('Could not load waiting inquiries', error.message || String(error));
  }
}

function populatePropertyOptions() {
  const select = document.getElementById('new-kb-property');
  if (!select) return;
  const current = select.value || '';
  const labels = new Map();
  state.properties.forEach((property) => {
    const propertyId = property.id || '';
    const propertyCode = property.property_code || property.external_id || '';
    if (!propertyId) return;
    const label = property.address_street
      ? `${property.address_street}${propertyCode ? ` (${propertyCode})` : ''}`
      : (propertyCode || propertyId || 'Property');
    labels.set(propertyId, { label, propertyCode });
  });
  select.innerHTML = '<option value="">All Properties</option>' + Array.from(labels.entries())
    .sort((a, b) => a[1].label.localeCompare(b[1].label))
    .map(([value, meta]) => `<option value="${escapeHtml(value)}" data-property-code="${escapeHtml(meta.propertyCode || '')}">${escapeHtml(meta.label)}</option>`)
    .join('');
  select.value = current;
}

function isKnowledgeView() {
  const knowledge = document.getElementById('view-knowledge');
  const gaps = document.getElementById('view-gaps');
  return (knowledge && knowledge.style.display !== 'none') || (gaps && gaps.style.display !== 'none');
}

async function saveKbEntry() {
  const qEl = document.getElementById('new-kb-q');
  const aEl = document.getElementById('new-kb-a');
  const propertyEl = document.getElementById('new-kb-property');
  const categoryEl = document.getElementById('new-kb-category');
  const question = (qEl?.value || '').trim();
  const answer = (aEl?.value || '').trim();
  if (!question || !answer) {
    alert('Add both a question and an answer.');
    return;
  }
  const propertyId = propertyEl?.value || '';
  const propertyCode = propertyEl?.selectedOptions?.[0]?.dataset?.propertyCode || '';
  try {
    const action = state.pendingKbAction;
    let response;
    if (action?.source === 'gap' && action?.gapId) {
      response = await api.kbGaps.resolve(action.gapId, {
        add_to_kb: true,
        answer,
        notes: 'Resolved from shared KB modal',
        retry_topic: action.retryTopic || '',
      });
    } else {
      response = await api.kb.create({
        question,
        answer,
        category: categoryEl?.value || 'General',
        property_id: propertyId || null,
        property_external_id: propertyCode || '__all_properties__',
        retry_topic: action?.retryTopic || '',
      });
    }
    if (qEl) qEl.value = '';
    if (aEl) aEl.value = '';
    if (propertyEl) propertyEl.value = '';
    state.pendingKbAction = null;
    closeModal('add-kb-modal');
    await reportRetryOutcome(response);
    await loadKnowledge();
    if (typeof window.reloadMessages === 'function') window.reloadMessages();
  } catch (error) {
    alert(error.message || 'Could not save knowledge entry.');
  }
}

async function testQuestion() {
  const input = document.getElementById('test-q');
  const result = document.getElementById('test-result');
  const answer = document.getElementById('test-answer');
  const confBar = document.getElementById('test-conf-bar');
  const confLabel = document.getElementById('test-conf-label');
  const sources = document.getElementById('test-sources');
  const question = (input?.value || '').trim();
  if (!question || !result || !answer || !confBar || !confLabel || !sources) return;

  result.style.display = 'block';
  answer.textContent = 'Testing this question against the knowledge base…';
  confBar.style.width = '0%';
  confLabel.textContent = '—';
  sources.textContent = '';

  try {
    const normalized = normalizeKbTestResult(await api.kb.test(question));
    const pct = Math.round(Math.max(0, Math.min(1, normalized.confidence)) * 100);
    answer.textContent = normalized.answer;
    confBar.style.width = `${pct}%`;
    confLabel.textContent = `${pct}% ${normalized.answered ? 'grounded' : 'gap detected'}`;
    confLabel.style.color = normalized.answered ? 'var(--green)' : 'var(--amber)';
    sources.textContent = normalized.sources.length
      ? normalized.sources.join(' · ')
      : 'No confident KB source matched this question.';
    if (!normalized.answered) {
      await loadKnowledge();
    }
  } catch (error) {
    answer.textContent = error.message || 'Could not test question.';
    confLabel.textContent = 'Error';
    confLabel.style.color = 'var(--red)';
  }
}

function openKbResolveFlow(config = {}) {
  state.pendingKbAction = {
    source: config.source || 'queue',
    gapId: config.gapId || '',
    retryTopic: config.retryTopic || '',
    retryCount: Number(config.retryCount || 0),
  };
  const qEl = document.getElementById('new-kb-q');
  const aEl = document.getElementById('new-kb-a');
  const propertyEl = document.getElementById('new-kb-property');
  const categoryEl = document.getElementById('new-kb-category');
  const retryPreviewEl = document.getElementById('new-kb-retry-preview');
  if (qEl) qEl.value = config.question || '';
  if (aEl) aEl.value = config.answerHint || '';
  if (propertyEl && config.propertyId) propertyEl.value = config.propertyId;
  if (categoryEl && config.category) categoryEl.value = config.category;
  if (retryPreviewEl) {
    if (state.pendingKbAction.retryCount > 0) {
      const noun = state.pendingKbAction.retryCount === 1 ? 'held draft' : 'held drafts';
      retryPreviewEl.textContent = `Saving this will retry ${state.pendingKbAction.retryCount} ${noun}.`;
      retryPreviewEl.style.display = 'block';
    } else {
      retryPreviewEl.textContent = '';
      retryPreviewEl.style.display = 'none';
    }
  }
  const modal = document.getElementById('add-kb-modal');
  if (modal) modal.style.display = 'flex';
}

async function reportRetryOutcome(response) {
  const triggered = Array.isArray(response?.triggered_regenerations) ? response.triggered_regenerations : [];
  if (!triggered.length) return;
  const ids = triggered.map((entry) => String(entry.inquiry_id || '')).filter(Boolean);
  await new Promise((resolve) => setTimeout(resolve, 1500));
  try {
    const feed = normalizeMessageFeed(await api.messages.list({ stage: 'pre_booking', status: 'all', limit: 200 }));
    const matching = (feed.items || []).filter((item) => ids.includes(String(item.id || '')));
    const sent = matching.filter((item) => String(item.status).toLowerCase() === 'replied').length;
    const returned = matching.filter((item) => String(item.status).toLowerCase() === 'pending_review').length;
    alert(`Retried ${triggered.length} drafts: ${sent} sent, ${returned} returned to your queue.`);
  } catch (_) {
    alert(`Retried ${triggered.length} drafts.`);
  }
}

async function resolveGap(gapId) {
  const gap = state.gaps.find((item) => item.id === gapId);
  if (!gap) return;
  openKbResolveFlow({
    source: 'gap',
    gapId,
    question: gap.question,
    answerHint: gap.aiAnswer || '',
    category: gap.categorySlug || gap.category || 'General',
    retryTopic: (gap.missingTopics && gap.missingTopics[0]) || '',
    retryCount: 0,
  });
}

async function dismissGap(gapId) {
  try {
    await api.kbGaps.dismiss(gapId);
    await loadKnowledge();
  } catch (error) {
    alert(error.message || 'Could not dismiss gap.');
  }
}

function editEntry(entryId) {
  const entry = state.entries.find((item) => item.id === entryId);
  if (!entry) return;
  const question = window.prompt('Update the guest question:', entry.question);
  if (question == null) return;
  const answer = window.prompt('Update the saved answer:', entry.answer);
  if (answer == null) return;
  api.kb.update(entryId, {
    question: question.trim(),
    answer: answer.trim(),
    category: entry.category,
  }).then(loadKnowledge).catch((error) => {
    alert(error.message || 'Could not update KB entry.');
  });
}

function deleteEntry(entryId) {
  if (!window.confirm('Delete this knowledge entry?')) return;
  api.kb.delete(entryId).then(loadKnowledge).catch((error) => {
    alert(error.message || 'Could not delete KB entry.');
  });
}

function wireDom() {
  const entriesList = document.getElementById('kb-entries-list');
  const gapsList = document.getElementById('kb-gaps-list');
  const waitingList = document.getElementById('kb-inquiries-waiting-list');
  if (entriesList && entriesList.dataset.wired !== '1') {
    entriesList.dataset.wired = '1';
    entriesList.addEventListener('click', (event) => {
      const editBtn = event.target.closest('.kb-edit-btn');
      const deleteBtn = event.target.closest('.kb-delete-btn');
      if (editBtn) editEntry(editBtn.getAttribute('data-entry-id'));
      if (deleteBtn) deleteEntry(deleteBtn.getAttribute('data-entry-id'));
    });
  }
  if (gapsList && gapsList.dataset.wired !== '1') {
    gapsList.dataset.wired = '1';
    gapsList.addEventListener('click', (event) => {
      const resolveBtn = event.target.closest('.kb-gap-resolve-btn');
      const dismissBtn = event.target.closest('.kb-gap-dismiss-btn');
      if (resolveBtn) resolveGap(resolveBtn.getAttribute('data-gap-id'));
      if (dismissBtn) dismissGap(dismissBtn.getAttribute('data-gap-id'));
    });
  }
  if (waitingList && waitingList.dataset.wired !== '1') {
    waitingList.dataset.wired = '1';
    waitingList.addEventListener('click', (event) => {
      const resolveBtn = event.target.closest('.kb-waiting-resolve-btn');
      if (!resolveBtn) return;
      const item = state.waitingInquiries.find((entry) => entry.id === resolveBtn.getAttribute('data-waiting-id'));
      if (!item) return;
      const qEl = document.getElementById('new-kb-q');
      openKbResolveFlow({
        source: 'queue',
        draftId: item.id,
        question: item.latestGuestTurn || item.messageText || item.messagePreview || '',
        answerHint: item.draftText || '',
        propertyId: item.propertyId || '',
        category: gapTopic(item),
        retryTopic: gapTopic(item),
        retryCount: state.waitingInquiries.filter((entry) => gapTopic(entry) === gapTopic(item)).length,
      });
    });
  }
}

export function init() {
  wireDom();
  window.testQuestion = testQuestion;
  window.saveKbEntry = saveKbEntry;
  window.dismissGap = dismissGap;
  window.openKbResolveFlow = openKbResolveFlow;
  window.addAllToKb = function() {};
  window.dismissAllSuggest = function() {};

  window.addEventListener('oyvoda:view-changed', (event) => {
    const view = event.detail?.view;
    if (view === 'knowledge' || view === 'gaps') {
      loadKnowledge();
    }
  });
  if (isKnowledgeView()) {
    loadKnowledge();
  }
}
