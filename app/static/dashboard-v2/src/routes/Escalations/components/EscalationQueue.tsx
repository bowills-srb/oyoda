/**
 * EscalationQueue — sortable/filterable list of escalations.
 *
 * Sort order: SLA-breached first, then by priority (urgent→high→medium→low),
 * then by age (oldest first). Filter: by stage and by ownership.
 */
import { useMemo, useState } from "react";
import { cn } from "../../../lib/utils";
import type { EscalationListItem, WorkflowStage } from "../../../domain/escalations/types";
import type { EscalationSummary } from "../../../domain/escalations/types";
import { EscalationRow } from "./EscalationRow";

type Props = {
  items: EscalationListItem[];
  summary: EscalationSummary;
  selectedId: string | null;
  onSelect: (id: string) => void;
};

const PRIORITY_ORDER = { urgent: 0, high: 1, medium: 2, low: 3 } as const;

const STAGE_FILTERS: { value: WorkflowStage | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "detected", label: "Detected" },
  { value: "triaged", label: "Triaged" },
  { value: "vendor_dispatch", label: "Vendor" },
  { value: "resolved", label: "Resolved" },
];

export function EscalationQueue({ items, summary, selectedId, onSelect }: Props) {
  const [stageFilter, setStageFilter] = useState<WorkflowStage | "all">("all");
  const [ownerFilter, setOwnerFilter] = useState<"all" | "unassigned">("all");

  const sorted = useMemo(() => {
    const filtered = items.filter((item) => {
      if (stageFilter !== "all" && item.workflow.stage !== stageFilter) return false;
      if (ownerFilter === "unassigned" && item.assigned_to) return false;
      return true;
    });

    return [...filtered].sort((a, b) => {
      // SLA breached first
      const aBreached = a.workflow.sla.ack_breached || a.workflow.sla.resolve_breached ? 0 : 1;
      const bBreached = b.workflow.sla.ack_breached || b.workflow.sla.resolve_breached ? 0 : 1;
      if (aBreached !== bBreached) return aBreached - bBreached;

      // Then priority
      const ap = PRIORITY_ORDER[a.priority] ?? 2;
      const bp = PRIORITY_ORDER[b.priority] ?? 2;
      if (ap !== bp) return ap - bp;

      // Then oldest first
      const at = a.created_at ? new Date(a.created_at).getTime() : 0;
      const bt = b.created_at ? new Date(b.created_at).getTime() : 0;
      return at - bt;
    });
  }, [items, stageFilter, ownerFilter]);

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="border-b border-hairline px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-primary">Escalations</h2>
          <div className="flex items-center gap-2 text-xs text-tertiary">
            <span>{summary.open} open</span>
            {summary.pending > 0 && (
              <span className="rounded bg-[var(--warning-100)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--warning-700)]">
                {summary.pending} pending
              </span>
            )}
          </div>
        </div>

        {/* Stage filter tabs */}
        <div className="mt-2 flex items-center gap-1 overflow-x-auto">
          {STAGE_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setStageFilter(f.value)}
              className={cn(
                "flex-shrink-0 rounded px-2 py-1 text-xs transition-colors",
                stageFilter === f.value
                  ? "bg-accent text-white font-medium"
                  : "text-tertiary hover:text-primary hover:bg-hover",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Ownership filter */}
        <div className="mt-1.5 flex items-center gap-1">
          {(["all", "unassigned"] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setOwnerFilter(v)}
              className={cn(
                "rounded px-2 py-0.5 text-xs transition-colors",
                ownerFilter === v
                  ? "bg-selected text-primary font-medium"
                  : "text-tertiary hover:text-primary hover:bg-hover",
              )}
            >
              {v === "all" ? "All owners" : "Unassigned"}
            </button>
          ))}
        </div>
      </div>

      {/* Rows */}
      {sorted.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-tertiary">
          No escalations match the current filter.
        </div>
      ) : (
        sorted.map((item) => (
          <EscalationRow
            key={item.ticket_id}
            item={item}
            isSelected={item.ticket_id === selectedId}
            onClick={() => onSelect(item.ticket_id)}
          />
        ))
      )}
    </div>
  );
}
