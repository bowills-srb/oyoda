/**
 * PortfolioAutonomyHero — portfolio-level autonomy score and domain bands.
 *
 * Wired to GET /app/api/v2/portfolio-autonomy (snapshot-first, live-compute
 * fallback). Shows the portfolio score, Inquiry domain band, and the
 * computed/insufficient-signal split so operators can see where signal is
 * thin. Insufficient Signal is a first-class state, not an edge case.
 *
 * Score thresholds (mirrors backend autonomy_score_service.py):
 *   ≥ 0.75 → Autonomous   (green)
 *   ≥ 0.45 → Developing   (amber)
 *   <  0.45 → Emerging    (orange)
 */
import { useQuery } from "@tanstack/react-query";
import { sessionQueryOptions } from "../../../domain/auth/queries";
import { portfolioAutonomyQueryOptions } from "../../../domain/autonomy/queries";
import type { DomainBand } from "../../../domain/autonomy/types";
import type { DashboardSummary } from "../../../domain/dashboard/types";

// ── Band helpers ────────────────────────────────────────────────────────────

function bandTone(band: DomainBand | string): "success" | "warning" | "muted" | "danger" {
  if (band === "Autonomous") return "success";
  if (band === "Developing") return "warning";
  if (band === "Insufficient Signal") return "muted";
  return "danger"; // Emerging
}

const TONE_CLASSES: Record<string, string> = {
  success: "text-[var(--success-700)]",
  warning: "text-[var(--warning-700)]",
  muted: "text-tertiary",
  danger: "text-[var(--danger-700)]",
};

const SCORE_BAR_CLASSES: Record<string, string> = {
  success: "bg-[var(--success-spine)]",
  warning: "bg-[var(--warning-spine)]",
  muted: "bg-border",
  danger: "bg-[var(--danger-spine)]",
};

function BandPill({ band }: { band: DomainBand | string }) {
  const tone = bandTone(band);
  return (
    <span className={`text-[11px] font-semibold tracking-wide ${TONE_CLASSES[tone]}`}>
      {band}
    </span>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

export function PortfolioAutonomyHero({ summary }: { summary: DashboardSummary }) {
  const { data: session } = useQuery({ ...sessionQueryOptions(), enabled: false });
  const { data, isLoading, isError } = useQuery(portfolioAutonomyQueryOptions());

  const workspaceName = session?.operator?.company?.trim() || "Your workspace";

  const scorePercent = data ? Math.round(data.portfolio_score * 100) : null;
  const inquiryBand = data?.domain_bands?.inquiry?.band ?? null;
  const tone = inquiryBand ? bandTone(inquiryBand) : "muted";
  const fallbackBlockers = (summary.kb_gaps ?? 0) + (summary.escalations.open ?? 0);

  const { included_properties = 0, excluded_properties = 0, total_managed = 0 } =
    data?.rollup ?? {};

  return (
    <section
      aria-label="Portfolio Autonomy"
      className="rounded-xl border border-hairline bg-raised px-7 py-6 flex flex-col gap-4"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex flex-col gap-0.5">
          <p className="text-[11px] font-medium text-tertiary uppercase tracking-[0.06em]">
            Portfolio Autonomy
          </p>
          <h2 className="text-[22px] font-semibold text-primary tracking-[-0.02em] leading-tight">
            {workspaceName}
          </h2>
        </div>

        {/* Score badge */}
        {scorePercent !== null && (
          <div className="flex flex-col items-end gap-0.5 shrink-0">
            <span
              className={`text-[32px] font-bold tracking-[-0.03em] leading-none tabular-nums ${TONE_CLASSES[tone]}`}
            >
              {scorePercent}
              <span className="text-[18px] font-semibold ml-0.5">%</span>
            </span>
            {inquiryBand && <BandPill band={inquiryBand} />}
          </div>
        )}

        {/* Loading skeleton */}
        {isLoading && (
          <div className="h-9 w-16 rounded bg-hover animate-pulse" />
        )}

        {scorePercent === null && !isLoading && (
          <div className="flex flex-col items-end gap-0.5 shrink-0">
            <span className="text-[13px] font-semibold text-tertiary">Score pending</span>
            <span className="text-[11px] text-tertiary">
              {fallbackBlockers} blocker{fallbackBlockers === 1 ? "" : "s"} visible
            </span>
          </div>
        )}
      </div>

      {/* Score bar */}
      {scorePercent !== null && (
        <div className="w-full h-1.5 rounded-full bg-border overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${SCORE_BAR_CLASSES[tone]}`}
            style={{ width: `${scorePercent}%` }}
          />
        </div>
      )}

      {/* Domain bands grid */}
      {data && (
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 pt-0.5">
          {(
            [
              ["Inquiry", data.domain_bands.inquiry.band],
              ["Guest Ops", data.domain_bands.guest_ops],
              ["Maintenance", data.domain_bands.maintenance],
              ["Turnover", data.domain_bands.turnover],
            ] as [string, DomainBand][]
          ).map(([label, band]) => (
            <div key={label} className="flex items-center justify-between gap-2">
              <span className="text-[12px] text-tertiary">{label}</span>
              <BandPill band={band} />
            </div>
          ))}
        </div>
      )}

      {/* Property signal summary */}
      {data && total_managed > 0 && (
        <div className="rounded-lg border border-hairline bg-hover px-4 py-3 flex items-center justify-between gap-4 flex-wrap">
          <div className="flex gap-4">
            <div className="flex flex-col gap-0.5">
              <span className="text-[18px] font-semibold text-primary tabular-nums leading-none">
                {included_properties}
              </span>
              <span className="text-[11px] text-tertiary">Computed</span>
            </div>
            {excluded_properties > 0 && (
              <div className="flex flex-col gap-0.5">
                <span className="text-[18px] font-semibold text-tertiary tabular-nums leading-none">
                  {excluded_properties}
                </span>
                <span className="text-[11px] text-tertiary">Insufficient signal</span>
              </div>
            )}
          </div>
          <span className="text-[12px] text-tertiary">
            of {total_managed} managed {total_managed === 1 ? "property" : "properties"}
          </span>
        </div>
      )}

      {/* Error state */}
      {isError && !data && (
        <div className="rounded-lg border border-hairline bg-hover px-5 py-4">
          <p className="text-[13px] text-secondary">
            Autonomy score unavailable. The briefing below still uses live operational signals.
          </p>
        </div>
      )}
    </section>
  );
}
