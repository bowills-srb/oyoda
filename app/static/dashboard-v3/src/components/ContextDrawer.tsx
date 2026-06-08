import { useState } from "react";

import { clock } from "../lib/time";
import type { Decision, DecisionOption, FeedUpdate, WorkItem } from "../types";
import {
  ChannelTag,
  DataGrid,
  DraftCard,
  MetaLine,
  PriorityTag,
  SectionTitle,
  draftHeading,
} from "./atoms";

interface Handlers {
  onClose: () => void;
  onResolve: (decision: Decision, option: DecisionOption) => void;
  onRedirect: (decision: Decision, note: string) => void;
  onCoach: (update: FeedUpdate, note: string) => void;
}

/** A collapsible "tell me differently" affordance with a small composer. */
function RedirectBox({
  label,
  placeholder,
  cta,
  onSubmit,
}: {
  label: string;
  placeholder: string;
  cta: string;
  onSubmit: (note: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-[13px] font-medium text-accent transition-opacity hover:opacity-80"
      >
        {label}
      </button>
    );
  }
  return (
    <div className="rounded-xl border border-hairline bg-panel p-3">
      <textarea
        autoFocus
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder={placeholder}
        rows={3}
        className="w-full resize-none rounded-lg border border-hairline bg-bg px-3 py-2 text-[13.5px] leading-relaxed text-ink placeholder:text-faint focus:outline-none focus:ring-1 focus:ring-accent/50"
      />
      <div className="mt-2 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            setNote("");
          }}
          className="rounded-lg px-3 py-1.5 text-[13px] text-muted hover:text-ink"
        >
          Never mind
        </button>
        <button
          type="button"
          disabled={!note.trim()}
          onClick={() => onSubmit(note.trim())}
          className="rounded-lg bg-accent px-3 py-1.5 text-[13px] font-semibold text-bg transition-opacity disabled:opacity-40"
        >
          {cta}
        </button>
      </div>
    </div>
  );
}

function Block({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <SectionTitle>{title}</SectionTitle>
      {children}
    </section>
  );
}

function Prose({ children }: { children: React.ReactNode }) {
  return (
    <p className="max-w-prose text-[14px] leading-relaxed text-ink/90">
      {children}
    </p>
  );
}

function UpdateBody({
  item,
  onCoach,
}: {
  item: FeedUpdate;
  onCoach: (update: FeedUpdate, note: string) => void;
}) {
  return (
    <div className="space-y-6">
      <header className="space-y-2.5">
        <div className="flex items-center gap-2">
          <ChannelTag channel={item.channel} />
          <time className="text-[12px] tabular-nums text-faint">
            {clock(item.at)}
          </time>
        </div>
        <p className="text-[16px] leading-snug text-ink">{item.summary}</p>
        <MetaLine parts={[item.property, item.guest]} />
      </header>

      <Block title="What I saw">
        <DataGrid points={item.reasoning.observed} />
      </Block>

      <Block title="How I thought about it">
        <Prose>{item.reasoning.thought}</Prose>
      </Block>

      <Block title="What I decided">
        <Prose>{item.decision}</Prose>
      </Block>

      <Block title="What I did">
        <Prose>{item.outcome}</Prose>
      </Block>

      {item.draft && (
        <Block title={draftHeading(item.draft.channel, item.draft.sent)}>
          <DraftCard draft={item.draft} />
        </Block>
      )}

      <div className="space-y-3 border-t border-hairline pt-5">
        <p className="text-[13px] text-muted">
          I handled this on my own. If I read it wrong, teach me — I’ll apply it
          next time.
        </p>
        <RedirectBox
          label="Adjust how I handle this →"
          placeholder="e.g. Always call me before dispatching a vendor to the Beach House, even small jobs."
          cta="Save guidance"
          onSubmit={(note) => onCoach(item, note)}
        />
      </div>
    </div>
  );
}

function optionClasses(option: DecisionOption): string {
  if (option.kind === "approve") {
    return "bg-accent text-bg font-semibold hover:opacity-90";
  }
  if (option.kind === "decline") {
    return "border border-hairline text-muted hover:text-ink hover:border-line";
  }
  return "border border-line text-ink hover:bg-hover";
}

function DecisionBody({
  item,
  onResolve,
  onRedirect,
}: {
  item: Decision;
  onResolve: (decision: Decision, option: DecisionOption) => void;
  onRedirect: (decision: Decision, note: string) => void;
}) {
  return (
    <div className="space-y-6">
      <header className="space-y-2.5">
        <div className="flex items-center justify-between gap-3">
          <PriorityTag priority={item.priority} />
          <ChannelTag channel={item.channel} />
        </div>
        <p className="text-[16px] leading-snug text-ink">{item.ask}</p>
        <MetaLine parts={[item.property, item.guest]} />
      </header>

      <Block title="What I saw">
        <DataGrid points={item.reasoning.observed} />
      </Block>

      <Block title="How I thought about it">
        <Prose>{item.reasoning.thought}</Prose>
      </Block>

      <Block title="What I’m proposing">
        <Prose>{item.proposal}</Prose>
      </Block>

      {item.draft && (
        <Block title={draftHeading(item.draft.channel, item.draft.sent)}>
          <DraftCard draft={item.draft} />
        </Block>
      )}

      <div className="space-y-3 border-t border-hairline pt-5">
        <SectionTitle>Your call</SectionTitle>
        <div className="space-y-2">
          {item.options.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => onResolve(item, option)}
              className={[
                "w-full rounded-xl px-4 py-2.5 text-left text-[14px] transition-colors",
                optionClasses(option),
              ].join(" ")}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="pt-1">
          <RedirectBox
            label="Or tell me differently →"
            placeholder="e.g. Move them to Pelican Perch and send a $150 dinner credit for the trouble."
            cta="Send it back to me"
            onSubmit={(note) => onRedirect(item, note)}
          />
        </div>
      </div>
    </div>
  );
}

function RestingState() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-8 text-center">
      <div
        className="mb-5 h-10 w-10 rounded-full border"
        style={{
          borderColor: "var(--hairline)",
          background:
            "radial-gradient(circle at 50% 40%, color-mix(in srgb, var(--accent) 22%, transparent), transparent 70%)",
        }}
      />
      <p className="text-[14px] text-ink/90">Tap anything to see my thinking.</p>
      <p className="mx-auto mt-2 max-w-[34ch] text-[13px] leading-relaxed text-muted">
        I’ll show what I saw, how I weighed it, and what I did or propose.
        Nothing I do is hidden from you.
      </p>
    </div>
  );
}

function DrawerBody({
  item,
  handlers,
}: {
  item: WorkItem | null;
  handlers: Handlers;
}) {
  if (!item) return <RestingState />;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-hairline px-5 py-3.5">
        <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
          {item.kind === "decision" ? "Decision" : "Context"}
        </span>
        <button
          type="button"
          onClick={handlers.onClose}
          aria-label="Close"
          className="rounded-md p-1 text-faint transition-colors hover:bg-hover hover:text-ink"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
            <path
              d="M4 4l8 8M12 4l-8 8"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        {item.kind === "decision" ? (
          <DecisionBody
            item={item}
            onResolve={handlers.onResolve}
            onRedirect={handlers.onRedirect}
          />
        ) : (
          <UpdateBody item={item} onCoach={handlers.onCoach} />
        )}
      </div>
    </div>
  );
}

export function ContextDrawer({
  item,
  handlers,
}: {
  item: WorkItem | null;
  handlers: Handlers;
}) {
  // Remount on selection change so any open composer resets cleanly.
  const body = <DrawerBody key={item?.id ?? "empty"} item={item} handlers={handlers} />;
  return (
    <>
      {/* Inline column on wide screens — always present, rests when empty. */}
      <aside className="hidden h-full min-h-0 bg-panel lg:block">{body}</aside>

      {/* Slide-over on narrow screens — only when something is selected. */}
      {item && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={handlers.onClose}
          />
          <aside className="absolute inset-y-0 right-0 flex w-[min(92vw,440px)] animate-drawer-in flex-col bg-panel shadow-2xl">
            {body}
          </aside>
        </div>
      )}
    </>
  );
}
