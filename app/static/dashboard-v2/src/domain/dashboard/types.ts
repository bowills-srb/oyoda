/**
 * DashboardSummary — shape of GET /app/api/dashboard-summary.
 *
 * Verified against backend _compute_live_summary (2025-05).
 * NOTE: `properties` is a bare integer count — no per-property readiness or
 * autonomy tier data exists in this payload. Draft-acceptance data DOES now
 * exist via pre_booking.draft_signals (operator_draft_events aggregation).
 */
export type DashboardSummary = {
  sessions: {
    active: number;
    in_stay: number;
    arriving: number;
    total_30d: number;
  };
  pre_booking: {
    pending: number;
    oldest_pending_age_minutes: number | null;
    replied_30d: number;
    total_30d: number;
    ai_sent_today: number;
    // Operator draft-learning signals over the last 30 days, sourced from
    // operator_draft_events. Optional because a persisted read-model cache
    // written before this field existed won't include it until recomputed;
    // consumers must default safely when absent.
    draft_signals?: {
      approved: number;
      edited: number;
      rejected: number;
    };
  };
  escalations: {
    open: number;
    resolved_30d: number;
  };
  properties: number;
  kb_entries: number;
  kb_gaps: number;
  vendors: number;
  messages_30d: number;
  notifications_unread: number;
  inbox: {
    connected: boolean;
    email: string | null;
    provider: string | null;
    connected_at: string | null;
    last_polled_at: string | null;
    last_poll_success: boolean | null;
    last_poll_summary: string | null;
    last_poll_error: string | null;
    last_messages_found: number | null;
    last_new_pending_inquiries: number | null;
    last_query_mode: string | null;
  };
  degraded: boolean;
  cache_source: string;
  // Filtered message counts over the last 24h. Optional because a
  // persisted read-model cache written before this field existed won't
  // include it until recomputed; consumers must default safely.
  filtered?: {
    total: number;
    counts: Partial<Record<"suppressed" | "non_guest" | "needs_review" | "system", number>>;
    window: string;
  };
};
