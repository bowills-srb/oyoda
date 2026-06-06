/**
 * Properties route — client-side gap grouping by knowledgeRef.
 *
 * The /app/api/kb-gaps endpoint does not accept a property filter
 * (verified in Contract 3). Each gap row carries a `property` string
 * sourced from `property_external_id` server-side. v2 groups client-side.
 *
 * Per Contract 4's runtime finding for Beach Habitats: some related gaps
 * remain unbound (blank property_external_id). These gaps are intentionally
 * dropped by the grouping — they would otherwise show up in every
 * property's list, or in none, depending on how we coerced the blank.
 * The cleaner choice is to omit them and note the floor in UI copy:
 * "Gaps tagged to this property" rather than "All gaps for this property".
 *
 * A future commit can add an "Unbound gaps" sidebar that surfaces the
 * dropped rows so operators can re-bind them. Out of scope for commit A.
 */

import type { PropertyGap } from "./types";

/**
 * Build a lookup index of gaps keyed by their property reference.
 * Compute once on load, look up O(1) per row.
 */
export function buildPropertyGapIndex(
  allGaps: PropertyGap[],
): Record<string, PropertyGap[]> {
  const index: Record<string, PropertyGap[]> = {};
  for (const gap of allGaps) {
    const key = (gap.property || "").trim();
    if (!key) continue;        // intentionally drop unbound gaps; see note above
    if (key === "All Properties") continue;  // portfolio-scope gaps are not per-property
    if (!index[key]) index[key] = [];
    index[key].push(gap);
  }
  return index;
}

/**
 * Look up gaps for a single property's knowledgeRef.
 * Returns an empty array when the property has no tagged gaps — callers
 * should treat zero as "no gaps tagged", not "no gaps".
 */
export function gapsForProperty(
  index: Record<string, PropertyGap[]>,
  knowledgeRef: string,
): PropertyGap[] {
  if (!knowledgeRef) return [];
  return index[knowledgeRef] || [];
}

/**
 * Count of unique property references that have at least one tagged gap.
 * Used by the top-of-page metric strip — "X properties have open gaps".
 */
export function propertiesWithGaps(
  index: Record<string, PropertyGap[]>,
): number {
  return Object.keys(index).length;
}

/**
 * Count of gaps that were dropped because they had no property reference.
 * Surfaced as a small advisory under the metric strip so operators know
 * the per-property numbers are a floor, not a ceiling.
 */
export function unboundGapCount(allGaps: PropertyGap[]): number {
  let count = 0;
  for (const gap of allGaps) {
    const key = (gap.property || "").trim();
    if (!key) count += 1;
  }
  return count;
}
