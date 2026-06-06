export type TodayWorkflow = {
  [key: string]: unknown;
  proactive?: {
    touch_type?: string;
    message?: string;
    backoff_reason?: string;
    eligible?: boolean;
  };
  turnover: {
    [key: string]: unknown;
    readyForNextGuest: boolean;
    assignedVendorId: string;
    assignedVendorName: string;
    startedAt: string | null;
    readyAt: string | null;
    archivedAt: string | null;
    updatedAt: string | null;
    updatedBy: string;
  };
  operationalState: string;
  archiveEligible: boolean;
};

export type TodaySession = {
  sessionId: string;
  token: string;
  guestName: string;
  guestPhone: string;
  guestEmail: string;
  propertyCode: string;
  propertyName: string;
  numGuests: number;
  checkIn: string | null;
  checkOut: string | null;
  status: string;
  phase: string;
  conversationCount: number;
  lastMessageAt: string | null;
  openEscalations: number;
  reservationId: string;
  pmsSyncedAt: string | null;
  proactiveTriggeredAt: string | null;
  hasBookingContext: boolean;
  journeyTracked: boolean;
  welcomeSent: boolean;
  checkinReminderSent: boolean;
  checkoutReminderSent: boolean;
  extendOfferSent: boolean;
  poolHeatOffered: boolean;
  poolHeatAccepted: boolean;
  notificationsSent: number;
  assignedOperatorId: string;
  assignedOperatorLabel: string;
  openHandoffCount: number;
  assignmentStatus: string;
  workflow: TodayWorkflow;
};

export type TodaySessionsSummary = {
  all: number;
  inStay: number;
  arriving: number;
  postStay: number;
  archived: number;
  withBookingContext: number;
  journeyTracked: number;
  proactiveEvaluated: number;
  notificationsSent: number;
};

export type TodaySessionsList = {
  sessions: TodaySession[];
  count: number;
  summary: TodaySessionsSummary;
};

export type StayAction = {
  actionType: string;
  status: string;
  priority: string;
  propertyCode: string;
  payload: {
    message_text?: string;
    [key: string]: unknown;
  };
  result: {
    replaced?: number;
    [key: string]: unknown;
  };
  dueAt: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  completedAt: string | null;
};

export type StayActions = {
  sessionId: string;
  actions: StayAction[];
  count: number;
};

export type ThreadTimelineItem = {
  itemType: string;
  itemId: string;
  propertyCode: string;
  guestName: string;
  summary: string;
  status: string;
  threadRef: string;
  occurredAt: string | null;
};

export type ThreadTimeline = {
  guestThreadId: string;
  guestName: string;
  propertyCodes: string[];
  timeline: ThreadTimelineItem[];
  count: number;
};

export type SessionDetail = {
  session: {
    sessionId: string;
    guestThreadId: string;
    token: string;
    guestName: string;
    guestPhone: string;
    guestEmail: string;
    propertyCode: string;
    propertyName: string;
    numGuests: number;
    checkIn: string | null;
    checkOut: string | null;
    status: string;
    phase: string;
    conversationCount: number;
    lastMessageAt: string | null;
    proactiveTriggeredAt: string | null;
    pmsSyncedAt: string | null;
    reservationId: string;
  };
  bookingContext: {
    available: boolean;
    source: string;
    provider: string;
    matchStrategy: string;
    guestIdentityAvailable: boolean;
    property: unknown | null;
    booking: unknown | null;
    activeBooking: unknown | null;
    nextBooking: unknown | null;
    upcomingBookings: unknown[];
    lookup: unknown | null;
  };
  postStayActions: {
    canRequestFeedback: boolean;
    feedbackPromptSuggestion: string;
    hasRepeatGuestMemory: boolean;
  };
  journey: {
    journeyId: string;
    welcomeSent: boolean;
    welcomeSentAt: string | null;
    extendOfferSent: boolean;
    extendOfferSentAt: string | null;
    extendOfferResponse: string;
    poolHeatOffered: boolean;
    poolHeatAccepted: boolean;
    checkinReminderSent: boolean;
    checkinReminderSentAt: string | null;
    checkoutReminderSent: boolean;
    checkoutReminderSentAt: string | null;
    activities: Array<{
      activityId: string;
      activityType: string;
      status: string;
      discussedAt: string | null;
      notes: string;
    }>;
  };
  messages: Array<{
    messageId: string;
    direction: string;
    content: string;
    contentType: string;
    intent: string;
    wasQuickAnswer: boolean;
    responseTimeMs: number | null;
    createdAt: string | null;
  }>;
  openEscalations: Array<{
    ticketId: string;
    reason: string;
    priority: string;
    status: string;
    summary: string;
    createdAt: string | null;
  }>;
  notifications: Array<{
    notificationId: string;
    notificationType: string;
    channel: string;
    recipient: string;
    status: string;
    sentAt: string | null;
    deliveredAt: string | null;
    externalId: string;
    errorMessage: string;
  }>;
  workOrders: Array<{
    workOrderId: string;
    workflowType: string;
    workflowRef: string;
    propertyCode: string;
    vendorId: string;
    vendorName: string;
    vendorPhone: string;
    issueCategory: string;
    status: string;
    priority: string;
    summary: string;
    details: string;
    dispatchState: string;
    etaMinutes: number | null;
    etaVisibilityMode: string;
    trackingUrl: string;
    lastKnownDistanceText: string;
    assetId: string;
    verificationState: string;
    invoiceState: string;
    invoiceAmount: number | null;
    invoiceReference: string;
    lastActorLabel: string;
    payload: Record<string, unknown>;
    resolution: Record<string, unknown>;
    createdAt: string | null;
    updatedAt: string | null;
    acceptedAt: string | null;
    scheduledAt: string | null;
    completedAt: string | null;
    verifiedAt: string | null;
    closedAt: string | null;
  }>;
  events: Array<{
    stayEventId: string;
    sessionId: string;
    sessionToken: string;
    propertyCode: string;
    eventType: string;
    eventDomain: string;
    status: string;
    source: string;
    note: string;
    payload: Record<string, unknown>;
    createdBy: string;
    occurredAt: string | null;
    createdAt: string | null;
    updatedAt: string | null;
  }>;
  workflow: TodayWorkflow;
  intentMix: Record<string, number>;
};

export type Escalation = {
  ticketId: string;
  sessionId: string;
  sessionToken: string;
  status: string;
  priority: string;
  guestUpdatedAt: string | null;
  guestUpdateStatus: string;
  createdAt: string | null;
};
