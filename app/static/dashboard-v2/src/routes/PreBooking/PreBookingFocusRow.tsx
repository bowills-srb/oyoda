import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";
import { cn } from "../../lib/utils";
import { Icon } from "../../shared/Icon";
import type { MessageFeedItem } from "../../domain/prebooking/types";
import { getDraftHoldInsight } from "./holdReason";

type ConfidenceChip = {
  label: string;
  tone: "success" | "warning" | "danger";
} | null;

const chipToneClass: Record<string, string> = {
  success: "bg-[var(--success-100)] text-[var(--success-700)]",
  warning: "bg-[var(--warning-100)] text-[var(--warning-700)]",
  danger: "bg-[var(--danger-100)] text-[var(--danger-700)]",
};

/**
 * PreBookingFocusRow — the focus-mode (triage) row.
 *
 * Unlike the compact scan row (PreBookingInquiryCard), this is a self-contained
 * action unit: guest message on top, AI draft below (subtly separated), and
 * Send / Edit / Reject inline so an operator can rip down the queue and confirm
 * without opening the workbench. An info icon opens the full ReviewDrawer
 * (via onOpenDetail) for the occasional row that needs the deeper picture.
 *
 * This is the trust-building loop surface: agreeing with the AI is the fast,
 * one-motion default; editing is a teachable adjustment (captured before/after
 * upstream). Chrome is kept minimal — the two messages and the action row only.
 */
type PreBookingFocusRowProps = {
  item: MessageFeedItem;
  isActive?: boolean;
  isExpanded?: boolean;
  guestText: string;
  draftText: string;
  confidenceChip: ConfidenceChip;
  needsKb: boolean;
  sendAllowed: boolean;
  isPending: boolean;
  isPendingSend: boolean;
  isPendingReject: boolean;
  isEditing: boolean;
  editDraft: string;
  getChannelLabel: (item: MessageFeedItem) => string;
  formatAge: (timestamp?: string | null) => string;
  onSend: (item: MessageFeedItem) => void;
  onStartEdit: (item: MessageFeedItem) => void;
  onSaveEdit: (item: MessageFeedItem) => void;
  onCancelEdit: () => void;
  onSetEditDraft: (value: string) => void;
  onReject: (item: MessageFeedItem) => void;
  onToggleExpand: (itemId: string) => void;
  onOpenDetail: (itemId: string) => void;
};

export function PreBookingFocusRow({
  item,
  isActive = false,
  isExpanded = false,
  guestText,
  draftText,
  confidenceChip,
  needsKb,
  sendAllowed,
  isPending,
  isPendingSend,
  isPendingReject,
  isEditing,
  editDraft,
  getChannelLabel,
  formatAge,
  onSend,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
  onSetEditDraft,
  onReject,
  onToggleExpand,
  onOpenDetail,
}: PreBookingFocusRowProps) {
  const isUnbound = !item.propertyId;
  const hasDraft = Boolean(draftText && draftText.trim());
  const holdInsight = !isUnbound && !hasDraft ? getDraftHoldInsight(item) : null;
  const chipLabel = confidenceChip?.label || "";
  const chipTone = confidenceChip?.tone || "";

  const threadContext = (item.priorThreadContext || "").trim();
  const hasThread = threadContext.length > 0;

  const draftLine = needsKb
    ? `Blocked — missing knowledge${item.blockedByGapTopics?.length ? `: ${item.blockedByGapTopics.join(", ")}` : ""}`
    : isUnbound
    ? "Bind to a property to ground the draft — open detail."
    : holdInsight?.summary || draftText || "No draft yet.";
  const draftMuted = needsKb || isUnbound || !hasDraft;

  return (
    <article
      className={cn(
        "relative rounded-md border transition-all duration-100",
        isActive
          ? "border-strong bg-raised shadow-[var(--shadow-md)] ring-1 ring-[color-mix(in_srgb,var(--accent-500)_40%,transparent)] before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:rounded-l-md before:bg-accent"
          : "border-default bg-raised/20 opacity-[0.64] hover:opacity-[0.88] hover:border-strong hover:bg-raised/30",
        isPending && "opacity-60 pointer-events-none",
      )}
      data-keyboard-nav-id={item.id}
    >
      {isEditing ? (
        <div className="flex flex-col gap-2 px-3 py-2.5">
          <div className="flex items-center gap-2">
            <strong className="text-[12.5px] font-semibold text-primary">{item.guestName || "Guest"}</strong>
            <span className="truncate text-[12px] text-secondary">{guestText || "—"}</span>
          </div>
          <Textarea
            value={editDraft}
            onChange={(event) => onSetEditDraft(event.target.value)}
            rows={3}
            aria-label="Edit draft"
            autoFocus
            disabled={isPending}
            className="text-[12.5px]"
          />
          <div className="flex items-center gap-2">
            <Button type="button" size="sm" disabled={isPending || !editDraft.trim()} onClick={() => onSaveEdit(item)}>
              {isPendingSend ? "Sending…" : "Save & send"}
            </Button>
            <Button type="button" variant="ghost" size="sm" disabled={isPending} onClick={onCancelEdit}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className={cn("grid grid-cols-[minmax(0,1fr)_auto] gap-3 px-3 py-2.5", isExpanded ? "items-start" : "items-center")}>
          {/* Message column — guest line, draft line directly beneath.
             min-w-0 + overflow-hidden so long messages truncate instead of
             pushing the action cluster off the right edge. */}
          <div className={cn("min-w-0 flex-1", isExpanded ? "" : "overflow-hidden")}>
            <div className="flex min-w-0 items-baseline gap-2">
              <strong className="flex-shrink-0 text-[12.5px] font-semibold text-primary">
                {item.guestName || "Guest"}
              </strong>
              {!isUnbound ? (
                <span className="flex-shrink-0 max-w-[140px] truncate text-[11px] text-tertiary">{item.propertyName}</span>
              ) : (
                <span className="flex-shrink-0 font-mono text-[9.5px] uppercase tracking-[0.1em] text-[var(--danger-text)]">unbound</span>
              )}
              <span
                className={cn(
                  "min-w-0 flex-1 text-[12.5px] text-secondary",
                  isExpanded ? "whitespace-normal break-words leading-snug" : "truncate",
                )}
              >
                {guestText || "—"}
              </span>
            </div>
            <p
              className={cn(
                "mt-0.5 text-[12px] leading-snug",
                draftMuted ? "text-tertiary" : "text-secondary",
                isExpanded ? "whitespace-normal break-words" : "truncate",
              )}
            >
              <span className="text-accent">↳ </span>
              {draftLine}
            </p>

            {/* Thread view — only when expanded. Renders the prior conversation
               turns the AI had in context, so an operator can verify the draft
               responds to the whole thread, not just the latest line. This is
               the multi-turn trust check on the path to autonomy. */}
            {isExpanded && (hasThread || (hasDraft && !isUnbound)) ? (
              <div className="mt-2.5 flex flex-col gap-2 rounded-md border border-hairline bg-sunken/60 px-3 py-2.5">
                {hasThread ? (
                  <div className="flex flex-col gap-1">
                    <span className="text-[10px] font-medium uppercase tracking-[0.08em] text-tertiary">
                      Earlier in this conversation
                    </span>
                    <p className="m-0 whitespace-pre-wrap break-words text-[12px] leading-relaxed text-secondary">
                      {threadContext}
                    </p>
                  </div>
                ) : (
                  <span className="text-[11px] italic text-tertiary">
                    No earlier turns — this is the first message in the thread.
                  </span>
                )}
                <div className="flex flex-col gap-1 border-t border-hairline pt-2">
                  <span className="text-[10px] font-medium uppercase tracking-[0.08em] text-tertiary">
                    Latest guest message
                  </span>
                  <p className="m-0 whitespace-pre-wrap break-words text-[12px] leading-relaxed text-primary">
                    {item.latestGuestTurn || guestText || "—"}
                  </p>
                </div>
                {hasDraft ? (
                  <div className="flex flex-col gap-1 border-t border-hairline pt-2">
                    <span className="flex items-center gap-1 text-[10px] font-medium uppercase tracking-[0.08em] text-accent">
                      <Icon name="spark" size={10} /> AI draft reply
                    </span>
                    <p className="m-0 whitespace-pre-wrap break-words text-[12px] leading-relaxed text-secondary">
                      {draftText}
                    </p>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>

          {/* Inline actions + meta, right-aligned — flex-shrink-0 keeps them
             visible no matter how long the message is. */}
          <div className="grid flex-shrink-0 grid-cols-[104px_72px_96px_60px_68px_32px_32px] items-center justify-items-end gap-2">
            <div className="flex w-full justify-end">
              {confidenceChip ? (
                <span
                  className={cn(
                    "inline-flex max-w-full items-center rounded px-1.5 py-0.5 text-[10px] font-semibold leading-none",
                    chipToneClass[chipTone] ?? "bg-hover text-secondary",
                  )}
                >
                  <span className="truncate">{chipLabel}</span>
                </span>
              ) : (
                <span className="invisible inline-flex rounded px-1.5 py-0.5 text-[10px] font-semibold leading-none">
                  placeholder
                </span>
              )}
            </div>
            <span className="w-full text-right font-mono text-[9.5px] uppercase tracking-[0.08em] text-tertiary tabular-nums">
              {getChannelLabel(item)} · {formatAge(item.occurredAt)}
            </span>
            {isUnbound ? (
              <>
                <Button type="button" size="sm" className="w-full justify-center" disabled={isPending} onClick={() => onOpenDetail(item.id)}>
                  Bind →
                </Button>
                <span />
                <span />
              </>
            ) : !hasDraft ? (
              <>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  className="w-full justify-center"
                  disabled={isPending}
                  onClick={() => onOpenDetail(item.id)}
                >
                  Review hold
                </Button>
                <span />
                <Button type="button" variant="ghost" size="sm" className="w-full justify-center" disabled={isPending} onClick={() => onReject(item)}>
                  {isPendingReject ? "…" : "Reject"}
                </Button>
              </>
            ) : (
              <>
                <Button
                  type="button"
                  size="sm"
                  className="w-full justify-center"
                  disabled={!sendAllowed || isPending}
                  onClick={() => onSend(item)}
                  title={sendAllowed ? "Send the draft" : "Needs review first"}
                >
                  {isPendingSend ? "…" : "Send"}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  className="w-full justify-center"
                  disabled={isPending || needsKb}
                  onClick={() => onStartEdit(item)}
                >
                  Edit
                </Button>
                <Button type="button" variant="ghost" size="sm" className="w-full justify-center" disabled={isPending} onClick={() => onReject(item)}>
                  {isPendingReject ? "…" : "Reject"}
                </Button>
              </>
            )}
            <button
              type="button"
              onClick={() => onToggleExpand(item.id)}
              className="flex h-7 w-7 items-center justify-center rounded border border-hairline text-secondary transition-colors hover:bg-hover hover:text-primary"
              aria-label={isExpanded ? "Collapse inline preview" : "Expand inline preview"}
              title={isExpanded ? "Collapse inline preview" : "Expand inline preview"}
            >
              <span className="text-[12px] leading-none">{isExpanded ? "−" : "…"}</span>
            </button>
            <button
              type="button"
              onClick={() => onOpenDetail(item.id)}
              className="flex h-7 w-7 items-center justify-center rounded border border-hairline text-secondary transition-colors hover:bg-hover hover:text-primary"
              aria-label="Open full detail"
              title="Open full detail"
            >
              <Icon name="info" size={14} />
            </button>
          </div>
        </div>
      )}
    </article>
  );
}
