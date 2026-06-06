import type {
  LifecycleBucket,
  LifecycleClassification,
} from "../../shared/lifecycle/windows";
import type { normalizeSessionsList } from "../../adapters/index.js";

/**
 * lifecycleLabels — pure date and lifecycle-stage formatting helpers for
 * the Today route.
 *
 * Everything here is a pure function over primitive inputs (or the
 * normalized session row shape). No React, no fetches, no state. The
 * route and SessionExpansion both consume these.
 *
 * Date handling note: everywhere we compare check-in / check-out against
 * "today" we go through parseDateUtc + todayUtc so the comparison is at
 * UTC midnight on both sides. This avoids subtle timezone bugs where a
 * stay ending at 11am local time was being classified as already
 * post-stay because the browser's `new Date()` rolled over.
 */

type Session = ReturnType<typeof normalizeSessionsList>["sessions"][number];

export const MS_PER_DAY = 86400000;

export function parseDateUtc(value: string | null | undefined): Date | null {
  if (!value) return null;
  const datePart = value.length >= 10 ? value.slice(0, 10) : value;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(datePart);
  if (!match) return null;
  const ms = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isFinite(ms) ? new Date(ms) : null;
}

export function todayUtc(): Date {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}

export function formatAge(timestamp?: string | null): string {
  if (!timestamp) return "—";
  const deltaMs = Date.now() - new Date(timestamp).getTime();
  if (!Number.isFinite(deltaMs) || deltaMs < 0) return "Now";
  const mins = Math.round(deltaMs / 60000);
  if (mins < 1) return "Now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

// Formats an ISO date string like '2026-05-30' as "May 30". Date-only,
// no timezone shift. Returns "—" for missing input.
export function formatDate(value: string | null): string {
  const parsed = parseDateUtc(value);
  if (!parsed) return "—";
  return parsed.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function nightsBetween(
  checkIn: string | null,
  checkOut: string | null,
): number | null {
  const inDate = parseDateUtc(checkIn);
  const outDate = parseDateUtc(checkOut);
  if (!inDate || !outDate) return null;
  const diff = Math.round((outDate.getTime() - inDate.getTime()) / MS_PER_DAY);
  return diff > 0 ? diff : null;
}

export function dayOfStay(
  checkIn: string | null,
  checkOut: string | null,
): { dayOf: number; total: number } | null {
  const inDate = parseDateUtc(checkIn);
  const outDate = parseDateUtc(checkOut);
  if (!inDate || !outDate) return null;
  const today = todayUtc();
  const total = Math.max(1, Math.round((outDate.getTime() - inDate.getTime()) / MS_PER_DAY));
  const dayOf = Math.max(1, Math.round((today.getTime() - inDate.getTime()) / MS_PER_DAY) + 1);
  if (dayOf > total) return null;
  return { dayOf, total };
}

export function lifecycleStageLabel(
  session: Session,
  classification: LifecycleClassification,
): string {
  if (classification.bucket === "pre_arrival") {
    return `Arrives ${formatDate(session.checkIn)}`;
  }
  if (classification.bucket === "arriving") {
    const days = classification.daysUntilCheckIn ?? 0;
    if (days === 1) return "Arrives tomorrow";
    return `Arrives in ${days} days`;
  }
  if (classification.bucket === "in_stay") {
    const stay = dayOfStay(session.checkIn, session.checkOut);
    return stay ? `Day ${stay.dayOf} of ${stay.total}` : "In stay";
  }
  if (classification.bucket === "post_stay") {
    const days = classification.daysSinceCheckOut ?? 0;
    if (days === 1) return "Checked out yesterday";
    return `Checked out ${days} days ago`;
  }
  return "—";
}

export type LifecycleStageTone = "accent" | "warning" | "success" | "danger" | "default";

export function lifecycleStageTone(
  bucket: LifecycleBucket,
  openEscalations: number,
): LifecycleStageTone {
  if (openEscalations > 0) return "danger";
  if (bucket === "in_stay") return "accent";
  if (bucket === "arriving") return "warning";
  if (bucket === "pre_arrival") return "default";
  if (bucket === "post_stay") return "success";
  return "default";
}
