/**
 * Properties route — shared type definitions.
 *
 * Lives in its own file because PropertiesRoute, PropertyExpansion, and
 * DocumentUploadForm all need the same shapes. Putting them here avoids
 * circular imports between sibling files and keeps each component file
 * focused on its own JSX/state logic.
 *
 * These shapes reflect what the audited backend actually returns
 * (see docs/PROPERTIES_V2_CONTRACT.md). They are not aspirational. If a
 * field is on this type, the backend exposes it today and we have the
 * citation in the contract doc.
 */

/**
 * One row in the Properties list.
 *
 * Composed client-side from /app/api/properties/autonomy +
 * /app/api/properties/identity-report. Autonomy gives us the base property
 * facts + the autonomy lanes; identity-report gives us the coverage signals
 * needed for the documentation-health heuristic.
 *
 * Reminder on identifier discipline (see Contract 1):
 *  - knowledgeRef is for KB and KB-gap lookups only
 *  - propertyCode is for asset list and document upload
 *  - id (the canonical UUID) is for any autonomy update calls
 * Do not collapse these into a single "property identifier" field.
 */
export interface PropertyRow {
  // Canonical row identity
  id: string;                  // properties.id UUID — used for autonomy updates
  propertyCode: string;        // e.g. "204SC" — used for assets and document upload
  externalId: string;          // often blank for Beach Habitats; some tenants populate

  // Identity / display
  propertyName: string;
  displayName: string;
  marketingName: string;
  addressStreet: string;
  addressCity: string;
  addressState: string;
  community: string;
  dataSource: string;          // PMS provider tag where available

  // Spec facts
  bedrooms: number | null;
  bathrooms: number | null;
  sleeps: number | null;
  hasPool: boolean;
  hasHotTub: boolean;
  petsAllowed: boolean;

  // Autonomy (read-only in commit A — surfaced in expansion only)
  approvalMode: string;        // "auto" | "required" | "mixed"
  minConfidenceForAuto: number;

  // Identity coverage (from identity-report.properties[])
  pmsPropertyIds: string[];
  pmsUnitCodes: string[];
  otaRefs: Record<string, string>;
  aliases: string[];
  knowledgeCount: number;
  assetCount: number;
  reviewStatusPending: number;
  profileUpdatedAt: string | null;  // ISO timestamp

  // The reference v2 uses for KB and KB-gap lookups. Per Contract 1, this
  // is propertyCode when present, externalId as a fallback. Per codex review,
  // we explicitly do NOT use this for asset list, document upload, or
  // autonomy updates — those keep their native identifiers.
  knowledgeRef: string;
}

/**
 * One open gap, after client-side filtering by knowledgeRef.
 *
 * Sourced from /app/api/kb-gaps (no server-side property filter today)
 * then grouped client-side by gap.property (which the backend sets from
 * property_external_id). Per Contract 4's runtime finding, some related
 * gaps remain unbound — they don't appear in any property's gap list.
 */
export interface PropertyGap {
  id: string;
  question: string;
  category: string;
  categorySlug: string;       // detected_intent slug; sent as retry_topic on resolve
  property: string;            // the raw property reference from kb_gap; matches knowledgeRef when bound
  missingTopics: string[];
  askCount: number;
  reason: string;
  createdAt: string | null;
  lastAskedAt: string | null;
}

/**
 * One KB entry shown in the per-property expansion.
 */
export interface PropertyKbEntry {
  id: string;
  question: string;
  answer: string;
  category: string;
  confidence: number;
  usageCount: number;
  updatedAt: string | null;
}

/**
 * One asset record per property (HVAC unit, appliance warranty, etc.).
 */
export interface PropertyAsset {
  assetId: string;
  assetType: string;
  assetName: string;
  manufacturer: string;
  modelNumber: string;
  serialNumber: string;
  status: string;
  warrantyEndDate: string | null;
  installDate: string | null;
  lastServiceAt: string | null;
  notes: string;
  updatedAt: string | null;
}

/**
 * One portfolio (used for the filter dropdown).
 */
export interface PortfolioOption {
  portfolioKey: string;
  displayName: string;
  propertyCount: number;
  propertyExternalIds: string[];
}

/**
 * Inputs to the documentation-health heuristic. Defined in Contract 3.
 * Kept as its own type so completeness.ts has a clean function signature
 * and so the heuristic can be tested independently.
 */
export interface CompletenessInputs {
  hasDisplayName: boolean;
  hasMarketingName: boolean;
  hasPmsPropertyId: boolean;
  hasPmsUnitCode: boolean;
  hasAnyOtaRef: boolean;
  knowledgeCount: number;
  assetCount: number;
  hasRecentProfileUpdate: boolean;
  hasAlias: boolean;
  hasPendingIdentityReview: boolean;
  hasOpenGap: boolean;
}

export interface CompletenessBreakdownItem {
  label: string;
  contribution: number;
}

/**
 * Output of the heuristic. Score is clamped [0, 1]; label buckets the
 * score for UI rendering.
 *
 * Bucket thresholds (codex-approved for commit A):
 *  - score >= 0.70 → "well-documented"
 *  - score >= 0.40 → "has-gaps"
 *  - score <  0.40 → "bare-bones"
 */
export interface CompletenessResult {
  score: number;
  label: "well-documented" | "has-gaps" | "bare-bones";
  breakdown?: {
    positives: CompletenessBreakdownItem[];
    negatives: CompletenessBreakdownItem[];
  };
}

/**
 * Document type taxonomy. Matches the v1 dropdown options. The backend
 * accepts these strings as `document_type` form fields.
 */
export type DocumentType =
  | "house_manual"
  | "amenities"
  | "guest_qa"
  | "rental_agreement"
  | "equipment_warranty"
  | "appliance_manual"
  | "portfolio_policy"
  | "misc";

/**
 * Document upload form state. Each field maps directly to a multipart
 * field that api.propertyDocuments.upload() will send. The UI constraint
 * around (target=asset|both + scope=portfolio) lives in DocumentUploadForm,
 * not on this type — the type allows the full backend matrix, the form
 * narrows it.
 */
export interface DocumentUploadState {
  file: File | null;
  documentType: DocumentType;
  target: "knowledge" | "asset" | "both";
  scope: "property" | "portfolio";
  assetType: string;
  assetName: string;
  status: "idle" | "uploading" | "error" | "success";
  errorMessage: string;
  lastUploadFilename: string;  // for the success-toast / confirmation copy
}

/**
 * Optional upload defaults when the form is opened from a specific gap.
 * The upload endpoint does not accept a KB category directly, so this preset
 * is the bridge between the gap context and the document-upload controls:
 * we can pre-select the closest document type, keep the scope property-bound,
 * and tag the source label for observability without inventing a new API.
 */
export interface DocumentUploadPreset {
  contextKey: string;
  documentType: DocumentType;
  target: "knowledge" | "asset" | "both";
  scope: "property" | "portfolio";
  sourceLabel: string;
  helperText?: string;
}

/**
 * Canonical response from /app/api/properties/documents/import.
 *
 * We keep the backend's snake_case field names here because the JS API
 * client returns the payload as-is. The properties UI only reads the
 * small subset needed to decide whether a gap can be auto-resolved after
 * upload or whether the document was merely staged for review.
 */
export interface PropertyDocumentUploadResult {
  ok: boolean;
  filename: string;
  document_type: string;
  scope: string;
  target: string;
  warnings?: string[];
  knowledge_result?: {
    updated?: boolean;
    auto_promoted_count?: number;
    staged_for_review_count?: number;
  } | null;
  guest_qa_result?: {
    imported_answers?: number;
    imported_gaps?: number;
    skipped?: number;
    total_records?: number;
  } | null;
  asset_result?: {
    asset_id?: string;
    auto_promoted?: boolean;
    staged_for_review?: boolean;
  } | null;
}

/**
 * Shape of the in-progress note creator for the per-property KB add form.
 * Kept on the route's state so the form can be re-opened with prior text
 * if a network error interrupts submission.
 */
export interface NoteDraft {
  question: string;
  answer: string;
  category: string;
}
