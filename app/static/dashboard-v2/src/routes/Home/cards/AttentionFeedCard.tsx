/**
 * AttentionFeedCard — prioritized operator briefing.
 *
 * Assembled from real signals in dashboard-summary:
 * - Oldest pending inquiry (pre_booking.oldest_pending_age_minutes)
 * - Open escalations count
 * - Open KB gaps count
 *
 * The spec's "highest-risk escalation" and "biggest knowledge blocker" need
 * detail joins not available in summary — omitted.
 */
import { Link } from "react-router-dom";
import { cn } from "../../../lib/utils";
import type { DashboardSummary } from "../../../domain/dashboard/types";

type Props = { summary: DashboardSummary };

type Item = {
  label: string;
  detail: string;
  tone: "danger" | "warning" | "default";
  to: string;
  linkLabel: string;
};

function formatAge(minutes: number | null | undefined): string {
  if (typeof minutes !== "number" || !Number.isFinite(minutes) || minutes < 0) return "unknown age";
  if (minutes < 60) return `${Math.round(minutes)} min`;
  if (minutes < 60 * 24) return `${Math.floor(minutes / 60)}h ${Math.round(minutes % 60)}m`;
  return `${Math.floor(minutes / (60 * 24))}d old`;
}

export function AttentionFeedCard({ summary }: Props) {
  const items: Item[] = [];

  const oldestAge = summary.pre_booking.oldest_pending_age_minutes;
  if (summary.pre_booking.pending > 0) {
    const ageStr = formatAge(oldestAge);
    const isStale = typeof oldestAge === "number" && Number.isFinite(oldestAge) && oldestAge > 240;
    items.push({
      label: `${summary.pre_booking.pending} ${summary.pre_booking.pending === 1 ? "inquiry" : "inquiries"} need${summary.pre_booking.pending === 1 ? "s" : ""} review`,
      detail: `Oldest: ${ageStr}`,
      tone: isStale ? "danger" : "warning",
      to: "/app/v2/prebooking",
      linkLabel: "Go to Inquiry Operations",
    });
  }

  if (summary.escalations.open > 0) {
    items.push({
      label: `${summary.escalations.open} open ${summary.escalations.open === 1 ? "escalation" : "escalations"}`,
      detail: "Human intervention required",
      tone: "danger",
      to: "/app/v2/escalations",
      linkLabel: "Go to Escalations",
    });
  }

  if (summary.kb_gaps > 0) {
    items.push({
      label: `${summary.kb_gaps} knowledge ${summary.kb_gaps === 1 ? "gap" : "gaps"} unresolved`,
      detail: "Blocked by missing knowledge",
      tone: "warning",
      to: "/app/v2/properties",
      linkLabel: "Go to Property Intelligence",
    });
  }

  const toneColors: Record<Item["tone"], { bg: string; bar: string; label: string }> = {
    danger: {
      bg: "bg-[var(--danger-fill)]",
      bar: "bg-[var(--danger-spine)]",
      label: "text-[var(--danger-text)]",
    },
    warning: {
      bg: "bg-[var(--warning-fill)]",
      bar: "bg-[var(--warning-spine)]",
      label: "text-[var(--warning-text)]",
    },
    default: {
      bg: "bg-hover",
      bar: "bg-[var(--neutral-spine)]",
      label: "text-primary",
    },
  };

  return (
    <section
      aria-label="Attention Feed"
      className="rounded-xl border border-hairline bg-raised px-5 py-4 flex flex-col gap-4"
    >
      <div>
        <p className="text-[11px] font-medium text-tertiary uppercase tracking-[0.06em] mb-0.5">
          Attention Feed
        </p>
        <p className="text-[13px] text-secondary">Highest-signal items needing operator attention</p>
      </div>

      {items.length === 0 ? (
        <p className="text-[13px] text-tertiary py-3">
          No items requiring immediate attention.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((item) => {
            const colors = toneColors[item.tone];
            return (
              <li
                key={item.label}
                className={cn("flex items-stretch gap-0 rounded-lg overflow-hidden border border-hairline")}
              >
                <span className={cn("w-1 flex-shrink-0", colors.bar)} aria-hidden />
                <div className={cn("flex-1 flex items-center justify-between gap-4 px-3 py-2.5", colors.bg)}>
                  <div className="flex flex-col gap-0.5 min-w-0">
                    <span className={cn("text-[13px] font-medium", colors.label)}>{item.label}</span>
                    <span className="text-[11.5px] text-tertiary">{item.detail}</span>
                  </div>
                  <Link
                    to={item.to}
                    className="flex-shrink-0 text-[11.5px] font-medium text-accent hover:underline whitespace-nowrap"
                  >
                    {item.linkLabel} →
                  </Link>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
