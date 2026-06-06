/**
 * READINESS_LABELS — human-facing strings for property readiness tiers.
 *
 * A-swap (autonomy verdicts, landed with per-property computation layer):
 * Keys are still the completeness label values from the KB coverage
 * calculation (well-documented / has-gaps / bare-bones) so the completeness
 * computation and filter logic are UNCHANGED. Only the display strings that
 * operators see have been re-keyed from coverage-readiness to autonomy verdicts.
 *
 * "insufficient-signal" is an explicit fourth state for properties where the
 * autonomy score could not be computed (no traffic yet). It must be shown
 * honestly — it is "no score," which is different from "Emerging" (low score).
 * A property that simply hasn't been used yet is NOT "Readiness Blocked."
 *
 * Per-property display in PropertiesRoute uses the inquiry_band from the
 * autonomy endpoint when available, falling back to the completeness label.
 */

export type ReadinessLabelKey = "well-documented" | "has-gaps" | "bare-bones" | "insufficient-signal";

export const READINESS_LABELS: Record<
  ReadinessLabelKey,
  {
    display: string;
    description: string;
    tone: "success" | "warning" | "danger" | "muted";
    filterOptionLabel: string;
  }
> = {
  "well-documented": {
    display: "Autonomous",
    description:
      "Strong coverage, few gaps — AI can handle routine questions without review",
    tone: "success",
    filterOptionLabel: "Autonomous",
  },
  "has-gaps": {
    display: "Developing",
    description: "Usable coverage but missing details that still create review burden",
    tone: "warning",
    filterOptionLabel: "Developing",
  },
  "bare-bones": {
    display: "Emerging",
    description: "Too little reliable context for consistent automation — needs KB work",
    tone: "danger",
    filterOptionLabel: "Emerging",
  },
  "insufficient-signal": {
    display: "Insufficient Signal",
    description:
      "Not enough guest traffic yet to compute a score — not the same as low readiness",
    tone: "muted",
    filterOptionLabel: "Insufficient Signal",
  },
};
