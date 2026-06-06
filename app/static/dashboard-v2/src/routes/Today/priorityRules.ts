import type { LifecycleClassification } from "../../shared/lifecycle/windows";
import type { normalizeSessionsList } from "../../adapters/index.js";

import { MS_PER_DAY, formatAge, parseDateUtc, todayUtc } from "./lifecycleLabels";

/**
 * priorityRules — derives a single "priority card" for each Today row.
 *
 * Each rule is a pure function from (session, classification, escalations)
 * to a card payload or null. Rules fire in priority order; the first rule
 * that returns non-null wins. The row's third line renders that card; if
 * every rule returns null, the line collapses and the row is two lines.
 *
 * The rule set is intentionally small (five rules) and operationally
 * meaningful — these are the things an operator would want to know about
 * a session in the first five minutes of their day. Each rule's logic is
 * derivable from list-level session fields plus the escalations join
 * (rule 1 only), so the priority card doesn't require sessions.detail.
 *
 * Adding a rule:
 *   1. Add a new rulePr*_name function below.
 *   2. Append it to PRIORITY_RULES in the desired priority order.
 *   3. That's it — the route picks it up automatically.
 *
 * Thresholds (1h for escalation staleness, 30m for vendor staleness,
 * 2 days for imminent arrival, 1 day for checkout-due) are v1 guesses.
 * If real Beach Habitats data shows different operator urgency curves,
 * tune the constants here.
 */

type Session = ReturnType<typeof normalizeSessionsList>["sessions"][number];

// Escalation is shared between the route's fetch effect and the rules.
// The route normalizes raw escalation rows into this shape at the fetch
// boundary; rules only ever read these typed fields.
export type Escalation = {
  ticketId: string;
  sessionId: string;
  sessionToken: string;
  status: string;
  priority: string;
  guestUpdatedAt: string | null;
  guestUpdateStatus: string;
  createdAt: string | null;
};

export type PriorityCardTone = "danger" | "warning" | "accent" | "default";

export type PriorityCard = {
  label: string;
  tone: PriorityCardTone;
};

type PriorityRule = (
  session: Session,
  classification: LifecycleClassification,
  escalations: Escalation[] | null,
) => PriorityCard | null;

// Rule 1: open escalation with stale guest update. The session has open
// escalations and the most-recent escalation either has no recorded guest
// update or the last update was >1h ago. The "first five minutes" case.
const rulePr1_escalationStale: PriorityRule = (session, _classification, escalations) => {
  if (session.openEscalations <= 0) return null;
  if (!escalations) {
    // Escalation join hasn't loaded yet. Don't fabricate staleness — fall
    // through to a generic "open escalation" card so the operator still
    // sees the urgency without false precision.
    return {
      label: `${session.openEscalations} open ${session.openEscalations === 1 ? "escalation" : "escalations"}`,
      tone: "danger",
    };
  }
  const sessionEscalations = escalations.filter(
    (e) => e.sessionId === session.sessionId || e.sessionToken === session.token,
  );
  if (sessionEscalations.length === 0) {
    // openEscalations count from the session disagrees with the escalations
    // list — most likely because the escalations endpoint returned a
    // filtered slice. Show the count without staleness rather than nothing.
    return {
      label: `${session.openEscalations} open ${session.openEscalations === 1 ? "escalation" : "escalations"}`,
      tone: "danger",
    };
  }
  // Take the freshest open escalation. "Stale" means no guest update or
  // last update >1h ago. Threshold is intentionally generous in v1 — it
  // catches the "I got distracted and forgot to update the guest" case
  // without flagging escalations that were just opened.
  const freshest = sessionEscalations.reduce<Escalation | null>((latest, current) => {
    if (!latest) return current;
    const latestTime = new Date(latest.createdAt || 0).getTime();
    const currentTime = new Date(current.createdAt || 0).getTime();
    return currentTime > latestTime ? current : latest;
  }, null);
  if (!freshest) return null;
  const lastUpdate = freshest.guestUpdatedAt;
  if (!lastUpdate) {
    return { label: "Open escalation · guest not yet updated", tone: "danger" };
  }
  const ageMs = Date.now() - new Date(lastUpdate).getTime();
  if (!Number.isFinite(ageMs) || ageMs < 60 * 60 * 1000) return null; // fresh enough
  return {
    label: `Open escalation · last guest update ${formatAge(lastUpdate)} ago`,
    tone: "danger",
  };
};

// Rule 2: stuck vendor / work order. A vendor is recommended or contacted
// but hasn't progressed in a while. Reads from workflow.vendor which the
// backend populates as { dispatch_state, name, eta_minutes, last_updated_at,
// status_changed_at, ... }. We treat 'recommended' and 'contacted' as
// "potentially stuck" states; 'en_route' / 'on_site' / 'completed' are
// healthy. Staleness threshold: 30m without an update.
const rulePr2_stuckVendor: PriorityRule = (session, _classification, _escalations) => {
  const vendor = (session.workflow as { vendor?: Record<string, unknown> } | undefined)?.vendor;
  if (!vendor || typeof vendor !== "object") return null;
  const dispatchState = String((vendor as { dispatch_state?: string }).dispatch_state || "").toLowerCase();
  if (!dispatchState) return null;
  const stuckStates = new Set(["recommended", "contacted", "coordination_required"]);
  if (!stuckStates.has(dispatchState)) return null;
  const lastUpdate =
    (vendor as { last_updated_at?: string | null }).last_updated_at ||
    (vendor as { status_changed_at?: string | null }).status_changed_at ||
    null;
  if (lastUpdate) {
    const ageMs = Date.now() - new Date(lastUpdate).getTime();
    if (Number.isFinite(ageMs) && ageMs < 30 * 60 * 1000) return null; // recently moved
  }
  const vendorName = String((vendor as { name?: string }).name || "Vendor");
  const stateLabel = dispatchState.replace(/_/g, " ");
  return { label: `Stuck work order · ${vendorName} ${stateLabel}`, tone: "warning" };
};

// Rule 3: welcome missing + imminent arrival. Arriving session, check-in
// within 2 days, welcome message not yet sent. "Imminent" is intentionally
// narrow (2 days vs. the 7-day window) because welcomes for arrivals 5 days
// out aren't actually urgent — they're scheduled work.
const rulePr3_welcomeMissingImminent: PriorityRule = (session, classification, _escalations) => {
  if (classification.bucket !== "arriving") return null;
  if (session.welcomeSent) return null;
  const days = classification.daysUntilCheckIn ?? 99;
  if (days > 2) return null;
  const arrivalPhrase =
    days === 0 ? "arrives today" : days === 1 ? "arrives tomorrow" : `arrives in ${days} days`;
  return { label: `Welcome not sent · ${arrivalPhrase}`, tone: "warning" };
};

// Rule 4: checkout reminder due. In-stay session, check-out within 1 day,
// reminder not yet sent. This is the "first five minutes of the day" case
// for the in-stay tab.
const rulePr4_checkoutReminderDue: PriorityRule = (session, classification, _escalations) => {
  if (classification.bucket !== "in_stay") return null;
  if (session.checkoutReminderSent) return null;
  const checkOut = parseDateUtc(session.checkOut);
  if (!checkOut) return null;
  const daysUntilCheckOut = Math.round((checkOut.getTime() - todayUtc().getTime()) / MS_PER_DAY);
  if (daysUntilCheckOut > 1) return null;
  if (daysUntilCheckOut < 0) return null; // already checked out, post_stay will handle it
  const phrase = daysUntilCheckOut === 0 ? "checks out today" : "checks out tomorrow";
  return { label: `Checkout reminder due · ${phrase}`, tone: "warning" };
};

// Rule 5: turnover blocked. Post-stay session where the turnover workflow
// hasn't reached ready_for_next_guest. The session is occupying a unit that
// can't be re-booked until cleaning completes.
const rulePr5_turnoverBlocked: PriorityRule = (session, classification, _escalations) => {
  if (classification.bucket !== "post_stay") return null;
  if (session.workflow.turnover?.readyForNextGuest) return null;
  const status = String(session.workflow.turnover?.status || "").toLowerCase();
  // If the backend says explicitly ready/archived, trust it even if the bool
  // flag didn't update for some reason.
  if (status === "ready" || status === "archived") return null;
  const statusLabel = status ? status.replace(/_/g, " ") : "pending";
  return { label: `Turnover blocked · ${statusLabel}`, tone: "warning" };
};

const PRIORITY_RULES: readonly PriorityRule[] = [
  rulePr1_escalationStale,
  rulePr2_stuckVendor,
  rulePr3_welcomeMissingImminent,
  rulePr4_checkoutReminderDue,
  rulePr5_turnoverBlocked,
] as const;

export function derivePriorityCard(
  session: Session,
  classification: LifecycleClassification,
  escalations: Escalation[] | null,
): PriorityCard | null {
  for (const rule of PRIORITY_RULES) {
    const card = rule(session, classification, escalations);
    if (card) return card;
  }
  return null;
}
