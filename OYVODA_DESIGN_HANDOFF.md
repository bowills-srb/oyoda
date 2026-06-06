# Oyvoda Dashboard Design Handoff

## Scope

This package is for the operator dashboard only.

- `v1`: legacy operator dashboard surfaces still mounted under the server-rendered operator app
- `v2`: current SPA dashboard mounted at `/app/v2/*`

This is intentionally not a full product architecture dump. It is a design handoff for drafting operator surfaces, layout, navigation, and data-backed cards.

## Screenshot Status

Screenshot capture/export is blocked in this environment, so this package includes the exact screen inventory and source files but not saved image exports.

Current `dashboard-v2` screens that should be captured when screenshot tooling is available:

1. `/app/v2/prebooking`
2. `/app/v2/today`
3. `/app/v2/properties`
4. `/app/v2/knowledge`
5. `/app/v2/vendors`
6. `/app/v2/settings`
7. Any expanded thread/session state inside `Today`
8. Any expanded property state inside `Properties`

## What Exists Now

### v2 app shell

- [Shell.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/app/Shell.tsx)
- [Router.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/app/Router.tsx)
- [styles.css](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/styles.css)
- [ThemeProvider.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/theme/ThemeProvider.tsx)

### v2 primary routes

`Router.tsx` defines these dashboard surfaces:

1. `/app/v2/prebooking`
2. `/app/v2/today`
3. `/app/v2/properties`
4. `/app/v2/knowledge`
5. `/app/v2/vendors`
6. `/app/v2/settings`
7. `/app/v2/components`

Notes:

- `/app/v2` redirects to `/app/v2/prebooking`
- unknown routes under `/app/v2/*` also redirect to `/app/v2/prebooking`
- `Pre-Booking` is the default landing surface and the only eagerly loaded route
- `Today`, `Properties`, `Knowledge`, `Vendors`, `Settings`, and `Components` lazy-load

### v2 shell behavior

`Shell.tsx` currently provides:

- persistent top bar
- operator identity and sign-out menu
- theme switcher: `system`, `light`, `dark`
- left nav for `Pre-Booking`, `Today`, `Properties`, `Knowledge`, `Vendors`, `Settings`
- live pre-booking queue badge derived from the pre-booking feed

Design implication: the main information architecture already exists. The design task is not inventing nav from scratch; it is turning the current route map into a clearer operational command center.

## Surface Inventory

### Pre-Booking

Route folder:

- [index.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/index.tsx)
- [PreBookingRoute.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingRoute.tsx)
- [PreBookingQueueShell.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingQueueShell.tsx)
- [PreBookingInquiryCard.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingInquiryCard.tsx)
- [PreBookingControls.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingControls.tsx)
- [PreBookingAutonomyPopover.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingAutonomyPopover.tsx)
- [viewModel.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/viewModel.ts)

What this surface is:

- the operator action queue for pre-booking inquiries
- triage plus draft review
- property binding and autonomy-aware handling

Primary design objects:

- inquiry queue
- draft/reply card
- confidence and fallback states
- property match/binding controls
- autonomy visibility

### Today

Route folder:

- [index.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/index.tsx)
- [SessionExpansion.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/SessionExpansion.tsx)
- [timeline.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/timeline.ts)
- [priorityRules.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/priorityRules.ts)
- [focusPredicates.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/focusPredicates.ts)
- [lifecycleLabels.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/lifecycleLabels.ts)
- [actionLabels.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/actionLabels.ts)
- [lifecycleBoundaries.test.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/lifecycleBoundaries.test.ts)

What this surface is:

- guest operations for live stays and stay-adjacent workflows
- session list plus expansion panel
- escalation/work-order/session action context

Primary design objects:

- session roster
- live stay state
- escalation summary
- work orders
- conversation timeline
- action rail for operator interventions

### Properties

Route folder:

- [index.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/index.tsx)
- [PropertiesRoute.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/PropertiesRoute.tsx)
- [PropertyExpansion.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/PropertyExpansion.tsx)
- [DocumentUploadForm.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/DocumentUploadForm.tsx)
- [completeness.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/completeness.ts)
- [gapGrouping.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/gapGrouping.ts)
- [types.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/types.ts)

What this surface is:

- property intelligence and documentation coverage
- autonomy roster merged with identity-report data
- KB gaps grouped by property

Primary design objects:

- property roster
- completeness scoring
- documentation gaps
- property expansion panel
- asset and KB drill-down

### Knowledge, Vendors, Settings

These are real nav surfaces in v2 and matter to the IA even though this package is centered on the first three route families.

- `Knowledge`: knowledge base entries, KB gaps, AI guidance
- `Vendors`: vendor directory and categories
- `Settings`: operator settings, alert routing, team scope, portfolios

## Shared Design System Inputs

Shared system components:

- [AnchoredPanel.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/components/system/AnchoredPanel.tsx)
- [ErrorBoundary.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/components/system/ErrorBoundary.tsx)
- [InlineError.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/components/system/InlineError.tsx)
- [SurfaceControls.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/components/system/SurfaceControls.tsx)
- [SurfaceErrorState.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/components/system/SurfaceErrorState.tsx)
- [SurfaceHeader.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/components/system/SurfaceHeader.tsx)
- [SurfaceTabs.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/components/system/SurfaceTabs.tsx)

Theme and styling:

- [styles.css](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/styles.css)
- [ThemeProvider.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/theme/ThemeProvider.tsx)

Styling takeaways:

- the app already uses a tokenized CSS approach rather than relying only on utility classes
- shell/sidebar/topbar patterns are already defined
- theme persistence uses local storage key `oyvoda.dashboard_v2.theme`
- the system is ready for visual refinement without first replacing the UI architecture

## Backend Contracts Needed For Design

These are the response shapes most relevant for drafting layout and cards. Full backend implementation is not required to start design work; these contracts are enough.

### 1. Dashboard summary

Endpoint:

- `/app/api/dashboard-summary`

Current default shape from [dashboard_summary_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/operator/dashboard_summary_service.py):

```json
{
  "sessions": {
    "active": 0,
    "in_stay": 0,
    "arriving": 0,
    "total_30d": 0
  },
  "pre_booking": {
    "pending": 0,
    "oldest_pending_age_minutes": 0,
    "replied_30d": 0,
    "total_30d": 0,
    "ai_sent_today": 0
  },
  "escalations": {
    "open": 0,
    "resolved_30d": 0
  },
  "properties": 0,
  "kb_entries": 0,
  "kb_gaps": 0,
  "vendors": 0,
  "messages_30d": 0,
  "notifications_unread": 0,
  "inbox": {
    "connected": false,
    "email": null,
    "provider": null,
    "connected_at": null,
    "last_polled_at": null,
    "last_poll_success": null,
    "last_poll_summary": null,
    "last_poll_error": null,
    "last_messages_found": null,
    "last_new_pending_inquiries": null,
    "last_query_mode": null
  },
  "degraded": true
}
```

Use in design:

- operator home summary cards
- inbox health card
- global health/status strip

### 2. Inquiries / pre-booking queue

Endpoints:

- `/app/api/messages?stage=pre_booking`
- `/app/api/inquiries`
- `/app/api/v2/prebooking/bootstrap`

Type source:

- [prebooking/types.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/domain/prebooking/types.ts)

Representative shape:

```json
{
  "count": 1,
  "stage": "pre_booking",
  "status": "pending_review",
  "property": "",
  "unboundOnly": false,
  "shipIKbRetryPrimary": false,
  "unboundCount": 0,
  "stageCounts": {
    "pending_review": 1
  },
  "properties": [
    {
      "id": "prop_123",
      "name": "Beach House",
      "count": 1
    }
  ],
  "items": [
    {
      "id": "INQ-123",
      "kind": "inquiry",
      "stage": "pre_booking",
      "status": "pending_review",
      "channel": "email",
      "sourceProvider": "gmail",
      "guestName": "Jordan Lee",
      "guestEmail": "guest@example.com",
      "guestPhone": "+15551234567",
      "messageText": "Is the pool heated in October?",
      "latestGuestTurn": "Is the pool heated in October?",
      "priorThreadContext": "",
      "messagePreview": "Is the pool heated in October?",
      "draftText": "Yes, pool heat can be arranged...",
      "draftPreview": "Yes, pool heat can be arranged...",
      "finalReply": "",
      "intent": "amenity_question",
      "asks": ["pool_heat"],
      "parserSource": "llm",
      "platformListingId": "",
      "platformUnitId": "",
      "propertyBindingCandidates": [],
      "priorOperatorCommitments": [],
      "propertyMatchType": "bound",
      "routeOutcome": "operator_review",
      "autonomyDecision": "review",
      "fallbackReason": "",
      "latestTurnConfidence": 0.94,
      "latestTurnExtracted": true,
      "confidence": 0.92,
      "confidenceSource": "classifier",
      "draftSource": "knowledge",
      "confidenceLabel": "high",
      "confidenceNote": "Good property and knowledge match",
      "draftReady": true,
      "propertyId": "prop_123",
      "propertyName": "Beach House",
      "checkIn": null,
      "checkOut": null,
      "occurredAt": "2026-05-30T14:10:00Z",
      "repliedAt": null,
      "policyFlags": [],
      "policyWarnings": [],
      "blockedByGapTopics": [],
      "triggeredBy": "inbox_poll",
      "gmailMessageId": "gmail_123",
      "threadRef": "thread_123",
      "sessionToken": "",
      "priority": "normal",
      "assignedOperatorId": "",
      "assignedTeamKey": "",
      "portfolioKey": "",
      "assignmentStatus": "unassigned"
    }
  ]
}
```

Use in design:

- action queue columns and tabs
- inquiry detail pane
- draft review state
- confidence/fallback badges
- property binding UI

### 3. Sessions / today workflow

Endpoints:

- `/app/api/sessions`
- `/app/api/sessions/{id}`
- `/app/api/threads/{id}`

Type source:

- [today/types.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/domain/today/types.ts)

Representative list shape:

```json
{
  "count": 1,
  "summary": {
    "all": 1,
    "inStay": 1,
    "arriving": 0,
    "postStay": 0,
    "archived": 0,
    "withBookingContext": 1,
    "journeyTracked": 1,
    "proactiveEvaluated": 1,
    "notificationsSent": 3
  },
  "sessions": [
    {
      "sessionId": "sess_123",
      "token": "STAY-123",
      "guestName": "Jordan Lee",
      "guestPhone": "+15551234567",
      "guestEmail": "guest@example.com",
      "propertyCode": "BH-01",
      "propertyName": "Beach House",
      "numGuests": 4,
      "checkIn": "2026-06-02",
      "checkOut": "2026-06-07",
      "status": "active",
      "phase": "in_stay",
      "conversationCount": 5,
      "lastMessageAt": "2026-05-30T13:55:00Z",
      "openEscalations": 1,
      "reservationId": "res_123",
      "pmsSyncedAt": "2026-05-30T13:50:00Z",
      "proactiveTriggeredAt": "2026-05-30T13:40:00Z",
      "hasBookingContext": true,
      "journeyTracked": true,
      "welcomeSent": true,
      "checkinReminderSent": true,
      "checkoutReminderSent": false,
      "extendOfferSent": false,
      "poolHeatOffered": true,
      "poolHeatAccepted": false,
      "notificationsSent": 3,
      "assignedOperatorId": "op_123",
      "assignedOperatorLabel": "Alex",
      "openHandoffCount": 0,
      "assignmentStatus": "owned",
      "workflow": {
        "operationalState": "stable",
        "archiveEligible": false,
        "turnover": {
          "readyForNextGuest": false,
          "assignedVendorId": "",
          "assignedVendorName": "",
          "startedAt": null,
          "readyAt": null,
          "archivedAt": null,
          "updatedAt": null,
          "updatedBy": ""
        }
      }
    }
  ]
}
```

Representative detail shape:

```json
{
  "session": {
    "sessionId": "sess_123",
    "guestThreadId": "thread_123",
    "token": "STAY-123",
    "guestName": "Jordan Lee",
    "guestPhone": "+15551234567",
    "guestEmail": "guest@example.com",
    "propertyCode": "BH-01",
    "propertyName": "Beach House",
    "numGuests": 4,
    "checkIn": "2026-06-02",
    "checkOut": "2026-06-07",
    "status": "active",
    "phase": "in_stay",
    "conversationCount": 5,
    "lastMessageAt": "2026-05-30T13:55:00Z",
    "proactiveTriggeredAt": "2026-05-30T13:40:00Z",
    "pmsSyncedAt": "2026-05-30T13:50:00Z",
    "reservationId": "res_123"
  },
  "bookingContext": {
    "available": true,
    "source": "pms",
    "provider": "escapia",
    "matchStrategy": "direct",
    "guestIdentityAvailable": true,
    "property": {},
    "booking": {},
    "activeBooking": {},
    "nextBooking": null,
    "upcomingBookings": [],
    "lookup": {}
  },
  "postStayActions": {
    "canRequestFeedback": false,
    "feedbackPromptSuggestion": "",
    "hasRepeatGuestMemory": false
  },
  "journey": {
    "journeyId": "journey_123",
    "welcomeSent": true,
    "welcomeSentAt": "2026-05-30T12:00:00Z",
    "extendOfferSent": false,
    "extendOfferSentAt": null,
    "extendOfferResponse": "",
    "poolHeatOffered": true,
    "poolHeatAccepted": false,
    "checkinReminderSent": true,
    "checkinReminderSentAt": "2026-05-30T11:00:00Z",
    "checkoutReminderSent": false,
    "checkoutReminderSentAt": null,
    "activities": []
  },
  "messages": [],
  "openEscalations": [],
  "notifications": [],
  "workOrders": [],
  "events": [],
  "workflow": {
    "operationalState": "stable",
    "archiveEligible": false,
    "turnover": {
      "readyForNextGuest": false,
      "assignedVendorId": "",
      "assignedVendorName": "",
      "startedAt": null,
      "readyAt": null,
      "archivedAt": null,
      "updatedAt": null,
      "updatedBy": ""
    }
  }
}
```

Use in design:

- session list
- session detail split-view
- guest profile block
- booking context module
- action rail
- escalation/work-order panels
- timeline and message history

### 4. Escalations

Endpoint:

- `/app/api/escalations`

Type source:

- [today/types.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/domain/today/types.ts)

The route consumes escalation data as part of the Today domain, with fields such as:

```json
{
  "ticketId": "esc_123",
  "reason": "maintenance",
  "priority": "high",
  "status": "open",
  "summary": "Guest reported AC issue",
  "createdAt": "2026-05-30T13:20:00Z"
}
```

Use in design:

- open escalation strip
- session risk badges
- escalation workspace card
- assignment/dispatch actions

### 5. Properties autonomy / roster

Endpoints:

- `/app/api/properties/autonomy`
- `/app/api/properties/identity-report`
- `/app/api/portfolios`
- `/app/api/properties/{propertyCode}/assets`
- `/app/api/kb?property_id=...`

Type sources:

- [PropertiesRoute.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/PropertiesRoute.tsx)
- [properties/types.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/domain/properties/types.ts)

Known identity-report shape:

```json
{
  "property_code": "BH-01",
  "external_id": "ext_123",
  "display_name": "Beach House",
  "marketing_name": "Beach House",
  "pms_property_ids": ["pms_123"],
  "pms_unit_codes": ["BH-01"],
  "ota_refs": {
    "airbnb": "ab_123"
  },
  "aliases": ["Beach House Gulf View"],
  "knowledge_count": 24,
  "asset_count": 8,
  "review_status": {
    "approved": 20,
    "pending": 4
  },
  "profile_updated_at": "2026-05-30T10:00:00Z"
}
```

Practical roster shape expected by the route after merge/normalization:

```json
{
  "propertyCode": "BH-01",
  "knowledgeRef": "BH-01",
  "propertyName": "Beach House",
  "displayName": "Beach House",
  "marketingName": "Beach House",
  "community": "Gulf Shores",
  "addressStreet": "100 Shoreline Dr",
  "addressCity": "Gulf Shores",
  "knowledgeCount": 24,
  "assetCount": 8,
  "autonomyEnabled": true,
  "autonomyMode": "assisted",
  "hasOpenGaps": true
}
```

Use in design:

- property table or board
- completeness and coverage metrics
- autonomy visibility
- property drill-down

### 6. KB gaps

Endpoint:

- `/app/api/kb-gaps?resolved=false`

Type source:

- [knowledge/types.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/domain/knowledge/types.ts)

Representative shape:

```json
{
  "id": "gap_123",
  "question": "Is the pool heated year-round?",
  "category": "Amenities",
  "categorySlug": "amenities",
  "confidence": 0.43,
  "aiAnswer": "",
  "stage": "pre_booking",
  "channel": "email",
  "source": "inquiry",
  "resolved": false,
  "property": "BH-01",
  "askCount": 3,
  "createdAt": "2026-05-30T09:00:00Z",
  "draftId": "INQ-123",
  "reason": "missing_knowledge",
  "intent": "amenity_question",
  "thresholdPct": 0.8,
  "actualPct": 0.43,
  "missingTopics": ["pool_heat"],
  "parserSource": "llm",
  "asks": ["pool_heat"],
  "platformListingId": "",
  "platformUnitId": "",
  "linkContextSummary": "",
  "policyWarnings": [],
  "lastAskedAt": "2026-05-30T09:00:00Z"
}
```

Use in design:

- knowledge gap queue
- property completeness scoring
- operator coaching and documentation prompts

## Design-Ready Surface Recommendations

If the goal is to start drafting layouts immediately, the highest-value surfaces are:

1. Operator Home
2. Pre-Booking Command Center
3. Today / Guest Operations
4. Property Intelligence
5. Escalation Workspace

Suggested relationship to current routes:

- `Operator Home`: new summary surface powered primarily by `/app/api/dashboard-summary`
- `Pre-Booking Command Center`: evolves current `/app/v2/prebooking`
- `Guest Operations`: evolves current `/app/v2/today`
- `Property Intelligence`: evolves current `/app/v2/properties`
- `Escalation Workspace`: likely starts as a Today sub-surface before becoming its own route if volume justifies it

## What You Need To Start Designing

You do not need the full backend codebase to draft the surfaces.

You do need:

1. the v2 route files
2. shell/layout files
3. styles and theme
4. shared system components
5. API response shapes for the main operational surfaces
6. screenshots of the current v2 screens when capture is available

That means the current package is already enough to start wireframes and layout exploration.

## Implementation Files To Keep Open While Designing

Most important frontend files:

- [Shell.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/app/Shell.tsx)
- [Router.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/app/Router.tsx)
- [styles.css](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/styles.css)
- [ThemeProvider.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/theme/ThemeProvider.tsx)
- [PreBookingRoute.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingRoute.tsx)
- [index.tsx Today](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/index.tsx)
- [PropertiesRoute.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/PropertiesRoute.tsx)

Most important domain contract files:

- [prebooking/types.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/domain/prebooking/types.ts)
- [today/types.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/domain/today/types.ts)
- [knowledge/types.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/domain/knowledge/types.ts)
- [properties/types.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/domain/properties/types.ts)

## Bottom Line

For layout and surface design, frontend structure plus typed/sample API shapes is sufficient.

The full backend becomes important later for:

- mutation wiring
- edge-case handling
- permissions
- data freshness and polling behavior
- error states
- empty-state realism

For the drafting phase, this handoff should be enough to start.
