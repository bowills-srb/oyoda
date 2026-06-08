import { useMemo, useState } from "react";

import { ContextDrawer } from "./components/ContextDrawer";
import { EmployeeFeed } from "./components/EmployeeFeed";
import { NeedsInput } from "./components/NeedsInput";
import { Topbar } from "./components/Topbar";
import { DECISIONS, FEED, PORTFOLIO } from "./data/mock";
import { NOW } from "./lib/time";
import type { Decision, DecisionOption, FeedUpdate, WorkItem } from "./types";

export default function App() {
  const [feed, setFeed] = useState<FeedUpdate[]>(FEED);
  const [decisions, setDecisions] = useState<Decision[]>(DECISIONS);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selected: WorkItem | null = useMemo(() => {
    if (!selectedId) return null;
    return (
      decisions.find((d) => d.id === selectedId) ??
      feed.find((f) => f.id === selectedId) ??
      null
    );
  }, [selectedId, decisions, feed]);

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
      reasoning: {
        observed: [{ label: "Your call", value: decisionLine }],
        thought:
          "You made the call and I carried it out right away. Here’s exactly what I did, so there’s nothing ambiguous between us.",
      },
      decision: decisionLine,
      outcome: summary,
      draft: source.draft ? { ...source.draft, sent: true } : undefined,
    };
    setFeed((prev) => [entry, ...prev]);
    setDecisions((prev) => prev.filter((d) => d.id !== source.id));
    setSelectedId(entry.id);
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

  function handleCoach(update: FeedUpdate, note: string) {
    const entry: FeedUpdate = {
      kind: "update",
      id: `${update.id}-coach-${Date.now()}`,
      channel: update.channel,
      at: NOW.toISOString(),
      tag: "noticed",
      property: update.property,
      guest: update.guest,
      summary: `Noted. Going forward on ${update.property}, I’ll handle it your way: “${note}”.`,
      reasoning: {
        observed: [{ label: "New guidance", value: note }],
        thought:
          "You taught me something about how you want this handled. I’ve stored it and I’ll apply it the next time a situation like this comes up.",
      },
      decision: "Adopt your guidance for next time.",
      outcome: "Guidance saved. I’ll follow it from here.",
    };
    setFeed((prev) => [entry, ...prev]);
    setSelectedId(entry.id);
  }

  const handled = feed.filter((f) => f.tag !== "noticed").length;
  const watching = feed.filter((f) => f.tag === "noticed").length;
  const urgent = decisions.filter((d) => d.priority === "high").length;

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
      />
      <main className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)_minmax(0,0.96fr)] lg:overflow-hidden">
        <EmployeeFeed
          items={feed}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <NeedsInput
          items={decisions}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <ContextDrawer
          item={selected}
          handlers={{
            onClose: () => setSelectedId(null),
            onResolve: handleResolve,
            onRedirect: handleRedirect,
            onCoach: handleCoach,
          }}
        />
      </main>
    </div>
  );
}
