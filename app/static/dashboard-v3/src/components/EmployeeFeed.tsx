import { Fragment } from "react";

import type { Brief } from "../lib/brief";
import { dayPart, relative } from "../lib/time";
import type { FeedUpdate, UpdateTag } from "../types";
import { ChannelTag, MetaLine, MicroLabel } from "./atoms";

function MorningBrief({ brief }: { brief: Brief }) {
  return (
    <div className="shrink-0 border-b border-hairline px-5 pb-4 pt-5">
      <div className="mb-2.5 flex items-center gap-2">
        <span aria-hidden style={{ color: "var(--accent)" }}>
          ✦
        </span>
        <MicroLabel accent>Your morning brief</MicroLabel>
      </div>
      <div className="space-y-2">
        {brief.lines.map((line, i) => (
          <p key={i} className="text-[14.5px] leading-relaxed text-ink/90">
            {line}
          </p>
        ))}
      </div>
      <p
        className="mt-3 border-l-2 pl-3 text-[14.5px] font-medium leading-relaxed text-ink"
        style={{ borderColor: "var(--accent)" }}
      >
        {brief.action}
      </p>
    </div>
  );
}

const TAG_LABEL: Record<UpdateTag, string> = {
  handled: "Handled",
  resolved: "Resolved",
  noticed: "Noticed",
  booking: "Booking",
  checkin: "Guest comms",
};

function FeedRow({
  item,
  selected,
  onSelect,
}: {
  item: FeedUpdate;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={[
        "group w-full rounded-xl border px-3.5 py-3 text-left transition-colors duration-150",
        selected
          ? "border-line bg-selected"
          : "border-transparent hover:border-hairline hover:bg-hover",
      ].join(" ")}
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <ChannelTag channel={item.channel} />
        <time className="shrink-0 text-[11.5px] tabular-nums text-faint">
          {relative(item.at)}
        </time>
      </div>
      <p className="text-[14px] leading-relaxed text-ink/95">{item.summary}</p>
      <div className="mt-2 flex items-center gap-2">
        <MicroLabel accent={item.tag === "noticed"}>
          {TAG_LABEL[item.tag]}
        </MicroLabel>
        <span className="text-faint">·</span>
        <MetaLine parts={[item.property, item.guest]} />
      </div>
    </button>
  );
}

export function EmployeeFeed({
  items,
  brief,
  selectedId,
  onSelect,
}: {
  items: FeedUpdate[];
  brief: Brief;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  let lastPart = "";
  return (
    <section className="flex h-full min-h-0 flex-col border-r border-hairline">
      <MorningBrief brief={brief} />
      <header className="shrink-0 px-5 pb-3 pt-4">
        <h2 className="text-[15px] font-semibold text-ink">Since you checked in</h2>
        <p className="mt-0.5 text-[12.5px] text-muted">
          What I’ve done, decided, and noticed — newest first.
        </p>
      </header>
      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto px-2.5 pb-8">
        {items.map((item) => {
          const part = dayPart(item.at);
          const showDivider = part !== lastPart;
          lastPart = part;
          return (
            <Fragment key={item.id}>
              {showDivider && (
                <div className="flex items-center gap-3 px-1.5 pb-1 pt-4 first:pt-1.5">
                  <MicroLabel>{part}</MicroLabel>
                  <span className="h-px flex-1 bg-hairline" />
                </div>
              )}
              <FeedRow
                item={item}
                selected={item.id === selectedId}
                onSelect={() => onSelect(item.id)}
              />
            </Fragment>
          );
        })}
      </div>
    </section>
  );
}
