import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { DashboardSummary } from "../../../domain/dashboard/types";
import { dashboardSummaryQueryOptions } from "../../../domain/dashboard/queries";
import { fetchFilteredList, promoteFilteredMessage } from "../../../domain/filtered/api";
import type { FilteredItem, FilteredListPayload, FilteredReason } from "../../../domain/filtered/types";
import type { ApiError } from "../../../api/client";
import { cn } from "../../../lib/utils";

// ── Bucket display config ─────────────────────────────────────────────────────

const BUCKET_LABELS: Record<FilteredReason, string> = {
  needs_review: "Needs review",
  suppressed: "Suppressed",
  non_guest: "Non-guest",
  system: "System",
};

const BUCKET_ORDER: FilteredReason[] = ["needs_review", "suppressed", "non_guest", "system"];

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  if (diffMs < 0) return "just now";
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Toast ─────────────────────────────────────────────────────────────────────

type ToastEntry = { id: number; message: string; tone: "success" | "danger" };

function Toast({ message, tone }: { message: string; tone: "success" | "danger" }) {
  return (
    <div
      className={cn(
        "fixed bottom-6 right-6 z-[200] px-4 py-3 rounded-lg shadow-lg text-[13px] font-medium max-w-sm",
        tone === "success"
          ? "bg-[var(--success-fill)] text-[var(--success-text)] border border-[var(--success-spine)]"
          : "bg-[var(--danger-fill)] text-[var(--danger-text)] border border-[var(--danger-spine)]",
      )}
      role="status"
    >
      {message}
    </div>
  );
}

// ── Filtered drawer ───────────────────────────────────────────────────────────

type DrawerProps = {
  window: string;
  onClose: () => void;
  onSummaryInvalidate: () => void;
};

function FilteredDrawer({ window: win, onClose, onSummaryInvalidate }: DrawerProps) {
  const [payload, setPayload] = useState<FilteredListPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [promoting, setPromoting] = useState<Record<string, boolean>>({});
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const toastCounter = useRef(0);

  const addToast = useCallback((message: string, tone: "success" | "danger") => {
    const id = ++toastCounter.current;
    setToasts((prev) => [...prev, { id, message, tone }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  }, []);

  useEffect(() => {
    setLoading(true);
    // limit=100 keeps the drawer list well within the backend cap (200) for
    // current tenant volumes. If a tenant's daily filtered count exceeds this,
    // the drawer will show fewer rows than the card count claims — the card
    // count comes from compute_filtered_counts (no row limit), the drawer from
    // the paginated /filtered endpoint. Add a "showing N of total" affordance
    // and raise limit before onboarding a high-volume tenant.
    fetchFilteredList({ window: win, limit: 100 })
      .then(setPayload)
      .catch(() => setError("Could not load filtered messages."))
      .finally(() => setLoading(false));
  }, [win]);

  const handlePromote = useCallback(
    async (item: FilteredItem) => {
      const key = `${item.source_channel}:${item.source_message_id}`;
      setPromoting((p) => ({ ...p, [key]: true }));
      try {
        const result = await promoteFilteredMessage(item.source_channel, item.source_message_id);
        if (result.ok) {
          setPayload((prev) =>
            prev
              ? {
                  ...prev,
                  total: Math.max(0, prev.total - 1),
                  items: prev.items.filter((i) => i.source_message_id !== item.source_message_id),
                }
              : prev,
          );
          addToast(
            result.already_in_queue ? "Already in Inquiry Operations." : "Moved to Inquiry Operations.",
            "success",
          );
          onSummaryInvalidate();
        }
      } catch (err) {
        const apiErr = err as ApiError;
        const detail =
          (apiErr.data as { error_detail?: { message?: string } } | null)?.error_detail?.message ||
          apiErr.message ||
          "Could not promote message.";
        addToast(detail, "danger");
      } finally {
        setPromoting((p) => {
          const next = { ...p };
          delete next[key];
          return next;
        });
      }
    },
    [addToast, onSummaryInvalidate],
  );

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  const items = payload?.items ?? [];

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[100] bg-black/30"
        onClick={onClose}
        aria-hidden
      />

      {/* Drawer panel */}
      <aside
        className="fixed right-0 top-0 bottom-0 z-[101] w-full max-w-[560px] bg-page border-l border-hairline flex flex-col shadow-2xl"
        aria-label="Filtered messages"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-hairline">
          <div>
            <p className="text-[11px] font-medium text-tertiary uppercase tracking-[0.06em] mb-0.5">
              Filtered Messages
            </p>
            <p className="text-[15px] font-semibold text-primary">
              {payload ? `${payload.total} in last 24h` : "Loading…"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-tertiary hover:text-primary hover:bg-hover transition-colors"
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
              <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Counts bar */}
        {payload && Object.keys(payload.counts).length > 0 && (
          <div className="flex gap-4 px-5 py-2.5 border-b border-hairline flex-wrap">
            {BUCKET_ORDER.filter((k) => (payload.counts[k] ?? 0) > 0).map((k) => (
              <span key={k} className="text-[12px] text-secondary">
                <span className="font-semibold text-primary tabular-nums">{payload.counts[k]}</span>
                {" "}{BUCKET_LABELS[k]}
              </span>
            ))}
          </div>
        )}

        {/* Body */}
        <div className="flex-1 overflow-y-auto [scrollbar-width:thin] [scrollbar-color:var(--border-default)_transparent]">
          {loading && (
            <div className="flex items-center justify-center py-16">
              <span className="text-[13px] text-tertiary">Loading…</span>
            </div>
          )}
          {!loading && error && (
            <div className="px-5 py-8 text-[13px] text-[var(--danger-text)]">{error}</div>
          )}
          {!loading && !error && items.length === 0 && (
            <div className="px-5 py-12 text-center">
              <p className="text-[14px] font-medium text-primary mb-1">Nothing filtered</p>
              <p className="text-[12.5px] text-tertiary">All messages in this window reached the queue.</p>
            </div>
          )}
          {!loading && !error && items.length > 0 && (
            <ul className="divide-y divide-hairline">
              {items.map((item) => {
                const key = `${item.source_channel}:${item.source_message_id}`;
                const isPending = promoting[key] ?? false;
                return (
                  <li key={key} className="px-5 py-3.5 flex flex-col gap-1.5">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[13px] font-medium text-primary truncate">
                          {item.sender_display_name || item.sender_address || "Unknown sender"}
                        </p>
                        {item.raw_subject && (
                          <p className="text-[12px] text-secondary truncate">{item.raw_subject}</p>
                        )}
                      </div>
                      <div className="flex flex-col items-end gap-1.5 shrink-0">
                        <span
                          className={cn(
                            "text-[10.5px] font-medium px-1.5 py-0.5 rounded",
                            item.reason === "needs_review"
                              ? "bg-[var(--warning-fill)] text-[var(--warning-text)]"
                              : "bg-hover text-tertiary",
                          )}
                        >
                          {BUCKET_LABELS[item.reason] ?? item.reason}
                        </span>
                        {item.sent_at && (
                          <span className="text-[11px] text-tertiary tabular-nums">
                            {formatTime(item.sent_at)}
                          </span>
                        )}
                      </div>
                    </div>
                    {item.preview && (
                      <p className="text-[12px] text-tertiary leading-snug line-clamp-2">{item.preview}</p>
                    )}
                    {item.promotable && (
                      <button
                        onClick={() => void handlePromote(item)}
                        disabled={isPending}
                        className="self-start mt-0.5 text-[11.5px] font-medium text-[var(--accent)] hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {isPending ? "Moving…" : "Promote to Inquiry Operations"}
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </aside>

      {/* Toasts */}
      {toasts.map((t) => (
        <Toast key={t.id} message={t.message} tone={t.tone} />
      ))}
    </>
  );
}

// ── FilteredMessagesCard ──────────────────────────────────────────────────────

type Props = { summary: DashboardSummary };

export function FilteredMessagesCard({ summary }: Props) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const queryClient = useQueryClient();

  const filtered = summary.filtered ?? { total: 0, counts: {}, window: "today" };
  const { total, counts } = filtered;

  const presentBuckets = BUCKET_ORDER.filter((k) => (counts[k] ?? 0) > 0);
  const needsReview = counts.needs_review ?? 0;

  const handleSummaryInvalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: dashboardSummaryQueryOptions().queryKey });
  }, [queryClient]);

  return (
    <>
      <section
        aria-label="Filtered Messages"
        className="rounded-xl border border-hairline bg-raised px-5 py-4 flex flex-col gap-3"
      >
        <div className="flex items-center justify-between gap-3">
          <p className="text-[11px] font-medium text-tertiary uppercase tracking-[0.06em]">
            Filtered Messages
          </p>
          {needsReview > 0 && (
            <span className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full bg-[var(--warning-fill)] text-[var(--warning-text)]">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--warning-spine)]" aria-hidden />
              {needsReview} need review
            </span>
          )}
        </div>

        <div>
          <button
            onClick={() => setDrawerOpen(true)}
            className="text-[28px] font-medium tabular-nums tracking-[-0.02em] leading-none text-primary hover:text-[var(--accent)] transition-colors"
            aria-label={`${total} filtered messages — open drawer`}
          >
            {total}
          </button>
          <p className="text-[11.5px] text-tertiary mt-1">filtered last 24h</p>
        </div>

        {presentBuckets.length > 0 ? (
          <dl className="grid gap-1">
            {presentBuckets.map((k) => (
              <div key={k} className="flex items-baseline justify-between gap-4">
                <dt className="text-[11.5px] text-tertiary">{BUCKET_LABELS[k]}</dt>
                <dd className="text-[11.5px] font-medium text-secondary tabular-nums">
                  {counts[k]}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-[11.5px] text-tertiary">Nothing filtered today.</p>
        )}
      </section>

      {drawerOpen && (
        <FilteredDrawer
          window="today"
          onClose={() => setDrawerOpen(false)}
          onSummaryInvalidate={handleSummaryInvalidate}
        />
      )}
    </>
  );
}
