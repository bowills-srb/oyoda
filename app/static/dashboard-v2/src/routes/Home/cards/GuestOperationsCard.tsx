import { Link } from "react-router-dom";
import type { DashboardSummary } from "../../../domain/dashboard/types";

type Props = { summary: DashboardSummary };

export function GuestOperationsCard({ summary }: Props) {
  const s = summary.sessions;

  return (
    <section
      aria-label="Guest Operations"
      className="rounded-xl border border-hairline bg-raised px-5 py-4 flex flex-col gap-4"
    >
      <div>
        <p className="text-[11px] font-medium text-tertiary uppercase tracking-[0.06em] mb-0.5">
          Guest Operations
        </p>
        <p className="text-[13px] text-secondary">Active stays and arrivals</p>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-3">
        <Stat label="Active stays" value={s.active} />
        <Stat label="Arriving" value={s.arriving} />
        <Stat label="In stay" value={s.in_stay} />
        <Stat label="Total (30d)" value={s.total_30d} />
      </div>

      <Link
        to="/app/v2/today"
        className="mt-auto text-[12.5px] font-medium text-accent hover:underline self-start"
      >
        Open Guest Operations →
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
