import { useCallback, useEffect, useMemo, useState } from "react";
import type { RefObject } from "react";
import { Badge } from "../../components/primitives/Badge";
import { Button } from "../../components/ui/button";
import { Select } from "../../components/ui/select";
import { ListDetailSurface } from "../../components/system/ListDetailSurface";
import type { SessionPayload } from "../../domain/auth/types";
import type { MessageFeedItem, PropertyMatchSuggestion } from "../../domain/prebooking/types";
import { Icon } from "../../shared/Icon";
import { useListKeyboardNav } from "../../shared/hooks/useListKeyboardNav";
import { PreBookingDetailPanel } from "./PreBookingDetailPanel";
import { PreBookingFocusRow } from "./PreBookingFocusRow";
import { PreBookingInquiryCard } from "./PreBookingInquiryCard";

type QueueTab = "action" | "sent" | "held" | "closed";
type QueueMetricFocus = "all" | "draft_ready" | "knowledge_gap" | "unbound";
type QueueDepth = 5 | 10 | 25 | 50 | "all";

type ConfidenceChip = {
  label: string;
  tone: "success" | "warning" | "danger";
} | null;

type Guidance = {
  tone: "accent" | "warning" | "danger" | "default";
  title: string;
  body: string;
};

type InquiryCardViewModel = {
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
  guidance: Guidance;
  showDraftPreview: boolean;
  confidenceChip: ConfidenceChip;
  bindingCandidates: MessageFeedItem["propertyBindingCandidates"];
  bindingSuggestionsForItem: PropertyMatchSuggestion[];
  bindingQueryForItem: string;
  bindingLoadingForItem: boolean;
  bindingErrorForItem: string;
};

type PreBookingQueueShellProps = {
  actionError: string;
  activeTab: QueueTab;
  error: string;
  focusMetric: QueueMetricFocus;
  freshnessBadge: { tone: "warning" | "danger"; label: string } | null;
  hasHydratedFeed: boolean;
  queueDepth: QueueDepth;
  focusMode?: boolean;
  searchedItemsCount: number;
  search: string;
  propertyId: string;
  showQueueSkeleton: boolean;
  visibleItemsCount: number;
  cards: InquiryCardViewModel[];
  formatAge: (timestamp?: string | null) => string;
  formatBindingCandidateType: (candidateType: string) => string;
  formatPercent: (value: number) => string;
  formatPropertyScore: (value?: number) => string;
  getChannelLabel: (item: MessageFeedItem) => string;
  getQueueLabel: (item: MessageFeedItem) => string;
  getQueueSpineTone: (item: MessageFeedItem) => string;
  getQueueTone: (item: MessageFeedItem) => "accent" | "warning" | "success" | "danger" | "default";
  editingId: string | null;
  editDraft: string;
  operator?: SessionPayload["operator"];
  pendingActionId: string | null;
  bindingDraftId: string | null;
  // Ref forwarded to the ListDetailSurface detail region for focus management.
  detailRef?: RefObject<HTMLDivElement>;
  // Optional className augmentation forwarded to ListDetailSurface (structural
  // layout is owned by the primitive; use this for surface-specific overrides only).
  layoutClassName?: string;
  onBindProperty: (item: MessageFeedItem, suggestion: PropertyMatchSuggestion) => void | Promise<void>;
  onBindingQueryChange: (itemId: string, query: string) => void;
  onCloseCard: () => void;
  onDepthChange: (value: string) => void;
  onFindBindingSuggestions: (item: MessageFeedItem, query: string) => void | Promise<void>;
  onReject: (item: MessageFeedItem) => void | Promise<void>;
  onSaveEdit: (item: MessageFeedItem) => void | Promise<void>;
  onSelectCard: (itemId: string) => void;
  onSetEditDraft: (value: string) => void;
  onStartEdit: (item: MessageFeedItem) => void;
  onCancelEdit: () => void;
  onSend: (item: MessageFeedItem) => void | Promise<void>;
};

export function PreBookingQueueShell({
  actionError,
  activeTab,
  error,
  focusMetric,
  freshnessBadge,
  hasHydratedFeed,
  queueDepth,
  focusMode = false,
  searchedItemsCount,
  search,
  propertyId,
  showQueueSkeleton,
  visibleItemsCount,
  cards,
  formatAge,
  formatBindingCandidateType,
  formatPercent,
  formatPropertyScore,
  getChannelLabel,
  getQueueLabel,
  getQueueSpineTone,
  getQueueTone,
  editingId,
  editDraft,
  operator,
  pendingActionId,
  bindingDraftId,
  detailRef,
  layoutClassName,
  onBindProperty,
  onBindingQueryChange,
  onCloseCard,
  onDepthChange,
  onFindBindingSuggestions,
  onReject,
  onSaveEdit,
  onSelectCard,
  onSetEditDraft,
  onStartEdit,
  onCancelEdit,
  onSend,
}: PreBookingQueueShellProps) {
  const selectedCard = cards.find((c) => c.isSelected) ?? null;
  const [processedCount, setProcessedCount] = useState(0);
  const [expandedIds, setExpandedIds] = useState<string[]>([]);

  useEffect(() => {
    setProcessedCount(0);
    setExpandedIds([]);
  }, [focusMode, activeTab, focusMetric, search, propertyId]);

  const handleTrackedSend = useCallback(
    async (item: MessageFeedItem) => {
      await onSend(item);
      setProcessedCount((count) => count + 1);
    },
    [onSend],
  );

  const handleTrackedReject = useCallback(
    async (item: MessageFeedItem) => {
      await onReject(item);
      setProcessedCount((count) => count + 1);
    },
    [onReject],
  );

  // ── Focus Mode keyboard cursor ──────────────────────────────────────────
  // A "cursor" highlights the row the operator is about to act on. It is
  // SEPARATE from drawer-selection (isSelected/?selected): j/k move the cursor
  // and highlight only; the drawer opens only via the info icon. Enter sends
  // (or binds, if unbound), e edits, r rejects, b binds. After a terminal
  // action the cursor auto-advances to the next row so the queue "manages
  // itself" — the operator never reaches for the mouse.
  const orderedIds = useMemo(() => cards.map((c) => c.item.id), [cards]);
  const [cursorId, setCursorId] = useState<string>("");
  // If the cursor's row left the queue (sent/rejected) or nothing is set,
  // fall back to the first row so there is always a sensible active target.
  const activeId = orderedIds.includes(cursorId) ? cursorId : orderedIds[0] ?? "";

  const advanceCursor = useCallback(
    (fromId: string) => {
      const idx = orderedIds.indexOf(fromId);
      // Prefer the next row; if at the end, stay where the list re-settles.
      const next = orderedIds[idx + 1] ?? orderedIds[idx - 1] ?? "";
      setCursorId(next);
    },
    [orderedIds],
  );

  const cardById = useCallback(
    (id: string) => cards.find((c) => c.item.id === id) ?? null,
    [cards],
  );

  const toggleExpanded = useCallback((id: string) => {
    setExpandedIds((current) => (current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id]));
  }, []);

  useListKeyboardNav({
    itemIds: orderedIds,
    selectedId: activeId,
    onSelect: setCursorId,
    onClose: () => setCursorId(""),
    // Only active in focus mode and when the drawer/edit isn't capturing input.
    enabled: focusMode && selectedCard == null && editingId == null,
    onPrimary: (id) => {
      const card = cardById(id);
      if (!card) return;
      if (!card.item.propertyId) {
        // Unbound → Enter opens bind (the only valid next step).
        onSelectCard(id);
        return;
      }
      if (card.sendAllowed && !card.isPending) {
        void handleTrackedSend(card.item);
        advanceCursor(id);
      }
    },
    onEdit: (id) => {
      const card = cardById(id);
      if (card && !card.item.propertyId) return; // can't edit an unbound draft
      if (card && !card.needsKb && !card.isPending) onStartEdit(card.item);
    },
    onReject: (id) => {
      const card = cardById(id);
      if (card && !card.isPending) {
        void handleTrackedReject(card.item);
        advanceCursor(id);
      }
    },
    onBind: (id) => {
      const card = cardById(id);
      if (card && !card.item.propertyId) onSelectCard(id);
    },
  });

  const totalSeenCount = cards.length + processedCount;
  const clearedPercent = totalSeenCount > 0 ? Math.round((processedCount / totalSeenCount) * 100) : 0;

  // Focus mode list — single column of fat, self-contained action rows.
  // Reuses the same cards view-model and the same handlers; the info icon
  // calls onSelectCard, which opens the ReviewDrawer in the detail slot as a
  // slide-over (ListDetailSurface handles the overlay).
  const focusList = (
    <div className="flex flex-col gap-1.5 px-4 py-3 max-[860px]:px-2">
      {!showQueueSkeleton && searchedItemsCount > 0 ? (
        <div className="mx-auto flex w-full max-w-[860px] flex-col items-center gap-1.5 px-1 pb-1 text-center">
          <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-tertiary tabular-nums">
            {cards.length} remaining · {processedCount} processed · {clearedPercent}% cleared
          </span>
          <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[10.5px] text-tertiary">
            <FocusKeyHint keys={["J", "K"]} label="move" />
            <FocusKeyHint keys={["↵"]} label="send" />
            <FocusKeyHint keys={["E"]} label="edit" />
            <FocusKeyHint keys={["R"]} label="reject" />
            <FocusKeyHint keys={["B"]} label="bind" />
            <FocusKeyHint keys={["Esc"]} label="exit cursor" />
          </div>
        </div>
      ) : null}
      {showQueueSkeleton ? (
        <div className="mx-auto w-full max-w-[860px] animate-pulse rounded-lg border border-hairline bg-hover h-40" aria-hidden="true" />
      ) : searchedItemsCount === 0 ? (
        <div className="queue-empty">
          <div className="empty-illustration">
            <Icon name="info" size={20} />
          </div>
          <h3 className="empty-title">Queue clear.</h3>
          <p className="empty-copy">Nothing left to action in this view. Exit focus to see the full dashboard.</p>
        </div>
      ) : (
        cards.map((card) => (
          <PreBookingFocusRow
            key={card.item.id}
            item={card.item}
            isActive={focusMode && card.item.id === activeId}
            isExpanded={expandedIds.includes(card.item.id)}
            guestText={card.guestText}
            draftText={card.draftText}
            confidenceChip={card.confidenceChip}
            needsKb={card.needsKb}
            sendAllowed={card.sendAllowed}
            isPending={card.isPending}
            isPendingSend={card.isPendingSend}
            isPendingReject={card.isPendingReject}
            isEditing={editingId === card.item.id}
            editDraft={editDraft}
            getChannelLabel={getChannelLabel}
            formatAge={formatAge}
            onSend={onSend}
            onStartEdit={onStartEdit}
            onSaveEdit={onSaveEdit}
            onCancelEdit={onCancelEdit}
            onSetEditDraft={onSetEditDraft}
            onReject={handleTrackedReject}
            onToggleExpand={toggleExpanded}
            onOpenDetail={onSelectCard}
          />
        ))
      )}
    </div>
  );

  const list = (
    <section className="p-0">
      <div className="flex items-center justify-between gap-4 px-7 py-4 pb-2">
        <h2 className="m-0 text-[13px] font-medium text-tertiary leading-[1.2]">
          {activeTab === "action"
            ? "Inquiries needing action"
            : activeTab === "sent"
            ? "Sent replies"
            : activeTab === "held"
            ? "Held for review"
            : "Closed"}
        </h2>
        <div className="flex items-center gap-3.5">
          {error ? <Badge tone="danger">{error}</Badge> : null}
          {freshnessBadge ? <Badge tone={freshnessBadge.tone}>{freshnessBadge.label}</Badge> : null}
          {!error ? (
            <span className="text-xs text-tertiary tabular-nums">
              {hasHydratedFeed ? `${visibleItemsCount} of ${searchedItemsCount}` : "Loading queue"}
            </span>
          ) : null}
          {focusMetric === "knowledge_gap" ? (
            <Button type="button" variant="secondary" size="sm" disabled title="Knowledge is coming in v2">
              Open knowledge
            </Button>
          ) : null}
          <label className="inline-flex items-center gap-1.5 text-[11.5px] text-tertiary font-medium">
            <span>Show</span>
            <Select
              aria-label="Queue depth"
              className="h-auto py-1 px-2 pr-6 text-xs font-medium rounded-md text-secondary w-auto"
              value={String(queueDepth)}
              onChange={(event) => onDepthChange(event.target.value)}
            >
              <option value="5">5</option>
              <option value="10">10</option>
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="all">All</option>
            </Select>
          </label>
        </div>
      </div>

      {showQueueSkeleton ? (
        <div className="grid divide-y divide-hairline" aria-hidden="true">
          {Array.from({ length: 5 }).map((_, index) => (
            <div
              key={index}
              className="relative animate-pulse p-[18px_28px_18px_44px]"
            >
              {/* Spine placeholder */}
              <span className="absolute bottom-[18px] left-5 top-[18px] w-[3px] rounded-full bg-hover" />
              <div className="flex flex-col gap-3">
                {/* Identity + badge row */}
                <div className="flex items-start justify-between gap-3">
                  <div className="flex flex-col gap-1.5">
                    <span className="h-3 w-32 rounded-full bg-hover" />
                    <span className="h-2.5 w-24 rounded-full bg-hover" />
                  </div>
                  <span className="h-5 w-16 rounded-full bg-hover" />
                </div>
                {/* Preview lines */}
                <div className="flex flex-col gap-1.5">
                  <span className="h-2.5 w-full rounded-full bg-hover" />
                  <span className="h-2.5 w-4/5 rounded-full bg-hover" />
                </div>
                {/* Footer row */}
                <div className="flex justify-between">
                  <span className="h-2.5 w-24 rounded-full bg-hover" />
                  <span className="h-2.5 w-20 rounded-full bg-hover" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : searchedItemsCount === 0 ? (
        <div className="queue-empty">
          <div className="empty-illustration">
            <Icon name="info" size={20} />
          </div>
          <h3 className="empty-title">No inquiries match this view.</h3>
          <p className="empty-copy">
            {search || propertyId
              ? "Try widening the filters or clearing search."
              : "Nothing in this view yet. Try widening filters or check back as inquiries arrive."}
          </p>
        </div>
      ) : (
        <div className="grid divide-y divide-hairline">
          {cards.map((card) => (
            <PreBookingInquiryCard
              key={card.item.id}
              confidenceChip={card.confidenceChip}
              formatAge={formatAge}
              getChannelLabel={getChannelLabel}
              getQueueLabel={getQueueLabel}
              getQueueSpineTone={getQueueSpineTone}
              getQueueTone={getQueueTone}
              guestText={card.guestText}
              isPending={card.isPending}
              isSelected={card.isSelected}
              item={card.item}
              onOpenBinding={() => onSelectCard(card.item.id)}
              onSelect={() => onSelectCard(card.item.id)}
            />
          ))}
        </div>
      )}

      {!showQueueSkeleton && visibleItemsCount > 0 ? (
        <div className="flex items-center gap-2 border-t border-hairline px-7 py-3.5 pl-11 text-[11.5px] uppercase tracking-[0.04em] text-tertiary">
          <span className="h-px w-4 bg-border" />
          {visibleItemsCount === searchedItemsCount
            ? `End of queue — ${visibleItemsCount} ${visibleItemsCount === 1 ? "inquiry" : "inquiries"}`
            : `Showing ${visibleItemsCount} of ${searchedItemsCount} — raise queue depth to see more`}
        </div>
      ) : null}
    </section>
  );

  const detail =
    selectedCard != null ? (
      <PreBookingDetailPanel
        actionError={actionError}
        actionable={selectedCard.actionable}
        bindingCandidates={selectedCard.bindingCandidates}
        bindingDraftId={bindingDraftId}
        bindingErrorForItem={selectedCard.bindingErrorForItem}
        bindingLoadingForItem={selectedCard.bindingLoadingForItem}
        bindingQueryForItem={selectedCard.bindingQueryForItem}
        bindingSuggestionsForItem={selectedCard.bindingSuggestionsForItem}
        draftText={selectedCard.draftText}
        editDraft={editDraft}
        editingId={editingId}
        formatBindingCandidateType={formatBindingCandidateType}
        formatPercent={formatPercent}
        formatPropertyScore={formatPropertyScore}
        guestText={selectedCard.guestText}
        guidance={selectedCard.guidance}
        isPending={selectedCard.isPending}
        isPendingBind={selectedCard.isPendingBind}
        isPendingReject={selectedCard.isPendingReject}
        isPendingSend={selectedCard.isPendingSend}
        item={selectedCard.item}
        needsKb={selectedCard.needsKb}
        operator={operator}
        pendingActionId={pendingActionId}
        sendAllowed={selectedCard.sendAllowed}
        onBindProperty={onBindProperty}
        onBindingQueryChange={onBindingQueryChange}
        onClose={onCloseCard}
        onFindBindingSuggestions={onFindBindingSuggestions}
        onReject={handleTrackedReject}
        onSaveEdit={onSaveEdit}
        onSetEditDraft={onSetEditDraft}
        onStartEdit={onStartEdit}
        onCancelEdit={onCancelEdit}
        onSend={handleTrackedSend}
      />
    ) : undefined;

  return (
    <ListDetailSurface
      list={focusMode ? focusList : list}
      detail={detail}
      detailOpen={selectedCard != null}
      onCloseDetail={onCloseCard}
      detailAriaLabel="Inquiry detail"
      className={layoutClassName}
      detailRef={detailRef}
    />
  );
}

// FocusKeyHint — a single "key + what it does" pair for the focus-mode legend.
// Renders the shortcut keys exactly when they're usable, so an operator
// dropping into focus mode immediately knows how to fly through the queue.
function FocusKeyHint({ keys, label }: { keys: string[]; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      {keys.map((k) => (
        <kbd
          key={k}
          className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-hairline bg-[var(--surface-hover)] px-1 font-mono text-[10px] font-medium text-secondary"
        >
          {k}
        </kbd>
      ))}
      <span className="text-tertiary">{label}</span>
    </span>
  );
}
