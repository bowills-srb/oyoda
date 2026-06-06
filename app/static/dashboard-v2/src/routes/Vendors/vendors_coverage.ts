import type { IconName } from "../../shared/Icon";
import type { VendorCategory, Vendor } from "../../domain/vendors/types";

/**
 * Vendors capability-map model.
 *
 * The categories ARE the surface spine — the full set of issue types the AI
 * can route, independent of whether any vendor fills them. A zero-vendor
 * system still renders the complete capability map; "Not set up" is a calm,
 * first-class state, not an error. This is the core constraint: the system
 * operates with no vendors added, so the surface must read as healthy when
 * empty.
 *
 * workflow_group splits the map into two lanes:
 *   dispatch   → maintenance responders (plumbing, HVAC, electrical, …)
 *   experience → recreational / guest-experience vendors (beach gear, chef, …)
 * Anything else falls into experience as the catch-all, matching the
 * normalize.ts default of "experience".
 */

export type LaneKey = "dispatch" | "experience";

export const LANE_META: Record<LaneKey, { label: string; icon: IconName; emptyCopy: string }> = {
  dispatch: {
    label: "Dispatch · maintenance",
    icon: "settings",
    emptyCopy:
      "Maintenance responders the AI can dispatch when a guest reports an issue. None added yet — issues route to you until you add one.",
  },
  experience: {
    label: "Experience · recreational",
    icon: "spark",
    emptyCopy:
      "Optional recreational and guest-experience vendors — beach gear, rentals, chefs, tours. Add when guests start asking.",
  },
};

export function laneOf(group: string): LaneKey {
  return group === "dispatch" ? "dispatch" : "experience";
}

export type CategoryCoverage = {
  category: VendorCategory;
  vendorCount: number;
  /** True when at least one active vendor is filed under this category. */
  covered: boolean;
  /** Any active vendor in this category marked after-hours available. */
  afterHours: boolean;
  /** Best (lowest) response SLA across this category's vendors, in minutes. */
  bestSlaMinutes: number | null;
  /** Count of properties this category can reach — null when portfolio-wide. */
  scopedPropertyCount: number | null;
};

/**
 * Derive per-category coverage from the category list + the vendor list.
 *
 * Everything here is real, client-side data: vendorCount comes off the
 * category, after-hours / SLA / scope come off each vendor's
 * operationalMetadata and applyScope. No projected or invented metric.
 */
export function deriveCoverage(
  categories: VendorCategory[],
  vendors: Vendor[],
): CategoryCoverage[] {
  const bySlug = new Map<string, Vendor[]>();
  for (const vendor of vendors) {
    if (!vendor.active) continue;
    const list = bySlug.get(vendor.categorySlug) || [];
    list.push(vendor);
    bySlug.set(vendor.categorySlug, list);
  }

  return categories.map((category) => {
    const filed = bySlug.get(category.slug) || [];
    const afterHours = filed.some((v) => v.operationalMetadata.afterHoursAvailable);

    const slas = filed
      .map((v) => v.operationalMetadata.responseSlaMinutes)
      .filter((n) => Number.isFinite(n) && n > 0);
    const bestSlaMinutes = slas.length ? Math.min(...slas) : null;

    // If any vendor is "all properties", the category reaches the whole
    // portfolio → scope count is not a meaningful limiter (null).
    const anyAllScope = filed.some((v) => v.applyScope === "all");
    const scopedPropertyCount = anyAllScope
      ? null
      : new Set(filed.flatMap((v) => v.propertyIds)).size || 0;

    return {
      category,
      vendorCount: filed.length || category.vendorCount,
      covered: filed.length > 0,
      afterHours,
      bestSlaMinutes,
      scopedPropertyCount,
    };
  });
}

export function groupByLane(
  coverage: CategoryCoverage[],
): Record<LaneKey, CategoryCoverage[]> {
  const lanes: Record<LaneKey, CategoryCoverage[]> = { dispatch: [], experience: [] };
  for (const item of coverage) {
    lanes[laneOf(item.category.workflowGroup)].push(item);
  }
  const bySort = (a: CategoryCoverage, b: CategoryCoverage) =>
    a.category.sortOrder - b.category.sortOrder ||
    a.category.displayName.localeCompare(b.category.displayName);
  lanes.dispatch.sort(bySort);
  lanes.experience.sort(bySort);
  return lanes;
}

export function summarizeCoverage(coverage: CategoryCoverage[]) {
  const total = coverage.length;
  const covered = coverage.filter((c) => c.covered).length;
  return {
    total,
    covered,
    uncovered: total - covered,
  };
}
