import { useMemo, useState } from "react";

import { ContextDrawer } from "./components/ContextDrawer";
import { EmployeeFeed } from "./components/EmployeeFeed";
import { NeedsInput } from "./components/NeedsInput";
import { Topbar } from "./components/Topbar";
import { composeBrief } from "./lib/brief";
import { DECISIONS, FEED, PORTFOLIO } from "./data/mock";
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
  ) {
    const entry: FeedUpdate = {
      kind: "update",
      id: `${source.id}-done-${Date.now()}`,
      channel: source.channel,
      at: NOW.toISOString(),
      tag: "handled",
      property: source.property,
      guest: source.guest,
      summary,
      governedBy: source.governedBy,
      reasoning: {
        observed: [{ label: "Your call", value: decisionLine }],
        thought:
          "You made the call and I carried it out right away. Here’s exactly what I did, so there’s nothing ambiguous between us.",
      },
      decision: decisionLine,
      outcome: summary,
      draft: source.draft ? { ...source.draft, sent: true } : undefined,
    };
    prependFeed(entry);
    setDecisions((prev) => prev.filter((d) => d.id !== source.id));
    setSelectedId(entry.id);
    setShowGuidance(false);
  }

  function handleResolve(decision: Decision, option: DecisionOption) {
    logResolution(decision, option.resultSummary, option.label);
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
  const urgent = decisions.filter((d) => d.priority === "high").length;
  const brief = useMemo(() => composeBrief(feed, decisions), [feed, decisions]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bg text-ink">
      <Topbar
        operator={PORTFOLIO.operator}
        now={NOW}
        lastCheckIn={PORTFOLIO.lastCheckIn}
        handled={handled}
        watching={watching}
        need={decisions.length}
        urgent={urgent}
        learned={rules.length}
        onOpenGuidance={() => setShowGuidance(true)}
      />
      <main className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)_minmax(0,0.96fr)] lg:overflow-hidden">
        <EmployeeFeed
          items={feed}
          brief={brief}
          selectedId={selectedId}
          onSelect={select}
        />
        <NeedsInput
          items={decisions}
          selectedId={selectedId}
          onSelect={select}
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
            onTeach: handleTeach,
            onRemoveRule: handleRemoveRule,
          }}
        />
      </main>
    </div>
  );
}
