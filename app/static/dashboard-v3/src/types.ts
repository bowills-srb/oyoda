/*
  The shape of what the employee tells Lanier.

  Two kinds of items share one screen:
    - FeedUpdate  — something I already did, decided, or noticed (left panel)
    - Decision    — something I need a word from you on before I proceed (center)

  Both can be opened in the Context Drawer, which always answers the same
  three questions: what I saw, how I thought about it, what I did / propose.

  Every item carries the `channel` it would be delivered through, so the
  communication style can be reviewed before those channels are wired up.
*/

export type Channel = "text" | "email" | "voice";

export type Priority = "high" | "medium" | "low";

/** Coarse tag for the left feed, drives the small category label. */
export type UpdateTag = "handled" | "resolved" | "noticed" | "booking" | "checkin";

export interface DataPoint {
  label: string;
  value: string;
}

/** A drafted communication — the actual words, so tone can be evaluated. */
export interface Draft {
  channel: Channel;
  /** Who it's addressed to (a guest, a vendor, an owner). */
  to: string;
  /** Email only. */
  subject?: string;
  body: string;
  /** True once I've actually sent/placed it; false if it's only proposed. */
  sent: boolean;
}

/** The reasoning shown in the drawer. */
export interface Reasoning {
  /** The data I leaned on. */
  observed: DataPoint[];
  /** How I thought about it, in my own words. */
  thought: string;
}

export interface FeedUpdate {
  kind: "update";
  id: string;
  channel: Channel;
  /** ISO timestamp. */
  at: string;
  tag: UpdateTag;
  property: string;
  guest?: string;
  /** First-person one-liner shown in the feed. The writing is the UI. */
  summary: string;
  reasoning: Reasoning;
  /** What I decided. */
  decision: string;
  /** What actually happened as a result. */
  outcome: string;
  draft?: Draft;
  /** Ids of guidance rules that shaped how I handled this. */
  governedBy?: string[];
}

export interface DecisionOption {
  id: string;
  label: string;
  kind: "approve" | "alternative" | "decline";
  /** First-person note logged to the feed if Lanier picks this. */
  resultSummary: string;
}

export interface Decision {
  kind: "decision";
  id: string;
  /** The channel I'd use to act on this once you decide. */
  channel: Channel;
  at: string;
  priority: Priority;
  property: string;
  guest?: string;
  /** The "quick question before I move forward." */
  ask: string;
  /** One extra line of context shown on the center card. */
  detail: string;
  /** A crisp phrasing of this for the morning brief, if it's brief-worthy. */
  briefLine?: string;
  reasoning: Reasoning;
  /** What I'd do if you just said "go." */
  proposal: string;
  draft?: Draft;
  options: DecisionOption[];
  /** Ids of guidance rules I'm already applying to this situation. */
  governedBy?: string[];
}

export type WorkItem = FeedUpdate | Decision;

/**
 * A standing instruction Lanier has taught me. The teaching loop: every time
 * she corrects or redirects me, it becomes one of these — scoped, persistent,
 * and applied to future work.
 *
 * `scope` is a property name, or "*" for the whole portfolio.
 */
export type GuidanceScope = string;

export interface GuidanceRule {
  id: string;
  scope: GuidanceScope;
  instruction: string;
  createdAt: string;
  /** Where this came from, in my words ("You taught me on the Beach House AC"). */
  source: string;
}
