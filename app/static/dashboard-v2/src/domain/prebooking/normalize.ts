import type { MessageFeed, MessageFeedProperty, MessageFeedPropertyBindingCandidate, MessageFeedItem } from "./types";

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

function parseBool(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  const normalized = safeString(value).trim().toLowerCase();
  if (!normalized) return false;
  if (["false", "0", "off", "no", "null", "undefined"].includes(normalized)) return false;
  if (["true", "1", "on", "yes"].includes(normalized)) return true;
  return false;
}

function normalizePropertyBindingCandidate(candidate: Record<string, unknown>): MessageFeedPropertyBindingCandidate {
  return {
    candidateType: safeString(candidate.candidate_type),
    value: safeString(candidate.value),
    confidence: safeNumber(candidate.confidence),
    source: safeString(candidate.source),
  };
}

function normalizeMessageFeedItem(item: Record<string, unknown>): MessageFeedItem {
  return {
    id: safeString(item.id || item.draft_id),
    kind: safeString(item.kind, "inquiry"),
    stage: safeString(item.stage, "pre_booking"),
    status: safeString(item.status, "pending_review"),
    channel: safeString(item.channel, "email"),
    sourceProvider: safeString(item.source_provider),
    guestName: safeString(item.guest_name, "Guest"),
    guestEmail: safeString(item.guest_email),
    guestPhone: safeString(item.guest_phone),
    messageText: safeString(item.message_text),
    latestGuestTurn: safeString(item.latest_guest_turn || item.message_text),
    priorThreadContext: safeString(item.prior_thread_context),
    messagePreview: safeString(item.message_preview),
    draftText: safeString(item.draft_text),
    draftPreview: safeString(item.draft_preview),
    finalReply: safeString(item.final_reply),
    intent: safeString(item.intent, "general"),
    asks: safeArray(item.asks).map((ask) => safeString(ask)),
    parserSource: safeString(item.parser_source),
    platformListingId: safeString(item.platform_listing_id),
    platformUnitId: safeString(item.platform_unit_id),
    propertyBindingCandidates: safeArray<Record<string, unknown>>(item.property_binding_candidates).map(
      normalizePropertyBindingCandidate,
    ),
    priorOperatorCommitments: safeArray(item.prior_operator_commitments),
    propertyMatchType: safeString(item.property_match_type),
    routeOutcome: safeString(item.route_outcome),
    autonomyDecision: safeString(item.autonomy_decision),
    fallbackReason: safeString(item.fallback_reason),
    latestTurnConfidence: safeNumber(item.latest_turn_confidence),
    latestTurnExtracted: Boolean(item.latest_turn_extracted),
    confidence: safeNumber(item.confidence),
    confidenceSource: safeString(item.confidence_source),
    draftSource: safeString(item.draft_source),
    confidenceLabel: safeString(item.confidence_label),
    confidenceNote: safeString(item.confidence_note),
    draftReady: Boolean(item.draft_ready),
    propertyId: safeString(item.property_id || item.property_external_id || item.property_code),
    propertyName: safeString(item.property_name, "Unknown property"),
    checkIn: (item.check_in as string | null | undefined) || null,
    checkOut: (item.check_out as string | null | undefined) || null,
    occurredAt: (item.occurred_at as string | null | undefined) || (item.received_at as string | null | undefined) || null,
    repliedAt: (item.replied_at as string | null | undefined) || null,
    policyFlags: safeArray(item.policy_flags).map((flag) => safeString(flag)),
    policyWarnings: safeArray(item.policy_warnings).map((flag) => safeString(flag)),
    blockedByGapTopics: safeArray(item.blocked_by_gap_topics).map((topic) => safeString(topic)),
    triggeredBy: safeString(item.triggered_by),
    gmailMessageId: safeString(item.gmail_message_id),
    threadRef: safeString(item.thread_ref),
    sessionToken: safeString(item.session_token),
    priority: safeString(item.priority),
    assignedOperatorId: safeString(item.assigned_operator_id),
    assignedTeamKey: safeString(item.assigned_team_key),
    portfolioKey: safeString(item.portfolio_key),
    assignmentStatus: safeString(item.assignment_status, "unassigned"),
  };
}

function normalizeProperty(property: Record<string, unknown>): MessageFeedProperty {
  return {
    id: safeString(property.id),
    name: safeString(property.name, safeString(property.id)),
    count: safeNumber(property.count),
  };
}

export function normalizePreBookingMessageFeed(payload: Record<string, unknown> = {}): MessageFeed {
  const items = safeArray<Record<string, unknown>>(payload.items).map(normalizeMessageFeedItem);

  return {
    count: safeNumber(payload.count, items.length),
    stage: safeString(payload.stage, "all"),
    status: safeString(payload.status, "all"),
    property: safeString(payload.property),
    unboundOnly: parseBool(payload.unbound_only),
    shipIKbRetryPrimary: parseBool(payload.ship_i_kb_retry_primary),
    unboundCount: safeNumber(payload.unbound_count, items.filter((item) => !item.propertyId).length),
    items,
    stageCounts: (payload.stage_counts as Record<string, number>) || {},
    properties: safeArray<Record<string, unknown>>(payload.properties).map(normalizeProperty),
  };
}
