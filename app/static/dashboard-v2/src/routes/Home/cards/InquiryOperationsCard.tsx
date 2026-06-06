import { Link } from "react-router-dom";
import type { DashboardSummary } from "../../../domain/dashboard/types";
import { cn } from "../../../lib/utils";

type Props = { summary: DashboardSummary };

function formatAge(minutes: number | null | undefined): string {
  if (typeof minutes !== "number" || !Number.isFinite(minutes) || minutes < 0) return "—";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  if (minutes < 60 * 24) return `${Math.floor(minutes / 60)}h ${Math.round(minutes % 60)}m`;
  return `${Math.floor(minutes / (60 * 24))}d`;
}

export function InquiryOperationsCard({ summary }: Props) {
  const pb = summary.pre_booking;
  const oldestAge = pb.oldest_pending_age_minutes;
  const ageLabel = formatAge(oldestAge);
  const oldestWarning = typeof oldestAge === "number" && Number.isFinite(oldestAge) && oldestAge > 240;

  return (
    <section
      aria-label="Inquiry Operations"
      className="rounded-xl border border-hairline bg-raised px-5 py-4 flex flex-col gap-4"
    >
      <div>
        <p className="text-[11px] font-medium text-tertiary uppercase tracking-[0.06em] mb-0.5">
          Inquiry Operations
        </p>
        <p className="text-[13px] text-secondary">Pre-booking inquiries and AI delegation</p>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-3">
        <Stat label="Needs review" value={pb.pending ?? 0} />
        <Stat label="AI sent today" value={pb.ai_sent_today ?? 0} />
        <Stat label="Replied (30d)" value={pb.replied_30d ?? 0} />
        <Stat label="Total (30d)" value={pb.total_30d ?? 0} />
      </div>

      {ageLabel !== "—" && (
        <p className={cn("text-[12px]", oldestWarning ? "text-[var(--warning-text)]" : "text-tertiary")}>
          Oldest pending: {ageLabel}{oldestWarning ? " — needs attention" : ""}
        </p>
      )}

      <Link
        to="/app/v2/prebooking"
        className="mt-auto text-[12.5px] font-medium text-accent hover:underline self-start"
      >
        Open Inquiry Operations →
      </Link>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[22px] font-semibold text-primary tracking-[-0.02em] leading-none tabular-nums">
        {value}
      </span>
      <span className="text-[11.5px] text-tertiary">{label}</span>
    </div>
  );
}
