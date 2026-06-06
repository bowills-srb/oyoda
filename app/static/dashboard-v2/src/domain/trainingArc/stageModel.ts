/**
 * Training Arc — the stage model.
 *
 * This is the synthesis layer that turns the existing per-property signals
 * into a single answer to the question an operator actually asks:
 *
 *   "Where is this employee in its training, and what unblocks the next step?"
 *
 * It invents NO new data. Every input here is already computed elsewhere:
 *   - completeness score  <- routes/Properties/completeness.ts (knowledge,
 *                            identity coverage, open gaps)
 *   - draft track record  <- dashboard-summary.pre_booking.draft_signals
 *                            (operator_draft_events: approved/edited/rejected)
 *   - automation state    <- PropertyRow.approvalMode ("auto"/"required"/"mixed")
 *   - traffic presence    <- whether the autonomy score could be computed
 *
 * The four stages mirror the agent arc:
 *   1. Onboard   - teach it what it needs to know
 *   2. Monitor   - watch it draft, correct it live, build a track record
 *   3. Automate  - turn it on; refine from afar
 *   4. Expand    - (portfolio concept) take the trained employee to new domains
 *
 * Graduation from Monitor -> Automate requires BOTH:
 *   - knowledge ready (completeness above threshold)
 *   - a proven draft track record (enough approvals, low edit/reject rate)
 * Knowledge without a track record is an untested library; a track record
 * without knowledge is luck that breaks on the first unusual question.
 *
 * Kept as a pure module (no React, no fetch) so it can be unit-tested in
 * isolation and reused by Properties, Home, and Inquiry Ops alike.
 */

// -- Stage vocabulary ----------------------------------------------------------

export type TrainingStage =
  | "insufficient_signal"
  | "onboard"
  | "monitor"
  | "automate";

/**
 * Draft track record for a property (or the portfolio, until per-property
 * draft signals exist). Mirrors dashboard-summary.pre_booking.draft_signals.
 */
export interface DraftTrackRecord {
  approved: number;
  edited: number;
  rejected: number;
}

/**
 * The minimum inputs the stage model needs. Callers assemble this from a
 * PropertyRow + completeness result + draft signals - all already on hand.
 */
export interface StageInputs {
  /** Documentation-health score in [0,1] from calculateCompleteness(). */
  completenessScore: number;
  /** Whether enough guest traffic exists to judge readiness at all. */
  hasTraffic: boolean;
  /** Approval mode from the property row. */
  approvalMode: string; // "auto" | "required" | "mixed"
  /** Draft outcomes. Portfolio-level today; per-property when available. */
  draftRecord: DraftTrackRecord;
  /** True when draftRecord is portfolio-wide, not specific to this property. */
  draftRecordIsPortfolioWide: boolean;
}

// -- Thresholds (single source of truth) ---------------------------------------
//
// These mirror the bucket cutoffs already used elsewhere so the arc never
// disagrees with the labels operators see on other surfaces:
//   - 0.70 is the "well-documented" / "Autonomous" completeness cutoff
//     (routes/Properties/completeness.ts and readiness.ts).
// The draft-record bar is new but deliberately conservative: we don't want
// to tell an operator a property is ready-to-automate on a thin record.

export const KNOWLEDGE_READY_THRESHOLD = 0.7;

/** Minimum approved drafts before a track record counts as "proven". */
export const MIN_APPROVALS_FOR_TRACK_RECORD = 10;

/**
 * Maximum share of reviewed drafts that were edited or rejected for the
 * record to count as "good". An employee whose drafts the operator keeps
 * rewriting has not earned automation, however many it has produced.
 */
export const MAX_INTERVENTION_RATE = 0.2;

// -- Derived signals -----------------------------------------------------------

export interface TrackRecordVerdict {
  /** Total reviewed drafts (approved + edited + rejected). */
  total: number;
  /** Approvals that needed no operator change. */
  approved: number;
  /** Share of reviewed drafts the operator had to edit or reject. */
  interventionRate: number;
  /** True when the record clears both volume and quality bars. */
  isProven: boolean;
}

export function evaluateTrackRecord(record: DraftTrackRecord): TrackRecordVerdict {
  const approved = Math.max(0, record.approved || 0);
  const edited = Math.max(0, record.edited || 0);
  const rejected = Math.max(0, record.rejected || 0);
  const total = approved + edited + rejected;

  const interventionRate = total > 0 ? (edited + rejected) / total : 1;
  const isProven =
    approved >= MIN_APPROVALS_FOR_TRACK_RECORD &&
    interventionRate <= MAX_INTERVENTION_RATE;

  return { total, approved, interventionRate, isProven };
}

export function isKnowledgeReady(completenessScore: number): boolean {
  return completenessScore >= KNOWLEDGE_READY_THRESHOLD;
}

// -- Stage resolution ----------------------------------------------------------

export interface StageResult {
  stage: TrainingStage;
  /** 1-based index for progress display; insufficient_signal is 0. */
  stageIndex: number;
  /** What this stage means, in the operator's language. */
  summary: string;
  /** The single most useful next action to advance the arc. */
  nextStep: string;
  /** Supporting signals so the UI can show *why* without recomputing. */
  signals: {
    knowledgeReady: boolean;
    trackRecord: TrackRecordVerdict;
    isAutomated: boolean;
  };
}

const STAGE_INDEX: Record<TrainingStage, number> = {
  insufficient_signal: 0,
  onboard: 1,
  monitor: 2,
  automate: 3,
};

/**
 * Resolve a property's training stage from its signals.
 *
 * Order of checks matters:
 *  1. Automation already on  -> Automate (regardless of score; the operator
 *     made the call, and we surface refinement, not graduation).
 *  2. No traffic at all      -> Insufficient signal (NOT a failing onboard).
 *  3. Knowledge not ready    -> Onboard (teach it more before monitoring).
 *  4. Knowledge ready, record
 *     not yet proven         -> Monitor (it knows enough; now watch it work).
 *  5. Knowledge ready AND
 *     record proven          -> Monitor, flagged ready-to-automate (the
 *     graduation moment - both conditions met, operator's decision to flip).
 */
export function resolveStage(inputs: StageInputs): StageResult {
  const trackRecord = evaluateTrackRecord(inputs.draftRecord);
  const knowledgeReady = isKnowledgeReady(inputs.completenessScore);
  const isAutomated = (inputs.approvalMode || "").toLowerCase() === "auto";

  const signals = { knowledgeReady, trackRecord, isAutomated };

  if (isAutomated) {
    return {
      stage: "automate",
      stageIndex: STAGE_INDEX.automate,
      summary: "Answering on its own. You drop in to refine, not to run it.",
      nextStep:
        "Review corrections and approved proposals so it keeps getting more confident.",
      signals,
    };
  }

  if (!inputs.hasTraffic) {
    return {
      stage: "insufficient_signal",
      stageIndex: STAGE_INDEX.insufficient_signal,
      summary: "No guest traffic yet - not enough signal to judge readiness.",
      nextStep:
        "Add core property knowledge now so it's ready when the first inquiries arrive.",
      signals,
    };
  }

  if (!knowledgeReady) {
    return {
      stage: "onboard",
      stageIndex: STAGE_INDEX.onboard,
      summary: "Still learning this property. Teach it before you rely on it.",
      nextStep: "Fill the open knowledge gaps and add missing property details.",
      signals,
    };
  }

  // Knowledge is ready from here on. The remaining question is the record.
  if (trackRecord.isProven) {
    return {
      stage: "monitor",
      stageIndex: STAGE_INDEX.monitor,
      summary:
        "Knows the property and has a strong draft record - ready to automate.",
      nextStep: inputs.draftRecordIsPortfolioWide
        ? "Track record is portfolio-wide for now; flip autonomy on when you're comfortable."
        : "Turn autonomy on for this property when you're comfortable.",
      signals,
    };
  }

  return {
    stage: "monitor",
    stageIndex: STAGE_INDEX.monitor,
    summary: "Knows the property. Watch its drafts and correct as it works.",
    nextStep:
      trackRecord.total === 0
        ? "Review its first drafts in the focus queue to start building a track record."
        : "Keep reviewing drafts - a few more clean approvals and it's ready to automate.",
    signals,
  };
}

// -- Display helpers -----------------------------------------------------------

export const STAGE_LABELS: Record<
  TrainingStage,
  { display: string; tone: "success" | "warning" | "danger" | "muted" | "accent" }
> = {
  insufficient_signal: { display: "Insufficient signal", tone: "muted" },
  onboard: { display: "Onboarding", tone: "danger" },
  monitor: { display: "Monitoring", tone: "warning" },
  automate: { display: "Automated", tone: "success" },
};

/** Ordered stages for rendering a 3-step progress rail (excludes the
 * insufficient-signal pre-state, which renders as an empty rail). */
export const STAGE_SEQUENCE: TrainingStage[] = ["onboard", "monitor", "automate"];

/**
 * Whether a monitored property has met BOTH graduation conditions and is
 * waiting only on the operator's decision to flip autonomy on.
 */
export function isReadyToAutomate(result: StageResult): boolean {
  return (
    result.stage === "monitor" &&
    result.signals.knowledgeReady &&
    result.signals.trackRecord.isProven
  );
}

// -- Portfolio verdict (the cockpit headline) ----------------------------------
//
// Turns the portfolio-wide draft track record into the single plain-language
// sentence the operator sees first: how often the AI's draft matched what they
// would have sent, and whether that earns more autonomy. This is the "how's my
// AI doing" brain, kept here so the headline copy is testable and consistent.

export type VerdictTone = "ready" | "developing" | "early" | "insufficient";

export interface PortfolioVerdict {
  tone: VerdictTone;
  /** Match rate as a fraction [0,1]; null when there's no signal yet. */
  matchRate: number | null;
  /** Count of drafts the operator sent unchanged. */
  matched: number;
  /** Total reviewed drafts. */
  total: number;
  /** The headline sentence. */
  headline: string;
  /** The supporting line under the headline. */
  detail: string;
  /** The single recommended action label, or null when none applies. */
  actionLabel: string | null;
}

/**
 * "Match" = the operator sent the AI's draft unchanged (approved). Edits and
 * rejects are misses the AI can learn from. Match rate is the share of
 * reviewed drafts that needed no operator change - the truest proxy for
 * "would I have sent what it wrote?"
 */
export function portfolioVerdict(
  record: DraftTrackRecord | null,
  autoEnabled: boolean,
): PortfolioVerdict {
  const approved = Math.max(0, record?.approved ?? 0);
  const edited = Math.max(0, record?.edited ?? 0);
  const rejected = Math.max(0, record?.rejected ?? 0);
  const total = approved + edited + rejected;
  const matchRate = total > 0 ? approved / total : null;
  const pct = matchRate != null ? Math.round(matchRate * 100) : null;

  if (total < MIN_APPROVALS_FOR_TRACK_RECORD || matchRate == null) {
    return {
      tone: "insufficient",
      matchRate,
      matched: approved,
      total,
      headline: "Still gathering evidence on your AI.",
      detail:
        total === 0
          ? "Once it has drafted a handful of replies you'll see how often they match what you'd send."
          : `${approved} of ${total} drafts matched so far - a few more and there's enough to judge.`,
      actionLabel: null,
    };
  }

  if (matchRate >= 1 - MAX_INTERVENTION_RATE && !autoEnabled) {
    return {
      tone: "ready",
      matchRate,
      matched: approved,
      total,
      headline: `Your AI matched what you'd send ${pct}% of the time.`,
      detail:
        "Strong enough to handle routine pre-booking replies on its own. You can step back and just spot-check.",
      actionLabel: "Let it send on its own",
    };
  }

  if (matchRate >= 1 - MAX_INTERVENTION_RATE && autoEnabled) {
    return {
      tone: "ready",
      matchRate,
      matched: approved,
      total,
      headline: `Your AI is sending on its own and matching ${pct}% of the time.`,
      detail: "Running well. Drop in to review the misses and keep it sharp.",
      actionLabel: "Review the misses",
    };
  }

  if (matchRate >= 0.6) {
    return {
      tone: "developing",
      matchRate,
      matched: approved,
      total,
      headline: `Your AI matched what you'd send ${pct}% of the time.`,
      detail:
        "Close, but not yet hands-off. Review the edits it needed - each one teaches it.",
      actionLabel: "Review the misses",
    };
  }

  return {
    tone: "early",
    matchRate,
    matched: approved,
    total,
    headline: `Your AI matched what you'd send ${pct}% of the time.`,
    detail:
      "Early days. Keep correcting its drafts and feeding it property knowledge - the match rate climbs as it learns.",
    actionLabel: "See what to teach it",
  };
}
