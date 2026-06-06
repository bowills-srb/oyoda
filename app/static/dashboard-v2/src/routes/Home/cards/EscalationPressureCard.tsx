/**
 * EscalationPressureCard — human intervention load.
 *
 * NOTE: the spec wants high-priority / waiting-vendor / waiting-guest splits.
 * Those sub-splits are NOT in dashboard-summary. Rendering open + resolved_30d
 * only; omitting fabricated splits.
 */
import { Link } from "react-router-dom";
import { cn } from "../../../lib/utils";
import type { DashboardSummary } from "../../../domain/dashboard/types";

type Props = { summary: DashboardSummary };

export function EscalationPressureCard({ summary }: Props) {
  const e = summary.escalations;
  const hasOpen = e.open > 0;

  return (
    <section
      aria-label="Escalation Pressure"
      className="rounded-xl border border-hairline bg-raised px-5 py-4 flex flex-col gap-4"
    >
      <div>
        <p className="text-[11px] font-medium text-tertiary uppercase tracking-[0.06em] mb-0.5">
          Human Intervention Load
        </p>
        <p className="text-[13px] text-secondary">Open escalations requiring human response</p>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-3">
        <div className="flex flex-col gap-0.5">
          <span
            className={cn(
              "text-[22px] font-semibold tracking-[-0.02em] leading-none tabular-nums",
              hasOpen ? "text-[var(--danger-text)]" : "text-primary",
            )}
          >
            {e.open}
          </span>
          <span className="text-[11.5px] text-tertiary">Open escalations</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-[22px] font-semibold text-primary tracking-[-0.02em] leading-none tabular-nums">
            {e.resolved_30d}
          </span>
          <span className="text-[11.5px] text-tertiary">Resolved (30d)</span>
        </div>
      </div>

      <Link
        to="/app/v2/escalations"
        className="mt-auto text-[12.5px] font-medium text-accent hover:underline self-start"
      >
        Open Escalations →
      </Link>
    </section>
  );
}
