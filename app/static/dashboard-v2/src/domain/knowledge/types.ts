export type KnowledgeEntry = {
  id: string;
  parentId: string;
  faqIndex: number;
  question: string;
  answer: string;
  confidence: number;
  category: string;
  usageCount: number;
  propertyId: string | null;
  propertyLabel: string;
  source: string;
  updatedAt: string | null;
};

export type KnowledgeGap = {
  id: string;
  question: string;
  category: string;
  categorySlug: string;
  confidence: number;
  aiAnswer: string;
  stage: string;
  channel: string;
  source: string;
  resolved: boolean;
  property: string;
  askCount: number;
  createdAt: string | null;
  draftId: string;
  reason: string;
  intent: string;
  thresholdPct: number | null;
  actualPct: number | null;
  missingTopics: string[];
  parserSource: string;
  asks: string[];
  platformListingId: string;
  platformUnitId: string;
  linkContextSummary: string;
  policyWarnings: string[];
  lastAskedAt: string | null;
};

export type KnowledgeGuidance = {
  guidanceText: string;
  updatedBy: string | null;
  updatedAt: string | null;
  charLimit: number;
};

export type KnowledgeTestResult = {
  answered: boolean;
  confidence: number;
  answer: string;
  sources: string[];
  matchQuestion: string;
};
