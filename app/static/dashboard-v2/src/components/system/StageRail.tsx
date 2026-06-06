/**
 * StageRail — the visible training arc for one property (or aggregate).
 *
 * Renders the onboard -> monitor -> automate progression as a compact
 * 3-step rail with the current stage emphasized, plus the operator-facing
 * "what's next" line. Styled exclusively with the Tailwind token utilities
 * the rest of v2 uses (bg-raised, border-hairline, text-tertiary, the
 * --success/--warning/--danger token families) so it stays on the same
 * design system as Home and Inquiry Ops - no hand-rolled CSS.
 *
 * Pure presentational: it takes a StageResult (already computed by
 * resolveStage) and draws it. No data fetching here.
 */
import type { CSSProperties } from "react";
import { cn } from "../../lib/utils";
import {
  STAGE_LABELS,
  STAGE_SEQUENCE,
  isReadyToAutomate,
  type StageResult,
} from "../../domain/trainingArc/stageModel";

type Props = {
  result: StageResult;
  /** Compact variant for dense rows; default is the fuller card treatment. */
  compact?: boolean;
};

const TONE_DOT: Record<string, string> = {
  success: "bg-[var(--success-spine)]",
  warning: "bg-[var(--warning-spine)]",
  danger: "bg-[var(--danger-spine)]",
  muted: "bg-border",
  accent: "bg-accent",
};

const TONE_TEXT: Record<string, string> = {
  success: "text-[var(--success-text)]",
  warning: "text-[var(--warning-text)]",
  danger: "text-[var(--danger-text)]",
  muted: "text-tertiary",
  accent: "text-accent",
};

export function StageRail({ result, compact = false }: Props) {
  const currentIndex = result.stageIndex; // 0 = insufficient, 1..3 = arc stages
  const readyToAutomate = isReadyToAutomate(result);

  return (
    <div className={cn("flex flex-col", compact ? "gap-1.5" : "gap-2.5")}>
      {/* Step rail */}
      <div className="flex items-center gap-1.5" aria-hidden>
        {STAGE_SEQUENCE.map((stage, i) => {
          const stepNumber = i + 1; // onboard=1, monitor=2, automate=3
          const reached = currentIndex >= stepNumber;
          const isCurrent = currentIndex === stepNumber;
          const label = STAGE_LABELS[stage];
          return (
            <div key={stage} className="flex items-center gap-1.5 flex-1 last:flex-none">
              <span
                className={cn(
                  "h-1.5 rounded-full transition-colors duration-200 flex-1 min-w-[20px]",
                  reached ? TONE_DOT[label.tone] : "bg-border/60",
                  isCurrent && "ring-2 ring-offset-1 ring-offset-transparent",
                )}
                style={
                  isCurrent
                    ? ({ ["--tw-ring-color" as string]: "var(--accent-glow)" } as CSSProperties)
                    : undefined
                }
              />
            </div>
          );
        })}
      </div>

      {/* Current stage label + ready flag */}
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 text-[11.5px] font-medium",
            TONE_TEXT[STAGE_LABELS[result.stage].tone],
          )}
        >
          <span
            className={cn("w-1.5 h-1.5 rounded-full", TONE_DOT[STAGE_LABELS[result.stage].tone])}
            aria-hidden
          />
          {STAGE_LABELS[result.stage].display}
        </span>
        {readyToAutomate && (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full bg-[var(--success-fill)] text-[var(--success-text)]">
            Ready to automate
          </span>
        )}
      </div>

      {!compact && (
        <>
          <p className="text-[12.5px] text-secondary leading-snug">{result.summary}</p>
          <p className="text-[12px] text-tertiary leading-snug">
            <span className="text-secondary font-medium">Next: </span>
            {result.nextStep}
          </p>
        </>
      )}
    </div>
  );
}
