import type { LifecycleClassification } from "../../shared/lifecycle/windows";
import type { normalizeSessionsList } from "../../adapters/index.js";

import { MS_PER_DAY, parseDateUtc, todayUtc } from "./lifecycleLabels";

/**
 * focusPredicates — per-tab focus chip filtering for the Today route.
 *
 * Each tab has its own set of focus chips (an "all" chip plus 2-3
 * operational filters). A predicate per tab answers "does this session
 * match the focus chip?" Predicates are pure over (session, classification,
 * focus) and don't reach into fetched detail — they run on the list
 * payload alone, so chip counts and filtering work without expansion.
 *
 * Adding a chip:
 *   1. Extend the appropriate Focus type union below.
 *   2. Add it to FOCUSES_BY_TAB for the right tab.
 *   3. Add a human label to FOCUS_LABELS.
 *   4. Add a predicate branch to the matching matches*Focus function.
 *
 * Tab semantics note: a focus chip is meaningful only on the tab that
 * owns it. `escalations` is on in_stay, not pre_arrival, because the
 * "first five minutes" reaction to an open escalation is for guests
 * currently on property. If a stale URL has a focus that doesn't apply
 * to the current tab, the route's coerceFocus falls back to "all".
 */

type Session = ReturnType<typeof normalizeSessionsList>["sessions"][number];

export type TodayTab = "pre_arrival" | "arriving" | "in_stay" | "post_stay";

// Focus chip identifiers per tab. "all" is the no-filter passthrough.
//
// Note on `arriving_soon`: the lifecycle classifier intentionally treats the
// day of check-in as `in_stay` (a guest arriving today is already on the
// operator's plate via the in_stay tab on day 1 of their stay). So
// `arriving_soon` filters arriving sessions for tomorrow's arrivals
// (daysUntilCheckIn === 1), which matches the operator's morning workflow:
// today's arrivals show up in in_stay tab; tomorrow's arrivals show up
// here under `arriving_soon` so welcomes and prep can happen now.
export type PreArrivalFocus = "all" | "needs_welcome" | "unbound";
export type ArrivingFocus = "all" | "arriving_soon" | "needs_welcome" | "unbound";
export type InStayFocus = "all" | "escalations" | "stuck_work_orders" | "checkout_due";
export type PostStayFocus = "all" | "turnover_blocked" | "review_window";
export type AnyFocus = PreArrivalFocus | ArrivingFocus | InStayFocus | PostStayFocus;

// Per-tab focus chip set, source of truth for URL coercion and chip
// rendering. Adding a new chip is a one-line change here plus a predicate
// branch below and a label entry.
export const FOCUSES_BY_TAB: Record<TodayTab, readonly AnyFocus[]> = {
  pre_arrival: ["all", "needs_welcome", "unbound"],
  arriving: ["all", "arriving_soon", "needs_welcome", "unbound"],
  in_stay: ["all", "escalations", "stuck_work_orders", "checkout_due"],
  post_stay: ["all", "turnover_blocked", "review_window"],
};

export const FOCUS_LABELS: Record<AnyFocus, string> = {
  all: "All",
  arriving_soon: "Arriving soon",
  needs_welcome: "Needs welcome",
  unbound: "Unbound",
  escalations: "Escalations",
  stuck_work_orders: "Stuck work orders",
  checkout_due: "Checkout reminder due",
  turnover_blocked: "Turnover blocked",
  review_window: "Review window",
};

export function matchesPreArrivalFocus(
  session: Session,
  _classification: LifecycleClassification,
  focus: PreArrivalFocus,
): boolean {
  if (focus === "all") return true;
  if (focus === "needs_welcome") return !session.welcomeSent;
  if (focus === "unbound") return !session.propertyCode || !session.hasBookingContext;
  return true;
}

export function matchesArrivingFocus(
  session: Session,
  classification: LifecycleClassification,
  focus: ArrivingFocus,
): boolean {
  if (focus === "all") return true;
  // `arriving_soon` = tomorrow's arrivals. The classifier puts today's
  // arrivals (day of check-in) in the in_stay bucket, so the smallest
  // daysUntilCheckIn this can ever see is 1 (tomorrow).
  if (focus === "arriving_soon") return classification.daysUntilCheckIn === 1;
  if (focus === "needs_welcome") return !session.welcomeSent;
  if (focus === "unbound") return !session.propertyCode || !session.hasBookingContext;
  return true;
}

export function matchesInStayFocus(session: Session, focus: InStayFocus): boolean {
  if (focus === "all") return true;
  if (focus === "escalations") return session.openEscalations > 0;
  if (focus === "stuck_work_orders") {
    const vendor = (session.workflow as { vendor?: Record<string, unknown> } | undefined)?.vendor;
    if (!vendor || typeof vendor !== "object") return false;
    const dispatchState = String((vendor as { dispatch_state?: string }).dispatch_state || "").toLowerCase();
    return ["recommended", "contacted", "coordination_required"].includes(dispatchState);
  }
  if (focus === "checkout_due") {
    if (session.checkoutReminderSent) return false;
    const checkOut = parseDateUtc(session.checkOut);
    if (!checkOut) return false;
    const days = Math.round((checkOut.getTime() - todayUtc().getTime()) / MS_PER_DAY);
    return days >= 0 && days <= 1;
  }
  return true;
}

export function matchesPostStayFocus(session: Session, focus: PostStayFocus): boolean {
  if (focus === "all") return true;
  if (focus === "turnover_blocked") {
    if (session.workflow.turnover?.readyForNextGuest) return false;
    const status = String(session.workflow.turnover?.status || "").toLowerCase();
    return status !== "ready" && status !== "archived";
  }
  if (focus === "review_window") {
    // Review window: post-stay sessions in the first 3 days after check-out
    // where the operator might still nudge for a review. A v1 approximation
    // pending a real review-state field.
    const checkOut = parseDateUtc(session.checkOut);
    if (!checkOut) return false;
    const days = Math.round((todayUtc().getTime() - checkOut.getTime()) / MS_PER_DAY);
    return days >= 1 && days <= 3;
  }
  return true;
}

export function matchesFocus(
  session: Session,
  classification: LifecycleClassification,
  tab: TodayTab,
  focus: AnyFocus,
): boolean {
  if (tab === "pre_arrival") {
    return matchesPreArrivalFocus(session, classification, focus as PreArrivalFocus);
  }
  if (tab === "arriving") {
    return matchesArrivingFocus(session, classification, focus as ArrivingFocus);
  }
  if (tab === "in_stay") return matchesInStayFocus(session, focus as InStayFocus);
  if (tab === "post_stay") return matchesPostStayFocus(session, focus as PostStayFocus);
  return true;
}
