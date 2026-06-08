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

export function NeedsInput({
  items,
  selectedId,
  onSelect,
}: {
  items: Decision[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const sorted = [...items].sort(byPriorityThenWaiting);
  return (
    <section className="flex h-full min-h-0 flex-col border-r border-hairline bg-bg">
      <header className="shrink-0 px-5 pb-3 pt-5">
        <div className="flex items-baseline gap-2">
          <h2 className="text-[15px] font-semibold text-ink">Needs your input</h2>
          {sorted.length > 0 && (
            <span className="text-[12.5px] font-medium text-muted">
              {sorted.length}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-[12.5px] text-muted">
          A quick word from you and I’ll take it from there.
        </p>
      </header>
      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3.5 pb-8">
        {sorted.length === 0 ? (
          <div className="mt-10 px-3 text-center">
            <p className="text-[14px] text-ink/90">You’re all caught up.</p>
            <p className="mx-auto mt-1.5 max-w-[34ch] text-[13px] leading-relaxed text-muted">
              I’ll keep working in the background and put anything that needs your
              call right here.
            </p>
          </div>
        ) : (
          sorted.map((item) => (
            <DecisionCard
              key={item.id}
              item={item}
              selected={item.id === selectedId}
              onSelect={() => onSelect(item.id)}
            />
          ))
        )}
      </div>
    </section>
  );
}
