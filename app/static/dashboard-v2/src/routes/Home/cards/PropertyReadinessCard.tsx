/**
 * PropertyReadinessCard — supply side of autonomy.
 *
 * Shows the managed property count and the computed/insufficient-signal split
 * from the portfolio autonomy snapshot. Insufficient Signal is a first-class
 * state: 13 of Beach Habitats' 45 properties have no traffic yet and must be
 * shown honestly as "not enough signal," not as a fabricated verdict.
 */
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { DashboardSummary } from "../../../domain/dashboard/types";
import { portfolioAutonomyQueryOptions } from "../../../domain/autonomy/queries";

type Props = { summary: DashboardSummary };

export function PropertyReadinessCard({ summary }: Props) {
  const { data: autonomy } = useQuery(portfolioAutonomyQueryOptions());

  const totalManaged = autonomy?.rollup.total_managed ?? summary.properties;
  const computed = autonomy?.rollup.included_properties ?? null;
  const insufficient = autonomy?.rollup.excluded_properties ?? null;

  return (
    <section
      aria-label="Property Readiness"
      className="rounded-xl border border-hairline bg-raised px-5 py-4 flex flex-col gap-4"
    >
      <div>
        <p className="text-[11px] font-medium text-tertiary uppercase tracking-[0.06em] mb-0.5">
          Properties Ready for Delegation
        </p>
        <p className="text-[13px] text-secondary">Supply side of portfolio autonomy</p>
      </div>

      <div className="flex flex-col gap-0.5">
        <span className="text-[26px] font-semibold text-primary tracking-[-0.02em] leading-none tabular-nums">
          {totalManaged}
        </span>
        <span className="text-[11.5px] text-tertiary">Managed properties</span>
      </div>

      {/* Computed / Insufficient signal split — shown once autonomy data loads */}
      {computed !== null && insufficient !== null && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between text-[12px]">
            <span className="text-secondary">Scoring computed</span>
            <span className="font-medium text-primary tabular-nums">{computed}</span>
          </div>
          <div className="flex items-center justify-between text-[12px]">
            <span className="text-tertiary">Insufficient signal</span>
            <span className="tabular-nums text-tertiary">{insufficient}</span>
          </div>
          {/* Visual bar — proportion with computed score */}
          {totalManaged > 0 && (
            <div className="w-full h-1 rounded-full bg-border overflow-hidden mt-0.5">
              <div
                className="h-full rounded-full bg-[var(--success-spine)] transition-all duration-500"
                style={{ width: `${Math.round((computed / totalManaged) * 100)}%` }}
              />
            </div>
          )}
        </div>
      )}

      <Link
        to="/app/v2/properties"
        className="mt-auto text-[12.5px] font-medium text-accent hover:underline self-start"
      >
        Open Properties →
      </Link>
    </section>
  );
}
