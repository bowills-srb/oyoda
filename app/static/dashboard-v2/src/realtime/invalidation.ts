import type { QueryClient } from "@tanstack/react-query";

import { autonomyQueryOptions } from "../domain/autonomy/queries";
import { dashboardSummaryQueryOptions } from "../domain/dashboard/queries";
import { preBookingMessageFeedQueryOptions } from "../domain/prebooking/queries";
import { todayEscalationsQueryOptions, todaySessionsQueryOptions } from "../domain/today/queries";
import { queryKeys } from "../lib/query/queryKeys";

export function queryKeysForRealtimeEvent(eventType: string) {
  switch (eventType) {
    case "summary.updated":
      return [
        queryKeys.prebooking.feed(),
        queryKeys.autonomy.current(),
        queryKeys.today.sessions({ include_archived: false, limit: 200 }),
        [...queryKeys.today.all(), "escalations"] as const,
      ];
    case "inquiry.sent":
    case "inquiry.updated":
    case "kb.retry_progress":
      return [queryKeys.prebooking.feed()];
    case "autonomy.changed":
      return [queryKeys.autonomy.current(), queryKeys.prebooking.feed()];
    default:
      return [];
  }
}

// summary.updated fires on every message dispatch and triggers four queries
// (three eager fetchQuery refetches + dashboard summary invalidation). During
// a high-volume intake burst that recomputes prebooking feed, today sessions,
// and today escalations many times per second. Coalesce rapid summary.updated
// events into at most one refresh per second via a trailing-edge debounce.
// Only this event is debounced — inquiry.sent / autonomy.changed are
// low-frequency and operators expect immediate response. Module-level timer
// is scoped to one dashboard tab.
const SUMMARY_REFRESH_DEBOUNCE_MS = 1000;
let summaryRefreshTimer: ReturnType<typeof setTimeout> | null = null;
let pendingSummaryQueryClient: QueryClient | null = null;

async function runSummaryRefresh(queryClient: QueryClient) {
  await Promise.all([
    queryClient.fetchQuery(preBookingMessageFeedQueryOptions()),
    queryClient.fetchQuery(todaySessionsQueryOptions()),
    queryClient.fetchQuery(todayEscalationsQueryOptions()),
    queryClient.invalidateQueries({ queryKey: dashboardSummaryQueryOptions().queryKey }),
  ]);
}

function scheduleSummaryRefresh(queryClient: QueryClient) {
  pendingSummaryQueryClient = queryClient; // trailing-edge run uses the latest client
  if (summaryRefreshTimer) return;          // already scheduled — coalesce
  summaryRefreshTimer = setTimeout(() => {
    summaryRefreshTimer = null;
    const qc = pendingSummaryQueryClient;
    pendingSummaryQueryClient = null;
    if (qc) void runSummaryRefresh(qc);
  }, SUMMARY_REFRESH_DEBOUNCE_MS);
}

export async function refetchForRealtimeEvent(queryClient: QueryClient, eventType: string) {
  switch (eventType) {
    case "summary.updated":
      // Debounced — coalesces bursts to one refresh per second. Returns
      // immediately; the refresh runs on the trailing edge. RealtimeBridge
      // calls this as `void refetchForRealtimeEvent(...)` so nothing awaits.
      scheduleSummaryRefresh(queryClient);
      return;
    case "inquiry.sent":
    case "inquiry.updated":
    case "kb.retry_progress":
      await queryClient.fetchQuery(preBookingMessageFeedQueryOptions());
      return;
    case "autonomy.changed":
      await Promise.all([
        queryClient.fetchQuery(autonomyQueryOptions()),
        queryClient.fetchQuery(preBookingMessageFeedQueryOptions()),
      ]);
      return;
    default:
      await Promise.all(
        queryKeysForRealtimeEvent(eventType).map((queryKey) =>
          queryClient.invalidateQueries({ queryKey }),
        ),
      );
  }
}
