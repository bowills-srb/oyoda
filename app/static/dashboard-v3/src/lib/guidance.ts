import type { GuidanceRule, GuidanceScope } from "../types";

/*
  The memory behind the teaching loop. Rules persist to localStorage so the
  employee "remembers" what Lanier has taught it across sessions. When this is
  wired to the backend, swap load/save for the `settings/ai-guidance` endpoints.
*/

const KEY = "oyvoda.v3.guidance";

export const ALL_PROPERTIES: GuidanceScope = "*";

/** Things Lanier has already taught me — so the portfolio starts with memory. */
const SEED: GuidanceRule[] = [
  {
    id: "seed-spend-cap",
    scope: ALL_PROPERTIES,
    instruction:
      "Don't spend more than $500 on a repair without my approval. Line it up, then ask me first if it's higher.",
    createdAt: "2026-05-12T16:00:00",
    source: "You set this earlier",
  },
  {
    id: "seed-returning-discount",
    scope: ALL_PROPERTIES,
    instruction:
      "For returning guests with two or more five-star stays, you can offer up to 10% off on your own. Anything deeper, check with me.",
    createdAt: "2026-04-28T14:30:00",
    source: "You set this earlier",
  },
  {
    id: "seed-checkin-timing",
    scope: "The Lookout",
    instruction:
      "At The Lookout, only promise a check-in time once the turnover is marked ready — never before.",
    createdAt: "2026-05-30T09:15:00",
    source: "You taught me on a check-in",
  },
];

export function loadRules(): GuidanceRule[] {
  if (typeof window === "undefined") return SEED;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) {
      window.localStorage.setItem(KEY, JSON.stringify(SEED));
      return SEED;
    }
    return JSON.parse(raw) as GuidanceRule[];
  } catch {
    return SEED;
  }
}

export function saveRules(rules: GuidanceRule[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(rules));
  } catch {
    /* storage unavailable — keep working in memory */
  }
}

export function scopeLabel(scope: GuidanceScope): string {
  return scope === ALL_PROPERTIES ? "Every property" : scope;
}

/** Resolve the rules that actually govern a given item, in current state. */
export function rulesByIds(
  ids: string[] | undefined,
  rules: GuidanceRule[],
): GuidanceRule[] {
  if (!ids || ids.length === 0) return [];
  return rules.filter((r) => ids.includes(r.id));
}
