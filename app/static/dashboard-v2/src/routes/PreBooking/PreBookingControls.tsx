import { cn } from "../../lib/utils";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { SurfaceControls } from "../../components/system/SurfaceControls";
import { SurfaceTabs } from "../../components/system/SurfaceTabs";
import { Icon } from "../../shared/Icon";
import type { MessageFeed } from "../../domain/prebooking/types";

type QueueTab = "action" | "sent" | "held" | "closed";
type QueueScope = "all" | "mine" | "unassigned";

type PreBookingControlsProps = {
  activeTab: QueueTab;
  hasHydratedFeed: boolean;
  propertyId: string;
  propertyOptions: MessageFeed["properties"];
  scope: QueueScope;
  search: string;
  tabCounts: Record<QueueTab, number>;
  focusMode?: boolean;
  onToggleFocusMode?: () => void;
  onSearchChange: (value: string) => void;
  onPropertyChange: (value: string) => void;
  onScopeChange: (value: string) => void;
  onTabChange: (key: QueueTab) => void;
};

// ── PreBookingControls ────────────────────────────────────────────────────────
//
// Tabs + filter bar only. The summary numbers (awaiting / draft-ready /
// knowledge-held / unbound / sent) and the readiness metrics now live in the
// PreBookingAssuranceBand above this component — they used to be duplicated
// here as an analytics strip and a metric-chip row. The band's ledger numbers
// double as the queue filters, so this component no longer owns filtering by
// metric; it owns search, property/scope selects, tab switching, and the
// focus-mode toggle.

export function PreBookingControls({
  activeTab,
  hasHydratedFeed,
  propertyId,
  propertyOptions,
  scope,
  search,
  tabCounts,
  focusMode = false,
  onToggleFocusMode,
  onSearchChange,
  onPropertyChange,
  onScopeChange,
  onTabChange,
}: PreBookingControlsProps) {
  const loading = !hasHydratedFeed;

  return (
    <SurfaceControls ariaLabel="Queue controls" flush={focusMode}>
      <div className={cn("flex min-w-0 items-center gap-4 pr-7", focusMode ? "justify-end" : "justify-between")}>
        {focusMode ? null : (
          <div className="min-w-0 flex-1 overflow-hidden">
            <SurfaceTabs
              ariaLabel="Pre-booking queues"
              tabs={[
                { key: "action", label: "Action", count: tabCounts.action },
                { key: "sent",   label: "Sent",   count: tabCounts.sent   },
                { key: "held",   label: "Held",   count: tabCounts.held   },
                { key: "closed", label: "Closed", count: tabCounts.closed },
              ]}
              activeKey={activeTab}
              loading={loading}
              onSelect={(key) => onTabChange(key as QueueTab)}
            />
          </div>
        )}
        {onToggleFocusMode ? (
          <button
            type="button"
            onClick={onToggleFocusMode}
            className={cn(
              "flex flex-shrink-0 items-center gap-1.5 rounded-md border border-hairline px-2.5 py-1 text-[11px] font-medium text-secondary transition-colors hover:bg-hover hover:text-primary",
              focusMode ? "" : "ml-auto",
            )}
            aria-pressed={focusMode}
            title={focusMode ? "Exit focus mode" : "Focus mode — hide chrome and work the queue full-screen"}
          >
            <Icon name={focusMode ? "minimize" : "maximize"} size={12} />
            {focusMode ? "Exit focus" : "Focus"}
          </button>
        ) : null}
      </div>

      {focusMode ? null : (
        <>
      {/* Filter bar */}
      <div className="flex items-center gap-2 px-7 py-3 border-b border-hairline max-[860px]:flex-col max-[860px]:items-stretch">
        {/* Search */}
        <label className="min-w-0 flex-1 flex items-center gap-2 px-2.5 bg-hover border border-transparent rounded-md text-tertiary transition-[background,border-color] duration-[120ms] focus-within:bg-raised focus-within:border-border max-[860px]:min-w-full">
          <Icon name="search" size={16} className="flex-shrink-0 text-tertiary" />
          <Input
            aria-label="Search inquiries"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search guest, property, or message"
            className="border-0 bg-transparent shadow-none h-auto py-[7px] text-[13px] text-primary focus-visible:ring-0 focus-visible:ring-offset-0 placeholder:text-tertiary rounded-none"
          />
        </label>

        {/* Selects */}
        <div className="flex gap-1.5 flex-wrap">
          <Select
            aria-label="Property filter"
            value={propertyId}
            onChange={(event) => onPropertyChange(event.target.value)}
            className="h-auto py-1.5 text-[12.5px] font-medium rounded-md text-secondary w-auto"
          >
            <option value="">All properties</option>
            {propertyOptions.map((property) => (
              <option key={property.id} value={property.id}>
                {property.name} {property.count ? `(${property.count})` : ""}
              </option>
            ))}
          </Select>

          <Select
            aria-label="Scope filter"
            value={scope}
            onChange={(event) => onScopeChange(event.target.value)}
            className="h-auto py-1.5 text-[12.5px] font-medium rounded-md text-secondary w-auto"
          >
            <option value="all">All</option>
            <option value="mine">Assigned to me</option>
            <option value="unassigned">Unassigned</option>
          </Select>
        </div>
      </div>
        </>
      )}
    </SurfaceControls>
  );
}
