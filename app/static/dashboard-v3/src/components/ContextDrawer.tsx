import { useState } from "react";

import { CHANNEL } from "../lib/channel";
import { ALL_PROPERTIES, rulesByIds, scopeLabel } from "../lib/guidance";
import { clock } from "../lib/time";
import type {
  Decision,
  DecisionOption,
  Draft,
  FeedUpdate,
  GuidanceRule,
  GuidanceScope,
  WorkItem,
} from "../types";
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
  /** Resolve a decision. `editedBody` carries any edits made to the draft. */
  onResolve: (
    decision: Decision,
    option: DecisionOption,
    editedBody?: string,
  ) => void;
  onRedirect: (decision: Decision, note: string) => void;
  /** Defer a decision until a human-labelled later moment. */
  onSnooze: (decision: Decision, until: string) => void;
  /** The teaching loop: store a standing rule, scoped, in my words. */
  onTeach: (note: string, scope: GuidanceScope, source: string) => void;
  onRemoveRule: (id: string) => void;
}

/** Preset deferral moments, plus a free-text option. */
const SNOOZE_PRESETS = ["this afternoon", "2:00 PM", "this evening", "after turnover"];

function SnoozeBox({ onSnooze }: { onSnooze: (until: string) => void }) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState("");
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-[13px] font-medium text-muted transition-colors hover:text-ink"
      >
        ☾ Not now — remind me later →
      </button>
    );
  }
  return (
    <div className="rounded-xl border border-hairline bg-panel p-3">
      <p className="mb-2 text-[12.5px] text-muted">
        I’ll keep this warm and bring it back when you say.
      </p>
      <div className="flex flex-wrap gap-1.5">
        {SNOOZE_PRESETS.map((label) => (
          <button
            key={label}
            type="button"
            onClick={() => onSnooze(label)}
            className="rounded-full border border-hairline px-2.5 py-1 text-[12px] text-ink transition-colors hover:border-line hover:bg-hover"
          >
            {label}
          </button>
        ))}
      </div>
      <div className="mt-2.5 flex items-center gap-2">
        <input
          type="text"
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          placeholder="or in your words…"
          className="flex-1 rounded-lg border border-hairline bg-bg px-2.5 py-1.5 text-[12.5px] text-ink placeholder:text-faint focus:border-line focus:outline-none focus:ring-1 focus:ring-accent/40"
        />
        <button
          type="button"
          disabled={!custom.trim()}
          onClick={() => onSnooze(custom.trim())}
          className="rounded-lg bg-accent px-3 py-1.5 text-[12.5px] font-semibold text-bg transition-opacity disabled:opacity-40"
        >
          Snooze
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded-lg px-2 py-1.5 text-[12.5px] text-muted hover:text-ink"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

/**
 * A proposed (unsent) draft Lanier can edit in place before approving — so
 * approving is genuine review, not a rubber stamp. Sent drafts use the plain
 * read-only DraftCard.
 */
function EditableDraft({
  draft,
  value,
  edited,
  onChange,
  onReset,
}: {
  draft: Draft;
  value: string;
  edited: boolean;
  onChange: (v: string) => void;
  onReset: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const meta = CHANNEL[draft.channel];
  return (
    <div className="rounded-xl border border-hairline bg-raised">
      <div className="flex items-center justify-between gap-2 border-b border-hairline px-3.5 py-2">
        <div className="flex items-center gap-2">
          <ChannelTag channel={draft.channel} />
          <span className="text-[12px] text-muted">
            to <span className="text-ink">{draft.to}</span>
          </span>
        </div>
        {editing ? (
          <div className="flex items-center gap-2">
            {edited && (
              <button
                type="button"
                onClick={onReset}
                className="text-[11.5px] text-faint hover:text-ink"
              >
                Reset
              </button>
            )}
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="text-[11.5px] font-semibold text-accent hover:opacity-80"
            >
              Done
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="text-[11.5px] font-medium text-accent transition-opacity hover:opacity-80"
          >
            {edited ? "Edited ✓ · edit" : "Edit"}
          </button>
        )}
      </div>
      <div className="px-3.5 py-3">
        {draft.subject && (
          <p className="mb-1.5 text-[13px] font-semibold text-ink">
            {draft.subject}
          </p>
        )}
        {editing ? (
          <textarea
            autoFocus
            value={value}
            onChange={(e) => onChange(e.target.value)}
            rows={6}
            className="w-full resize-none rounded-lg border border-hairline bg-bg px-3 py-2 text-[13.5px] leading-relaxed text-ink focus:border-line focus:outline-none focus:ring-1 focus:ring-accent/40"
          />
        ) : (
          <p className="whitespace-pre-line text-[13.5px] leading-relaxed text-ink/90">
            {value}
          </p>
        )}
        <p className="mt-2 text-[11.5px] text-faint">
          {editing
            ? `These are the exact words I’ll ${
                draft.channel === "voice" ? "say" : "send"
              }.`
            : `I’ll ${draft.channel === "voice" ? "say" : "send"} this as ${meta.label.toLowerCase()} when you approve — edit it first if you’d like.`}
        </p>
      </div>
    </div>
  );
}

/** A one-off composer for redirecting a single decision. */
function RedirectBox({
  onSubmit,
}: {
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
        Or tell me differently →
      </button>
    );
  }
  return (
    <div className="rounded-xl border border-hairline bg-panel p-3">
      <textarea
        autoFocus
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="e.g. Move them to Pelican Perch and send a $150 dinner credit for the trouble."
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
          Send it back to me
        </button>
      </div>
    </div>
  );
}

/** Teach a standing rule. Scope toggles between this property and the portfolio. */
function TeachBox({
  label,
  property,
  source,
  onTeach,
}: {
  label: string;
  property?: string;
  source: string;
  onTeach: (note: string, scope: GuidanceScope, source: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [wide, setWide] = useState(false);
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
  const scope: GuidanceScope = property && !wide ? property : ALL_PROPERTIES;
  return (
    <div className="rounded-xl border border-hairline bg-panel p-3">
      <textarea
        autoFocus
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="e.g. Always call me before dispatching a vendor here, even small jobs."
        rows={3}
        className="w-full resize-none rounded-lg border border-hairline bg-bg px-3 py-2 text-[13.5px] leading-relaxed text-ink placeholder:text-faint focus:outline-none focus:ring-1 focus:ring-accent/50"
      />
      {property && (
        <div className="mt-2.5 flex items-center gap-1.5">
          <span className="mr-1 text-[12px] text-muted">Applies to</span>
          {[
            { on: false, label: property },
            { on: true, label: "Every property" },
          ].map((opt) => (
            <button
              key={opt.label}
              type="button"
              onClick={() => setWide(opt.on)}
              className={[
                "rounded-full border px-2.5 py-1 text-[12px] transition-colors",
                wide === opt.on
                  ? "border-line bg-selected text-ink"
                  : "border-hairline text-muted hover:text-ink",
              ].join(" ")}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
      <div className="mt-2.5 flex items-center justify-end gap-2">
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
          onClick={() => {
            onTeach(note.trim(), scope, source);
            setOpen(false);
            setNote("");
          }}
          className="rounded-lg bg-accent px-3 py-1.5 text-[13px] font-semibold text-bg transition-opacity disabled:opacity-40"
        >
          Save guidance
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

/** The standing rules already shaping this item — the visible payoff of teaching. */
function GoverningRules({
  ids,
  rules,
}: {
  ids: string[] | undefined;
  rules: GuidanceRule[];
}) {
  const applied = rulesByIds(ids, rules);
  if (applied.length === 0) return null;
  return (
    <Block title="What I'm already following here">
      <ul className="space-y-2">
        {applied.map((rule) => (
          <li
            key={rule.id}
            className="flex gap-2.5 rounded-lg border border-hairline bg-panel px-3 py-2.5"
          >
            <span aria-hidden className="mt-px shrink-0 text-accent">
              ✦
            </span>
            <div>
              <p className="text-[13.5px] leading-relaxed text-ink/90">
                {rule.instruction}
              </p>
              <p className="mt-1 text-[11px] font-medium uppercase tracking-[0.1em] text-faint">
                {scopeLabel(rule.scope)}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </Block>
  );
}

function UpdateBody({
  item,
  rules,
  onTeach,
}: {
  item: FeedUpdate;
  rules: GuidanceRule[];
  onTeach: Handlers["onTeach"];
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

      <GoverningRules ids={item.governedBy} rules={rules} />

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
        <TeachBox
          label="Adjust how I handle this →"
          property={item.property}
          source={`You taught me on the ${item.property} ${
            item.tag === "noticed" ? "watch" : "update"
          }`}
          onTeach={onTeach}
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
  rules,
  onResolve,
  onRedirect,
  onSnooze,
  onTeach,
}: {
  item: Decision;
  rules: GuidanceRule[];
  onResolve: Handlers["onResolve"];
  onRedirect: Handlers["onRedirect"];
  onSnooze: Handlers["onSnooze"];
  onTeach: Handlers["onTeach"];
}) {
  const original = item.draft?.body ?? "";
  const [body, setBody] = useState(original);
  const edited = body.trim() !== original.trim();
  // Only a draft-sending option carries my edits; declining doesn't send it.
  const resolve = (option: DecisionOption) =>
    onResolve(item, option, option.kind === "decline" ? undefined : body);

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

      <GoverningRules ids={item.governedBy} rules={rules} />

      <Block title="What I’m proposing">
        <Prose>{item.proposal}</Prose>
      </Block>

      {item.draft && (
        <Block title={draftHeading(item.draft.channel, item.draft.sent)}>
          <EditableDraft
            draft={item.draft}
            value={body}
            edited={edited}
            onChange={setBody}
            onReset={() => setBody(original)}
          />
        </Block>
      )}

      <div className="space-y-3 border-t border-hairline pt-5">
        <SectionTitle>Your call</SectionTitle>
        {edited && (
          <p className="text-[12.5px] text-accent">
            You’ve edited the message — I’ll send your version.
          </p>
        )}
        <div className="space-y-2">
          {item.options.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => resolve(option)}
              className={[
                "w-full rounded-xl px-4 py-2.5 text-left text-[14px] transition-colors",
                optionClasses(option),
              ].join(" ")}
            >
              {edited && option.kind !== "decline"
                ? `${option.label} — as you edited it`
                : option.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-1">
          <RedirectBox onSubmit={(note) => onRedirect(item, note)} />
          <SnoozeBox onSnooze={(until) => onSnooze(item, until)} />
        </div>
      </div>

      <div className="space-y-2 border-t border-hairline pt-5">
        <p className="text-[13px] text-muted">
          Want me to handle situations like this on my own next time?
        </p>
        <TeachBox
          label="Teach me a standing rule →"
          property={item.property}
          source={`You taught me on the ${item.property} decision`}
          onTeach={onTeach}
        />
      </div>
    </div>
  );
}

function GuidanceBody({
  rules,
  onTeach,
  onRemove,
}: {
  rules: GuidanceRule[];
  onTeach: Handlers["onTeach"];
  onRemove: (id: string) => void;
}) {
  const portfolio = rules.filter((r) => r.scope === ALL_PROPERTIES);
  const perProperty = rules.filter((r) => r.scope !== ALL_PROPERTIES);

  function Group({ title, list }: { title: string; list: GuidanceRule[] }) {
    if (list.length === 0) return null;
    return (
      <Block title={title}>
        <ul className="space-y-2">
          {list.map((rule) => (
            <li
              key={rule.id}
              className="group flex items-start gap-2.5 rounded-lg border border-hairline bg-panel px-3 py-2.5"
            >
              <span aria-hidden className="mt-px shrink-0 text-accent">
                ✦
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[13.5px] leading-relaxed text-ink/90">
                  {rule.instruction}
                </p>
                <p className="mt-1 text-[11px] text-faint">
                  {scopeLabel(rule.scope)} · {rule.source}
                </p>
              </div>
              <button
                type="button"
                onClick={() => onRemove(rule.id)}
                className="shrink-0 rounded-md px-1.5 py-0.5 text-[12px] text-faint opacity-0 transition hover:text-high group-hover:opacity-100"
              >
                Unlearn
              </button>
            </li>
          ))}
        </ul>
      </Block>
    );
  }

  return (
    <div className="space-y-6">
      <header className="space-y-1.5">
        <p className="text-[16px] leading-snug text-ink">
          Here’s everything you’ve taught me.
        </p>
        <p className="text-[13px] leading-relaxed text-muted">
          I apply these on my own, so the work gets more yours over time. Remove
          any and I’ll stop — or teach me a new one below.
        </p>
      </header>

      {rules.length === 0 ? (
        <p className="text-[13.5px] text-muted">
          Nothing yet. As you correct and redirect me, what you teach me lands
          here.
        </p>
      ) : (
        <>
          <Group title="Across the portfolio" list={portfolio} />
          <Group title="Property-specific" list={perProperty} />
        </>
      )}

      <div className="border-t border-hairline pt-5">
        <TeachBox
          label="Teach me something new →"
          source="Added directly"
          onTeach={onTeach}
        />
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
  showGuidance,
  rules,
  handlers,
}: {
  item: WorkItem | null;
  showGuidance: boolean;
  rules: GuidanceRule[];
  handlers: Handlers;
}) {
  if (!showGuidance && !item) return <RestingState />;
  const heading = showGuidance
    ? "What I've learned"
    : item?.kind === "decision"
      ? "Decision"
      : "Context";
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-hairline px-5 py-3.5">
        <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
          {heading}
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
        {showGuidance ? (
          <GuidanceBody
            rules={rules}
            onTeach={handlers.onTeach}
            onRemove={handlers.onRemoveRule}
          />
        ) : item?.kind === "decision" ? (
          <DecisionBody
            item={item}
            rules={rules}
            onResolve={handlers.onResolve}
            onRedirect={handlers.onRedirect}
            onSnooze={handlers.onSnooze}
            onTeach={handlers.onTeach}
          />
        ) : item ? (
          <UpdateBody item={item} rules={rules} onTeach={handlers.onTeach} />
        ) : null}
      </div>
    </div>
  );
}

export function ContextDrawer({
  item,
  showGuidance,
  rules,
  handlers,
}: {
  item: WorkItem | null;
  showGuidance: boolean;
  rules: GuidanceRule[];
  handlers: Handlers;
}) {
  // Remount on what's shown so any open composer resets cleanly.
  const bodyKey = showGuidance ? "guidance" : (item?.id ?? "empty");
  const body = (
    <DrawerBody
      key={bodyKey}
      item={item}
      showGuidance={showGuidance}
      rules={rules}
      handlers={handlers}
    />
  );
  const open = showGuidance || item !== null;
  return (
    <>
      {/* Inline column on wide screens — always present, rests when empty. */}
      <aside className="hidden h-full min-h-0 bg-panel lg:block">{body}</aside>

      {/* Slide-over on narrow screens — only when something is shown. */}
      {open && (
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
