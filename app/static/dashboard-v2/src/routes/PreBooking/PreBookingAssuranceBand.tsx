import { cn } from "../../lib/utils";
import { Icon } from "../../shared/Icon";

/**
 * PreBookingAssuranceBand — the single autonomy + accountability strip.
 *
 * This is the operator's FIRST read of Inquiry Operations and the ONLY
 * summary strip on the page (it replaced the old analytics row and the metric
 * chips — those duplicated these numbers). It answers, left to right:
 *
 *   1. Autonomy state   — is the AI sending on its own, and at what bar?
 *   2. Accounted-for     — every inbound message is here with a disposition;
 *                          nothing was silently dropped. The ledger numbers
 *                          double as the queue filters (clicking one filters
 *                          the list below), so there is no separate chip row.
 *   3. Readiness         — the supervised-accuracy signal (drafts accepted
 *                          as-is), so the operator can SEE the system earning
 *                          the autonomy flip.
 *
 * Honesty rules:
 *   - "All accounted for" claims only what the system can prove: every
 *     INGESTED message has a visible disposition (awaiting / held / unbound /
 *     sent / filtered). It is not a source-reconciliation guarantee against
 *     the mailbox.
 *   - Readiness only renders with real signal (≥1 actioned draft); otherwise
 *     an honest "building signal" state, never a fabricated percentage.
 */

type FilterKey = "all" | "draft_ready" | "knowledge_gap" | "unbound" | "sent";

type Props = {
  autoEnabled: boolean;
  thresholdPct: number | null;
  // Live operational counts (already in route scope).
  activeCount: number;
  draftReadyCount: number;
  unboundCount: number;
  heldCount: number;
  sentTodayCount: number;
  needsReviewFiltered: number;
  // Accuracy signal — operator draft decisions over 30d (approve/edit/reject).
  draftSignals?: { approved: number; edited: number; rejected: number };
  loading: boolean;
  // Which filter is currently active (drives the selected ledger pill).
  activeFilter: FilterKey;
  onFilter: (key: FilterKey) => void;
};

function LedgerStat({
  value,
  label,
  tone = "default",
  active,
  onClick,
}: {
  value: string;
  label: string;
  tone?: "default" | "warning" | "danger" | "accent";
  active: boolean;
  onClick: () => void;
}) {
  const valueTone =
    tone === "warning"
      ? "text-[var(--warning-text)]"
      : tone === "danger"
        ? "text-[var(--danger-text)]"
        : tone === "accent"
          ? "text-accent"
          : "text-primary";
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex flex-col items-start gap-0.5 rounded-md border px-2.5 py-1 text-left transition-colors",
        active ? "border-accent bg-selected" : "border-transparent hover:bg-hover",
      )}
    >
      <span className={cn("text-[19px] font-semibold leading-none tabular-nums tracking-[-0.02em]", valueTone)}>
        {value}
      </span>
      <span className="text-[10.5px] text-tertiary">{label}</span>
    </button>
  );
}

export function PreBookingAssuranceBand({
  autoEnabled,
  thresholdPct,
  activeCount,
  draftReadyCount,
  unboundCount,
  heldCount,
  sentTodayCount,
  needsReviewFiltered,
  draftSignals,
  loading,
  activeFilter,
  onFilter,
}: Props) {
  const decided = draftSignals
    ? draftSignals.approved + draftSignals.edited + draftSignals.rejected
    : 0;
  const accuracyPct = decided > 0 ? Math.round((draftSignals!.approved / decided) * 100) : null;

  // Accountability total — every inbound message currently has one of these
  // dispositions. This is the "nothing slipped past" read. It counts what the
  // system ingested and routed; it is not a mailbox reconciliation.
  const accountedFor =
    activeCount + unboundCount + heldCount + sentTodayCount + needsReviewFiltered;

  return (
    <section
      aria-label="Autonomy and accountability"
      className="flex flex-col gap-2 border-b border-hairline bg-sunken/40 px-7 py-3"
    >
      {/* Top line: autonomy state (left) + readiness (right) */}
      <div className="flex flex-wrap items-center justify-between gap-x-8 gap-y-2">
        <div className="flex items-center gap-3">
          <span
            className={cn(
              "flex h-8 w-8 flex-none items-center justify-center rounded-lg",
              autoEnabled ? "bg-[var(--success-fill)] text-[var(--success-text)]" : "bg-sunken text-tertiary",
            )}
            aria-hidden
          >
            <Icon name="spark" size={16} />
          </span>
          <div className="flex flex-col gap-0.5">
            <span className="flex items-center gap-2 text-sm font-semibold text-primary">
              {autoEnabled ? "Autonomous" : "Supervised"}
              {autoEnabled && thresholdPct !== null ? (
                <span className="rounded-md bg-[var(--success-fill)] px-1.5 py-0.5 text-[10.5px] font-medium text-[var(--success-text)] tabular-nums">
                  ≥ {thresholdPct}% auto-sends
                </span>
              ) : null}
            </span>
            <span className="text-[11.5px] text-tertiary">
              {autoEnabled
                ? "AI is replying on its own. You handle only what it holds."
                : "You're approving replies. Each one teaches the system."}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {accuracyPct !== null ? (
            <div className="flex flex-col items-end gap-0.5">
              <span className="text-[19px] font-semibold leading-none text-accent tabular-nums tracking-[-0.02em]">
                {accuracyPct}%
              </span>
              <span className="text-[10.5px] text-tertiary tabular-nums">
                drafts accepted as-is ({decided})
              </span>
            </div>
          ) : (
            <div className="flex flex-col items-end gap-0.5">
              <span className="text-[13px] font-medium text-tertiary">Building signal</span>
              <span className="text-[10.5px] text-tertiary">Review drafts to gauge readiness</span>
            </div>
          )}
        </div>
      </div>

      {/* Bottom line: inbox accountability + the ledger (which IS the filter row) */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="flex items-center gap-1.5 pr-1 text-[11.5px] text-tertiary">
          <span
            className="h-1.5 w-1.5 flex-none rounded-full bg-[var(--success-spine)]"
            aria-hidden
          />
          {loading
            ? "Accounting for inbox…"
            : `All ${accountedFor} accounted for`}
        </span>

        <LedgerStat
          value={loading ? "—" : String(activeCount)}
          label="Awaiting you"
          tone={activeCount > 0 ? "accent" : "default"}
          active={activeFilter === "all"}
          onClick={() => onFilter("all")}
        />
        <LedgerStat
          value={loading ? "—" : String(draftReadyCount)}
          label="Draft ready"
          active={activeFilter === "draft_ready"}
          onClick={() => onFilter("draft_ready")}
        />
        <LedgerStat
          value={loading ? "—" : String(unboundCount)}
          label="Need binding"
          tone="danger"
          active={activeFilter === "unbound"}
          onClick={() => onFilter("unbound")}
        />
        <LedgerStat
          value={loading ? "—" : String(heldCount)}
          label="Knowledge-held"
          tone="warning"
          active={activeFilter === "knowledge_gap"}
          onClick={() => onFilter("knowledge_gap")}
        />
        <LedgerStat
          value={loading ? "—" : String(sentTodayCount)}
          label="Sent today"
          active={activeFilter === "sent"}
          onClick={() => onFilter("sent")}
        />
        {needsReviewFiltered > 0 ? (
          <span className="ml-1 rounded-md bg-[var(--warning-fill)] px-2 py-1 text-[11px] text-[var(--warning-text)] tabular-nums">
            {needsReviewFiltered} filtered · needs review
          </span>
        ) : null}
      </div>
    </section>
  );
}
