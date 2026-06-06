import type { Escalation, SessionDetail, StayActions, ThreadTimeline, TodaySessionsList, TodayWorkflow } from "./types";

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

function normalizeWorkflow(workflow: unknown): TodayWorkflow {
  const value = workflow && typeof workflow === "object" ? { ...(workflow as Record<string, unknown>) } : {};
  const turnover = value.turnover && typeof value.turnover === "object" ? (value.turnover as Record<string, unknown>) : {};
  return {
    ...value,
    turnover: {
      ...turnover,
      readyForNextGuest: Boolean(turnover.ready_for_next_guest),
      assignedVendorId: safeString(turnover.assigned_vendor_id),
      assignedVendorName: safeString(turnover.assigned_vendor_name),
      startedAt: (turnover.started_at as string | null | undefined) || null,
      readyAt: (turnover.ready_at as string | null | undefined) || null,
      archivedAt: (turnover.archived_at as string | null | undefined) || null,
      updatedAt: (turnover.updated_at as string | null | undefined) || null,
      updatedBy: safeString(turnover.updated_by),
    },
    operationalState: safeString(value.operational_state, "active"),
    archiveEligible: Boolean(value.archive_eligible),
  };
}

export function normalizeTodaySessionsList(payload: Record<string, unknown> = {}): TodaySessionsList {
  const sessions = safeArray<Record<string, unknown>>(payload.sessions).map((session) => ({
    sessionId: safeString(session.session_id),
    token: safeString(session.token),
    guestName: safeString(session.guest_name, "Guest"),
    guestPhone: safeString(session.guest_phone),
    guestEmail: safeString(session.guest_email),
    propertyCode: safeString(session.property_code),
    propertyName: safeString(session.property_name, "Unknown property"),
    numGuests: safeNumber(session.num_guests),
    checkIn: (session.check_in as string | null | undefined) || null,
    checkOut: (session.check_out as string | null | undefined) || null,
    status: safeString(session.status, "active"),
    phase: safeString(session.phase),
    conversationCount: safeNumber(session.conversation_count),
    lastMessageAt: (session.last_message_at as string | null | undefined) || null,
    openEscalations: safeNumber(session.open_escalations),
    reservationId: safeString(session.reservation_id),
    pmsSyncedAt: (session.pms_synced_at as string | null | undefined) || null,
    proactiveTriggeredAt: (session.proactive_triggered_at as string | null | undefined) || null,
    hasBookingContext: Boolean(session.has_booking_context),
    journeyTracked: Boolean(session.journey_tracked),
    welcomeSent: Boolean(session.welcome_sent),
    checkinReminderSent: Boolean(session.checkin_reminder_sent),
    checkoutReminderSent: Boolean(session.checkout_reminder_sent),
    extendOfferSent: Boolean(session.extend_offer_sent),
    poolHeatOffered: Boolean(session.pool_heat_offered),
    poolHeatAccepted: Boolean(session.pool_heat_accepted),
    notificationsSent: safeNumber(session.notifications_sent),
    assignedOperatorId: safeString(session.assigned_operator_id),
    assignedOperatorLabel: safeString(session.assigned_operator_label),
    openHandoffCount: safeNumber(session.open_handoff_count),
    assignmentStatus: safeString(session.assignment_status, "unassigned"),
    workflow: normalizeWorkflow(session.workflow),
  }));

  const summary = (payload.summary as Record<string, unknown> | undefined) || {};
  return {
    sessions,
    count: safeNumber(payload.count, sessions.length),
    summary: {
      all: safeNumber(summary.all),
      inStay: safeNumber(summary.in_stay),
      arriving: safeNumber(summary.arriving),
      postStay: safeNumber(summary.post_stay),
      archived: safeNumber(summary.archived),
      withBookingContext: safeNumber(summary.with_booking_context),
      journeyTracked: safeNumber(summary.journey_tracked),
      proactiveEvaluated: safeNumber(summary.proactive_evaluated),
      notificationsSent: safeNumber(summary.notifications_sent),
    },
  };
}

export function normalizeTodaySessionDetail(payload: Record<string, unknown> = {}): SessionDetail {
  const session = (payload.session as Record<string, unknown> | undefined) || {};
  const bookingContext = (payload.booking_context as Record<string, unknown> | undefined) || {};
  const journey = (payload.journey as Record<string, unknown> | undefined) || {};
  const workflow = normalizeWorkflow(payload.workflow);

  return {
    session: {
      sessionId: safeString(session.session_id),
      guestThreadId: safeString(session.guest_thread_id),
      token: safeString(session.token),
      guestName: safeString(session.guest_name, "Guest"),
      guestPhone: safeString(session.guest_phone),
      guestEmail: safeString(session.guest_email),
      propertyCode: safeString(session.property_code),
      propertyName: safeString(session.property_name, "Unknown property"),
      numGuests: safeNumber(session.num_guests),
      checkIn: (session.check_in as string | null | undefined) || null,
      checkOut: (session.check_out as string | null | undefined) || null,
      status: safeString(session.status, "active"),
      phase: safeString(session.phase),
      conversationCount: safeNumber(session.conversation_count),
      lastMessageAt: (session.last_message_at as string | null | undefined) || null,
      proactiveTriggeredAt: (session.proactive_triggered_at as string | null | undefined) || null,
      pmsSyncedAt: (session.pms_synced_at as string | null | undefined) || null,
      reservationId: safeString(session.reservation_id),
    },
    bookingContext: {
      available: Boolean(bookingContext.available),
      source: safeString(bookingContext.source),
      provider: safeString(bookingContext.provider),
      matchStrategy: safeString(bookingContext.match_strategy),
      guestIdentityAvailable: Boolean(bookingContext.guest_identity_available),
      property: bookingContext.property || null,
      booking: bookingContext.booking || null,
      activeBooking: bookingContext.active_booking || null,
      nextBooking: bookingContext.next_booking || null,
      upcomingBookings: safeArray(bookingContext.upcoming_bookings),
      lookup: bookingContext.lookup || null,
    },
    postStayActions: {
      canRequestFeedback: Boolean((payload.post_stay_actions as Record<string, unknown> | undefined)?.can_request_feedback),
      feedbackPromptSuggestion: safeString((payload.post_stay_actions as Record<string, unknown> | undefined)?.feedback_prompt_suggestion),
      hasRepeatGuestMemory: Boolean((payload.post_stay_actions as Record<string, unknown> | undefined)?.has_repeat_guest_memory),
    },
    journey: {
      journeyId: safeString(journey.journey_id),
      welcomeSent: Boolean(journey.welcome_sent),
      welcomeSentAt: (journey.welcome_sent_at as string | null | undefined) || null,
      extendOfferSent: Boolean(journey.extend_offer_sent),
      extendOfferSentAt: (journey.extend_offer_sent_at as string | null | undefined) || null,
      extendOfferResponse: safeString(journey.extend_offer_response),
      poolHeatOffered: Boolean(journey.pool_heat_offered),
      poolHeatAccepted: Boolean(journey.pool_heat_accepted),
      checkinReminderSent: Boolean(journey.checkin_reminder_sent),
      checkinReminderSentAt: (journey.checkin_reminder_sent_at as string | null | undefined) || null,
      checkoutReminderSent: Boolean(journey.checkout_reminder_sent),
      checkoutReminderSentAt: (journey.checkout_reminder_sent_at as string | null | undefined) || null,
      activities: safeArray<Record<string, unknown>>(journey.activities).map((activity) => ({
        activityId: safeString(activity.activity_id),
        activityType: safeString(activity.activity_type),
        status: safeString(activity.status, "not_discussed"),
        discussedAt: (activity.discussed_at as string | null | undefined) || null,
        notes: safeString(activity.notes),
      })),
    },
    messages: safeArray<Record<string, unknown>>(payload.messages).map((message) => ({
      messageId: safeString(message.message_id),
      direction: safeString(message.direction, "inbound"),
      content: safeString(message.content),
      contentType: safeString(message.content_type, "text"),
      intent: safeString(message.intent),
      wasQuickAnswer: Boolean(message.was_quick_answer),
      responseTimeMs: message.response_time_ms == null ? null : safeNumber(message.response_time_ms),
      createdAt: (message.created_at as string | null | undefined) || null,
    })),
    openEscalations: safeArray<Record<string, unknown>>(payload.open_escalations).map((escalation) => ({
      ticketId: safeString(escalation.ticket_id),
      reason: safeString(escalation.reason),
      priority: safeString(escalation.priority, "medium"),
      status: safeString(escalation.status, "pending"),
      summary: safeString(escalation.summary),
      createdAt: (escalation.created_at as string | null | undefined) || null,
    })),
    notifications: safeArray<Record<string, unknown>>(payload.notifications).map((notification) => ({
      notificationId: safeString(notification.notification_id),
      notificationType: safeString(notification.notification_type),
      channel: safeString(notification.channel),
      recipient: safeString(notification.recipient),
      status: safeString(notification.status, "pending"),
      sentAt: (notification.sent_at as string | null | undefined) || null,
      deliveredAt: (notification.delivered_at as string | null | undefined) || null,
      externalId: safeString(notification.external_id),
      errorMessage: safeString(notification.error_message),
    })),
    workOrders: safeArray<Record<string, unknown>>(payload.work_orders).map((order) => ({
      workOrderId: safeString(order.work_order_id),
      workflowType: safeString(order.workflow_type),
      workflowRef: safeString(order.workflow_ref),
      propertyCode: safeString(order.property_code),
      vendorId: safeString(order.vendor_id),
      vendorName: safeString(order.vendor_name),
      vendorPhone: safeString(order.vendor_phone),
      issueCategory: safeString(order.issue_category),
      status: safeString(order.status),
      priority: safeString(order.priority),
      summary: safeString(order.summary),
      details: safeString(order.details),
      dispatchState: safeString(order.dispatch_state),
      etaMinutes: order.eta_minutes == null ? null : safeNumber(order.eta_minutes),
      etaVisibilityMode: safeString(order.eta_visibility_mode, "estimated"),
      trackingUrl: safeString(order.tracking_url),
      lastKnownDistanceText: safeString(order.last_known_distance_text),
      assetId: safeString(order.asset_id),
      verificationState: safeString(order.verification_state),
      invoiceState: safeString(order.invoice_state),
      invoiceAmount: order.invoice_amount == null ? null : safeNumber(order.invoice_amount),
      invoiceReference: safeString(order.invoice_reference),
      lastActorLabel: safeString(order.last_actor_label),
      payload: order.payload && typeof order.payload === "object" ? (order.payload as Record<string, unknown>) : {},
      resolution: order.resolution && typeof order.resolution === "object" ? (order.resolution as Record<string, unknown>) : {},
      createdAt: (order.created_at as string | null | undefined) || null,
      updatedAt: (order.updated_at as string | null | undefined) || null,
      acceptedAt: (order.accepted_at as string | null | undefined) || null,
      scheduledAt: (order.scheduled_at as string | null | undefined) || null,
      completedAt: (order.completed_at as string | null | undefined) || null,
      verifiedAt: (order.verified_at as string | null | undefined) || null,
      closedAt: (order.closed_at as string | null | undefined) || null,
    })),
    events: safeArray<Record<string, unknown>>(payload.events).map((event) => ({
      stayEventId: safeString(event.stay_event_id),
      sessionId: safeString(event.session_id),
      sessionToken: safeString(event.session_token),
      propertyCode: safeString(event.property_code),
      eventType: safeString(event.event_type),
      eventDomain: safeString(event.event_domain, "ops"),
      status: safeString(event.status, "completed"),
      source: safeString(event.source, "operator"),
      note: safeString(event.note),
      payload: event.payload_json && typeof event.payload_json === "object" ? (event.payload_json as Record<string, unknown>) : {},
      createdBy: safeString(event.created_by, "operator"),
      occurredAt: (event.occurred_at as string | null | undefined) || null,
      createdAt: (event.created_at as string | null | undefined) || null,
      updatedAt: (event.updated_at as string | null | undefined) || null,
    })),
    workflow,
    intentMix: Object.fromEntries(
      Object.entries((payload.intent_mix as Record<string, unknown> | undefined) || {}).map(([key, value]) => [
        safeString(key),
        safeNumber(value),
      ]),
    ),
  };
}

export function normalizeTodayStayActions(payload: Record<string, unknown> = {}): StayActions {
  const actions = safeArray<Record<string, unknown>>(payload.actions).map((action) => ({
    actionType: safeString(action.action_type),
    status: safeString(action.status, "ready"),
    priority: safeString(action.priority, "medium"),
    propertyCode: safeString(action.property_code),
    payload: action.payload && typeof action.payload === "object" ? (action.payload as Record<string, unknown>) : {},
    result: action.result && typeof action.result === "object" ? (action.result as Record<string, unknown>) : {},
    dueAt: (action.due_at as string | null | undefined) || null,
    createdAt: (action.created_at as string | null | undefined) || null,
    updatedAt: (action.updated_at as string | null | undefined) || null,
    completedAt: (action.completed_at as string | null | undefined) || null,
  }));
  return {
    sessionId: safeString(payload.session_id),
    actions,
    count: safeNumber(payload.count, actions.length),
  };
}

export function normalizeTodayThreadTimeline(payload: Record<string, unknown> = {}): ThreadTimeline {
  const timeline = safeArray<Record<string, unknown>>(payload.timeline).map((item) => ({
    itemType: safeString(item.item_type),
    itemId: safeString(item.item_id),
    propertyCode: safeString(item.property_code),
    guestName: safeString(item.guest_name),
    summary: safeString(item.summary),
    status: safeString(item.status),
    threadRef: safeString(item.thread_ref),
    occurredAt: (item.occurred_at as string | null | undefined) || null,
  }));
  return {
    guestThreadId: safeString(payload.guest_thread_id),
    guestName: safeString(payload.guest_name, "Guest"),
    propertyCodes: safeArray(payload.property_codes).map((code) => safeString(code)),
    timeline,
    count: timeline.length,
  };
}

export function normalizeOpenEscalations(payload: Record<string, unknown> = {}): Escalation[] {
  const escalationItems = safeArray<Record<string, unknown>>(payload.escalations);
  const openStatuses = new Set(["pending", "acknowledged"]);
  return escalationItems
    .map((item) => ({
      ticketId: safeString(item.ticket_id),
      sessionId: safeString(item.session_id),
      sessionToken: safeString(item.session_token),
      status: safeString(item.status).toLowerCase(),
      priority: safeString(item.priority, "medium"),
      guestUpdatedAt: (item.guest_updated_at as string | null | undefined) || null,
      guestUpdateStatus: safeString(item.guest_update_status),
      createdAt: (item.created_at as string | null | undefined) || null,
    }))
    .filter((item) => openStatuses.has(item.status));
}
