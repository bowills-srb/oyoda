export const queryKeys = {
  auth: {
    all: () => ["auth"] as const,
    session: () => [...queryKeys.auth.all(), "session"] as const,
  },
  autonomy: {
    all: () => ["autonomy"] as const,
    current: () => [...queryKeys.autonomy.all(), "current"] as const,
    portfolio: () => [...queryKeys.autonomy.all(), "portfolio"] as const,
  },
  prebooking: {
    all: () => ["prebooking"] as const,
    bootstrap: () => [...queryKeys.prebooking.all(), "bootstrap"] as const,
    feed: () => [...queryKeys.prebooking.all(), "feed"] as const,
  },
  today: {
    all: () => ["today"] as const,
    sessions: (params: Record<string, unknown>) => [...queryKeys.today.all(), "sessions", params] as const,
    sessionDetail: (sessionId: string) => [...queryKeys.today.all(), "session-detail", sessionId] as const,
    sessionActions: (sessionId: string) => [...queryKeys.today.all(), "session-actions", sessionId] as const,
    threadTimeline: (threadId: string) => [...queryKeys.today.all(), "thread-timeline", threadId] as const,
  },
  properties: {
    all: () => ["properties"] as const,
    roster: () => [...queryKeys.properties.all(), "roster"] as const,
    groups: () => [...queryKeys.properties.all(), "groups"] as const,
    identity: () => [...queryKeys.properties.all(), "identity"] as const,
    portfolios: () => [...queryKeys.properties.all(), "portfolios"] as const,
    gaps: (resolved: boolean) => [...queryKeys.properties.all(), "gaps", { resolved }] as const,
    kb: (knowledgeRef: string) => [...queryKeys.properties.all(), "kb", knowledgeRef] as const,
    assets: (propertyCode: string) => [...queryKeys.properties.all(), "assets", propertyCode] as const,
  },
  knowledge: {
    all: () => ["knowledge"] as const,
    entries: (property: string) => [...queryKeys.knowledge.all(), "entries", property] as const,
    gaps: (resolved: boolean) => [...queryKeys.knowledge.all(), "gaps", { resolved }] as const,
    guidance: () => [...queryKeys.knowledge.all(), "guidance"] as const,
    proposals: () => [...queryKeys.knowledge.all(), "proposals"] as const,
  },
  vendors: {
    all: () => ["vendors"] as const,
    categories: () => [...queryKeys.vendors.all(), "categories"] as const,
    list: (params: Record<string, unknown>) => [...queryKeys.vendors.all(), "list", params] as const,
  },
  escalations: {
    all: () => ["escalations"] as const,
    list: (params: Record<string, unknown>) => [...queryKeys.escalations.all(), "list", params] as const,
  },
  dashboard: {
    all: () => ["dashboard"] as const,
    summary: () => [...queryKeys.dashboard.all(), "summary"] as const,
  },
  settings: {
    all: () => ["settings"] as const,
    base: () => [...queryKeys.settings.all(), "base"] as const,
    alertRouting: () => [...queryKeys.settings.all(), "alert-routing"] as const,
    team: () => [...queryKeys.settings.all(), "team"] as const,
    teamScopes: (memberId: string) => [...queryKeys.settings.all(), "team-scopes", memberId] as const,
    portfolios: () => [...queryKeys.settings.all(), "portfolios"] as const,
    aiGuidance: () => [...queryKeys.settings.all(), "ai-guidance"] as const,
  },
} as const;
