import type { MessageFeedItem, PropertyMatchSuggestion } from "../../domain/prebooking/types";

export type QueueTab = "action" | "sent" | "held" | "closed";
export type QueueScope = "all" | "mine" | "unassigned";
export type QueueDepth = 5 | 10 | 25 | 50 | "all";
export type QueueMetricFocus = "all" | "draft_ready" | "knowledge_gap" | "unbound";

export type QueueCardViewModel = {
  item: MessageFeedItem;
  isSelected: boolean;
  actionable: boolean;
  sendAllowed: boolean;
  needsKb: boolean;
  isPendingSend: boolean;
  isPendingReject: boolean;
  isPendingBind: boolean;
  isPending: boolean;
  guestText: string;
  draftText: string;
  guidance: {
    tone: "accent" | "warning" | "danger" | "default";
    title: string;
    body: string;
  };
  showDraftPreview: boolean;
  confidenceChip: {
    label: string;
    tone: "success" | "warning" | "danger";
  } | null;
  bindingCandidates: MessageFeedItem["propertyBindingCandidates"];
  bindingSuggestionsForItem: PropertyMatchSuggestion[];
  bindingQueryForItem: string;
  bindingLoadingForItem: boolean;
  bindingErrorForItem: string;
};

type BuildQueueViewModelArgs = {
  activeTab: QueueTab;
  bindingDraftId: string | null;
  bindingError: string;
  bindingLoading: boolean;
  bindingQuery: string;
  bindingSuggestions: PropertyMatchSuggestion[];
  canOperatorSend: (item: MessageFeedItem) => boolean;
  focusMetric: QueueMetricFocus;
  getConfidenceLabel: (confidence: number) => { label: string; tone: "success" | "warning" | "danger" };
  getNextStepGuidance: (item: MessageFeedItem) => {
    tone: "accent" | "warning" | "danger" | "default";
    title: string;
    body: string;
  };
  getQueueBucket: (item: MessageFeedItem) => QueueTab;
  getRowState: (item: MessageFeedItem, threshold: number) => "ready" | "needs_review" | "blocked" | "other";
  inquiries: MessageFeedItem[];
  matchesMetricFocus: (item: MessageFeedItem, focus: QueueMetricFocus) => boolean;
  needsKnowledgeGap: (item: MessageFeedItem) => boolean;
  operatorId: string;
  pendingAction: { id: string; kind: "send" | "reject" | "edit" | "bind" } | null;
  propertyId: string;
  queueDepth: QueueDepth;
  scope: QueueScope;
  search: string;
  selectedInquiryId: string | null;
  threshold: number;
};

export function buildQueueViewModel({
  activeTab,
  bindingDraftId,
  bindingError,
  bindingLoading,
  bindingQuery,
  bindingSuggestions,
  canOperatorSend,
  focusMetric,
  getConfidenceLabel,
  getNextStepGuidance,
  getQueueBucket,
  getRowState,
  inquiries,
  matchesMetricFocus,
  needsKnowledgeGap,
  operatorId,
  pendingAction,
  propertyId,
  queueDepth,
  scope,
  search,
  selectedInquiryId,
  threshold,
}: BuildQueueViewModelArgs) {
  const normalizedSearch = search.trim().toLowerCase();

  const queueByTab = inquiries.reduce<Record<QueueTab, MessageFeedItem[]>>(
    (acc, item) => {
      acc[getQueueBucket(item)].push(item);
      return acc;
    },
    { action: [], sent: [], held: [], closed: [] },
  );

  const baseFilter = (items: MessageFeedItem[]) =>
    items.filter((item) => {
      if (propertyId && item.propertyId !== propertyId) return false;
      if (scope === "mine" && (!operatorId || item.assignedOperatorId !== operatorId)) return false;
      if (scope === "unassigned" && (item.assignmentStatus === "assigned" || item.assignedOperatorId)) return false;
      if (!normalizedSearch) return true;
      const haystack =
        `${item.guestName} ${item.messagePreview} ${item.latestGuestTurn} ${item.propertyName}`.toLowerCase();
      return haystack.includes(normalizedSearch);
    });

  const filterPipeline = (items: MessageFeedItem[]) =>
    baseFilter(items).filter((item) => matchesMetricFocus(item, focusMetric));

  const searchedItems = filterPipeline(queueByTab[activeTab]);
  const depthLimit = queueDepth === "all" ? searchedItems.length : queueDepth;
  const visibleItems = searchedItems.slice(0, depthLimit);

  const tabCounts: Record<QueueTab, number> = {
    action: baseFilter(queueByTab.action).length,
    sent: baseFilter(queueByTab.sent).length,
    held: baseFilter(queueByTab.held).length,
    closed: baseFilter(queueByTab.closed).length,
  };

  const actionBase = baseFilter(queueByTab.action);
  const heldBase = baseFilter(queueByTab.held);
  const awaitingCount = actionBase.length;
  const draftReadyCount = actionBase.filter((item) => matchesMetricFocus(item, "draft_ready")).length;
  const unboundCount = actionBase.filter((item) => matchesMetricFocus(item, "unbound")).length;
  const knowledgeGapCount =
    actionBase.filter((item) => matchesMetricFocus(item, "knowledge_gap")).length +
    heldBase.filter((item) => matchesMetricFocus(item, "knowledge_gap")).length;

  const selectedInquiry = selectedInquiryId
    ? visibleItems.find((item) => item.id === selectedInquiryId) ?? null
    : null;

  const oldestAction = queueByTab.action
    .slice()
    .sort((a, b) => new Date(a.occurredAt || 0).getTime() - new Date(b.occurredAt || 0).getTime())[0];

  const cards: QueueCardViewModel[] = visibleItems.map((item) => {
    const isSelected = selectedInquiryId === item.id;
    const actionable = item.kind === "inquiry" && ["pending_review", "backlog_held"].includes((item.status || "").toLowerCase());
    const sendAllowed = canOperatorSend(item);
    const needsKb = needsKnowledgeGap(item);
    const isPendingSend = pendingAction?.id === item.id && pendingAction.kind === "send";
    const isPendingReject = pendingAction?.id === item.id && pendingAction.kind === "reject";
    const isPendingBind = pendingAction?.id === item.id && pendingAction.kind === "bind";
    const isPending = isPendingSend || isPendingReject || isPendingBind;
    const guestText = item.latestGuestTurn || item.messageText || item.messagePreview || "";
    const draftText = item.draftText || "";
    const guidance = getNextStepGuidance(item);
    const rowState = getRowState(item, threshold);
    const showDraftPreview = Boolean(draftText);
    const confidenceChip =
      rowState === "ready" && typeof item.confidence === "number"
        ? getConfidenceLabel(item.confidence)
        : null;
    const bindingCandidates = (item.propertyBindingCandidates || [])
      .filter((candidate) => candidate.value)
      .slice(0, 4);

    return {
      item,
      isSelected,
      actionable,
      sendAllowed,
      needsKb,
      isPendingSend,
      isPendingReject,
      isPendingBind,
      isPending,
      guestText,
      draftText,
      guidance,
      showDraftPreview,
      confidenceChip,
      bindingCandidates,
      bindingSuggestionsForItem: bindingDraftId === item.id ? bindingSuggestions : [],
      bindingQueryForItem: bindingDraftId === item.id ? bindingQuery : "",
      bindingLoadingForItem: bindingDraftId === item.id && bindingLoading,
      bindingErrorForItem: bindingDraftId === item.id ? bindingError : "",
    };
  });

  return {
    queueByTab,
    searchedItems,
    visibleItems,
    tabCounts,
    awaitingCount,
    draftReadyCount,
    unboundCount,
    knowledgeGapCount,
    selectedInquiry,
    oldestAction,
    cards,
  };
}
