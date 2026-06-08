import { useState } from "react";

import type { Decision, Priority } from "../types";
import { relative } from "../lib/time";
import { ChannelTag, MetaLine, PriorityTag } from "./atoms";

const PRIORITY_RANK: Record<Priority, number> = { high: 0, medium: 1, low: 2 };

function byPriorityThenWaiting(a: Decision, b: Decision): number {
  const r = PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority];
  if (r !== 0) return r;
  // Within a priority, the one waiting longest comes first.
  return new Date(a.at).getTime() - new Date(b.at).getTime();
}

function DecisionCard({
  item,
  selected,
  onSelect,
}: {
  item: Decision;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={[
        "block w-full rounded-2xl border px-4 py-3.5 text-left transition-colors duration-150",
        selected
          ? "border-line bg-selected"
          : "border-hairline bg-panel hover:border-line hover:bg-hover",
      ].join(" ")}
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <PriorityTag priority={item.priority} />
        <ChannelTag channel={item.channel} />
      </div>
      <p className="text-[14.5px] font-medium leading-snug text-ink">
        {item.ask}
      </p>
      <p className="mt-1.5 text-[13px] leading-relaxed text-muted">
        {item.detail}
      </p>
      <div className="mt-2.5 flex items-center justify-between gap-3">
        <MetaLine parts={[item.property, item.guest]} />
        <span className="flex shrink-0 items-center gap-2">
          {item.governedBy && item.governedBy.length > 0 && (
            <span
              title="Following your standing guidance"
              className="text-[11px]"
              style={{ color: "var(--accent)" }}
            >
              ✦ guided
            </span>
          )}
          <span className="text-[11.5px] tabular-nums text-faint">
            {relative(item.at)}
          </span>
        </span>
      </div>
    </button>
  );
}

/** A deferred decision, collapsed into a quiet row with a way back. */
function SnoozedRow({
  item,
  selected,
  onSelect,
  onWake,
}: {
  item: Decision;
  selected: boolean;
  onSelect: () => void;
  onWake: () => void;
}) {
  return (
    <div
      className={[
        "flex items-center gap-2 rounded-xl border px-3 py-2 transition-colors",
        selected ? "border-line bg-selected" : "border-hairline bg-panel/60",
      ].join(" ")}
    >
      <button
        type="button"
        onClick={onSelect}
        className="flex min-w-0 flex-1 items-center gap-2 text-left"
      >
        <span aria-hidden className="shrink-0 text-faint">
          ☾
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] text-ink/80">
            {item.ask}
          </span>
          <span className="text-[11px] text-faint">
            {item.property} · back at {item.snoozedUntil}
          </span>
        </span>
      </button>
      <button
        type="button"
        onClick={onWake}
        className="shrink-0 rounded-md px-2 py-1 text-[11.5px] font-medium text-muted transition-colors hover:text-ink"
      >
        Wake
      </button>
    </div>
  );
}

export function NeedsInput({
  items,
  selectedId,
  onSelect,
  onWake,
}: {
  items: Decision[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onWake: (id: string) => void;
}) {
  const [showSnoozed, setShowSnoozed] = useState(false);
  const active = items.filter((d) => !d.snoozedUntil).sort(byPriorityThenWaiting);
  const snoozed = items.filter((d) => d.snoozedUntil);

  return (
    <section className="flex h-full min-h-0 flex-col border-r border-hairline bg-bg">
      <header className="shrink-0 px-5 pb-3 pt-5">
        <div className="flex items-baseline gap-2">
          <h2 className="text-[15px] font-semibold text-ink">Needs your input</h2>
          {active.length > 0 && (
            <span className="text-[12.5px] font-medium text-muted">
              {active.length}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-[12.5px] text-muted">
          A quick word from you and I’ll take it from there.
        </p>
      </header>
      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3.5 pb-8">
        {active.length === 0 ? (
          <div className="mt-10 px-3 text-center">
            <p className="text-[14px] text-ink/90">You’re all caught up.</p>
            <p className="mx-auto mt-1.5 max-w-[34ch] text-[13px] leading-relaxed text-muted">
              I’ll keep working in the background and put anything that needs your
              call right here.
            </p>
          </div>
        ) : (
          active.map((item) => (
            <DecisionCard
              key={item.id}
              item={item}
              selected={item.id === selectedId}
              onSelect={() => onSelect(item.id)}
            />
          ))
        )}

        {snoozed.length > 0 && (
          <div className="pt-2">
            <button
              type="button"
              onClick={() => setShowSnoozed((v) => !v)}
              className="flex w-full items-center gap-2 px-1 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-faint transition-colors hover:text-muted"
            >
              <span aria-hidden>☾</span>
              Snoozed · {snoozed.length}
              <span className="ml-auto text-[13px]">
                {showSnoozed ? "–" : "+"}
              </span>
            </button>
            {showSnoozed && (
              <div className="mt-1.5 space-y-1.5">
                {snoozed.map((item) => (
                  <SnoozedRow
                    key={item.id}
                    item={item}
                    selected={item.id === selectedId}
                    onSelect={() => onSelect(item.id)}
                    onWake={() => onWake(item.id)}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
