/**
 * Lifecycle window classification for the Today and (future) Arrivals surfaces.
 *
 * The Today surface shows the operator's near-term operational queue across
 * four buckets — pre_arrival (more than 7 days out), arriving (within the
 * next 7 days), in_stay (currently on property), and post_stay (within the
 * last 7 days). The older Arrivals concept has been folded into Today's
 * pre_arrival tab rather than becoming a separate surface.
 *
 * Both surfaces share `/app/api/sessions` as their data source. The window
 * policy — what counts as "near-term" vs "farther out" — lives here, in one
 * place, so neither route needs to embed date math directly.
 *
 * Contract:
 *   - Day of check-in counts as in_stay (the guest may already be at the
 *     property, even if they haven't messaged yet).
 *   - Day of check-out counts as in_stay (they're still here until they
 *     leave). The day after check-out begins post_stay.
 *   - Sessions with no dates fall to out_of_window.
 *   - Backend `phase === 'in_stay'` overrides date math when present, because
 *     the backend has more context (PMS sync, manual overrides) than a date
 *     range alone.
 *
 * Day comparisons are done at UTC midnight to avoid timezone-induced
 * off-by-one errors around midnight in the operator's local zone.
 */

export const TODAY_ARRIVING_WINDOW_DAYS = 7;
export const TODAY_POST_STAY_WINDOW_DAYS = 7;

/**
 * The minimal session shape this module reads. Intentionally not imported
 * from the adapter — we only name the three fields we actually use, which
 * keeps this module standalone and easy to unit-test.
 *
 * `checkIn` and `checkOut` are expected to be ISO date strings ('2026-05-30')
 * or null. Day-only, no time component. This matches what the backend emits
 * for `concierge_guest_sessions.check_in` / `check_out` (DATE columns).
 *
 * `phase` is whatever the backend wrote — typically one of
 * 'pre_arrival' | 'arrival_day' | 'in_stay' | 'departure_day' | 'post_stay'
 * — but we only check for the literal 'in_stay' as an override.
 */
export interface LifecycleSession {
  phase?: string;
  checkIn?: string | null;
  checkOut?: string | null;
}

export type LifecycleBucket =
  | 'pre_arrival'
  | 'arriving'
  | 'in_stay'
  | 'post_stay'
  | 'out_of_window';

export interface LifecycleClassification {
  bucket: LifecycleBucket;
  /** Days from today to check-in. Present only when bucket === 'pre_arrival' or 'arriving'. >= 1. */
  daysUntilCheckIn?: number;
  /** Days from check-out to today. Present only when bucket === 'post_stay'. >= 1. */
  daysSinceCheckOut?: number;
}

/**
 * Parse an ISO date string ('2026-05-30') to a UTC-midnight Date.
 * Returns null for null, undefined, or malformed input.
 */
function parseDateUtc(value: string | null | undefined): Date | null {
  if (!value) return null;
  // Accept either 'YYYY-MM-DD' or a full ISO timestamp; in both cases the
  // calendar date portion is what we want, anchored at UTC midnight.
  const datePart = value.length >= 10 ? value.slice(0, 10) : value;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(datePart);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null;
  const ms = Date.UTC(year, month - 1, day);
  if (!Number.isFinite(ms)) return null;
  return new Date(ms);
}

/**
 * Floor a Date to its UTC midnight. Used to make "today" comparable to
 * a date-only field without time-of-day affecting the comparison.
 */
function floorToUtcDay(now: Date): Date {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}

/**
 * Whole-day difference between two UTC-midnight Dates. `b - a`, in days.
 * Both inputs must already be UTC-midnight (use floorToUtcDay / parseDateUtc).
 */
function daysBetween(a: Date, b: Date): number {
  const MS_PER_DAY = 86400000;
  return Math.round((b.getTime() - a.getTime()) / MS_PER_DAY);
}

/**
 * Classify a session for the Today surface.
 *
 * Returns the bucket the session belongs to and, where applicable, the
 * day distance to or from the relevant lifecycle event.
 *
 * `now` is optional and defaults to the real current time. Passing it
 * explicitly is useful for tests and for rendering a stable snapshot
 * across a long-lived page session.
 */
export function classifyForToday(
  session: LifecycleSession,
  now: Date = new Date(),
): LifecycleClassification {
  const today = floorToUtcDay(now);
  const checkIn = parseDateUtc(session.checkIn);
  const checkOut = parseDateUtc(session.checkOut);

  // Phase override: backend says in_stay → trust it. Backend has PMS sync,
  // manual operator overrides, and other context that day math doesn't see.
  if (session.phase === 'in_stay') {
    return { bucket: 'in_stay' };
  }

  // Date-based in_stay: today is within [checkIn, checkOut]. Check-in day
  // and check-out day both count as in_stay; the day after check-out is
  // the first post_stay day.
  if (checkIn && checkOut) {
    const inStayStart = checkIn;
    const postStayStart = new Date(checkOut.getTime() + 86400000);
    if (today >= inStayStart && today < postStayStart) {
      return { bucket: 'in_stay' };
    }
  }

  // Arrival lanes: check-in is in the future. Near-term arrivals land in the
  // arriving bucket; farther-out bookings now stay visible in pre_arrival.
  if (checkIn) {
    const daysUntilCheckIn = daysBetween(today, checkIn);
    if (daysUntilCheckIn >= 1 && daysUntilCheckIn <= TODAY_ARRIVING_WINDOW_DAYS) {
      return { bucket: 'arriving', daysUntilCheckIn };
    }
    if (daysUntilCheckIn > TODAY_ARRIVING_WINDOW_DAYS) {
      return { bucket: 'pre_arrival', daysUntilCheckIn };
    }
  }

  // Post-stay: check-out was in the past, within the window. The day after
  // check-out is day 1 of post_stay.
  if (checkOut) {
    const daysSinceCheckOut = daysBetween(checkOut, today);
    if (daysSinceCheckOut >= 1 && daysSinceCheckOut <= TODAY_POST_STAY_WINDOW_DAYS) {
      return { bucket: 'post_stay', daysSinceCheckOut };
    }
  }

  return { bucket: 'out_of_window' };
}

/**
 * Reserved stub from the older Arrivals concept. Farther-out bookings now
 * live in Today's pre_arrival tab instead of a separate Arrivals surface.
 * Kept throwing so no one accidentally revives a second lifecycle surface.
 *
 * Throwing here means any premature import will surface immediately at the
 * call site instead of silently returning a wrong bucket.
 */
export function classifyForArrivals(
  _session: LifecycleSession,
  _now: Date = new Date(),
): LifecycleClassification {
  throw new Error(
    'classifyForArrivals is not implemented. Farther-out bookings now live ' +
      "in Today's pre_arrival tab. If you need Today bucketing, call " +
      'classifyForToday instead of reviving a second Arrivals surface.',
  );
}
