import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "../../components/primitives/Badge";
import { SurfaceControls } from "../../components/system/SurfaceControls";
import { SurfaceTabs } from "../../components/system/SurfaceTabs";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import {
  useExecuteTodaySessionActionMutation,
  useRequestTodaySessionFeedbackMutation,
  useSendTodaySessionUpdateMutation,
} from "../../domain/today/mutations";
import { normalizeTodaySessionsList } from "../../domain/today/normalize";
import {
  todayEscalationsQueryOptions,
  todaySessionActionsQueryOptions,
  todaySessionDetailQueryOptions,
  todaySessionsQueryOptions,
  todayThreadTimelineQueryOptions,
} from "../../domain/today/queries";
import type { SessionDetail, StayActions, ThreadTimeline, TodaySessionsList } from "../../domain/today/types";
import { cn } from "../../lib/utils";
import { Icon } from "../../shared/Icon";
import { useUrlState } from "../../shared/url-state/useUrlState";
import { useListKeyboardNav } from "../../shared/hooks/useListKeyboardNav";
import {
  TODAY_POST_STAY_WINDOW_DAYS,
  TODAY_ARRIVING_WINDOW_DAYS,
  classifyForToday,
  type LifecycleClassification,
} from "../../shared/lifecycle/windows";

import {
  formatAge,
  formatDate,
  dayOfStay,
  lifecycleStageLabel,
  lifecycleStageTone,
  nightsBetween,
} from "./lifecycleLabels";
import {
  FOCUSES_BY_TAB,
  FOCUS_LABELS,
  matchesFocus,
  matchesInStayFocus,
  matchesPostStayFocus,
  type AnyFocus,
  type TodayTab,
} from "./focusPredicates";
import { derivePriorityCard, type Escalation } from "./priorityRules";
import {
  OPERATOR_TOOL_REASSURE,
  OPERATOR_TOOL_REQUEST_FEEDBACK,
  SessionExpansion,
} from "./SessionExpansion";
/**
 * Today — operator live operations queue.
 *
 * Today rows are session objects, not message objects. The row's primary noun
 * is the guest + stay + property, with messaging as one tool inside the
 * workflow alongside vendor dispatch, escalation resolution, journey touches,
 * and turnover coordination. This shape is intentionally different from
 * Pre-Booking, which is message-first.
 *
 * Four lifecycle tabs:
 *   pre_arrival  — check-in more than 7 days out
 *   arriving     — check-in within the next 7 days
 *   in_stay      — currently on property (default tab)
 *   post_stay    — check-out within the last 7 days
 *
 * Sessions farther out than the arriving window stay visible in the
 * pre_arrival planning lane instead of falling out of the surface.
 *
 * Each row surfaces, in order:
 *   1. Header     — guest · property · lifecycle stage · last activity
 *   2. Stay line  — check-in → check-out · nights · day-of-stay
 *   3. Priority   — the most pressing operational fact (collapses if none)
 *
 * Clicking a row expands it inline to show the session's operational
 * context: a stay timeline strip, open work orders, the conversation
 * snippet, and (when present) the cross-session guest history. The
 * expansion is actionable — an Actions block above the read-only blocks
 * surfaces AI-recommended next steps (from sessions.actions(id)) and
 * always-available operator tools (Reassure, Request feedback).
 *
 * Selection model (non-toggle):
 *   click unselected row → opens it
 *   click selected row   → no-op
 *   Enter/Space on unselected row → opens it
 *   Enter/Space on selected row   → no-op
 *   Close button / Escape → closes selection
 * Closing is always explicit. Accidental clicks on the open row don't
 * collapse the expansion.
 *
 * Per-tab focus chips filter the visible rows by operational signal:
 *   pre_arrival  — needs_welcome · unbound
 *   arriving     — arriving_soon · needs_welcome · unbound
 *   in_stay      — escalations · stuck_work_orders · checkout_due
 *   post_stay    — turnover_blocked · review_window
 *
 * Scalability note: this surface uses a single 200-row fetch and client-side
 * bucketing as a prototype shape. That keeps the new pre_arrival lane inside
 * one frontend workstream, but the dedicated lazy-load/server-filter follow-up
 * remains tracked in docs/TODAY_SCALABILITY_WORK_ITEM.md and
 * docs/scratch/TODAY_FOUR_STAGE_RESHAPE_SPEC.md.
 *
 * Module layout under routes/Today/:
 *   index.tsx           — route component, URL state, fetch effects, JSX
 *   lifecycleLabels.ts  — date helpers + lifecycle stage formatters
 *   priorityRules.ts    — the five priority card rules
 *   focusPredicates.ts  — focus chip type unions + predicates
 *   timeline.ts         — stay timeline strip derivation
 *   actionLabels.ts     — UI labels for each StayActionAgent action_type
 *   SessionExpansion.tsx — the inline expanded row
 *
 * Out of scope intentionally:
 *   - Vendor picker UI for vendor_coordination (deferred to step 6.5 if
 *     real usage shows the backend's auto-pick isn't good enough)
 *   - Editing pre-composed messages before sending (Reassure is the
 *     custom-text escape hatch)
 *   - SSE patch-by-ID updates (deferred per scalability work item)
 */

type Session = TodaySessionsList["sessions"][number];
type SessionsSummary = TodaySessionsList["summary"];
type StayAction = StayActions["actions"][number];

const TODAY_TABS: readonly TodayTab[] = ["pre_arrival", "arriving", "in_stay", "post_stay"] as const;

const TAB_LABELS: Record<TodayTab, string> = {
  pre_arrival: "Pre-arrival",
  arriving: "Arriving",
  in_stay: "In stay",
  post_stay: "Post-stay",
};

const TAB_EMPTY_COPY: Record<TodayTab, { title: string; copy: string }> = {
  pre_arrival: {
    title: "No upcoming bookings beyond the next 7 days.",
    copy: "Guests further out on the calendar appear here for calm planning and early outreach.",
  },
  arriving: {
    title: "No guests arriving in the next 7 days.",
    copy: `Guests checking in within the next ${TODAY_ARRIVING_WINDOW_DAYS} days appear here for welcome and arrival prep.`,
  },
  in_stay: {
    title: "No guests on property right now.",
    copy: "When a guest checks in, their session will appear here for the length of the stay.",
  },
  post_stay: {
    title: "No recent check-outs.",
    copy: `Stays that checked out in the last ${TODAY_POST_STAY_WINDOW_DAYS} days appear here for follow-up.`,
  },
};

// URL state defaults.
const URL_DEFAULTS = {
  tab: "in_stay",
  property: "",
  q: "",
  focus: "all",
  selected: "",
};

type ProactiveIndicator = {
  tone: "warning" | "accent" | "default";
  label: string;
  summary: string;
};

function humanizeTouchType(value: string): string {
  if (!value) return "Proactive touch due";
  const normalized = value
    .replace(/^touch_/, "")
    .replace(/^proactive_/, "")
    .replace(/_/g, " ")
    .trim();
  if (!normalized) return "Proactive touch due";
  return `${normalized[0].toUpperCase()}${normalized.slice(1)} due`;
}

function summarizeCompletedTouch(session: Session): string {
  if (session.welcomeSent && session.notificationsSent <= 1) return "Welcome sent";
  if (session.poolHeatAccepted) return "Pool heat accepted";
  if (session.poolHeatOffered) return "Pool heat offered";
  if (session.checkoutReminderSent) return "Checkout reminder sent";
  if (session.checkinReminderSent) return "Check-in reminder sent";
  if (session.extendOfferSent) return "Extend offer sent";
  if (session.notificationsSent > 0) {
    return `${session.notificationsSent} ${session.notificationsSent === 1 ? "touch" : "touches"} sent`;
  }
  return "Journey active";
}

function deriveProactiveIndicator(session: Session): ProactiveIndicator | null {
  const proactive = (session.workflow as { proactive?: Record<string, unknown> } | undefined)?.proactive;
  const proactiveEligible = proactive && typeof proactive === "object" && proactive.eligible === true;
  const touchType =
    proactive && typeof proactive === "object" ? String(proactive.touch_type || "") : "";
  if (proactiveEligible && touchType) {
    return {
      tone: "warning",
      label: "Proactive due",
      summary: humanizeTouchType(touchType),
    };
  }

  const hasTouches =
    session.welcomeSent ||
    session.checkinReminderSent ||
    session.checkoutReminderSent ||
    session.extendOfferSent ||
    session.poolHeatOffered ||
    session.poolHeatAccepted ||
    session.notificationsSent > 0;
  if (hasTouches) {
    return {
      tone: "accent",
      label: "Agent active",
      summary: summarizeCompletedTouch(session),
    };
  }

  if (session.journeyTracked || session.proactiveTriggeredAt) {
    return {
      tone: "default",
      label: "Monitoring",
      summary: "No proactive activity yet",
    };
  }

  return null;
}

function coerceTab(raw: string): TodayTab {
  return (TODAY_TABS as readonly string[]).includes(raw) ? (raw as TodayTab) : "in_stay";
}

// Focus coercion depends on the active tab — `escalations` is valid on
// in_stay but nonsensical on pre_arrival. If the URL has a stale focus for
// the current tab, we fall back to "all" rather than throwing.
function coerceFocus(raw: string, tab: TodayTab): AnyFocus {
  const allowed = FOCUSES_BY_TAB[tab] as readonly string[];
  if (allowed.includes(raw)) return raw as AnyFocus;
  return "all";
}

export default function TodayRoute() {
  const queryClient = useQueryClient();
  const executeActionMutation = useExecuteTodaySessionActionMutation();
  const sendUpdateMutation = useSendTodaySessionUpdateMutation();
  const requestFeedbackMutation = useRequestTodaySessionFeedbackMutation();
  const sessionsQuery = useQuery(todaySessionsQueryOptions());
  const escalationsQuery = useQuery(todayEscalationsQueryOptions());
  const sessions = sessionsQuery.data?.sessions ?? null;
  const sessionsSummary = sessionsQuery.data?.summary ?? null;
  const escalations = escalationsQuery.data ?? null;
  const error = sessionsQuery.error instanceof Error
    ? sessionsQuery.error.message
    : escalationsQuery.error instanceof Error
      ? escalationsQuery.error.message
      : "";
  const isLoading = sessionsQuery.isLoading || escalationsQuery.isLoading;

  // Local in-flight set, keyed by `${sessionId}::${actionKey}` so concurrent
  // selections don't collide. actionKey is either the queued action_type or
  // one of OPERATOR_TOOL_* constants for the always-available operator
  // tools. The set drives immediate visual feedback on the action button —
  // refetch still runs for correctness, but the button commits the moment
  // the operator clicks.
  const [executingKeys, setExecutingKeys] = useState<Set<string>>(() => new Set());

  // Action error, scoped to (sessionId, key) so a Reassure failure on one
  // row doesn't show an error banner on a different row. Cleared the moment
  // the operator retries the same action.
  const [actionError, setActionError] = useState<{
    sessionId: string;
    key: string;
    message: string;
  } | null>(null);

  const [urlState, updateUrl] = useUrlState(URL_DEFAULTS);
  const activeTab = coerceTab(urlState.tab);
  const activeFocus = coerceFocus(urlState.focus, activeTab);
  const propertyFilter = urlState.property;
  const search = urlState.q;
  const selectedId = urlState.selected;
  const selectedDetailQuery = useQuery({
    ...todaySessionDetailQueryOptions(selectedId || ""),
    enabled: Boolean(selectedId),
  });
  const selectedActionsQuery = useQuery({
    ...todaySessionActionsQueryOptions(selectedId || ""),
    enabled: Boolean(selectedId),
  });
  const selectedThreadId = selectedDetailQuery.data?.session.guestThreadId || "";
  const selectedThreadQuery = useQuery({
    ...todayThreadTimelineQueryOptions(selectedThreadId),
    enabled: Boolean(selectedThreadId),
  });

  // Non-toggle selection: opening a row is always an explicit "select this
  // one", never a toggle. Closing happens via the Close button or Escape.
  // Both mouse and keyboard handlers below call handleSelect, which is now
  // a one-way operation; the toggle semantics from step 5 have been removed.
  const handleSelect = useCallback(
    (sessionId: string) => {
      if (selectedId === sessionId) return; // already open, no-op
      updateUrl({ selected: sessionId }, { replace: true });
    },
    [selectedId, updateUrl],
  );

  const handleClose = useCallback(() => {
    updateUrl({ selected: "" }, { replace: true });
  }, [updateUrl]);

  // Shared executor for any action click. Manages the in-flight set, fires
  // the supplied API call, then refetches detail + actions to swap in the
  // server-side truth. Errors are scoped to (sessionId, key) so a failure
  // on one row doesn't leak across rows.
  //
  // The in-flight key is `${sessionId}::${actionKey}` to avoid collisions
  // when the operator selects another row mid-flight; the expansion
  // component receives a filtered Set of just the bare keys for the
  // currently visible session.
  const runAction = useCallback(
    async (
      sessionId: string,
      actionKey: string,
      apiCall: () => Promise<unknown>,
    ) => {
      const fullKey = `${sessionId}::${actionKey}`;
      setExecutingKeys((prev) => {
        const next = new Set(prev);
        next.add(fullKey);
        return next;
      });
      // Clear any prior error for this (sessionId, actionKey) pair so the
      // operator's retry doesn't show the previous failure alongside the
      // new in-flight state.
      setActionError((prev) =>
        prev && prev.sessionId === sessionId && prev.key === actionKey ? null : prev,
      );
      try {
        await apiCall();
        await Promise.all([
          queryClient.fetchQuery(todaySessionDetailQueryOptions(sessionId)),
          queryClient.fetchQuery(todaySessionActionsQueryOptions(sessionId)),
          queryClient.fetchQuery(todaySessionsQueryOptions()),
          queryClient.fetchQuery(todayEscalationsQueryOptions()),
        ]);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Action failed";
        setActionError({ sessionId, key: actionKey, message });
      } finally {
        setExecutingKeys((prev) => {
          const next = new Set(prev);
          next.delete(fullKey);
          return next;
        });
      }
    },
    [queryClient],
  );

  const handleExecuteAction = useCallback(
    (sessionId: string, actionType: string) => {
      void runAction(sessionId, actionType, () =>
        executeActionMutation.mutateAsync({ sessionId, actionType }),
      );
    },
    [executeActionMutation, runAction],
  );

  const handleReassure = useCallback(
    (sessionId: string, messageText: string) => {
      void runAction(sessionId, OPERATOR_TOOL_REASSURE, () =>
        sendUpdateMutation.mutateAsync({ sessionId, messageText }),
      );
    },
    [runAction, sendUpdateMutation],
  );

  const handleRequestFeedback = useCallback(
    (sessionId: string) => {
      void runAction(sessionId, OPERATOR_TOOL_REQUEST_FEEDBACK, () =>
        requestFeedbackMutation.mutateAsync({ sessionId }),
      );
    },
    [requestFeedbackMutation, runAction],
  );

  // Escape key clears the selection. Same pattern as Pre-Booking.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && selectedId) {
        updateUrl({ selected: "" }, { replace: true });
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedId, updateUrl]);

  // Classify all sessions once. Pure function over phase + dates; memoized
  // against the sessions reference.
  const classified = useMemo(() => {
    if (!sessions) return null;
    return sessions.map((session) => ({
      session,
      classification: classifyForToday(session),
    }));
  }, [sessions]);

  // Bucket by lifecycle tab, then sort by operational priority within each.
  // Sort order: escalations first, then bucket-specific priority.
  const byBucket = useMemo(() => {
    const buckets: Record<TodayTab, { session: Session; classification: LifecycleClassification }[]> = {
      pre_arrival: [],
      arriving: [],
      in_stay: [],
      post_stay: [],
    };
    if (!classified) return buckets;
    for (const entry of classified) {
      if (entry.classification.bucket === "out_of_window") continue;
      buckets[entry.classification.bucket as TodayTab].push(entry);
    }

    // In-stay sort: escalations → stuck vendors → checkout due → activity
    buckets.in_stay.sort((a, b) => {
      if (b.session.openEscalations !== a.session.openEscalations) {
        return b.session.openEscalations - a.session.openEscalations;
      }
      const aStuck = matchesInStayFocus(a.session, "stuck_work_orders") ? 1 : 0;
      const bStuck = matchesInStayFocus(b.session, "stuck_work_orders") ? 1 : 0;
      if (bStuck !== aStuck) return bStuck - aStuck;
      const aCheckout = matchesInStayFocus(a.session, "checkout_due") ? 1 : 0;
      const bCheckout = matchesInStayFocus(b.session, "checkout_due") ? 1 : 0;
      if (bCheckout !== aCheckout) return bCheckout - aCheckout;
      const aTime = new Date(a.session.lastMessageAt || a.session.checkIn || 0).getTime();
      const bTime = new Date(b.session.lastMessageAt || b.session.checkIn || 0).getTime();
      return bTime - aTime;
    });

    // Arriving sort: escalations → arrival imminence
    buckets.arriving.sort((a, b) => {
      if (b.session.openEscalations !== a.session.openEscalations) {
        return b.session.openEscalations - a.session.openEscalations;
      }
      return (a.classification.daysUntilCheckIn ?? 99) - (b.classification.daysUntilCheckIn ?? 99);
    });

    // Pre-arrival sort: soonest upcoming booking first.
    buckets.pre_arrival.sort((a, b) => {
      if (b.session.openEscalations !== a.session.openEscalations) {
        return b.session.openEscalations - a.session.openEscalations;
      }
      return (a.classification.daysUntilCheckIn ?? Number.POSITIVE_INFINITY) - (b.classification.daysUntilCheckIn ?? Number.POSITIVE_INFINITY);
    });

    // Post-stay sort: turnover blocked → most recent check-out
    buckets.post_stay.sort((a, b) => {
      const aBlocked = matchesPostStayFocus(a.session, "turnover_blocked") ? 1 : 0;
      const bBlocked = matchesPostStayFocus(b.session, "turnover_blocked") ? 1 : 0;
      if (bBlocked !== aBlocked) return bBlocked - aBlocked;
      return (a.classification.daysSinceCheckOut ?? 99) - (b.classification.daysSinceCheckOut ?? 99);
    });

    return buckets;
  }, [classified]);

  const propertyOptions = useMemo(() => {
    if (!sessions) return [];
    const seen = new Map<string, string>();
    for (const session of sessions) {
      if (!session.propertyCode) continue;
      if (!seen.has(session.propertyCode)) {
        seen.set(session.propertyCode, session.propertyName || session.propertyCode);
      }
    }
    return Array.from(seen.entries())
      .map(([code, name]) => ({ code, name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [sessions]);

  // Apply property + search + focus filtering to the active tab.
  const visibleEntries = useMemo(() => {
    const tabEntries = byBucket[activeTab];
    const q = search.trim().toLowerCase();
    return tabEntries.filter((entry) => {
      if (propertyFilter && entry.session.propertyCode !== propertyFilter) return false;
      if (!matchesFocus(entry.session, entry.classification, activeTab, activeFocus)) return false;
      if (!q) return true;
      const haystack = `${entry.session.guestName} ${entry.session.propertyName} ${entry.session.propertyCode}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [byBucket, activeTab, activeFocus, propertyFilter, search]);

  // Per-tab focus chip counts. Count over the bucket (post property filter)
  // so the chip number reflects "how many in this tab" not "how many fetched".
  const focusCounts = useMemo(() => {
    const counts: Record<AnyFocus, number> = {
      all: 0,
      arriving_soon: 0,
      needs_welcome: 0,
      unbound: 0,
      escalations: 0,
      stuck_work_orders: 0,
      checkout_due: 0,
      turnover_blocked: 0,
      review_window: 0,
    };
    const bucketEntries = byBucket[activeTab].filter((entry) => {
      if (!propertyFilter) return true;
      return entry.session.propertyCode === propertyFilter;
    });
    for (const focus of FOCUSES_BY_TAB[activeTab]) {
      counts[focus] = bucketEntries.filter((entry) =>
        matchesFocus(entry.session, entry.classification, activeTab, focus),
      ).length;
    }
    return counts;
  }, [byBucket, activeTab, propertyFilter]);

  const tabCounts: Record<TodayTab, number> = {
    pre_arrival: byBucket.pre_arrival.length,
    arriving: byBucket.arriving.length,
    in_stay: byBucket.in_stay.length,
    post_stay: byBucket.post_stay.length,
  };

  // Keyboard navigation: j/k through the visible session list, Escape to close.
  const visibleSessionIds = useMemo(
    () => visibleEntries.map((entry) => entry.session.sessionId),
    [visibleEntries],
  );
  useListKeyboardNav({
    itemIds: visibleSessionIds,
    selectedId: selectedId ?? "",
    onSelect: handleSelect,
    onClose: handleClose,
  });

  const hasData = sessions !== null;
  const showSkeleton = isLoading && !hasData;

  // Auth-shaped errors should not look like empty queues. The fetch wrapper
  // attaches `status` to the thrown error; we surface a Not-authenticated
  // affordance here instead of bleeding into empty-state copy below. If the
  // error has no status (network failure, JSON parse failure, etc.) we still
  // treat it as a load failure and avoid claiming the queue is empty.
  const authFailed = Boolean(error) && /401|not authenticated|unauthorized|sign in/i.test(error);
  const loadFailed = Boolean(error) && !authFailed;

  const headerSubtitle = hasData
    ? `${tabCounts.in_stay} in stay · ${tabCounts.arriving} arriving · ${tabCounts.pre_arrival} upcoming · ${tabCounts.post_stay} recently checked out`
    : authFailed
      ? "Sign in to view your live operational queue."
      : loadFailed
        ? "Couldn't load your operational queue."
        : "Loading your live operational queue.";

  const aiSummary = useMemo(() => {
    if (!sessions) return "";
    // When auth or load failed, don't render a misleading "AI support today: 0 / 0 / 0"
    // line — that reads as "the AI did nothing today" when really we just couldn't
    // fetch the data. The headerSubtitle already explains the failure.
    if (authFailed || loadFailed) return "";

    const journeyManaged =
      (sessionsSummary?.journeyTracked ?? 0) ||
      sessions.filter((session) => session.journeyTracked).length;
    const proactiveEvaluated =
      (sessionsSummary?.proactiveEvaluated ?? 0) ||
      sessions.filter((session) => Boolean(session.proactiveTriggeredAt)).length;
    const touchesSent =
      (sessionsSummary?.notificationsSent ?? 0) ||
      sessions.reduce((total, session) => total + Math.max(session.notificationsSent, 0), 0);

    return `AI support today: ${journeyManaged} stays on journey automation · ${proactiveEvaluated} proactive checks evaluated · ${touchesSent} guest touches already sent`;
  }, [sessions, sessionsSummary, authFailed, loadFailed]);

  return (
    <main className="grid grid-rows-[auto_auto_1fr] content-start gap-0 p-0 min-w-0 h-full overflow-y-auto [scrollbar-width:thin] [scrollbar-color:var(--border-default)_transparent]">
      {/* Slim context strip — replaces the full SurfaceHeader. The "Guest
         Operations" title was redundant (the operator navigated here from a
         nav item that says exactly that) and the tall serif block wasted
         vertical space. We keep the operational context that earns its place:
         the lifecycle count line and the AI-support summary, plus the
         auth/load failure messaging that keys off headerSubtitle. Today is the
         default landing, so it's intentionally the one surface without a big
         page title. */}
      <div className="flex flex-col gap-0.5 border-b border-hairline px-7 pt-4 pb-3">
        <p
          className={cn(
            "m-0 text-xs tabular-nums",
            authFailed || loadFailed ? "text-[var(--danger-text)]" : "text-tertiary",
          )}
        >
          {headerSubtitle}
        </p>
        {aiSummary ? (
          <p className="m-0 text-[12.5px] leading-[1.5] text-secondary max-[640px]:text-xs">{aiSummary}</p>
        ) : null}
      </div>

      <SurfaceControls ariaLabel="Today controls">
        <SurfaceTabs
          ariaLabel="Today lifecycle queues"
          tabs={TODAY_TABS.map((tab) => ({
            key: tab,
            label: TAB_LABELS[tab],
            count: hasData ? tabCounts[tab] : "—",
          }))}
          activeKey={activeTab}
          onSelect={(key) => updateUrl({ tab: key as TodayTab, focus: "all" })}
        />

        <div className="flex items-center gap-2 px-7 py-3 border-b border-hairline max-[860px]:flex-col max-[860px]:items-stretch">
          <label className="min-w-0 flex-1 flex items-center gap-2 px-2.5 bg-hover border border-transparent rounded-md focus-within:bg-raised focus-within:border-border">
            <Icon name="search" size={16} />
            <Input
              aria-label="Search sessions"
              className="border-0 bg-transparent shadow-none h-auto py-[7px] text-[13px] focus-visible:ring-0 focus-visible:ring-offset-0 flex-1"
              value={search}
              onChange={(event) => updateUrl({ q: event.target.value })}
              placeholder="Search guest or property"
            />
          </label>

          <div className="flex gap-1.5 flex-wrap">
            <Select
              aria-label="Property filter"
              className="h-auto py-1.5 text-[12.5px] font-medium rounded-md text-secondary w-auto"
              value={propertyFilter}
              onChange={(event) => updateUrl({ property: event.target.value })}
            >
              <option value="">All properties</option>
              {propertyOptions.map((property) => (
                <option key={property.code} value={property.code}>
                  {property.name}
                </option>
              ))}
            </Select>
          </div>
        </div>

        {/*
          Per-tab focus chips. Each chip is a filter on the active tab's
          rows. Numbers reflect how many sessions in the current bucket
          match the focus, honoring the active property filter but ignoring
          the search query (search is for finding a specific guest, not
          for redefining the operational view).
        */}
        <div
          className="grid gap-3 px-7 pt-4 pb-5 border-b border-hairline max-[860px]:grid-cols-2"
          style={{ gridTemplateColumns: `repeat(${FOCUSES_BY_TAB[activeTab].length}, minmax(0, 1fr))` }}
          aria-label={`${TAB_LABELS[activeTab]} focus`}
        >
          {FOCUSES_BY_TAB[activeTab].map((focus) => {
            const isDanger = focus === "escalations" || focus === "turnover_blocked";
            const isWarning = focus === "stuck_work_orders" || focus === "needs_welcome" || focus === "checkout_due";
            const isActive = activeFocus === focus;
            return (
              <button
                key={focus}
                type="button"
                className={cn(
                  "grid gap-1.5 items-start justify-items-start px-[18px] py-4 border rounded-[10px] bg-raised cursor-pointer text-left transition-[border-color,background] duration-100 font-[inherit] text-inherit",
                  "[data-theme=dark]:bg-[var(--surface-solid)]",
                  !isActive && isDanger && "border-[color-mix(in_srgb,var(--danger-spine)_32%,var(--border-hairline))]",
                  !isActive && isWarning && "border-[color-mix(in_srgb,var(--warning-spine)_32%,var(--border-hairline))]",
                  !isActive && !isDanger && !isWarning && "border-hairline hover:bg-hover hover:border-border",
                  isActive && "border-accent bg-selected [data-theme=dark]:border-[var(--accent-500)] [data-theme=dark]:bg-selected",
                )}
                onClick={() => updateUrl({ focus })}
              >
                <span className={cn(
                  "text-[22px] font-medium tabular-nums leading-none tracking-[-0.02em]",
                  isDanger && "text-[var(--danger-text)]",
                  isWarning && "text-[var(--warning-text)]",
                  !isDanger && !isWarning && "text-primary",
                )}>
                  {hasData ? focusCounts[focus] : "—"}
                </span>
                <span className="text-[10.5px] text-tertiary font-medium tracking-[0.06em] uppercase">
                  {FOCUS_LABELS[focus]}
                </span>
              </button>
            );
          })}
        </div>
      </SurfaceControls>

      <section className="p-0">
        <div className="flex items-center justify-between gap-4 px-7 py-4 pb-2">
          <h2 className="m-0 text-[13px] font-medium text-tertiary leading-[1.2]">{TAB_LABELS[activeTab]}</h2>
          <div className="flex items-center gap-3.5">
            {hasData ? (
              <span className="text-xs text-tertiary tabular-nums">
                {`${visibleEntries.length} of ${tabCounts[activeTab]}`}
              </span>
            ) : authFailed ? null : loadFailed ? (
              <Badge tone="danger">{error}</Badge>
            ) : (
              <span className="text-xs text-tertiary tabular-nums">Loading queue</span>
            )}
          </div>
        </div>

        {/*
          Auth and load failures get a proper banner with a sign-in affordance
          (auth) or retry guidance (load). The banner replaces both the inline
          danger badge above and the misleading empty-state copy below — a
          screenshot in the May 27 polish review showed "No guests on property"
          rendering directly under "Not authenticated", which read as success-
          with-zero-results when it was actually a fetch failure.
        */}
        {authFailed ? (
          <div className="flex items-center justify-between gap-4 mx-7 mb-3 px-3.5 py-3 rounded-lg border bg-[var(--warning-fill)] border-[color-mix(in_srgb,var(--warning-spine)_28%,var(--border-hairline))]">
            <div className="flex flex-col gap-0.5 min-w-0">
              <strong className="text-[13px] font-semibold text-[var(--warning-text)]">Your session expired.</strong>
              <span className="text-[12.5px] text-secondary leading-[1.45]">Sign in again to see today's operational queue.</span>
            </div>
            <Button asChild size="sm">
              <a href="/app">Sign in</a>
            </Button>
          </div>
        ) : loadFailed ? (
          <div className="flex items-center justify-between gap-4 mx-7 mb-3 px-3.5 py-3 rounded-lg border bg-[var(--danger-fill)] border-[color-mix(in_srgb,var(--danger-spine)_28%,var(--border-hairline))]">
            <div className="flex flex-col gap-0.5 min-w-0">
              <strong className="text-[13px] font-semibold text-[var(--danger-text)]">Couldn't load your queue.</strong>
              <span className="text-[12.5px] text-secondary leading-[1.45]">{error}</span>
            </div>
            <Button
              type="button"
              size="sm"
              onClick={() => window.location.reload()}
            >
              Retry
            </Button>
          </div>
        ) : null}

        {showSkeleton ? (
          <div className="grid divide-y divide-hairline" aria-hidden="true">
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className="relative animate-pulse p-[18px_28px_18px_44px]">
                {/* Spine placeholder */}
                <span className="absolute bottom-[18px] left-5 top-[18px] w-[3px] rounded-full bg-hover" />
                <div className="flex flex-col gap-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex flex-col gap-1.5">
                      <span className="h-3 w-32 rounded-full bg-hover" />
                      <span className="h-2.5 w-24 rounded-full bg-hover" />
                    </div>
                    <span className="h-5 w-16 rounded-full bg-hover" />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <span className="h-2.5 w-full rounded-full bg-hover" />
                    <span className="h-2.5 w-4/5 rounded-full bg-hover" />
                  </div>
                  <div className="flex justify-between">
                    <span className="h-2.5 w-24 rounded-full bg-hover" />
                    <span className="h-2.5 w-20 rounded-full bg-hover" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : visibleEntries.length === 0 ? (
          // Suppress the empty-state when there's a real failure — the banner
          // above already explains what happened. Showing "no guests on
          // property" beneath an auth/load error mis-narrates the failure as
          // a successful zero-results query.
          authFailed || loadFailed ? null : (
          <div className="py-14 px-7 grid gap-2.5 justify-items-center text-center">
            <div className="w-8 h-8 rounded-lg grid place-items-center bg-hover text-tertiary mb-1">
              <Icon name="info" size={20} />
            </div>
            <h3 className="m-0 text-sm font-[450] leading-[1.3] text-primary">
              {search || propertyFilter || activeFocus !== "all"
                ? "No sessions match this view."
                : TAB_EMPTY_COPY[activeTab].title}
            </h3>
            <p className="m-0 max-w-[36ch] text-tertiary text-[13px] leading-[1.5]">
              {search || propertyFilter || activeFocus !== "all"
                ? "Try widening the filters or clearing search."
                : TAB_EMPTY_COPY[activeTab].copy}
            </p>
          </div>
          )
        ) : (
          <div className="grid divide-y divide-hairline">
            {visibleEntries.map(({ session, classification }) => {
              const tone = lifecycleStageTone(classification.bucket, session.openEscalations);
              const stageLabel = lifecycleStageLabel(session, classification);
              const priorityCard = derivePriorityCard(session, classification, escalations);
              const proactiveIndicator = deriveProactiveIndicator(session);
              const nights = nightsBetween(session.checkIn, session.checkOut);
              const stay = dayOfStay(session.checkIn, session.checkOut);
              const isSelected = selectedId === session.sessionId;
              const detail =
                isSelected && selectedId === session.sessionId ? (selectedDetailQuery.data ?? null) : null;
              const threadTimeline =
                isSelected && selectedId === session.sessionId ? (selectedThreadQuery.data ?? null) : null;
              const isDetailLoading =
                isSelected &&
                selectedId === session.sessionId &&
                (selectedDetailQuery.isLoading || selectedActionsQuery.isLoading);
              const expansionError =
                isSelected && selectedId === session.sessionId
                  ? selectedDetailQuery.error instanceof Error
                    ? selectedDetailQuery.error.message
                    : selectedActionsQuery.error instanceof Error
                      ? selectedActionsQuery.error.message
                      : selectedThreadQuery.error instanceof Error
                        ? selectedThreadQuery.error.message
                        : ""
                  : "";
              // Build a per-session view of the in-flight set: strip the
              // `${sessionId}::` prefix so the expansion sees bare action
              // keys. Only constructed when the row is selected; otherwise
              // we pass an empty set so the unused-row path stays cheap.
              const sessionExecutingKeys = isSelected
                ? new Set(
                    Array.from(executingKeys)
                      .filter((key) => key.startsWith(`${session.sessionId}::`))
                      .map((key) => key.slice(`${session.sessionId}::`.length)),
                  )
                : new Set<string>();
              const sessionActionError =
                isSelected && actionError && actionError.sessionId === session.sessionId
                  ? { key: actionError.key, message: actionError.message }
                  : null;
              const sessionActions =
                isSelected && selectedId === session.sessionId
                  ? (selectedActionsQuery.data?.actions ?? null)
                  : null;
              return (
                <div
                  key={session.sessionId}
                  data-keyboard-nav-id={session.sessionId}
                  className={cn(
                    "relative cursor-pointer p-[18px_28px_18px_44px] transition-colors duration-100",
                    isSelected
                      ? "bg-[color-mix(in_srgb,var(--accent-500)_7%,transparent)] border-y border-[var(--accent-600)]"
                      : "hover:bg-hover",
                  )}
                  role="button"
                  tabIndex={0}
                  aria-expanded={isSelected}
                  onClick={() => handleSelect(session.sessionId)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      handleSelect(session.sessionId);
                    }
                  }}
                >
                  <span
                    aria-hidden="true"
                    className={cn(
                      "absolute left-5 top-[18px] bottom-[18px] w-[3px] rounded-full",
                      tone === "accent" && "bg-accent [box-shadow:0_0_6px_var(--accent-500)]",
                      tone === "warning" && "bg-[var(--warning-500)]",
                      tone === "success" && "bg-[var(--success-500)]",
                      tone === "danger" && "bg-[var(--danger-500)]",
                      (tone === "default" || !["accent","warning","success","danger"].includes(tone)) && "bg-[var(--border-default)]",
                    )}
                  />
                  <div className="flex flex-col gap-2">
                    {/* Line 1: header */}
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex min-w-0 flex-col gap-0.5">
                        <strong className="truncate text-sm font-semibold text-primary">{session.guestName || "Guest"}</strong>
                        <span className="truncate text-xs text-secondary">
                          {session.propertyName || session.propertyCode || "Unknown property"}
                        </span>
                      </div>
                      <div className="flex flex-shrink-0 flex-wrap items-center justify-end gap-1.5">
                        <Badge tone={tone}>{stageLabel}</Badge>
                        <span className="text-xs text-tertiary">{formatAge(session.lastMessageAt)}</span>
                      </div>
                    </div>

                    {/* Line 2: stay context */}
                    <div className="flex flex-col gap-1">
                      <p className="flex gap-1.5 text-xs items-baseline">
                        <span className="flex-shrink-0 font-semibold text-tertiary">Stay</span>
                        <span className="truncate text-secondary">
                          {formatDate(session.checkIn)} → {formatDate(session.checkOut)}
                          {nights ? ` · ${nights} ${nights === 1 ? "night" : "nights"}` : ""}
                          {stay && classification.bucket === "in_stay"
                            ? ` · day ${stay.dayOf} of ${stay.total}`
                            : ""}
                        </span>
                      </p>

                      {proactiveIndicator ? (
                        <p className="flex gap-1.5 text-xs items-baseline">
                          <span className={cn(
                            "flex-shrink-0 font-semibold",
                            proactiveIndicator.tone === "warning" && "text-[var(--warning-600)]",
                            proactiveIndicator.tone === "accent" && "text-accent",
                            proactiveIndicator.tone === "default" && "text-tertiary",
                          )}>
                            {proactiveIndicator.label}
                          </span>
                          <span className="truncate text-secondary">{proactiveIndicator.summary}</span>
                        </p>
                      ) : null}

                      {/* Line 3: priority card (collapses if no rule fires) */}
                      {priorityCard ? (
                        <p className="flex gap-1.5 text-xs items-baseline">
                          <span className={cn(
                            "flex-shrink-0 font-semibold",
                            priorityCard.tone === "danger" && "text-[var(--danger-600)]",
                            priorityCard.tone === "warning" && "text-[var(--warning-600)]",
                            priorityCard.tone === "default" && "text-tertiary",
                          )}>
                            {priorityCard.tone === "danger"
                              ? "!"
                              : priorityCard.tone === "warning"
                                ? "•"
                                : "·"}
                          </span>
                          <span className="truncate text-secondary">{priorityCard.label}</span>
                        </p>
                      ) : null}
                    </div>
                  </div>

                  {isSelected ? (
                    <SessionExpansion
                      session={session}
                      classification={classification}
                      detail={detail}
                      threadTimeline={threadTimeline}
                      actions={sessionActions}
                      executingKeys={sessionExecutingKeys}
                      actionError={sessionActionError}
                      isLoading={isDetailLoading}
                      error={expansionError}
                      onClose={handleClose}
                      onExecuteAction={(actionType) => handleExecuteAction(session.sessionId, actionType)}
                      onReassure={(messageText) => handleReassure(session.sessionId, messageText)}
                      onRequestFeedback={() => handleRequestFeedback(session.sessionId)}
                    />
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </main>
  );
}
