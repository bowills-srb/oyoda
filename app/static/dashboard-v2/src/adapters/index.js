
import { createElement } from "react";

import { InlineError } from "../components/system/InlineError";

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function safeNumber(value, fallback = 0) {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
}

function safeString(value, fallback = '') {
  return typeof value === 'string' ? value : (value == null ? fallback : String(value));
}

export function normalizeDashboardSummary(payload = {}) {
  const inbox = payload.inbox || {};
  return {
    sessions: {
      active: safeNumber(payload.sessions?.active),
      inStay: safeNumber(payload.sessions?.in_stay),
      arriving: safeNumber(payload.sessions?.arriving),
      total30d: safeNumber(payload.sessions?.total_30d),
    },
    preBooking: {
      pending: safeNumber(payload.pre_booking?.pending),
      oldestPendingAgeMinutes: safeNumber(payload.pre_booking?.oldest_pending_age_minutes),
      replied30d: safeNumber(payload.pre_booking?.replied_30d),
      total30d: safeNumber(payload.pre_booking?.total_30d),
    },
    escalations: {
      open: safeNumber(payload.escalations?.open),
      resolved30d: safeNumber(payload.escalations?.resolved_30d),
    },
    properties: safeNumber(payload.properties),
    kbEntries: safeNumber(payload.kb_entries),
    kbGaps: safeNumber(payload.kb_gaps),
    vendors: safeNumber(payload.vendors),
    messages30d: safeNumber(payload.messages_30d),
    notificationsUnread: safeNumber(payload.notifications_unread),
    inbox: {
      connected: !!inbox.connected,
      email: safeString(inbox.email, ''),
      provider: safeString(inbox.provider, ''),
      connectedAt: inbox.connected_at || null,
      lastPolledAt: inbox.last_polled_at || null,
      lastPollSuccess: inbox.last_poll_success,
      lastPollSummary: safeString(inbox.last_poll_summary, ''),
      lastPollError: safeString(inbox.last_poll_error, ''),
      lastMessagesFound: inbox.last_messages_found == null ? null : safeNumber(inbox.last_messages_found),
      lastNewPendingInquiries: inbox.last_new_pending_inquiries == null ? null : safeNumber(inbox.last_new_pending_inquiries),
      lastQueryMode: safeString(inbox.last_query_mode, ''),
    },
  };
}

export function normalizeKbEntries(payload = {}) {
  const entries = safeArray(payload.entries).map((entry) => ({
    id: safeString(entry.id),
    parentId: safeString(entry.parent_id),
    faqIndex: safeNumber(entry.faq_index, -1),
    question: safeString(entry.question),
    answer: safeString(entry.answer),
    confidence: safeNumber(entry.confidence, 0.9),
    category: safeString(entry.category, 'General'),
    usageCount: safeNumber(entry.usage_count),
    propertyId: entry.property_id || null,
    propertyLabel: safeString(entry.property_label, 'All Properties'),
    source: safeString(entry.source),
    updatedAt: entry.updated_at || null,
  }));
  return {
    entries,
    count: safeNumber(payload.count, entries.length),
  };
}

export function normalizeKbGaps(payload = {}) {
  const gaps = safeArray(payload.gaps).map((gap) => ({
    id: safeString(gap.gap_id),
    question: safeString(gap.question),
    category: safeString(gap.category, 'General'),
    categorySlug: safeString(gap.category_slug, 'general'),
    confidence: safeNumber(gap.confidence),
    aiAnswer: safeString(gap.ai_answer),
    stage: safeString(gap.stage),
    channel: safeString(gap.channel),
    source: safeString(gap.source),
    resolved: !!gap.resolved,
    property: safeString(gap.property, 'All Properties'),
    askCount: safeNumber(gap.ask_count, 1),
    createdAt: gap.created_at || null,
    draftId: safeString(gap.draft_id),
    reason: safeString(gap.reason),
    intent: safeString(gap.intent),
    thresholdPct: gap.threshold_pct == null ? null : safeNumber(gap.threshold_pct),
    actualPct: gap.actual_pct == null ? null : safeNumber(gap.actual_pct),
    missingTopics: safeArray(gap.missing_topics).map((item) => safeString(item)),
    parserSource: safeString(gap.parser_source),
    asks: safeArray(gap.asks).map((item) => safeString(item)),
    platformListingId: safeString(gap.platform_listing_id),
    platformUnitId: safeString(gap.platform_unit_id),
    linkContextSummary: safeString(gap.link_context_summary),
    policyWarnings: safeArray(gap.policy_warnings).map((item) => safeString(item)),
  }));
  return {
    gaps,
    count: safeNumber(payload.count, gaps.length),
    totalUnresolved: safeNumber(payload.total_unresolved),
  };
}

export function normalizeKbTestResult(payload = {}) {
  return {
    answered: !!payload.answered,
    confidence: safeNumber(payload.confidence),
    answer: safeString(payload.answer),
    sources: safeArray(payload.sources).map((item) => safeString(item)),
    matchQuestion: safeString(payload.match_question),
  };
}

export function normalizeVendorCategories(payload = {}) {
  return {
    categories: safeArray(payload.categories).map((category) => ({
      id: safeString(category.category_id || category.id),
      slug: safeString(category.slug),
      displayName: safeString(category.display_name, 'Category'),
      icon: safeString(category.icon, ''),
      sortOrder: safeNumber(category.sort_order),
      vendorCount: safeNumber(category.vendor_count),
      workflowGroup: safeString(category.workflow_group, 'experience'),
    })),
  };
}

export function normalizeVendors(payload = {}) {
  const vendors = safeArray(payload.vendors).map((vendor) => ({
    id: safeString(vendor.vendor_id || vendor.id),
    name: safeString(vendor.name),
    categorySlug: safeString(vendor.category_slug),
    phone: safeString(vendor.phone),
    website: safeString(vendor.website),
    aiScript: safeString(vendor.ai_script),
    internalNotes: safeString(vendor.internal_notes),
    priority: safeNumber(vendor.priority, 1),
    applyScope: safeString(vendor.apply_scope, 'all'),
    propertyIds: safeArray(vendor.property_ids),
    active: vendor.active !== false,
    referralCount: safeNumber(vendor.referral_count),
    lastReferredAt: vendor.last_referred_at || null,
    workflowGroup: safeString(vendor.workflow_group, 'experience'),
    operationalMetadata: {
      manufacturerTags: safeArray(vendor.operational_metadata?.manufacturer_tags).map((item) => safeString(item)),
      excludedManufacturerTags: safeArray(vendor.operational_metadata?.excluded_manufacturer_tags).map((item) => safeString(item)),
      warrantyProviderTags: safeArray(vendor.operational_metadata?.warranty_provider_tags).map((item) => safeString(item)),
      supportedIssueTags: safeArray(vendor.operational_metadata?.supported_issue_tags).map((item) => safeString(item)),
      preferredPropertyCodes: safeArray(vendor.operational_metadata?.preferred_property_codes).map((item) => safeString(item)),
      warrantyCapable: !!vendor.operational_metadata?.warranty_capable,
      warrantyOnly: !!vendor.operational_metadata?.warranty_only,
      emergencyCapable: !!vendor.operational_metadata?.emergency_capable,
      emergencyOverrideOnly: !!vendor.operational_metadata?.emergency_override_only,
      afterHoursAvailable: !!vendor.operational_metadata?.after_hours_available,
      backupRank: safeNumber(vendor.operational_metadata?.backup_rank),
      responseSlaMinutes: safeNumber(vendor.operational_metadata?.response_sla_minutes),
      approvalMode: safeString(vendor.operational_metadata?.approval_mode, 'standard'),
      costTier: safeString(vendor.operational_metadata?.cost_tier, 'standard'),
    },
  }));
  return {
    vendors,
    count: safeNumber(payload.count, vendors.length),
  };
}

export function normalizeSettings(payload = {}) {
  const raw = payload.settings || {};
  const account = payload.account || {};
  return {
    account: {
      companyName: safeString(account.company_name),
      contactEmail: safeString(account.email || account.messaging_email),
      pms: safeString(account.pms, 'escapia'),
      plan: safeString(account.plan, 'beta'),
      propertyCount: safeNumber(account.property_count),
      onboardingComplete: !!account.onboarding_complete,
    },
    settings: {
      aiConciergeName: safeString(raw.ai_concierge_name, 'Your Concierge'),
      prebookingAutosendThreshold: safeNumber(raw.prebooking_autosend_threshold, 95),
      escalationUrgencyThreshold: safeNumber(raw.escalation_urgency_threshold, 70),
      kbGapDetectionThreshold: safeNumber(raw.kb_gap_detection_threshold, 40),
      notifyEmergency: raw.notify_emergency !== false,
      notifyMaintenance: raw.notify_maintenance !== false,
      notifyPrebooking: raw.notify_prebooking !== false,
      notifyKbGaps: !!raw.notify_kb_gaps,
      notifyWeeklyAnalytics: raw.notify_weekly_analytics !== false,
      kbSuppressedCategories: safeArray(raw.kb_suppressed_categories),
      proactivePolicy: {
        enabledTouchTypes: safeArray(raw.proactive_policy?.enabled_touch_types),
        minHoursBetweenProactiveTouches: safeNumber(raw.proactive_policy?.min_hours_between_proactive_touches, 18),
        minHoursBetweenServiceUpdates: safeNumber(raw.proactive_policy?.min_hours_between_service_updates, 4),
        maxNotificationsPerStayWindow: safeNumber(raw.proactive_policy?.max_notifications_per_stay_window, 6),
        allowServiceUpdatesDuringEscalation: raw.proactive_policy?.allow_service_updates_during_escalation !== false,
      },
      escalationGuestPolicy: {
        allowEtaUpdates: raw.escalation_guest_policy?.allow_eta_updates !== false,
        allowReassuranceWithoutEta: raw.escalation_guest_policy?.allow_reassurance_without_eta !== false,
        operatorApprovalRequiredForStatusUpdates: !!raw.escalation_guest_policy?.operator_approval_required_for_status_updates,
      },
      stayOperationsPolicy: {
        workflowProfile: safeString(raw.stay_operations_policy?.workflow_profile, 'assisted_ops'),
        enableAccessWorkflows: raw.stay_operations_policy?.enable_access_workflows !== false,
        enableRentalWorkflows: raw.stay_operations_policy?.enable_rental_workflows !== false,
        enableTurnoverWorkflows: raw.stay_operations_policy?.enable_turnover_workflows !== false,
        enableMaintenanceWorkflows: raw.stay_operations_policy?.enable_maintenance_workflows !== false,
        enablePostCheckoutWalkthrough: !!raw.stay_operations_policy?.enable_post_checkout_walkthrough,
        walkthroughRequiredBeforeReady: !!raw.stay_operations_policy?.walkthrough_required_before_ready,
        autoArchiveWhenTurnoverReady: raw.stay_operations_policy?.auto_archive_when_turnover_ready !== false,
      },
      retentionPolicy: {
        activeSearchWindowDays: safeNumber(raw.retention_policy?.active_search_window_days, 30),
        postStayFollowUpDays: safeNumber(raw.retention_policy?.post_stay_follow_up_days, 21),
        rawGuestContentRetentionDays: safeNumber(raw.retention_policy?.raw_guest_content_retention_days, 90),
        preBookingRecordRetentionDays: safeNumber(raw.retention_policy?.pre_booking_record_retention_days, 120),
        guestSessionShellRetentionDays: safeNumber(raw.retention_policy?.guest_session_shell_retention_days, 730),
        structuredSignalRetentionDays: safeNumber(raw.retention_policy?.structured_signal_retention_days, 365),
        autoCleanupEnabled: raw.retention_policy?.auto_cleanup_enabled !== false,
        preserveGuestIdentity: raw.retention_policy?.preserve_guest_identity !== false,
      },
      aiPaused: !!raw.ai_paused,
      aiPausedAt: raw.ai_paused_at || null,
      updatedAt: raw.updated_at || null,
    },
  };
}

export function normalizeAlertRouting(payload = {}) {
  return {
    contacts: safeArray(payload.contacts).map((contact) => ({
      id: safeString(contact.id),
      contactName: safeString(contact.contact_name, 'Contact'),
      contactPhone: safeString(contact.contact_phone),
      contactEmail: safeString(contact.contact_email),
      alertType: safeString(contact.alert_type, 'general'),
      propertyCode: safeString(contact.property_code),
      isPrimary: !!contact.is_primary,
      escalationOrder: safeNumber(contact.escalation_order, 1),
      timeoutMinutes: safeNumber(contact.escalation_timeout_minutes, 30),
      activeHours: safeString(contact.active_hours, '24/7'),
      isAvailable: contact.is_available !== false,
      unavailableUntil: contact.unavailable_until || null,
      redirectToId: contact.redirect_to_id || null,
      notes: safeString(contact.notes),
      statusLabel: safeString(contact.status_label, 'Available'),
    })),
    coverage: safeArray(payload.coverage).map((item) => ({
      alertType: safeString(item.alert_type),
      hasCoverage: !!item.has_coverage,
      availableCount: safeNumber(item.available_count),
      availableContacts: safeArray(item.available_contacts).map((name) => safeString(name)),
      oooContacts: safeArray(item.ooo_contacts).map((name) => safeString(name)),
      timeoutMinutes: safeNumber(item.escalation_timeout_minutes, 30),
      gapDetails: safeString(item.gap_details),
    })),
    allCovered: !!payload.all_covered,
    gapCount: safeNumber(payload.gap_count),
    properties: safeArray(payload.properties).map((property) => ({
      propertyId: property.property_id || null,
      propertyName: safeString(property.property_name, 'Property'),
      propertyCode: safeString(property.property_code),
    })),
    alertTypes: safeArray(payload.alert_types).map((type) => safeString(type)),
  };
}

export function normalizeNotifications(payload = {}) {
  const notifications = safeArray(payload.notifications).map((item) => ({
    id: safeString(item.notification_id),
    kind: safeString(item.kind),
    severity: safeString(item.severity, 'info'),
    title: safeString(item.title, 'Notification'),
    body: safeString(item.body),
    linkTarget: safeString(item.link_target),
    linkLabel: safeString(item.link_label),
    readAt: item.read_at || null,
    createdAt: item.created_at || null,
  }));
  return {
    notifications,
    unreadCount: safeNumber(payload.unread_count, notifications.filter((item) => !item.readAt).length),
  };
}

export function normalizePropertiesAutonomy(payload = {}) {
  const properties = safeArray(payload.properties).map((property) => ({
    id: safeString(property.id || property.property_id),
    propertyCode: safeString(property.property_code || property.property_external_id),
    propertyName: safeString(property.property_name || property.address_street || property.property_code, 'Property'),
    addressStreet: safeString(property.address_street),
    addressCity: safeString(property.address_city),
    addressState: safeString(property.address_state),
    community: safeString(property.community),
    bedrooms: safeNumber(property.bedrooms),
    bathrooms: safeNumber(property.bathrooms),
    sleeps: safeNumber(property.sleeps),
    approvalMode: safeString(property.approval_mode, 'required'),
    minConfidenceForAuto: safeNumber(property.min_confidence_for_auto, 0.95),
    dataSource: safeString(property.data_source),
    hasPool: !!property.has_pool,
    hasHotTub: !!property.has_hot_tub,
    petsAllowed: !!property.pets_allowed,
    autonomy: {
      all: {
        approvalMode: safeString(property.autonomy?.all?.approval_mode, safeString(property.approval_mode, 'required')),
        minConfidenceForAuto: safeNumber(property.autonomy?.all?.min_confidence_for_auto, safeNumber(property.min_confidence_for_auto, 0.95)),
        sourceStage: safeString(property.autonomy?.all?.source_stage || property.autonomy?.all?.stage || 'all'),
      },
      preBooking: {
        approvalMode: safeString(property.autonomy?.pre_booking?.approval_mode, safeString(property.approval_mode, 'required')),
        minConfidenceForAuto: safeNumber(property.autonomy?.pre_booking?.min_confidence_for_auto, safeNumber(property.min_confidence_for_auto, 0.95)),
        sourceStage: safeString(property.autonomy?.pre_booking?.source_stage || property.autonomy?.pre_booking?.stage || 'default'),
      },
      guestSessions: {
        approvalMode: safeString(property.autonomy?.guest_sessions?.approval_mode, safeString(property.approval_mode, 'required')),
        minConfidenceForAuto: safeNumber(property.autonomy?.guest_sessions?.min_confidence_for_auto, safeNumber(property.min_confidence_for_auto, 0.95)),
        sourceStage: safeString(property.autonomy?.guest_sessions?.source_stage || property.autonomy?.guest_sessions?.stage || 'default'),
      },
    },
  }));
  return {
    properties,
    count: safeNumber(payload.count, properties.length),
    summary: {
      autoCount: safeNumber(payload.summary?.auto_count),
      reviewCount: safeNumber(payload.summary?.review_count),
      preBookingAutoCount: safeNumber(payload.summary?.pre_booking_auto_count),
      preBookingReviewCount: safeNumber(payload.summary?.pre_booking_review_count),
      guestSessionsAutoCount: safeNumber(payload.summary?.guest_sessions_auto_count),
      guestSessionsReviewCount: safeNumber(payload.summary?.guest_sessions_review_count),
    },
  };
}

export function normalizeMessageFeed(payload = {}) {
  const parseBool = (value) => {
    if (typeof value === 'boolean') return value;
    if (typeof value === 'number') return value !== 0;
    const normalized = safeString(value).trim().toLowerCase();
    if (!normalized) return false;
    if (['false', '0', 'off', 'no', 'null', 'undefined'].includes(normalized)) return false;
    if (['true', '1', 'on', 'yes'].includes(normalized)) return true;
    return false;
  };
  const items = safeArray(payload.items).map((item) => ({
    id: safeString(item.id || item.draft_id),
    kind: safeString(item.kind, 'inquiry'),
    stage: safeString(item.stage, 'pre_booking'),
    status: safeString(item.status, 'pending_review'),
    channel: safeString(item.channel, 'email'),
    sourceProvider: safeString(item.source_provider),
    guestName: safeString(item.guest_name, 'Guest'),
    guestEmail: safeString(item.guest_email),
    guestPhone: safeString(item.guest_phone),
    messageText: safeString(item.message_text),
    latestGuestTurn: safeString(item.latest_guest_turn || item.message_text),
    priorThreadContext: safeString(item.prior_thread_context),
    messagePreview: safeString(item.message_preview),
    draftText: safeString(item.draft_text),
    draftPreview: safeString(item.draft_preview),
    finalReply: safeString(item.final_reply),
    intent: safeString(item.intent, 'general'),
    asks: safeArray(item.asks).map((ask) => safeString(ask)),
    parserSource: safeString(item.parser_source),
    platformListingId: safeString(item.platform_listing_id),
    platformUnitId: safeString(item.platform_unit_id),
    propertyBindingCandidates: safeArray(item.property_binding_candidates).map((candidate) => ({
      candidateType: safeString(candidate.candidate_type),
      value: safeString(candidate.value),
      confidence: safeNumber(candidate.confidence),
      source: safeString(candidate.source),
    })),
    priorOperatorCommitments: safeArray(item.prior_operator_commitments),
    propertyMatchType: safeString(item.property_match_type),
    routeOutcome: safeString(item.route_outcome),
    autonomyDecision: safeString(item.autonomy_decision),
    fallbackReason: safeString(item.fallback_reason),
    latestTurnConfidence: safeNumber(item.latest_turn_confidence),
    latestTurnExtracted: !!item.latest_turn_extracted,
    confidence: safeNumber(item.confidence),
    confidenceSource: safeString(item.confidence_source),
    draftSource: safeString(item.draft_source),
    confidenceLabel: safeString(item.confidence_label),
    confidenceNote: safeString(item.confidence_note),
    draftReady: !!item.draft_ready,
    propertyId: safeString(item.property_id || item.property_external_id || item.property_code),
    propertyName: safeString(item.property_name, 'Unknown property'),
    checkIn: item.check_in || null,
    checkOut: item.check_out || null,
    occurredAt: item.occurred_at || item.received_at || null,
    repliedAt: item.replied_at || null,
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
    assignmentStatus: safeString(item.assignment_status, 'unassigned'),
  }));

  return {
    count: safeNumber(payload.count, items.length),
    stage: safeString(payload.stage, 'all'),
    status: safeString(payload.status, 'all'),
    property: safeString(payload.property),
    unboundOnly: parseBool(payload.unbound_only),
    shipIKbRetryPrimary: parseBool(payload.ship_i_kb_retry_primary),
    unboundCount: safeNumber(payload.unbound_count, items.filter((item) => !item.propertyId).length),
    items,
    stageCounts: payload.stage_counts || {},
    properties: safeArray(payload.properties).map((property) => ({
      id: safeString(property.id),
      name: safeString(property.name, property.id),
      count: safeNumber(property.count),
    })),
  };
}

export function normalizeSessionsList(payload = {}) {
  const normalizeWorkflow = (workflow) => {
    const value = workflow && typeof workflow === 'object' ? { ...workflow } : {};
    const turnover = value.turnover && typeof value.turnover === 'object' ? value.turnover : {};
    value.turnover = {
      ...turnover,
      readyForNextGuest: !!turnover.ready_for_next_guest,
      assignedVendorId: safeString(turnover.assigned_vendor_id),
      assignedVendorName: safeString(turnover.assigned_vendor_name),
      startedAt: turnover.started_at || null,
      readyAt: turnover.ready_at || null,
      archivedAt: turnover.archived_at || null,
      updatedAt: turnover.updated_at || null,
      updatedBy: safeString(turnover.updated_by),
    };
    value.operationalState = safeString(value.operational_state, 'active');
    value.archiveEligible = !!value.archive_eligible;
    return value;
  };

  const sessions = safeArray(payload.sessions).map((session) => ({
    sessionId: safeString(session.session_id),
    token: safeString(session.token),
    guestName: safeString(session.guest_name, 'Guest'),
    guestPhone: safeString(session.guest_phone),
    guestEmail: safeString(session.guest_email),
    propertyCode: safeString(session.property_code),
    propertyName: safeString(session.property_name, 'Unknown property'),
    numGuests: safeNumber(session.num_guests),
    checkIn: session.check_in || null,
    checkOut: session.check_out || null,
    status: safeString(session.status, 'active'),
    phase: safeString(session.phase),
    conversationCount: safeNumber(session.conversation_count),
    lastMessageAt: session.last_message_at || null,
    openEscalations: safeNumber(session.open_escalations),
    reservationId: safeString(session.reservation_id),
    pmsSyncedAt: session.pms_synced_at || null,
    proactiveTriggeredAt: session.proactive_triggered_at || null,
    hasBookingContext: !!session.has_booking_context,
    journeyTracked: !!session.journey_tracked,
    welcomeSent: !!session.welcome_sent,
    checkinReminderSent: !!session.checkin_reminder_sent,
    checkoutReminderSent: !!session.checkout_reminder_sent,
    extendOfferSent: !!session.extend_offer_sent,
    poolHeatOffered: !!session.pool_heat_offered,
    poolHeatAccepted: !!session.pool_heat_accepted,
    notificationsSent: safeNumber(session.notifications_sent),
    assignedOperatorId: safeString(session.assigned_operator_id),
    assignedOperatorLabel: safeString(session.assigned_operator_label),
    openHandoffCount: safeNumber(session.open_handoff_count),
    assignmentStatus: safeString(session.assignment_status, 'unassigned'),
    workflow: normalizeWorkflow(session.workflow),
  }));

  return {
    sessions,
    count: safeNumber(payload.count, sessions.length),
    summary: {
      all: safeNumber(payload.summary?.all),
      inStay: safeNumber(payload.summary?.in_stay),
      arriving: safeNumber(payload.summary?.arriving),
      postStay: safeNumber(payload.summary?.post_stay),
      archived: safeNumber(payload.summary?.archived),
      withBookingContext: safeNumber(payload.summary?.with_booking_context),
      journeyTracked: safeNumber(payload.summary?.journey_tracked),
      proactiveEvaluated: safeNumber(payload.summary?.proactive_evaluated),
      notificationsSent: safeNumber(payload.summary?.notifications_sent),
    },
  };
}

export function normalizeSessionDetail(payload = {}) {
  const workflow = payload.workflow && typeof payload.workflow === 'object' ? { ...payload.workflow } : {};
  const turnover = workflow.turnover && typeof workflow.turnover === 'object' ? workflow.turnover : {};
  const session = payload.session || {};
  const bookingContext = payload.booking_context || {};
  const journey = payload.journey || {};
  const workOrders = safeArray(payload.work_orders).map((order) => ({
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
    etaVisibilityMode: safeString(order.eta_visibility_mode, 'estimated'),
    trackingUrl: safeString(order.tracking_url),
    lastKnownDistanceText: safeString(order.last_known_distance_text),
    assetId: safeString(order.asset_id),
    verificationState: safeString(order.verification_state),
    invoiceState: safeString(order.invoice_state),
    invoiceAmount: order.invoice_amount == null ? null : safeNumber(order.invoice_amount),
    invoiceReference: safeString(order.invoice_reference),
    lastActorLabel: safeString(order.last_actor_label),
    payload: order.payload && typeof order.payload === 'object' ? order.payload : {},
    resolution: order.resolution && typeof order.resolution === 'object' ? order.resolution : {},
    createdAt: order.created_at || null,
    updatedAt: order.updated_at || null,
    acceptedAt: order.accepted_at || null,
    scheduledAt: order.scheduled_at || null,
    completedAt: order.completed_at || null,
    verifiedAt: order.verified_at || null,
    closedAt: order.closed_at || null,
  }));
  return {
    session: {
      sessionId: safeString(session.session_id),
      guestThreadId: safeString(session.guest_thread_id),
      token: safeString(session.token),
      guestName: safeString(session.guest_name, 'Guest'),
      guestPhone: safeString(session.guest_phone),
      guestEmail: safeString(session.guest_email),
      propertyCode: safeString(session.property_code),
      propertyName: safeString(session.property_name, 'Unknown property'),
      numGuests: safeNumber(session.num_guests),
      checkIn: session.check_in || null,
      checkOut: session.check_out || null,
      status: safeString(session.status, 'active'),
      phase: safeString(session.phase),
      conversationCount: safeNumber(session.conversation_count),
      lastMessageAt: session.last_message_at || null,
      proactiveTriggeredAt: session.proactive_triggered_at || null,
      pmsSyncedAt: session.pms_synced_at || null,
      reservationId: safeString(session.reservation_id),
    },
    bookingContext: {
      available: !!bookingContext.available,
      source: safeString(bookingContext.source),
      provider: safeString(bookingContext.provider),
      matchStrategy: safeString(bookingContext.match_strategy),
      guestIdentityAvailable: !!bookingContext.guest_identity_available,
      property: bookingContext.property || null,
      booking: bookingContext.booking || null,
      activeBooking: bookingContext.active_booking || null,
      nextBooking: bookingContext.next_booking || null,
      upcomingBookings: safeArray(bookingContext.upcoming_bookings),
      lookup: bookingContext.lookup || null,
    },
    // Post-stay action gating. Surfaced separately from the action queue
    // because feedback request eligibility is computed on the session row
    // itself (phase + feedback_rating presence) rather than via the agent.
    // The route uses canRequestFeedback to decide whether to render the
    // Request feedback button, and feedbackPromptSuggestion as the message
    // body backend will send if it's clicked.
    postStayActions: {
      canRequestFeedback: !!(payload.post_stay_actions && payload.post_stay_actions.can_request_feedback),
      feedbackPromptSuggestion: safeString(payload.post_stay_actions && payload.post_stay_actions.feedback_prompt_suggestion),
      hasRepeatGuestMemory: !!(payload.post_stay_actions && payload.post_stay_actions.has_repeat_guest_memory),
    },
    journey: {
      journeyId: safeString(journey.journey_id),
      welcomeSent: !!journey.welcome_sent,
      welcomeSentAt: journey.welcome_sent_at || null,
      extendOfferSent: !!journey.extend_offer_sent,
      extendOfferSentAt: journey.extend_offer_sent_at || null,
      extendOfferResponse: safeString(journey.extend_offer_response),
      poolHeatOffered: !!journey.pool_heat_offered,
      poolHeatAccepted: !!journey.pool_heat_accepted,
      checkinReminderSent: !!journey.checkin_reminder_sent,
      checkinReminderSentAt: journey.checkin_reminder_sent_at || null,
      checkoutReminderSent: !!journey.checkout_reminder_sent,
      checkoutReminderSentAt: journey.checkout_reminder_sent_at || null,
      activities: safeArray(journey.activities).map((activity) => ({
        activityId: safeString(activity.activity_id),
        activityType: safeString(activity.activity_type),
        status: safeString(activity.status, 'not_discussed'),
        discussedAt: activity.discussed_at || null,
        notes: safeString(activity.notes),
      })),
    },
    messages: safeArray(payload.messages).map((message) => ({
      messageId: safeString(message.message_id),
      direction: safeString(message.direction, 'inbound'),
      content: safeString(message.content),
      contentType: safeString(message.content_type, 'text'),
      intent: safeString(message.intent),
      wasQuickAnswer: !!message.was_quick_answer,
      responseTimeMs: message.response_time_ms == null ? null : safeNumber(message.response_time_ms),
      createdAt: message.created_at || null,
    })),
    openEscalations: safeArray(payload.open_escalations).map((escalation) => ({
      ticketId: safeString(escalation.ticket_id),
      reason: safeString(escalation.reason),
      priority: safeString(escalation.priority, 'medium'),
      status: safeString(escalation.status, 'pending'),
      summary: safeString(escalation.summary),
      createdAt: escalation.created_at || null,
    })),
    notifications: safeArray(payload.notifications).map((notification) => ({
      notificationId: safeString(notification.notification_id),
      notificationType: safeString(notification.notification_type),
      channel: safeString(notification.channel),
      recipient: safeString(notification.recipient),
      status: safeString(notification.status, 'pending'),
      sentAt: notification.sent_at || null,
      deliveredAt: notification.delivered_at || null,
      externalId: safeString(notification.external_id),
      errorMessage: safeString(notification.error_message),
    })),
    workOrders,
    // Operational event log for the expanded row's timeline strip. Same
    // shape as normalizeStayEvents — every event has stayEventId, eventType,
    // eventDomain, status, source, occurredAt. The detail endpoint includes
    // these inline so the timeline strip doesn't need a second fetch.
    events: safeArray(payload.events).map((event) => ({
      stayEventId: safeString(event.stay_event_id),
      sessionId: safeString(event.session_id),
      sessionToken: safeString(event.session_token),
      propertyCode: safeString(event.property_code),
      eventType: safeString(event.event_type),
      eventDomain: safeString(event.event_domain, 'ops'),
      status: safeString(event.status, 'completed'),
      source: safeString(event.source, 'operator'),
      note: safeString(event.note),
      payload: event.payload_json && typeof event.payload_json === 'object' ? event.payload_json : {},
      createdBy: safeString(event.created_by, 'operator'),
      occurredAt: event.occurred_at || null,
      createdAt: event.created_at || null,
      updatedAt: event.updated_at || null,
    })),
    workflow: {
      ...workflow,
      turnover: {
        ...turnover,
        readyForNextGuest: !!turnover.ready_for_next_guest,
        assignedVendorId: safeString(turnover.assigned_vendor_id),
        assignedVendorName: safeString(turnover.assigned_vendor_name),
        startedAt: turnover.started_at || null,
        readyAt: turnover.ready_at || null,
        archivedAt: turnover.archived_at || null,
        updatedAt: turnover.updated_at || null,
        updatedBy: safeString(turnover.updated_by),
      },
      operationalState: safeString(workflow.operational_state, 'active'),
      archiveEligible: !!workflow.archive_eligible,
    },
    intentMix: Object.fromEntries(
      Object.entries(payload.intent_mix || {}).map(([key, value]) => [safeString(key), safeNumber(value)])
    ),
  };
}

// Wraps GET /app/api/sessions/{id}/actions.
//
// The backend returns each item as { action_type, status, priority,
// property_code, payload, result, due_at, created_at, updated_at,
// completed_at }. action_type is one of the StayActionAgent.ACTION_*
// constants (proactive_outreach, guest_status_response, knowledge_response,
// ops_review, vendor_coordination, guest_eta_update, turnover_coordination,
// post_checkout_walkthrough, owner_internal_update, accounting_claim_handoff).
// Today's row uses status + priority + action_type to decide which inline
// buttons to surface and whether they're ready/in-progress/blocked.
export function normalizeStayActions(payload = {}) {
  const actions = safeArray(payload.actions).map((action) => ({
    actionType: safeString(action.action_type),
    status: safeString(action.status, 'ready'),
    priority: safeString(action.priority, 'medium'),
    propertyCode: safeString(action.property_code),
    payload: action.payload && typeof action.payload === 'object' ? action.payload : {},
    result: action.result && typeof action.result === 'object' ? action.result : {},
    dueAt: action.due_at || null,
    createdAt: action.created_at || null,
    updatedAt: action.updated_at || null,
    completedAt: action.completed_at || null,
  }));
  return {
    sessionId: safeString(payload.session_id),
    actions,
    count: safeNumber(payload.count, actions.length),
  };
}

// Wraps GET /app/api/sessions/{id}/events. Operational timeline for the
// expanded row — guest_checked_out, housekeeping_arrived/completed, vendor
// arrived, walkthrough started/completed, etc. event_domain buckets each
// event into post_stay / turnover / walkthrough / vendor / ops so the row
// can group strips by domain.
export function normalizeStayEvents(payload = {}) {
  const events = safeArray(payload.events).map((event) => ({
    stayEventId: safeString(event.stay_event_id),
    sessionId: safeString(event.session_id),
    sessionToken: safeString(event.session_token),
    propertyCode: safeString(event.property_code),
    eventType: safeString(event.event_type),
    eventDomain: safeString(event.event_domain, 'ops'),
    status: safeString(event.status, 'completed'),
    source: safeString(event.source, 'operator'),
    note: safeString(event.note),
    payload: event.payload_json && typeof event.payload_json === 'object' ? event.payload_json : {},
    createdBy: safeString(event.created_by, 'operator'),
    occurredAt: event.occurred_at || null,
    createdAt: event.created_at || null,
    updatedAt: event.updated_at || null,
  }));
  return {
    events,
    count: safeNumber(payload.count, events.length),
  };
}

// Wraps GET /app/api/threads/{guest_thread_id}. Cross-session guest history
// stitched together by guest_thread_id — prior pre-booking inquiries, prior
// sessions, and prior escalations. Used by the expanded Today row to answer
// "what else has this guest done with us". Each item has an item_type that
// callers can switch on to render the right link target (prebooking thread,
// session, or escalation ticket).
export function normalizeThreadTimeline(payload = {}) {
  const timeline = safeArray(payload.timeline).map((item) => ({
    itemType: safeString(item.item_type),
    itemId: safeString(item.item_id),
    propertyCode: safeString(item.property_code),
    guestName: safeString(item.guest_name),
    summary: safeString(item.summary),
    status: safeString(item.status),
    threadRef: safeString(item.thread_ref),
    occurredAt: item.occurred_at || null,
  }));
  return {
    guestThreadId: safeString(payload.guest_thread_id),
    guestName: safeString(payload.guest_name, 'Guest'),
    propertyCodes: safeArray(payload.property_codes).map((code) => safeString(code)),
    timeline,
    count: timeline.length,
  };
}

export function normalizeMessagingObservability(payload = {}) {
  return {
    available: !!payload.available,
    windowDays: safeNumber(payload.window_days, 7),
    totalMessages: safeNumber(payload.total_messages),
    modelCount: safeNumber(payload.model_count),
    fallbackCount: safeNumber(payload.fallback_count),
    routeFallbackCount: safeNumber(payload.route_fallback_count),
    propertyBoundCount: safeNumber(payload.property_bound_count),
    latestTurnCount: safeNumber(payload.latest_turn_count),
    parserMix: safeArray(payload.parser_mix).map((item) => ({
      parserUsed: safeString(item.parser_used, 'unknown'),
      count: safeNumber(item.count),
    })),
    routeMix: safeArray(payload.route_mix).map((item) => ({
      routeOutcome: safeString(item.route_outcome, 'unknown'),
      count: safeNumber(item.count),
    })),
  };
}

// Normalizes /app/api/messaging-events (both default and composer_only=true).
// Default mode populates `events` with synthesized observability rows; the
// composer_only=true mode populates `composerRows` with raw audit rows for
// the LLM-composer compare-mode review surface in Audit. Both fields are
// always present in the output regardless of which mode the backend was
// called in, so callers can read whichever one they care about.
export function normalizeMessagingEvents(payload = {}) {
  const events = safeArray(payload.events).map((event) => ({
    id: safeString(event.event_id),
    severity: safeString(event.severity, 'info'),
    title: safeString(event.title, 'Messaging event'),
    body: safeString(event.body),
    linkTarget: safeString(event.link_target),
    linkLabel: safeString(event.link_label),
    createdAt: event.created_at || null,
  }));
  const composerRows = safeArray(payload.composer_rows).map((row) => ({
    sourceMessageId: safeString(row.source_message_id),
    sentAt: row.sent_at || null,
    guestName: safeString(row.guest_name),
    propertyCode: safeString(row.property_code),
    latestGuestTurn: safeString(row.latest_guest_turn),
    guestTurnTruncated: !!row.guest_turn_truncated,
    composerActive: !!row.composer_active,
    composerSource: safeString(row.composer_source),
    composerResponseText: safeString(row.composer_response_text),
    composerTextTruncated: !!row.composer_text_truncated,
    composerLatencyMs: row.composer_latency_ms == null ? null : safeNumber(row.composer_latency_ms),
    composerInputTokens: row.composer_input_tokens == null ? null : safeNumber(row.composer_input_tokens),
    composerOutputTokens: row.composer_output_tokens == null ? null : safeNumber(row.composer_output_tokens),
    composerNotes: safeArray(row.composer_notes).map((note) => {
      if (note && typeof note === 'object') return note;
      return { message: safeString(note) };
    }),
    draftSource: safeString(row.draft_source),
    routeOutcome: safeString(row.route_outcome),
    fallbackReason: safeString(row.fallback_reason),
  }));
  return {
    events,
    count: safeNumber(payload.count, events.length),
    available: payload.available !== false,
    composerRows,
    composerCount: safeNumber(payload.composer_count, composerRows.length),
  };
}

export function normalizeTeamMembers(payload = {}) {
  const members = safeArray(payload.members).map((member) => ({
    id: safeString(member.id),
    email: safeString(member.email),
    name: safeString(member.name, 'Team member'),
    role: safeString(member.role, 'staff'),
    activated: !!member.activated,
    invitePending: !!member.invite_pending,
    inviteExpires: member.invite_expires || null,
    lastLoginAt: member.last_login_at || null,
    joinedAt: member.joined_at || null,
  }));
  return {
    members,
    count: safeNumber(payload.count, members.length),
  };
}

export function renderInlineError(title, detail, retryId) {
  return createElement(InlineError, {
    title: safeString(title),
    detail: safeString(detail),
    retryId: retryId ? safeString(retryId) : null,
  });
}
