/**
 * EscalationRow — single row in the escalations queue.
 *
 * Shows: priority tone, SLA breach flag, reason/guest, property, stage,
 * assignee, and age. Breached or urgent rows render with danger tone;
 * high priority with warning; otherwise default.
 */
import { cn } from "../../../lib/utils";
import type { EscalationListItem, Priority } from "../../../domain/escalations/types";

type Props = {
  item: EscalationListItem;
  isSelected: boolean;
  onClick: () => void;
};

function priorityLabel(p: Priority): string {
  return { urgent: "Urgent", high: "High", medium: "Med", low: "Low" }[p] ?? p;
}

function stageLabel(stage: string): string {
  return (
    {
      detected: "Detected",
      triaged: "Triaged",
      vendor_dispatch: "Vendor",
      resolved: "Resolved",
    }[stage] ?? stage
  );
}

function age(createdAt: string | null): string {
  if (!createdAt) return "—";
  const ms = Date.now() - new Date(createdAt).getTime();
  const h = Math.floor(ms / 3_600_000);
  if (h < 1) return `${Math.floor(ms / 60_000)}m`;
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

export function EscalationRow({ item, isSelected, onClick }: Props) {
  const slaBreached =
    item.workflow.sla.ack_breached || item.workflow.sla.resolve_breached;

  const tone: "danger" | "warning" | "default" = slaBreached
    ? "danger"
    : item.priority === "urgent" || item.priority === "high"
    ? "warning"
    : "default";

  const toneBar = {
    danger: "bg-[var(--danger-500)]",
    warning: "bg-[var(--warning-500)]",
    default: "bg-transparent",
  }[tone];

  return (
    <button
      type="button"
      onClick={onClick}
      data-keyboard-nav-id={item.ticket_id}
      className={cn(
        "group relative flex w-full items-start gap-3 border-b border-hairline px-4 py-3 text-left transition-colors",
        isSelected ? "bg-selected" : "hover:bg-hover",
      )}
      aria-current={isSelected ? "true" : undefined}
    >
      {/* tone bar */}
      <span className={cn("absolute left-0 top-0 h-full w-0.5", toneBar)} aria-hidden />

      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {/* top line: reason + age */}
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-sm font-semibold text-primary">
            {item.reason || "Escalation"}
          </span>
          <span className="flex-shrink-0 text-xs text-tertiary tabular-nums">{age(item.created_at)}</span>
        </div>

        {/* guest + property */}
        <span className="truncate text-xs text-secondary">
          {[item.guest_name, item.property_name].filter(Boolean).join(" · ") || "—"}
        </span>

        {/* bottom line: priority badge + stage + assignee + SLA breach */}
        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
          <span
            className={cn(
              "rounded px-1.5 py-0.5 text-[10px] font-semibold leading-none",
              tone === "danger"
                ? "bg-[var(--danger-100)] text-[var(--danger-700)]"
                : tone === "warning"
                ? "bg-[var(--warning-100)] text-[var(--warning-700)]"
                : "bg-hover text-secondary",
            )}
          >
            {priorityLabel(item.priority)}
          </span>

          <span className="text-[10px] text-tertiary">{stageLabel(item.workflow.stage)}</span>

          {item.assigned_to ? (
            <span className="text-[10px] text-tertiary">· {item.assigned_to}</span>
          ) : (
            <span className="text-[10px] text-[var(--warning-600)]">· Unassigned</span>
          )}

          {slaBreached ? (
            <span className="text-[10px] font-semibold text-[var(--danger-600)]">· SLA</span>
          ) : null}
        </div>
      </div>
    </button>
  );
}
