import type { SessionDetail } from "../../domain/today/types";

/**
 * timeline — derives a compact lifecycle strip from the detail payload.
 *
 * Every dot is a meaningful operational touch (welcome sent, escalation
 * opened, vendor dispatched, etc.) ordered by time. Each dot has a tone
 * the row uses to render the right color.
 *
 * Dot sources, in order of contribution:
 *   - journey flags (welcome, check-in reminder, etc.) — boolean + timestamp
 *   - stay events (housekeeping_arrived, vendor_completed, etc.) — timestamped
 *   - open escalations — alert-tone, by createdAt
 *   - turnover lifecycle (started, ready) — by phase timestamp
 *
 * All sources collapse into a single time-ordered TimelineDot[] that
 * SessionExpansion renders horizontally. Dots without timestamps land at
 * the end since they're state-derived rather than time-stamped (e.g. a
 * welcome that was sent without a recorded timestamp).
 *
 * The strip is intentionally read-only — no click-to-act in this step.
 * Action affordances on individual dots land in step 6.
 */

export type TimelineDotTone = "done" | "alert" | "pending";

export type TimelineDot = {
  key: string;
  label: string;
  occurredAt: string | null;
  tone: TimelineDotTone;
};

// Friendly label per known event_type. Unknown event types fall back to a
// snake-case-to-Title-Case conversion so backend-added events surface
// reasonably without a frontend change.
const TIMELINE_EVENT_LABELS: Record<string, string> = {
  guest_checked_out: "Guest checked out",
  housekeeping_arrived: "Housekeeping arrived",
  housekeeping_completed: "Housekeeping completed",
  feedback_requested: "Feedback requested",
  linen_pickup_started: "Linen pickup",
  linen_returned: "Linen returned",
  property_ready: "Property ready",
  documentation_started: "Documentation started",
  documentation_completed: "Documentation completed",
  walkthrough_started: "Walkthrough started",
  walkthrough_completed: "Walkthrough completed",
  vendor_arrived: "Vendor arrived",
  vendor_completed: "Vendor completed",
};

export function humanizeEventType(eventType: string): string {
  if (TIMELINE_EVENT_LABELS[eventType]) return TIMELINE_EVENT_LABELS[eventType];
  if (!eventType) return "Event";
  return eventType
    .split("_")
    .map((part) => (part ? part[0].toUpperCase() + part.slice(1) : part))
    .join(" ");
}

export function deriveTimeline(detail: SessionDetail | null): TimelineDot[] {
  if (!detail) return [];
  const dots: TimelineDot[] = [];
  const journey = detail.journey;
  const turnover = detail.workflow.turnover;

  if (journey.welcomeSent) {
    dots.push({
      key: "welcome",
      label: "Welcome sent",
      occurredAt: journey.welcomeSentAt,
      tone: "done",
    });
  }
  if (journey.checkinReminderSent) {
    dots.push({
      key: "checkin_reminder",
      label: "Check-in reminder sent",
      occurredAt: journey.checkinReminderSentAt,
      tone: "done",
    });
  }
  if (journey.checkoutReminderSent) {
    dots.push({
      key: "checkout_reminder",
      label: "Check-out reminder sent",
      occurredAt: journey.checkoutReminderSentAt,
      tone: "done",
    });
  }
  if (journey.extendOfferSent) {
    dots.push({
      key: "extend_offer",
      label: "Extend offer sent",
      occurredAt: journey.extendOfferSentAt,
      tone: "done",
    });
  }

  // Operational events from stay_event_service — each one is a real
  // "something happened" record (housekeeping arrived, vendor completed,
  // etc.). Render as done dots ordered by occurredAt; failed/blocked
  // statuses surface as alert dots so the operator sees them as problems.
  for (const event of detail.events) {
    dots.push({
      key: `event:${event.stayEventId}`,
      label: humanizeEventType(event.eventType),
      occurredAt: event.occurredAt,
      tone: event.status === "failed" || event.status === "blocked" ? "alert" : "done",
    });
  }

  // Open escalations are alert dots ordered by creation time.
  for (const escalation of detail.openEscalations) {
    if (escalation.status === "resolved") continue;
    dots.push({
      key: `escalation:${escalation.ticketId}`,
      label: `Escalation opened·${escalation.reason || "unknown"}`,
      occurredAt: escalation.createdAt,
      tone: "alert",
    });
  }

  // Turnover lifecycle dots. Started + ready, when present.
  if (turnover.startedAt) {
    dots.push({
      key: "turnover_started",
      label: "Turnover started",
      occurredAt: turnover.startedAt,
      tone: "done",
    });
  }
  if (turnover.readyForNextGuest && turnover.readyAt) {
    dots.push({
      key: "turnover_ready",
      label: "Turnover ready",
      occurredAt: turnover.readyAt,
      tone: "done",
    });
  }

  // Sort by occurredAt ascending. Dots without timestamps land at the end
  // (they're typically state-derived rather than time-stamped, e.g. a
  // welcome that was sent without a recorded timestamp).
  dots.sort((a, b) => {
    const aTime = a.occurredAt ? new Date(a.occurredAt).getTime() : Number.POSITIVE_INFINITY;
    const bTime = b.occurredAt ? new Date(b.occurredAt).getTime() : Number.POSITIVE_INFINITY;
    return aTime - bTime;
  });

  return dots;
}
