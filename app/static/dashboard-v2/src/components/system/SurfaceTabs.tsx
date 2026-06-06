import { cn } from "../../lib/utils";

type SurfaceTab = {
  key: string;
  label: string;
  count?: number | string;
};

type SurfaceTabsProps = {
  ariaLabel: string;
  tabs: SurfaceTab[];
  activeKey: string;
  onSelect: (key: string) => void;
  loading?: boolean;
};

/**
 * Tab strip for surface-level queue/section switching.
 *
 * Designed to nest inside SurfaceControls, which owns the bottom border and
 * the sticky positioning. SurfaceTabs does not add its own bottom border —
 * adding one here would double-border against SurfaceControls's border-b.
 * The pt-1 matches the legacy .surface-controls .tab-strip { padding-top: 4px }
 * override that applied in the only real-world nesting context.
 */
export function SurfaceTabs({
  ariaLabel,
  tabs,
  activeKey,
  onSelect,
  loading = false,
}: SurfaceTabsProps) {
  return (
    <div className="px-7 pt-1">
      <div className="flex gap-1 flex-wrap -mb-px" role="tablist" aria-label={ariaLabel}>
        {tabs.map((tab) => {
          const isActive = activeKey === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => onSelect(tab.key)}
              className={cn(
                // Base: mimics .tab-pill
                "border-0 border-b-2 bg-transparent rounded-none",
                "py-3 pb-3.5 mr-[18px]",
                "inline-flex items-center gap-2",
                "cursor-pointer text-[13.5px] font-normal relative",
                "transition-colors duration-[120ms]",
                // State
                isActive
                  ? "text-primary font-medium border-b-accent"
                  : "text-tertiary border-b-transparent hover:text-secondary",
              )}
            >
              <span>{tab.label}</span>
              {tab.count != null ? (
                <span
                  className={cn(
                    "min-w-[18px] px-1.5 py-px rounded-full text-[11.5px] tabular-nums font-normal",
                    isActive
                      ? "bg-selected text-accent"
                      : "bg-hover text-tertiary",
                  )}
                >
                  {loading ? "—" : tab.count}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
