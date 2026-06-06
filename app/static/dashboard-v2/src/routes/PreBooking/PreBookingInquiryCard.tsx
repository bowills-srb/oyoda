import { Badge } from "../../components/primitives/Badge";
import type { MessageFeedItem } from "../../domain/prebooking/types";
import { cn } from "../../lib/utils";

type ConfidenceChip = {
  label: string;
  tone: "success" | "warning" | "danger";
} | null;

// Props used only by the compact list row. The expanded detail has moved to
// PreBookingDetailPanel, which renders in the ListDetailSurface detail slot.
type PreBookingInquiryCardProps = {
  confidenceChip: ConfidenceChip;
  formatAge: (timestamp?: string | null) => string;
  getChannelLabel: (item: MessageFeedItem) => string;
  getQueueLabel: (item: MessageFeedItem) => string;
  getQueueSpineTone: (item: MessageFeedItem) => string;
  getQueueTone: (item: MessageFeedItem) => "accent" | "warning" | "success" | "danger" | "default";
  guestText: string;
  isPending: boolean;
  isSelected: boolean;
  item: MessageFeedItem;
  onOpenBinding: () => void;
  onSelect: () => void;
};

// Maps the tone string returned by getQueueSpineTone() to Tailwind bg utilities.
// The accent spine gets a subtle glow matching the legacy box-shadow rule.
const spineToneClass: Record<string, string> = {
  accent: "bg-accent [box-shadow:0_0_6px_var(--accent-500)]",
  warning: "bg-[var(--warning-500)]",
  success: "bg-[var(--success-500)]",
  danger: "bg-[var(--danger-500)]",
  default: "bg-[var(--border-default)]",
};

// Maps the Badge tone returned by getQueueTone() to a row-state chip colour.
const chipToneClass: Record<string, string> = {
  success: "bg-[var(--success-100)] text-[var(--success-700)]",
  warning: "bg-[var(--warning-100)] text-[var(--warning-700)]",
  danger: "bg-[var(--danger-100)] text-[var(--danger-700)]",
};

export function PreBookingInquiryCard({
  confidenceChip,
  formatAge,
  getChannelLabel,
  getQueueLabel,
  getQueueSpineTone,
  getQueueTone,
  guestText,
  isPending,
  isSelected,
  item,
  onOpenBinding,
  onSelect,
}: PreBookingInquiryCardProps) {
  const isUnboundBlocked = !item.propertyId;
  const spineTone = getQueueSpineTone(item);

  return (
    <div
      className={cn(
        // Structure — tight single-line scan row
        "relative cursor-pointer py-2 pl-10 pr-6 transition-colors duration-100",
        // Separators owned by the list container (divide-y divide-hairline).
        // Selected wins over hover.
        isSelected
          ? "bg-[color-mix(in_srgb,var(--accent-500)_8%,transparent)] before:absolute before:inset-y-0 before:left-0 before:w-[2px] before:bg-accent"
          : "hover:bg-hover",
        isPending && "opacity-60 pointer-events-none",
      )}
      data-keyboard-nav-id={item.id}
      onClick={() => {
        if (!isSelected) onSelect();
      }}
      role="button"
      tabIndex={0}
      aria-pressed={isSelected}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          if (!isSelected) onSelect();
        }
      }}
    >
      {/* Colored left spine — state at a glance */}
      <span
        aria-hidden="true"
        className={cn(
          "absolute left-4 top-2 bottom-2 w-[3px] rounded-full",
          spineToneClass[spineTone] ?? spineToneClass.default,
        )}
      />

      {/*
        Single-line scan row: identity + guest-message preview on the left,
        state/confidence/channel/age cluster on the right. The "next step"
        guidance, full guest text, and AI draft preview live in the detail
        panel (opened on select) and the Focus-mode row — keeping this list a
        dense, legible register the operator can rip down quickly.
      */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-baseline gap-2 overflow-hidden">
          <strong className="flex-shrink-0 text-[13px] font-semibold text-primary">
            {item.guestName || "Guest"}
          </strong>
          {isUnboundBlocked ? (
            <button
              type="button"
              className="flex-shrink-0 text-[11px] font-semibold text-accent underline-offset-2 hover:underline"
              onClick={(event) => {
                event.stopPropagation();
                onOpenBinding();
              }}
              aria-label="Open binding resolver for this inquiry"
            >
              Bind to property →
            </button>
          ) : (
            <span className="flex-shrink-0 max-w-[180px] truncate text-[11.5px] text-tertiary">
              {item.propertyName || "Unknown property"}
            </span>
          )}
          {/* Guest-message preview — truncates hard AND caps at a readable
             width so ultrawide monitors don't stretch one message across the
             whole screen. min-w-0 lets the flex child shrink below content
             width (required for truncate); max-w gives a comfortable ceiling. */}
          {!isUnboundBlocked ? (
            <span className="min-w-0 flex-1 truncate text-[12px] text-secondary max-w-[90ch]">
              {guestText || "—"}
            </span>
          ) : null}
        </div>

        <div className="flex flex-shrink-0 items-center gap-2">
          <Badge tone={getQueueTone(item)}>{getQueueLabel(item)}</Badge>
          {confidenceChip ? (
            <span
              className={cn(
                "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold leading-none",
                chipToneClass[confidenceChip.tone] ?? "bg-hover text-secondary",
              )}
              aria-label={`Confidence: ${confidenceChip.label}`}
            >
              {confidenceChip.label}
            </span>
          ) : null}
          <span className="w-12 text-right text-[11px] text-tertiary tabular-nums">
            {getChannelLabel(item)}
          </span>
          <span className="w-8 text-right text-[11px] text-tertiary tabular-nums">
            {formatAge(item.occurredAt)}
          </span>
        </div>
      </div>
    </div>
  );
}
