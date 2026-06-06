/**
 * Properties route — documentation-health heuristic.
 *
 * Implementation of Contract 3 from docs/PROPERTIES_V2_CONTRACT.md.
 * This is a frontend heuristic, not a backend truth. The UI labels it
 * "Documentation health (estimate)" so operators understand the score
 * is derived, not asserted.
 *
 * Formula:
 *   health =
 *     0.20 * has_display_name
 *   + 0.10 * has_marketing_name
 *   + 0.15 * has_pms_property_id
 *   + 0.10 * has_pms_unit_code
 *   + 0.10 * has_any_ota_ref
 *   + 0.15 * min(knowledge_count, 8) / 8
 *   + 0.08 * min(asset_count, 4) / 4
 *   + 0.07 * has_recent_profile_update
 *   + 0.05 * has_alias
 *   - 0.10 * has_pending_identity_review
 *   - 0.10 * has_open_gap
 *
 * Calibration checks (from Contract 4 spot-check):
 *   204 Spartina Cir: ~0.82 → "well-documented" (correct)
 *   bare new property: ~0.35 → "bare-bones" (correct)
 *
 * Bucket thresholds chosen so a property like 204SC (rich KB, no assets,
 * has open gaps) still reads as well-documented, while a property with
 * only PMS identity and a display name reads as bare-bones.
 */

import type {
  CompletenessBreakdownItem,
  CompletenessInputs,
  CompletenessResult,
  PropertyRow,
} from "./types";

const NINETY_DAYS_MS = 90 * 24 * 60 * 60 * 1000;

// Knowledge count gets capped at 8 so a single rich property doesn't make
// every other property look bare by comparison. 8 is the rough threshold
// above which a property has enough coverage for the brain to ground most
// guest questions.
const KNOWLEDGE_CAP = 8;

// Asset count gets capped at 4. Most properties only have a handful of
// trackable assets (HVAC, water heater, pool equipment, one or two
// appliance warranties). 4 covers a well-documented unit without
// requiring exhaustive paperwork.
const ASSET_CAP = 4;

/**
 * Calculate documentation health from already-derived boolean/count inputs.
 *
 * Kept as a pure function so it can be tested independently of any
 * PropertyRow shape. Callers should use deriveCompletenessInputs to build
 * the input from a PropertyRow + the per-property gap presence flag.
 */
export function calculateCompleteness(inputs: CompletenessInputs): CompletenessResult {
  const knowledgePart = Math.min(inputs.knowledgeCount, KNOWLEDGE_CAP) / KNOWLEDGE_CAP;
  const assetPart = Math.min(inputs.assetCount, ASSET_CAP) / ASSET_CAP;
  const positives: CompletenessBreakdownItem[] = [];
  const negatives: CompletenessBreakdownItem[] = [];

  function addPositive(active: boolean, label: string, contribution: number) {
    if (active) positives.push({ label, contribution });
  }

  function addScaledPositive(
    rawValue: number,
    cap: number,
    baseLabel: string,
    contributionWeight: number,
    unitLabel: string,
  ) {
    const clamped = Math.min(Math.max(rawValue, 0), cap);
    if (clamped <= 0) return;
    const contribution = contributionWeight * (clamped / cap);
    const countLabel = rawValue === 1 ? unitLabel : `${unitLabel}s`;
    positives.push({
      label: `${baseLabel} (${rawValue} ${countLabel}, capped at ${cap})`,
      contribution,
    });
  }

  function addNegative(active: boolean, label: string, contribution: number) {
    if (active) negatives.push({ label, contribution });
  }

  addPositive(inputs.hasDisplayName, "Display name", 0.20);
  addPositive(inputs.hasMarketingName, "Marketing name", 0.10);
  addPositive(inputs.hasPmsPropertyId, "PMS property ID", 0.15);
  addPositive(inputs.hasPmsUnitCode, "PMS unit code", 0.10);
  addPositive(inputs.hasAnyOtaRef, "OTA reference", 0.10);
  addScaledPositive(inputs.knowledgeCount, KNOWLEDGE_CAP, "Knowledge", 0.15, "entry");
  addScaledPositive(inputs.assetCount, ASSET_CAP, "Assets", 0.08, "asset");
  addPositive(inputs.hasRecentProfileUpdate, "Recent profile update", 0.07);
  addPositive(inputs.hasAlias, "Alias coverage", 0.05);
  addNegative(inputs.hasPendingIdentityReview, "Pending identity review", 0.10);
  addNegative(inputs.hasOpenGap, "Open gap", 0.10);

  let score =
    positives.reduce((sum, item) => sum + item.contribution, 0) -
    negatives.reduce((sum, item) => sum + item.contribution, 0);

  if (score < 0) score = 0;
  if (score > 1) score = 1;

  let label: CompletenessResult["label"];
  if (score >= 0.70) label = "well-documented";
  else if (score >= 0.40) label = "has-gaps";
  else label = "bare-bones";

  return { score, label, breakdown: { positives, negatives } };
}

/**
 * Build the heuristic inputs from a PropertyRow + the per-property
 * gap presence flag.
 *
 * The gap presence flag is passed in rather than derived from the row
 * because gaps come from a separate endpoint and are grouped client-side.
 * Keeping the dependency explicit makes it obvious that "open gap" status
 * needs to be supplied by the caller, not assumed.
 */
export function deriveCompletenessInputs(
  property: PropertyRow,
  hasOpenGap: boolean,
): CompletenessInputs {
  const profileUpdatedRecent =
    !!property.profileUpdatedAt &&
    Date.now() - new Date(property.profileUpdatedAt).getTime() < NINETY_DAYS_MS;

  return {
    hasDisplayName: !!property.displayName,
    hasMarketingName: !!property.marketingName,
    hasPmsPropertyId: property.pmsPropertyIds.length > 0,
    hasPmsUnitCode: property.pmsUnitCodes.length > 0,
    hasAnyOtaRef: Object.keys(property.otaRefs).length > 0,
    knowledgeCount: property.knowledgeCount,
    assetCount: property.assetCount,
    hasRecentProfileUpdate: profileUpdatedRecent,
    hasAlias: property.aliases.length > 0,
    hasPendingIdentityReview: property.reviewStatusPending > 0,
    hasOpenGap,
  };
}

/**
 * UI labels and tones for the three buckets. Centralized here so the
 * row, the metric strip, and any future surface that references the
 * label all stay in sync.
 */
export const COMPLETENESS_LABELS: Record<
  CompletenessResult["label"],
  { display: string; tone: "success" | "warning" | "danger" }
> = {
  "well-documented": { display: "Well-documented", tone: "success" },
  "has-gaps":        { display: "Has gaps",        tone: "warning" },
  "bare-bones":      { display: "Bare bones",      tone: "danger" },
};

/**
 * Tooltip copy explaining what's in the heuristic. Surfaced from a small
 * "?" affordance next to the chip. Kept here so the disclosure language
 * stays close to the formula it explains.
 */
export const COMPLETENESS_TOOLTIP =
  "Estimate based on identity coverage (display name, PMS IDs, OTA refs), " +
  "knowledge entries, asset records, recent profile updates, and open gaps. " +
  "Not a backend-certified score.";

export function formatCompletenessBreakdown(result: CompletenessResult): string {
  const positives = result.breakdown?.positives || [];
  const negatives = result.breakdown?.negatives || [];
  const parts = [
    ...positives.map((item) => `+${Math.round(item.contribution * 100)}% ${item.label}`),
    ...negatives.map((item) => `-${Math.round(item.contribution * 100)}% ${item.label}`),
  ];
  if (parts.length === 0) {
    return `${Math.round(result.score * 100)}% ${COMPLETENESS_LABELS[result.label].display}.`;
  }
  return `${parts.join(", ")} = ${Math.round(result.score * 100)}% ${COMPLETENESS_LABELS[result.label].display}.`;
}
