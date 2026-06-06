/**
 * KnowledgeHealthCard — where missing knowledge is limiting autonomy.
 *
 * NOTE: the spec wants "frequently asked unresolved topics" and
 * "properties blocking automation" — those need detail joins not in the
 * dashboard-summary payload. Rendering gap count + kb entry count honestly;
 * omitting the detail breakdowns.
 */
import { Link } from "react-router-dom";
import { cn } from "../../../lib/utils";
import type { DashboardSummary } from "../../../domain/dashboard/types";

type Props = { summary: DashboardSummary };

export function KnowledgeHealthCard({ summary }: Props) {
  const hasGaps = summary.kb_gaps > 0;

  return (
    <section
      aria-label="Knowledge Health"
      className="rounded-xl border border-hairline bg-raised px-5 py-4 flex flex-col gap-4"
    >
      <div>
        <p className="text-[11px] font-medium text-tertiary uppercase tracking-[0.06em] mb-0.5">
          Knowledge Health
        </p>
        <p className="text-[13px] text-secondary">Missing knowledge blocking automation</p>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-3">
        <div className="flex flex-col gap-0.5">
          <span
            className={cn(
              "text-[22px] font-semibold tracking-[-0.02em] leading-none tabular-nums",
              hasGaps ? "text-[var(--warning-text)]" : "text-primary",
            )}
          >
            {summary.kb_gaps}
          </span>
          <span className="text-[11.5px] text-tertiary">
            {hasGaps ? "Blocked by missing knowledge" : "Open gaps"}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-[22px] font-semibold text-primary tracking-[-0.02em] leading-none tabular-nums">
            {summary.kb_entries}
          </span>
          <span className="text-[11.5px] text-tertiary">KB entries</span>
        </div>
      </div>

      <Link
        to="/app/v2/properties"
        className="mt-auto text-[12.5px] font-medium text-accent hover:underline self-start"
      >
        Open Property Intelligence →
      </Link>
    </section>
  );
}
