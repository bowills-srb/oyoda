import { Fragment, useMemo, useState } from "react";

import type { Brief } from "../lib/brief";
import { CHANNEL } from "../lib/channel";
import { dayPart, relative } from "../lib/time";
import type { Channel, FeedUpdate, UpdateTag } from "../types";
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

const CHANNELS: Channel[] = ["text", "email", "voice"];

/** A quiet search + channel filter so the feed stays findable as it grows. */
function FilterBar({
  query,
  onQuery,
  channel,
  onChannel,
}: {
  query: string;
  onQuery: (v: string) => void;
  channel: Channel | null;
  onChannel: (c: Channel | null) => void;
}) {
  return (
    <div className="shrink-0 px-5 pb-2.5">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <svg
            width="13"
            height="13"
            viewBox="0 0 16 16"
            fill="none"
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint"
          >
            <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4" />
            <path
              d="M10.5 10.5L14 14"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </svg>
          <input
            type="text"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            placeholder="Search what I've done…"
            className="w-full rounded-lg border border-hairline bg-panel py-1.5 pl-8 pr-7 text-[12.5px] text-ink placeholder:text-faint focus:border-line focus:outline-none focus:ring-1 focus:ring-accent/40"
          />
          {query && (
            <button
              type="button"
              onClick={() => onQuery("")}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-ink"
            >
              ✕
            </button>
          )}
        </div>
        <div className="flex items-center gap-1">
          {CHANNELS.map((c) => {
            const on = channel === c;
            return (
              <button
                key={c}
                type="button"
                onClick={() => onChannel(on ? null : c)}
                aria-pressed={on}
                title={`Only ${CHANNEL[c].label}`}
                className={[
                  "rounded-lg border px-2 py-1 text-[12px] leading-none transition-colors",
                  on
                    ? "border-line bg-selected text-ink"
                    : "border-hairline text-muted hover:text-ink",
                ].join(" ")}
              >
                {CHANNEL[c].emoji}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

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
  const [query, setQuery] = useState("");
  const [channel, setChannel] = useState<Channel | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((item) => {
      if (channel && item.channel !== channel) return false;
      if (!q) return true;
      const hay = [
        item.summary,
        item.property,
        item.guest,
        TAG_LABEL[item.tag],
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [items, query, channel]);

  const filtering = query.trim() !== "" || channel !== null;
  let lastPart = "";
  return (
    <section className="flex h-full min-h-0 flex-col border-r border-hairline">
      <MorningBrief brief={brief} />
      <header className="shrink-0 px-5 pb-2.5 pt-4">
        <h2 className="text-[15px] font-semibold text-ink">Since you checked in</h2>
        <p className="mt-0.5 text-[12.5px] text-muted">
          What I’ve done, decided, and noticed — newest first.
        </p>
      </header>
      <FilterBar
        query={query}
        onQuery={setQuery}
        channel={channel}
        onChannel={setChannel}
      />
      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto px-2.5 pb-8">
        {filtered.length === 0 ? (
          <div className="mt-10 px-3 text-center">
            <p className="text-[13.5px] text-ink/90">Nothing matches that.</p>
            <p className="mx-auto mt-1.5 max-w-[32ch] text-[12.5px] leading-relaxed text-muted">
              Try a different word or channel — or clear the filter to see
              everything again.
            </p>
          </div>
        ) : (
          filtered.map((item) => {
            const part = dayPart(item.at);
            const showDivider = !filtering && part !== lastPart;
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
          })
        )}
      </div>
    </section>
  );
}
