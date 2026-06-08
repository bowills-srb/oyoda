import type { CSSProperties, ReactNode } from "react";

import { CHANNEL, draftHeading } from "../lib/channel";
import type { Channel, DataPoint, Draft, Priority } from "../types";

function channelColor(channel: Channel): string {
  return `var(--${CHANNEL[channel].tone})`;
}

/** Soft tinted background derived from a CSS color, for pills. */
function tint(color: string, pct: number): string {
  return `color-mix(in srgb, ${color} ${pct}%, transparent)`;
}

/** 📱 Text / 📧 Email / 🔊 Voice — the channel an item travels on. */
export function ChannelTag({ channel }: { channel: Channel }) {
  const meta = CHANNEL[channel];
  const color = channelColor(channel);
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-[3px] text-[11px] font-medium leading-none"
      style={{
        color,
        borderColor: tint(color, 32),
        background: tint(color, 12),
      }}
    >
      <span aria-hidden className="text-[12px] leading-none grayscale-0">
        {meta.emoji}
      </span>
      {meta.label}
    </span>
  );
}

const PRIORITY_META: Record<Priority, { label: string; color: string }> = {
  high: { label: "Needs you now", color: "var(--high)" },
  medium: { label: "When you can", color: "var(--med)" },
  low: { label: "No rush", color: "var(--low)" },
};

export function PriorityTag({ priority }: { priority: Priority }) {
  const meta = PRIORITY_META[priority];
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[11px] font-medium leading-none"
      style={{ color: meta.color }}
    >
      <span
        aria-hidden
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: meta.color }}
      />
      {meta.label}
    </span>
  );
}

/** Tiny uppercase category marker. */
export function MicroLabel({
  children,
  accent = false,
}: {
  children: ReactNode;
  accent?: boolean;
}) {
  return (
    <span
      className="text-[10px] font-semibold uppercase tracking-[0.12em]"
      style={{ color: accent ? "var(--accent)" : "var(--faint)" }}
    >
      {children}
    </span>
  );
}

/** "Beach House · Jordan Lee" quiet metadata line. */
export function MetaLine({
  parts,
  className = "",
}: {
  parts: (string | undefined)[];
  className?: string;
}) {
  const clean = parts.filter(Boolean) as string[];
  return (
    <span className={`text-[12.5px] text-muted ${className}`}>
      {clean.map((p, i) => (
        <span key={i}>
          {i > 0 && <span className="text-faint"> · </span>}
          {p}
        </span>
      ))}
    </span>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
      {children}
    </h3>
  );
}

/** The data the employee leaned on, as a clean label/value list. */
export function DataGrid({ points }: { points: DataPoint[] }) {
  return (
    <dl className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-hairline bg-hairline">
      {points.map((p, i) => (
        <div
          key={i}
          className="flex items-baseline justify-between gap-4 bg-panel px-3 py-2"
        >
          <dt className="shrink-0 text-[12.5px] text-muted">{p.label}</dt>
          <dd className="text-right text-[12.5px] font-medium text-ink">
            {p.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * A drafted communication, rendered in the voice and shape of its channel so
 * the writing can be judged before the channel is wired up.
 */
export function DraftCard({ draft }: { draft: Draft }) {
  const color = channelColor(draft.channel);
  const accent: CSSProperties = { borderColor: tint(color, 30) };
  return (
    <div className="rounded-xl border bg-raised" style={accent}>
      <div
        className="flex items-center justify-between gap-2 border-b px-3.5 py-2"
        style={{ borderColor: "var(--hairline)" }}
      >
        <div className="flex items-center gap-2">
          <ChannelTag channel={draft.channel} />
          <span className="text-[12px] text-muted">
            to <span className="text-ink">{draft.to}</span>
          </span>
        </div>
        <span
          className="text-[10px] font-semibold uppercase tracking-[0.12em]"
          style={{ color: draft.sent ? "var(--ch-voice)" : "var(--faint)" }}
        >
          {draft.sent ? "Sent ✓" : "Draft"}
        </span>
      </div>
      <div className="px-3.5 py-3">
        {draft.subject && (
          <p className="mb-1.5 text-[13px] font-semibold text-ink">
            {draft.subject}
          </p>
        )}
        <p className="text-[13.5px] leading-relaxed text-ink/90 whitespace-pre-line">
          {draft.body}
        </p>
      </div>
    </div>
  );
}

export { draftHeading };
