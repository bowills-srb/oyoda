import type { DashboardSummary } from "../../../domain/dashboard/types";
import { cn } from "../../../lib/utils";

type Props = { summary: DashboardSummary };

function formatTimeAgo(isoString: string | null): string {
  if (!isoString) return "never";
  const diffMs = Date.now() - new Date(isoString).getTime();
  if (diffMs < 0) return "just now";
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function InboxHealthCard({ summary }: Props) {
  const inbox = summary.inbox;
  const statusOk = inbox.connected && inbox.last_poll_success !== false;

  return (
    <section
      aria-label="Inbox Health"
      className="rounded-xl border border-hairline bg-raised px-5 py-4 flex flex-col gap-3"
    >
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] font-medium text-tertiary uppercase tracking-[0.06em]">
          Inbox Health
        </p>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 text-[11.5px] font-medium px-2 py-0.5 rounded-full",
            inbox.connected
              ? "bg-[var(--success-fill)] text-[var(--success-text)]"
              : "bg-[var(--danger-fill)] text-[var(--danger-text)]",
          )}
        >
          <span
            className={cn(
              "w-1.5 h-1.5 rounded-full",
              inbox.connected ? "bg-[var(--success-spine)]" : "bg-[var(--danger-spine)]",
            )}
            aria-hidden
          />
          {inbox.connected ? "Connected" : "Disconnected"}
        </span>
      </div>

      <dl className="grid gap-1.5">
        {inbox.provider && (
          <Row label="Provider" value={inbox.provider} />
        )}
        {inbox.email && (
          <Row label="Account" value={inbox.email} />
        )}
        <Row label="Last polled" value={formatTimeAgo(inbox.last_polled_at)} />
        {inbox.last_poll_success !== null && (
          <Row
            label="Last result"
            value={inbox.last_poll_success ? "Success" : "Failed"}
            valueClass={inbox.last_poll_success ? "text-[var(--success-text)]" : "text-[var(--danger-text)]"}
          />
        )}
        {inbox.last_messages_found !== null && (
          <Row label="Messages found" value={String(inbox.last_messages_found)} />
        )}
        {inbox.last_new_pending_inquiries !== null && (
          <Row label="New inquiries" value={String(inbox.last_new_pending_inquiries)} />
        )}
      </dl>

      {!statusOk && inbox.last_poll_error && (
        <p className="text-[11.5px] text-[var(--danger-text)] leading-snug bg-[var(--danger-fill)] rounded-md px-3 py-2">
          {inbox.last_poll_error}
        </p>
      )}

      {inbox.last_poll_summary && statusOk && (
        <p className="text-[11.5px] text-tertiary leading-snug">{inbox.last_poll_summary}</p>
      )}
    </section>
  );
}

function Row({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-[11.5px] text-tertiary">{label}</dt>
      <dd className={cn("text-[11.5px] font-medium text-secondary truncate max-w-[160px]", valueClass)}>
        {value}
      </dd>
    </div>
  );
}
