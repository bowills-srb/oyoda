/**
 * ReviewDrawer — shared content shell for every review surface.
 *
 * Renders named regions in a fixed order. Optional regions (blockerResolution,
 * context, proposedAction, decisionBar) render nothing when absent.
 *
 * Reuse contract for future surfaces:
 *   Escalation adapter  → severity maps to summary.tone, SLA summary maps to
 *     context.body, no proposedAction.confidence (omit the field — region adapts).
 *   Session adapter     → journey context maps to context, no proposedAction at all.
 * The shell never changes; only adapters differ.
 *
 * This component owns INTERNAL STRUCTURE only. Split geometry and the mobile
 * sheet belong to ListDetailSurface. Focus-trap belongs to the container.
 */

import type { ReactNode } from "react";
import { Button } from "../../ui/button";
import { Icon } from "../../../shared/Icon";
import { cn } from "../../../lib/utils";

const summaryBorderClass: Record<string, string> = {
  accent: "border-accent",
  warning: "border-[var(--warning-500)]",
  danger: "border-[var(--danger-500)]",
  default: "border-hairline",
};

export type ReviewDrawerProps = {
  onClose: () => void;

  // Region: trust/next-step summary. Always present.
  summary: { tone: "accent" | "warning" | "danger" | "default"; title: string; body: string };

  // Header: identity for the selected item. Optional — falls back to a bare
  // close row when absent so existing callers keep working.
  headerTitle?: string;
  headerMeta?: string;

  // Region: blocker resolution. null/undefined → hidden.
  blockerResolution?: ReactNode;

  // Region: context (e.g. guest message). null/undefined → hidden.
  context?: { label: string; body: string };

  // Region: proposed action. confidence is optional — omit for escalations.
  proposedAction?: {
    label: string;
    confidence?: number;
    body: ReactNode;
  };

  // Region: action buttons. Surface supplies its own verbs.
  decisionBar?: ReactNode;
  attribution?: { name: string; email?: string };
};

export function ReviewDrawer({
  onClose,
  summary,
  headerTitle,
  headerMeta,
  blockerResolution,
  context,
  proposedAction,
  decisionBar,
  attribution,
}: ReviewDrawerProps) {
  return (
    <div className="flex h-full flex-col">
      {/* Header — identity + close, anchored at the top of the workbench */}
      <div className="flex items-center justify-between gap-3 border-b border-hairline px-5 py-3.5">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="truncate text-[14px] font-semibold text-primary leading-tight">
            {headerTitle || "Inquiry detail"}
          </span>
          {headerMeta ? (
            <span className="truncate font-mono text-[10px] uppercase tracking-[0.1em] text-tertiary">{headerMeta}</span>
          ) : null}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onClose}
          aria-label="Close detail panel"
          className="flex-shrink-0"
        >
          Close
        </Button>
      </div>

      {/* Scrollable body */}
      <div className="flex flex-1 flex-col gap-2.5 overflow-y-auto px-5 py-4 [scrollbar-width:thin] [scrollbar-color:var(--border-default)_transparent]">
        {/* Summary region */}
        <div
          className={cn(
            "grid gap-1 rounded-md border border-l-[3px] px-3 py-2.5 bg-hover",
            summaryBorderClass[summary.tone] ?? "border-hairline",
          )}
        >
          <span className="text-[12.5px] font-semibold text-primary leading-snug">{summary.title}</span>
          <p className="text-[12.5px] text-secondary leading-snug">{summary.body}</p>
        </div>

        {/* Blocker resolution region */}
        {blockerResolution ?? null}

        {/* Context region */}
        {context ? (
          <div className="grid gap-1.5 rounded-md border border-hairline border-l-2 border-l-border bg-hover px-3 py-2.5">
            <span className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-tertiary">
              {context.label}
            </span>
            <p className="text-[13px] text-primary leading-relaxed">{context.body}</p>
          </div>
        ) : null}

        {/* Proposed action region */}
        {proposedAction ? (
          <div className="grid gap-1.5 rounded-md border border-hairline border-l-2 border-l-accent bg-gradient-to-b from-selected to-transparent px-3 py-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1 font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-accent">
                <Icon name="spark" size={11} />
                {proposedAction.label}
              </span>
              {proposedAction.confidence != null ? (
                <span className="text-[11px] text-tertiary tabular-nums">
                  {Math.round(proposedAction.confidence * 100)}% confidence
                </span>
              ) : null}
            </div>
            {proposedAction.body}
          </div>
        ) : null}
      </div>

      {/* Decision bar — anchored footer, visually separated from the body */}
      {decisionBar || attribution ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-hairline bg-raised px-5 py-3.5">
          {decisionBar}
          {attribution?.name ? (
            <p className="w-full text-[11px] text-tertiary">
              Acting as <strong>{attribution.name}</strong>
              {attribution.email ? ` · ${attribution.email}` : ""}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
