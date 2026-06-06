import type {
  KnowledgeEntry,
  KnowledgeGap,
  KnowledgeGuidance,
  KnowledgeTestResult,
} from "./types";

function safeArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function safeNumber(value: unknown, fallback = 0): number {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
}

function safeString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : value == null ? fallback : String(value);
}

export function normalizeKnowledgeEntries(payload: Record<string, unknown>): KnowledgeEntry[] {
  return safeArray<Record<string, unknown>>(payload.entries).map((entry) => ({
    id: safeString(entry.id),
    parentId: safeString(entry.parent_id),
    faqIndex: safeNumber(entry.faq_index, -1),
    question: safeString(entry.question),
    answer: safeString(entry.answer),
    confidence: safeNumber(entry.confidence, 0.9),
    category: safeString(entry.category, "General"),
    usageCount: safeNumber(entry.usage_count),
    propertyId: entry.property_id == null ? null : safeString(entry.property_id),
    propertyLabel: safeString(entry.property_label, "All Properties"),
    source: safeString(entry.source),
    updatedAt: (entry.updated_at as string | null | undefined) || null,
  }));
}

export function normalizeKnowledgeGaps(payload: Record<string, unknown>): KnowledgeGap[] {
  return safeArray<Record<string, unknown>>(payload.gaps).map((gap) => ({
    id: safeString(gap.gap_id || gap.id),
    question: safeString(gap.question),
    category: safeString(gap.category, "General"),
    categorySlug: safeString(gap.category_slug, "general"),
    confidence: safeNumber(gap.confidence),
    aiAnswer: safeString(gap.ai_answer),
    stage: safeString(gap.stage),
    channel: safeString(gap.channel),
    source: safeString(gap.source),
    resolved: Boolean(gap.resolved),
    property: safeString(gap.property, "All Properties"),
    askCount: safeNumber(gap.ask_count, 1),
    createdAt: (gap.created_at as string | null | undefined) || null,
    draftId: safeString(gap.draft_id),
    reason: safeString(gap.reason),
    intent: safeString(gap.intent),
    thresholdPct: gap.threshold_pct == null ? null : safeNumber(gap.threshold_pct),
    actualPct: gap.actual_pct == null ? null : safeNumber(gap.actual_pct),
    missingTopics: safeArray(gap.missing_topics).map(String),
    parserSource: safeString(gap.parser_source),
    asks: safeArray(gap.asks).map(String),
    platformListingId: safeString(gap.platform_listing_id),
    platformUnitId: safeString(gap.platform_unit_id),
    linkContextSummary: safeString(gap.link_context_summary),
    policyWarnings: safeArray(gap.policy_warnings).map(String),
    lastAskedAt:
      (gap.last_asked_at as string | null | undefined) ||
      (gap.created_at as string | null | undefined) ||
      null,
  }));
}

export function normalizeKnowledgeGuidance(payload: Record<string, unknown>): KnowledgeGuidance {
  return {
    guidanceText: safeString(payload.guidance_text),
    updatedBy: payload.updated_by == null ? null : safeString(payload.updated_by),
    updatedAt: (payload.updated_at as string | null | undefined) || null,
    charLimit: safeNumber(payload.char_limit, 8000),
  };
}

export function normalizeKnowledgeTestResult(payload: Record<string, unknown>): KnowledgeTestResult {
  return {
    answered: Boolean(payload.answered),
    confidence: safeNumber(payload.confidence),
    answer: safeString(payload.answer),
    sources: safeArray(payload.sources).map(String),
    matchQuestion: safeString(payload.match_question),
  };
}
