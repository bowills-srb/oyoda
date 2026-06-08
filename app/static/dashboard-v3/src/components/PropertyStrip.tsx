import { useState } from "react";

import type { Decision, FeedUpdate, Property, PropertyStatus } from "../types";

/*
  The portfolio overview strip — a spatial map of every unit before anything
  is flagged below. Each tile shows where a property stands and how many
  things it has pending, so a 12-property morning can be scanned at a glance.
  Clicking a tile filters the feed and decisions to that property; clicking
  the active one clears the filter. Collapsible, because some mornings you
  just want the two panels.
*/

const STATUS_META: Record<
  PropertyStatus,
  { label: string; color: string }
> = {
  occupied: { label: "Occupied", color: "var(--ch-text)" },
  turning: { label: "Turning", color: "var(--accent)" },
  vacant: { label: "Vacant", color: "var(--faint)" },
};

function Dot({ color }: { color: string }) {
  return (
    <span
      aria-hidden
      className="h-1.5 w-1.5 shrink-0 rounded-full"
      style={{ background: color }}
    />
  );
}

function PropertyTile({
  property,
  pending,
  watching,
  active,
  dimmed,
  onClick,
}: {
  property: Property;
  pending: number;
  watching: number;
  active: boolean;
  dimmed: boolean;
  onClick: () => void;
}) {
  const meta = STATUS_META[property.status];
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={[
        "flex w-[190px] shrink-0 flex-col gap-1.5 rounded-xl border px-3 py-2.5 text-left transition-all duration-150",
        active
          ? "border-line bg-selected"
          : "border-hairline bg-panel hover:border-line hover:bg-hover",
        dimmed ? "opacity-40" : "opacity-100",
      ].join(" ")}
      title={property.note}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[13px] font-semibold text-ink">
          {property.name}
        </span>
        {(pending > 0 || watching > 0) && (
          <span className="flex shrink-0 items-center gap-1">
            {pending > 0 && (
              <span
                className="rounded-full px-1.5 py-px text-[10px] font-semibold leading-none text-bg"
                style={{ background: "var(--high)" }}
                title={`${pending} pending your input`}
              >
                {pending}
              </span>
            )}
            {watching > 0 && (
              <span
                className="text-[10px] font-semibold leading-none"
                style={{ color: "var(--accent)" }}
                title={`${watching} I'm watching`}
              >
                ✦{watching}
              </span>
            )}
          </span>
        )}
      </div>
      <div className="flex items-center gap-1.5">
        <Dot color={meta.color} />
        <span
          className="text-[11px] font-medium"
          style={{ color: meta.color }}
        >
          {meta.label}
        </span>
        {property.guest && (
          <>
            <span className="text-faint">·</span>
            <span className="truncate text-[11px] text-muted">
              {property.guest}
            </span>
          </>
        )}
      </div>
    </button>
  );
}

export function PropertyStrip({
  properties,
  feed,
  decisions,
  activeProperty,
  onSelectProperty,
}: {
  properties: Property[];
  feed: FeedUpdate[];
  decisions: Decision[];
  activeProperty: string | null;
  onSelectProperty: (name: string | null) => void;
}) {
  const [open, setOpen] = useState(true);

  const pendingFor = (name: string) =>
    decisions.filter((d) => d.property === name && !d.snoozedUntil).length;
  const watchingFor = (name: string) =>
    feed.filter((f) => f.property === name && f.tag === "noticed").length;

  const needsAttention = properties.filter(
    (p) => pendingFor(p.name) > 0 || watchingFor(p.name) > 0,
  ).length;

  return (
    <div className="shrink-0 border-b border-hairline bg-bg">
      <div className="flex items-center justify-between gap-3 px-5 pt-2.5">
        <div className="flex items-center gap-2.5">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
            Portfolio
          </span>
          <span className="text-[11.5px] text-muted">
            {properties.length} properties
            {needsAttention > 0 && (
              <>
                {" · "}
                <span className="text-ink/80">
                  {needsAttention} with something open
                </span>
              </>
            )}
          </span>
          {activeProperty && (
            <button
              type="button"
              onClick={() => onSelectProperty(null)}
              className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink transition-colors hover:bg-hover"
            >
              Filtered: {activeProperty} · clear ✕
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-[11.5px] font-medium text-muted transition-colors hover:text-ink"
        >
          {open ? "Hide" : "Show"}
        </button>
      </div>
      {open && (
        <div className="flex gap-2 overflow-x-auto px-5 pb-3 pt-2.5">
          {properties.map((p) => {
            const active = activeProperty === p.name;
            return (
              <PropertyTile
                key={p.name}
                property={p}
                pending={pendingFor(p.name)}
                watching={watchingFor(p.name)}
                active={active}
                dimmed={activeProperty !== null && !active}
                onClick={() => onSelectProperty(active ? null : p.name)}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
