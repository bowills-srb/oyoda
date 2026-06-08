/*
  Time is anchored to a fixed "now" so the mock story reads the same every
  time it's opened — Lanier's morning check-in. When this is wired to the
  backend, swap NOW for `new Date()`.
*/
export const NOW = new Date("2026-06-08T09:42:00");

const MIN = 60 * 1000;
const HOUR = 60 * MIN;

/** "just now", "14m ago", "2h ago", or a clock time for older items. */
export function relative(iso: string, now: Date = NOW): string {
  const then = new Date(iso);
  const diff = now.getTime() - then.getTime();
  if (diff < 2 * MIN) return "just now";
  if (diff < HOUR) return `${Math.round(diff / MIN)}m ago`;
  if (diff < 6 * HOUR) return `${Math.round(diff / HOUR)}h ago`;
  return clock(iso);
}

/** "9:42 AM" */
export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Which side of the morning an item falls on, for the feed's section breaks. */
export function dayPart(iso: string): "Overnight" | "This morning" {
  return new Date(iso).getHours() < 7 ? "Overnight" : "This morning";
}
