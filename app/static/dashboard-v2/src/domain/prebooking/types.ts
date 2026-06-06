export type MessageFeedPropertyBindingCandidate = {
  candidateType: string;
  value: string;
  confidence: number;
  source: string;
};

export type MessageFeedItem = {
  id: string;
  kind: string;
  stage: string;
  status: string;
  channel: string;
  sourceProvider: string;
  guestName: string;
  guestEmail: string;
  guestPhone: string;
  messageText: string;
  latestGuestTurn: string;
  priorThreadContext: string;
  messagePreview: string;
  draftText: string;
  draftPreview: string;
  finalReply: string;
  intent: string;
  asks: string[];
  parserSource: string;
  platformListingId: string;
  platformUnitId: string;
  propertyBindingCandidates: MessageFeedPropertyBindingCandidate[];
  priorOperatorCommitments: unknown[];
  propertyMatchType: string;
  routeOutcome: string;
  autonomyDecision: string;
  fallbackReason: string;
  latestTurnConfidence: number;
  latestTurnExtracted: boolean;
  confidence: number;
  confidenceSource: string;
  draftSource: string;
  confidenceLabel: string;
  confidenceNote: string;
  draftReady: boolean;
  propertyId: string;
  propertyName: string;
  checkIn: string | null;
  checkOut: string | null;
  occurredAt: string | null;
  repliedAt: string | null;
  policyFlags: string[];
  policyWarnings: string[];
  blockedByGapTopics: string[];
  triggeredBy: string;
  gmailMessageId: string;
  threadRef: string;
  sessionToken: string;
  priority: string;
  assignedOperatorId: string;
  assignedTeamKey: string;
  portfolioKey: string;
  assignmentStatus: string;
};

export type MessageFeedProperty = {
  id: string;
  name: string;
  count: number;
};

export type MessageFeed = {
  count: number;
  stage: string;
  status: string;
  property: string;
  unboundOnly: boolean;
  shipIKbRetryPrimary: boolean;
  unboundCount: number;
  items: MessageFeedItem[];
  stageCounts: Record<string, number>;
  properties: MessageFeedProperty[];
};

export type BootstrapPayload = {
  operator?: {
    id?: string;
    name?: string;
    email?: string;
  };
  tenant?: {
    id?: string;
    name?: string;
  };
  inquiries?: unknown[];
  properties?: unknown[];
  autonomy?: import("../autonomy/types").AutonomyPayload;
};

export type PropertyMatchSuggestion = {
  property_code?: string;
  property_name?: string;
  address_street?: string;
  community?: string;
  external_id?: string;
  score?: number;
  matched_on?: string;
  matched_value?: string;
};

export type PropertySuggestionResponse = {
  matches?: PropertyMatchSuggestion[];
};

export type BindPropertyInput = {
  property_code: string;
  selected_candidate_value: string;
  selected_candidate_type: string;
  search_query: string;
};

export type BindPropertyResult = {
  regenerated?: boolean;
  regenerate_error?: string | null;
};
