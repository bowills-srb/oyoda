import { Icon } from "../../shared/Icon";
import { cn } from "../../lib/utils";
import {
  LANE_META,
  groupByLane,
  summarizeCoverage,
  type CategoryCoverage,
  type LaneKey,
} from "./vendors_coverage";

/**
 * CapabilityMap — the spine of the redesigned Vendors surface.
 *
 * Renders every category the AI can route, grouped into the dispatch and
 * experience lanes, with coverage state shown inline. The categories are the
 * navigation; there is no manual directory list to click through. Selecting a
 * tile opens it in the detail panel (parent owns selection via ?selected).
 *
 * Empty is healthy: a category with no vendors reads "Not set up · routes to
 * you" in calm tertiary tone, never as an error. A whole empty lane shows its
 * onboarding copy instead of a blank column.
 */

type Props = {
  coverage: CategoryCoverage[];
  selectedSlug: string | null;
  onSelect: (slug: string) => void;
  loading: boolean;
};

function CoverageHint({ item }: { item: CategoryCoverage }) {
  if (!item.covered) {
    return (
      <span className="text-[11.5px] text-tertiary">Not set up · routes to you</span>
    );
  }
  const bits: string[] = [];
  bits.push(item.vendorCount === 1 ? "1 responder" : `${item.vendorCount} responders`);
  if (item.scopedPropertyCount === null) {
    bits.push("all properties");
  } else if (item.scopedPropertyCount > 0) {
    bits.push(`${item.scopedPropertyCount} properties`);
  }
  if (item.bestSlaMinutes) bits.push(`~${item.bestSlaMinutes}m SLA`);
  return <span className="text-[11.5px] text-secondary tabular-nums">{bits.join(" · ")}</span>;
}

function CoverageBadge({ item }: { item: CategoryCoverage }) {
  if (!item.covered) {
    return <span className="text-[11px] text-tertiary">Not set up</span>;
  }
  if (!item.afterHours && item.category.workflowGroup === "dispatch") {
    return (
      <span className="text-[11px] text-[var(--warning-text)]">No after-hours</span>
    );
  }
  return (
    <span className="text-[11px] text-[var(--success-text)]">
      {item.afterHours ? "After-hours ready" : "Covered"}
    </span>
  );
}

function Lane({
  laneKey,
  items,
  selectedSlug,
  onSelect,
}: {
  laneKey: LaneKey;
  items: CategoryCoverage[];
  selectedSlug: string | null;
  onSelect: (slug: string) => void;
}) {
  const meta = LANE_META[laneKey];
  return (
    <div>
      <div className="flex items-center gap-1.5 px-4 pb-1 pt-3 text-[11px] font-medium uppercase tracking-[0.06em] text-tertiary">
        <Icon name={meta.icon} size={14} />
        {meta.label}
      </div>
      {items.length === 0 ? (
        <p className="px-4 py-2 text-[12px] leading-relaxed text-tertiary">{meta.emptyCopy}</p>
      ) : (
        items.map((item) => {
          const selected = item.category.slug === selectedSlug;
          return (
            <button
              key={item.category.id}
              type="button"
              onClick={() => onSelect(item.category.slug)}
              aria-current={selected ? "true" : undefined}
              className={cn(
                "flex w-full flex-col gap-0.5 border-l-2 px-4 py-2.5 text-left transition-colors",
                selected
                  ? "border-l-accent bg-selected"
                  : "border-l-transparent hover:bg-hover",
              )}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 truncate text-[13.5px] font-medium text-primary">
                  <span aria-hidden className="text-[14px] leading-none">{item.category.icon}</span>
                  {item.category.displayName}
                </span>
                <CoverageBadge item={item} />
              </span>
              <CoverageHint item={item} />
            </button>
          );
        })
      )}
    </div>
  );
}

export function CapabilityMap({ coverage, selectedSlug, onSelect, loading }: Props) {
  const lanes = groupByLane(coverage);
  const summary = summarizeCoverage(coverage);

  return (
    <div className="flex flex-col">
      <div className="border-b border-hairline px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-primary">Response coverage</h2>
          <span className="text-xs text-tertiary">
            {loading ? "Loading…" : `${summary.total} categories`}
          </span>
        </div>
        <p className="mt-1.5 text-[12px] leading-relaxed text-secondary">
          Every kind of issue your AI can route. Add responders where it matters — anything not set
          up routes to you until you do.
        </p>
      </div>

      {loading ? (
        <p className="px-4 py-8 text-center text-sm text-tertiary">Loading capability map…</p>
      ) : (
        <>
          <Lane laneKey="dispatch" items={lanes.dispatch} selectedSlug={selectedSlug} onSelect={onSelect} />
          <div className="mt-1 border-t border-hairline" />
          <Lane laneKey="experience" items={lanes.experience} selectedSlug={selectedSlug} onSelect={onSelect} />
        </>
      )}
    </div>
  );
}
