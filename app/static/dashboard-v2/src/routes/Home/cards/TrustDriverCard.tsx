/**
 * TrustDriverCard — explains why the Portfolio Autonomy score is what it is.
 *
 * Option (a): render ONLY the one derivable driver (Escalation Rate).
 * Draft Acceptance, Knowledge Coverage, and Policy Compliance have no data
 * source yet — omitting them entirely rather than showing "Coming soon" tiles.
 *
 * Escalation Rate = escalations.open ÷ max(1, pre_booking.total_30d + sessions.total_30d),
 * expressed as a percentage of 30-day volume. Labeled explicitly so the operator
 * understands the denominator.
 */
import type { DashboardSummary } from "../../../domain/dashboard/types";

type Props = {
  summary: DashboardSummary;
};

export function TrustDriverCard({ summary }: Props) {
  const volume30d = (summary.pre_booking.total_30d ?? 0) + (summary.sessions.total_30d ?? 0);
  const escalationRate = volume30d > 0
    ? ((summary.escalations.open / volume30d) * 100).toFixed(1)
    : null;

  return (
    <section
      aria-label="Escalation Rate"
      className="rounded-xl border border-hairline bg-raised px-5 py-4 flex flex-col gap-2"
    >
      <p className="text-[11px] font-medium text-tertiary uppercase tracking-[0.06em]">
        Escalation Rate
      </p>
      {escalationRate !== null ? (
        <>
          <p className="text-[26px] font-semibold text-primary tracking-[-0.02em] leading-none tabular-nums">
            {escalationRate}%
          </p>
          <p className="text-[12px] text-tertiary leading-snug">
            Open escalations as % of 30-day inquiry + session volume
          </p>
        </>
      ) : (
        <p className="text-[13px] text-tertiary">No volume data yet</p>
      )}
    </section>
  );
}
