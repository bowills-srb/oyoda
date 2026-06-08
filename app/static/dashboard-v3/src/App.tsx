import { useMemo, useState } from "react";

import { ContextDrawer } from "./components/ContextDrawer";
import { EmployeeFeed } from "./components/EmployeeFeed";
import { NeedsInput } from "./components/NeedsInput";
import { PropertyStrip } from "./components/PropertyStrip";
import { Topbar } from "./components/Topbar";
import { composeBrief } from "./lib/brief";
import { DECISIONS, FEED, PORTFOLIO, PROPERTIES } from "./data/mock";
import { ALL_PROPERTIES, loadRules, saveRules, scopeLabel } from "./lib/guidance";
import { NOW } from "./lib/time";
import type {
  Decision,
  DecisionOption,
  FeedUpdate,
  GuidanceRule,
  GuidanceScope,
  WorkItem,
} from "./types";

export default function App() {
  const [feed, setFeed] = useState<FeedUpdate[]>(FEED);
  const [decisions, setDecisions] = useState<Decision[]>(DECISIONS);
  const [rules, setRules] = useState<GuidanceRule[]>(() => loadRules());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showGuidance, setShowGuidance] = useState(false);
  const [activeProperty, setActiveProperty] = useState<string | null>(null);

  const selected: WorkItem | null = useMemo(() => {
    if (!selectedId) return null;
    return (
      decisions.find((d) => d.id === selectedId) ??
      feed.find((f) => f.id === selectedId) ??
      null
    );
  }, [selectedId, decisions, feed]);

  function select(id: string) {
    setSelectedId(id);
    setShowGuidance(false);
  }

  function updateRules(next: GuidanceRule[]) {
    setRules(next);
    saveRules(next);
  }

  function prependFeed(entry: FeedUpdate) {
    setFeed((prev) => [entry, ...prev]);
  }

  /** A resolved decision becomes a fresh entry in the feed, in my voice. */
  function logResolution(
    source: Decision,
    summary: string,
    decisionLine: string,
    editedBody?: string,
  ) {
    // If Lanier edited the draft before approving, send her exact words.
    const wasEdited =
      editedBody !== undefined &&
      source.draft !== undefined &&
      editedBody.trim() !== source.draft.body.trim();
    const draft = source.draft
      ? {
          ...source.draft,
          body: editedBody ?? source.draft.body,
          sent: true,
        }
      : undefined;
    const observed = [{ label: "Your call", value: decisionLine }];
    if (wasEdited) {
      observed.push({ label: "Message", value: "Sent in your wording" });
    }

    const entry: FeedUpdate = {
      kind: "update",
      id: `${source.id}-done-${Date.now()}`,
      channel: source.channel,
      at: NOW.toISOString(),
      tag: "handled",
      property: source.property,
      guest: source.guest,
      summary: wasEdited
        ? `${summary} I sent it in the wording you edited, word for word.`
        : summary,
      governedBy: source.governedBy,
      reasoning: {
        observed,
        thought:
          "You made the call and I carried it out right away. Here’s exactly what I did, so there’s nothing ambiguous between us.",
      },
      decision: decisionLine,
      outcome: summary,
      draft,
    };
    prependFeed(entry);
    setDecisions((prev) => prev.filter((d) => d.id !== source.id));
    setSelectedId(entry.id);
    setShowGuidance(false);
  }

  function handleResolve(
    decision: Decision,
    option: DecisionOption,
    editedBody?: string,
  ) {
    logResolution(decision, option.resultSummary, option.label, editedBody);
  }

  /** Defer a decision; it drops into the Snoozed group until she wakes it. */
  function handleSnooze(decision: Decision, until: string) {
    setDecisions((prev) =>
      prev.map((d) => (d.id === decision.id ? { ...d, snoozedUntil: until } : d)),
    );
    setSelectedId(null);
    setShowGuidance(false);
  }

  function handleWake(id: string) {
    setDecisions((prev) =>
      prev.map((d) =>
        d.id === id ? { ...d, snoozedUntil: undefined } : d,
      ),
    );
  }

  function handleRedirect(decision: Decision, note: string) {
    logResolution(
      decision,
      `You redirected me on this — “${note}”. I’ve taken it from here and I’ll follow exactly that.`,
      "Redirected in your words",
    );
  }

  /** The teaching loop: store a standing rule and acknowledge it in the feed. */
  function handleTeach(note: string, scope: GuidanceScope, source: string) {
    const rule: GuidanceRule = {
      id: `rule-${Date.now()}`,
      scope,
      instruction: note,
      createdAt: NOW.toISOString(),
      source,
    };
    updateRules([rule, ...rules]);

    const where =
      scope === ALL_PROPERTIES ? "across every property" : `for ${scope}`;
    prependFeed({
      kind: "update",
      id: `${rule.id}-ack`,
      channel: "text",
      at: NOW.toISOString(),
      tag: "noticed",
      property: scope === ALL_PROPERTIES ? "Portfolio-wide" : scope,
      summary: `Got it. ${where[0].toUpperCase()}${where.slice(1)}, I’ll now: “${note}”.`,
      governedBy: [rule.id],
      reasoning: {
        observed: [
          { label: "New guidance", value: note },
          { label: "Applies to", value: scopeLabel(scope) },
        ],
        thought:
          "You taught me something about how you want this handled. I’ve stored it and I’ll apply it the next time a situation like this comes up — without asking again.",
      },
      decision: "Adopt your guidance going forward.",
      outcome: "Saved. I’ll follow it from here.",
    });
  }

  function handleRemoveRule(id: string) {
    updateRules(rules.filter((r) => r.id !== id));
  }

  const handled = feed.filter((f) => f.tag !== "noticed").length;
  const watching = feed.filter((f) => f.tag === "noticed").length;
  const active = decisions.filter((d) => !d.snoozedUntil);
  const urgent = active.filter((d) => d.priority === "high").length;
  const brief = useMemo(() => composeBrief(feed, decisions), [feed, decisions]);

  // The portfolio strip filters both panels to one property at a time.
  const shownFeed = activeProperty
    ? feed.filter((f) => f.property === activeProperty)
    : feed;
  const shownDecisions = activeProperty
    ? decisions.filter((d) => d.property === activeProperty)
    : decisions;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bg text-ink">
      <Topbar
        operator={PORTFOLIO.operator}
        now={NOW}
        lastCheckIn={PORTFOLIO.lastCheckIn}
        handled={handled}
        watching={watching}
        need={active.length}
        urgent={urgent}
        learned={rules.length}
        onOpenGuidance={() => setShowGuidance(true)}
      />
      <PropertyStrip
        properties={PROPERTIES}
        feed={feed}
        decisions={decisions}
        activeProperty={activeProperty}
        onSelectProperty={setActiveProperty}
      />
      <main className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)_minmax(0,0.96fr)] lg:overflow-hidden">
        <EmployeeFeed
          items={shownFeed}
          brief={brief}
          selectedId={selectedId}
          onSelect={select}
        />
        <NeedsInput
          items={shownDecisions}
          selectedId={selectedId}
          onSelect={select}
          onWake={handleWake}
        />
        <ContextDrawer
          item={selected}
          showGuidance={showGuidance}
          rules={rules}
          handlers={{
            onClose: () => {
              setSelectedId(null);
              setShowGuidance(false);
            },
            onResolve: handleResolve,
            onRedirect: handleRedirect,
            onSnooze: handleSnooze,
            onTeach: handleTeach,
            onRemoveRule: handleRemoveRule,
          }}
        />
      </main>
    </div>
  );
}
