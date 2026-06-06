# Oyvoda Operator Dashboard Architecture Review Package

Generated: 2026-05-30  
Repo root: `/Users/dhuntermckenzie/Downloads/oyvoda`

## Scope

This package is centered on the operator dashboard, per current product focus.

It still includes repo-wide architecture context, but the frontend analysis, surfaced-vs-unsurfaced feature mapping, and product gap assessment prioritize:

- `/app/dashboard` legacy operator shell (v1)
- `/app/v2` React operator dashboard (v2)
- the operator-facing backend APIs under `/app/api/*` and `/app/api/v2/*`

## Executive Summary

Oyvoda currently has a strong backend substrate for operator workflows, but the frontend story is split across two main dashboard generations:

- `app/static/dashboard/` is a large legacy operator dashboard shell with many sections and a broad endpoint surface.
- `app/static/dashboard-v2/` is the newer React/TanStack Query dashboard and is the clearest path forward.
- `app/api/v1/endpoints/operator_dashboard.py`, `operator_dashboard_v2.py`, and `operator_app.py` expose overlapping operator-facing UI entry points around those two generations.

The backend is materially ahead of the frontend. There is already meaningful support for:

- pre-booking review and autonomy controls
- session/today workflows
- escalation workflows and action agents
- knowledge gaps and operator guidance
- property autonomy, assets, and identity review
- vendor intelligence and scoped alert routing
- PMS-backed stay context and message normalization

The biggest product issue is not missing backend capability. It is fragmentation:

- multiple frontend shells
- multiple dashboard entry points
- duplicated service families
- dashboard-v2 only partially surfacing the existing operator APIs

The highest-value path is to make `dashboard-v2` the single operator surface and progressively absorb:

- escalations deep views
- property identity review and autonomy editing
- PMS/session operational detail
- dashboard summary/briefing
- market/operator intelligence cards

## 1. Repository Tree

Operator-dashboard-relevant tree, with dependency/build/env folders omitted and very large fixture/data areas summarized.

```text
.
├── app
│   ├── api
│   │   ├── dependencies
│   │   │   ├── ops_auth.py
│   │   │   ├── request_tenant.py
│   │   │   └── tenant.py
│   │   ├── v1
│   │   │   ├── __init__.py
│   │   │   └── endpoints
│   │   │       ├── admin_llm_usage.py
│   │   │       ├── alert_contacts.py
│   │   │       ├── audit.py
│   │   │       ├── concierge.py
│   │   │       ├── knowledge.py
│   │   │       ├── market_intelligence.py
│   │   │       ├── messaging_webhooks.py
│   │   │       ├── mobile_v2.py
│   │   │       ├── operator.py
│   │   │       ├── operator_app.py
│   │   │       ├── operator_dashboard.py
│   │   │       ├── operator_dashboard_api.py
│   │   │       ├── operator_dashboard_v2.py
│   │   │       ├── operator_dashboard_v2_api.py
│   │   │       ├── operator_onboarding.py
│   │   │       ├── operator_policies.py
│   │   │       ├── operator_prebooking.py
│   │   │       ├── operator_properties.py
│   │   │       ├── operator_signup.py
│   │   │       ├── prebooking_page.py
│   │   │       ├── privacy.py
│   │   │       └── public_landing.py
│   ├── core
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── db_connect.py
│   │   ├── exceptions.py
│   │   ├── security.py
│   │   ├── security_layer.py
│   │   └── totp_mfa.py
│   ├── domain
│   │   ├── signals
│   │   │   ├── computations.py
│   │   │   ├── confidence.py
│   │   │   └── models.py
│   │   └── concierge
│   ├── mcp
│   │   ├── registry.py
│   │   └── servers
│   │       ├── concierge_mcp.py
│   │       ├── detector_mcp.py
│   │       ├── governance_mcp.py
│   │       ├── knowledge_mcp.py
│   │       ├── neighborhood_intel_mcp.py
│   │       ├── pms_mcp.py
│   │       ├── sanitizer_mcp.py
│   │       ├── scraper_mcp.py
│   │       └── signal_mcp.py
│   ├── services
│   │   ├── agents
│   │   │   ├── escalation_handoff_agent.py
│   │   │   ├── healer_agent.py
│   │   │   ├── knowledge_curator_agent.py
│   │   │   ├── pms_sync_agent.py
│   │   │   ├── property_router.py
│   │   │   └── router_agent.py
│   │   ├── concierge
│   │   │   ├── ai_concierge.py
│   │   │   ├── escalation_service.py
│   │   │   ├── guest_profile_service.py
│   │   │   ├── guest_session.py
│   │   │   ├── guest_thread_service.py
│   │   │   ├── guidebook_ingest_service.py
│   │   │   ├── inquiry_persistence.py
│   │   │   ├── knowledge_gap_recorder.py
│   │   │   ├── knowledge_service.py
│   │   │   ├── market_brain.py
│   │   │   ├── operator_learning.py
│   │   │   ├── post_booking_routing.py
│   │   │   ├── property_context.py
│   │   │   ├── property_router.py
│   │   │   ├── sms_service.py
│   │   │   └── thread_property_inheritance.py
│   │   ├── connectors
│   │   │   ├── adapter_backed_booking_data_provider.py
│   │   │   ├── booking_data_provider.py
│   │   │   ├── escapia_connector.py
│   │   │   ├── escapia_sync.py
│   │   │   ├── guesty_connector.py
│   │   │   ├── integration_gateway.py
│   │   │   ├── integration_registry.py
│   │   │   ├── pms_connectors.py
│   │   │   ├── pms_ingest_worker.py
│   │   │   └── track_connector.py
│   │   ├── integrations
│   │   │   ├── direct_email_parsers.py
│   │   │   ├── email_dispatch.py
│   │   │   ├── email_inbound.py
│   │   │   ├── email_pipeline.py
│   │   │   ├── email_reply.py
│   │   │   ├── email_routing.py
│   │   │   ├── email_type_classifier.py
│   │   │   ├── gmail_inbox_poller.py
│   │   │   ├── gmail_push.py
│   │   │   ├── llm_email_extractor.py
│   │   │   ├── ota_email_parsers.py
│   │   │   ├── ota_reservation_events.py
│   │   │   ├── reservation_aware_routing.py
│   │   │   ├── vendor_email_parsers.py
│   │   │   ├── website_widget.py
│   │   │   └── website_widget_v2.py
│   │   ├── knowledge
│   │   │   ├── indexer.py
│   │   │   ├── knowledge_indexer.py
│   │   │   ├── librarian_agent.py
│   │   │   ├── market_inference.py
│   │   │   ├── places_pipeline.py
│   │   │   ├── vector_store.py
│   │   │   └── voice_pod.py
│   │   ├── market
│   │   │   └── market_context_builder.py
│   │   ├── market_intelligence
│   │   │   ├── expansion_intelligence.py
│   │   │   ├── market_intelligence_engine.py
│   │   │   ├── platform_weighting.py
│   │   │   └── platform_weighting_v2.py
│   │   ├── messaging
│   │   │   ├── autonomy_gate.py
│   │   │   ├── booking_context_adapters.py
│   │   │   ├── channel_router.py
│   │   │   ├── coverage_monitor.py
│   │   │   ├── guest_messaging.py
│   │   │   ├── identity_resolver.py
│   │   │   ├── inbound_normalizer.py
│   │   │   ├── inbound_transport.py
│   │   │   ├── inbox_adapters.py
│   │   │   ├── message_event_store.py
│   │   │   ├── operator_alerts.py
│   │   │   ├── parser_notes_schema.py
│   │   │   └── rcs_templates.py
│   │   ├── messaging_brain
│   │   │   ├── agents
│   │   │   ├── context
│   │   │   ├── eval
│   │   │   ├── grounding
│   │   │   ├── modules
│   │   │   ├── persistence
│   │   │   ├── audit.py
│   │   │   ├── inbound_message_gate.py
│   │   │   ├── orchestrator.py
│   │   │   ├── pre_booking.py
│   │   │   ├── pre_booking_lifecycle.py
│   │   │   ├── pre_booking_retry.py
│   │   │   ├── proactive_trigger_adapter.py
│   │   │   ├── property_resolution_writeback.py
│   │   │   └── session_channel_adapter.py
│   │   ├── observability
│   │   │   ├── deployment_runtime.py
│   │   │   ├── infra_health.py
│   │   │   ├── llm_usage_tracker.py
│   │   │   ├── model_pricing.py
│   │   │   ├── slo_metrics.py
│   │   │   ├── startup_checks.py
│   │   │   └── watch_layer.py
│   │   ├── operator
│   │   │   ├── dashboard_summary_service.py
│   │   │   ├── escalation_action_agent.py
│   │   │   ├── escalation_detector_service.py
│   │   │   ├── escalation_workflow_service.py
│   │   │   ├── handoff_service.py
│   │   │   ├── historical_thread_evaluator.py
│   │   │   ├── message_retention_service.py
│   │   │   ├── prebooking_queue_service.py
│   │   │   ├── property_asset_service.py
│   │   │   ├── realtime_hub.py
│   │   │   ├── safety_protocol_service.py
│   │   │   ├── scope_service.py
│   │   │   ├── stay_action_agent.py
│   │   │   ├── stay_detector_service.py
│   │   │   ├── stay_event_service.py
│   │   │   ├── stay_journey_service.py
│   │   │   ├── stay_operations_service.py
│   │   │   ├── stay_pms_feed_service.py
│   │   │   ├── stay_proactive_runtime.py
│   │   │   ├── stay_proactive_service.py
│   │   │   ├── stay_receptiveness_service.py
│   │   │   ├── stay_workflow_service.py
│   │   │   ├── vendor_intelligence_service.py
│   │   │   └── work_order_service.py
│   │   ├── signals
│   │   │   ├── amenity.py
│   │   │   ├── attribution.py
│   │   │   ├── coverage_score.py
│   │   │   ├── dynamic_decay.py
│   │   │   ├── market_dynamics.py
│   │   │   ├── operator.py
│   │   │   ├── platform.py
│   │   │   ├── regime_detection.py
│   │   │   ├── scheduler.py
│   │   │   ├── seasonality.py
│   │   │   ├── signal_contract.py
│   │   │   └── signal_pipeline.py
│   │   ├── transport
│   │   │   ├── base.py
│   │   │   ├── credentials.py
│   │   │   ├── factory.py
│   │   │   └── providers
│   │   │       └── gmail_transport.py
│   │   └── voice
│   │       ├── conversation_logger.py
│   │       ├── twilio_integration.py
│   │       ├── voice_session.py
│   │       ├── voice_translation.py
│   │       └── providers
│   │           ├── deepgram_stt.py
│   │           └── elevenlabs_tts.py
│   ├── static
│   │   ├── dashboard
│   │   │   ├── index.html
│   │   │   ├── js
│   │   │   │   ├── adapters.js
│   │   │   │   ├── api.js
│   │   │   │   ├── auth.js
│   │   │   │   ├── main.js
│   │   │   │   ├── router.js
│   │   │   │   ├── state.js
│   │   │   │   ├── ui.js
│   │   │   │   └── sections
│   │   │   │       ├── analytics.js
│   │   │   │       ├── audit.js
│   │   │   │       ├── escalations.js
│   │   │   │       ├── knowledge.js
│   │   │   │       ├── llm-usage.js
│   │   │   │       ├── market.js
│   │   │   │       ├── messages.js
│   │   │   │       ├── notifications.js
│   │   │   │       ├── properties.js
│   │   │   │       ├── sessions.js
│   │   │   │       ├── settings.js
│   │   │   │       ├── shell.js
│   │   │   │       ├── team.js
│   │   │   │       ├── today.js
│   │   │   │       └── vendors.js
│   │   │   ├── shell.html
│   │   │   └── styles
│   │   │       ├── dashboard.css
│   │   │       └── tokens.css
│   │   ├── dashboard-v2
│   │   │   ├── index.html
│   │   │   ├── postcss.config.cjs
│   │   │   ├── tailwind.config.cjs
│   │   │   ├── tsconfig.json
│   │   │   ├── vite.config.ts
│   │   │   └── src
│   │   │       ├── api
│   │   │       ├── app
│   │   │       ├── components
│   │   │       ├── domain
│   │   │       ├── lib
│   │   │       ├── realtime
│   │   │       ├── routes
│   │   │       ├── shared
│   │   │       ├── theme
│   │   │       ├── main.tsx
│   │   │       └── styles.css
│   │   └── og-image.svg
│   ├── workers
│   │   ├── celery_app.py
│   │   └── tasks.py
│   └── main.py
├── db
│   ├── migrations
│   │   └── versions
│   └── models
│       ├── concierge_dining_reservations.py
│       ├── concierge_escalations.py
│       ├── concierge_knowledge.py
│       ├── concierge_sessions.py
│       ├── core.py
│       ├── documents.py
│       ├── guest_profiles.py
│       ├── guest_thread.py
│       ├── healer.py
│       ├── integrations.py
│       ├── intelligence_artifacts.py
│       ├── market_events.py
│       ├── market_model.py
│       ├── operator_policy.py
│       ├── property_group.py
│       └── signals.py
├── docs
│   ├── ARCHITECTURE.md
│   ├── DEVELOPER_GUIDEBOOK.md
│   ├── DUPLICATION_ANALYSIS.md
│   ├── FRONTEND_UNIFICATION_CARRYFORWARD.md
│   ├── INBOUND_MESSAGE_GATE.md
│   ├── MESSAGING_ARCHITECTURE.md
│   ├── MESSAGING_BRAIN_PREBOOKING_BEACH_HABITATS_ROLLOUT.md
│   ├── MESSAGING_BRAIN_RICH_CONTEXT_ROLLOUT.md
│   ├── OPERATOR_CONTEXT_SCHEMA.md
│   ├── OPERATOR_INTELLIGENCE_LAYER_CARRYFORWARD.md
│   ├── OPERATOR_KNOWLEDGE_CARRYFORWARD.md
│   ├── PHASE_0_BRAIN_AUDIT.md
│   ├── PHASE_1_3_SEAM_MAP.md
│   ├── PHASE_2_SEAM_MAP.md
│   ├── PROPERTIES_V2_CONTRACT.md
│   ├── RUNBOOK_COMPOSER_ROLLOUT.md
│   ├── SESSION_12_COMPOSER_DESIGN.md
│   ├── SIGNAL_ARCHITECTURE_STATUS.md
│   └── SIGNAL_PIPELINE_INFRASTRUCTURE.md
├── schemas
│   ├── canonical_signals.py
│   ├── contracts.py
│   ├── core.py
│   └── signals.py
├── scripts
│   ├── build-dashboard.js
│   ├── dashboard_smoke.mjs
│   ├── historical_inbox_replay_report.py
│   ├── index_guidebooks.py
│   ├── pre_booking_setup.py
│   ├── replay_brain_prebooking_primary.py
│   ├── run-dashboard-v2-boundaries.mjs
│   ├── run_feature_flag.py
│   └── synthetic_inbound_pipeline_report.py
├── tests
│   ├── integration
│   │   ├── test_context_builder_agent_canonical_kb_postgres.py
│   │   ├── test_context_builder_agent_rich_context_postgres.py
│   │   ├── test_guidebook_ingest_scoped_knowledge_postgres.py
│   │   ├── test_inquiry_corpus_replay.py
│   │   ├── test_operator_policies_postgres.py
│   │   ├── test_operator_properties_reconcile.py
│   │   └── test_schema_shape_regression.py
│   ├── policy
│   │   └── test_policies.py
│   └── unit
│       ├── test_ai_concierge_pipeline.py
│       ├── test_booking_context_agent.py
│       ├── test_context_builder_agent_rich_context.py
│       ├── test_dashboard_kb_service.py
│       ├── test_dashboard_summary_service.py
│       ├── test_email_pipeline.py
│       ├── test_escalation_action_agent.py
│       ├── test_escalation_workflow_service.py
│       ├── test_identity_resolver.py
│       ├── test_inbound_message_gate.py
│       ├── test_inbound_transport.py
│       ├── test_knowledge_gap_recorder.py
│       ├── test_llm_composer_agent.py
│       ├── test_llm_intake_agent.py
│       ├── test_message_event_store_property_binding.py
│       ├── test_operator_prebooking_contract.py
│       ├── test_prebooking_queue_service.py
│       ├── test_property_asset_service.py
│       ├── test_response_policy_agent_aggregate_confidence.py
│       ├── test_router_agent.py
│       ├── test_session_channel_adapter.py
│       ├── test_stay_action_agent.py
│       ├── test_stay_event_service.py
│       ├── test_stay_pms_feed_service.py
│       ├── test_stay_workflow_service.py
│       ├── test_transport_factory.py
│       └── test_vendor_intelligence_service.py
├── workers
│   ├── analytics
│   ├── concierge
│   ├── detectors
│   ├── feedback
│   ├── ingestion
│   ├── normalization
│   └── projections
├── docker-compose.yml
├── main_railway.py
├── package.json
├── README.md
├── requirements.txt
└── railway.toml
```

## 2. Frontend

### 2.1 Dashboard Frontend Generations

There are two main operator dashboard frontend generations:

| Surface | Route | Stack | Status |
| --- | --- | --- | --- |
| Legacy authenticated operator shell | `/app/dashboard` | static HTML + modular ES scripts | Broadest feature coverage, older architecture |
| Dashboard v2 | `/app/v2/*` | React 18 + React Router + TanStack Query + Tailwind/CSS tokens | Strategic future path |

There is also a standalone pre-booking page at `/app/pre-booking`, but it is better understood as a workflow slice that overlaps both dashboard generations rather than a third dashboard generation.

There are also two `/operator-dashboard` routes in the repo:

- `app/api/v1/endpoints/operator_dashboard.py`
- `app/api/v1/endpoints/operator_dashboard_v2.py`

These are separate public/dashboard experiments and should not be treated as the main authenticated operator app.

### 2.2 Routes / Pages

#### Active React `dashboard-v2` route table

Defined in `app/static/dashboard-v2/src/app/Router.tsx`.

| Route | File | Purpose |
| --- | --- | --- |
| `/app/v2/prebooking` | `routes/PreBooking/PreBookingRoute.tsx` | operator pre-booking queue |
| `/app/v2/today` | `routes/Today/index.tsx` | live stay/session operations |
| `/app/v2/properties` | `routes/Properties/PropertiesRoute.tsx` | property roster, completeness, assets, KB linkage |
| `/app/v2/knowledge` | `routes/Knowledge/index.tsx` | KB entries, gaps, guidance |
| `/app/v2/vendors` | `routes/Vendors/index.tsx` | vendor directory and categories |
| `/app/v2/settings` | `routes/Settings/index.tsx` | autonomy, alert routing, team, portfolios |
| `/app/v2/components` | `routes/Components/index.tsx` | internal component gallery, not product UI |

#### Legacy dashboard sections

Defined in `app/static/dashboard/index.html` with per-section JS modules under `app/static/dashboard/js/sections/`.

Major sections:

- `today`
- `prebooking`
- `prearrival`
- `instay`
- `poststay`
- `properties`
- `vendors`
- `knowledge`
- `escalations`
- `analytics`
- `audit`
- `settings`

### 2.3 Major Screens

#### Operator Dashboard / Today

- Primary file: `app/static/dashboard-v2/src/routes/Today/index.tsx`
- Purpose: stay-centric queue with lifecycle tabs for `pre_arrival`, `arriving`, `in_stay`, `post_stay`
- Data model: session-first, not message-first
- Expansion component: `routes/Today/SessionExpansion.tsx`

#### Pre-Booking Inbox

- Primary file: `app/static/dashboard-v2/src/routes/PreBooking/PreBookingRoute.tsx`
- Supporting files:
  - `PreBookingInquiryCard.tsx`
  - `PreBookingQueueShell.tsx`
  - `PreBookingControls.tsx`
  - `PreBookingAutonomyPopover.tsx`
  - `viewModel.ts`
- Purpose: AI-drafted inquiry review, approve/edit/reject/bind-property, autonomy threshold control

#### Thread / Session View

- React v2: inline expansion inside Today via `SessionExpansion.tsx`
- Legacy: split pane in `app/static/dashboard/index.html` section `sess-thread`
- Backend data source: `/app/api/threads/{guest_thread_id}` plus `/app/api/sessions/{session_id}`

#### Properties

- Primary file: `app/static/dashboard-v2/src/routes/Properties/PropertiesRoute.tsx`
- Expansion file: `PropertyExpansion.tsx`
- Purpose: property roster, completeness, gaps, assets, scoped KB views

#### Settings

- Primary file: `app/static/dashboard-v2/src/routes/Settings/index.tsx`
- Tabs:
  - `AutonomyTab.tsx`
  - `AlertRoutingTab.tsx`
  - `TeamTab.tsx`
  - `PortfoliosTab.tsx`

#### Knowledge

- Primary file: `app/static/dashboard-v2/src/routes/Knowledge/index.tsx`
- Purpose: KB CRUD, KB gap resolution, operator AI guidance

#### Vendors

- Primary file: `app/static/dashboard-v2/src/routes/Vendors/index.tsx`
- Purpose: category and vendor management, scoped application to properties

### 2.4 Components

#### Shared system components

Under `app/static/dashboard-v2/src/components/system/`:

- `AnchoredPanel.tsx`
- `ErrorBoundary.tsx`
- `InlineError.tsx`
- `SurfaceControls.tsx`
- `SurfaceErrorState.tsx`
- `SurfaceHeader.tsx`
- `SurfaceTabs.tsx`

These are the main layout primitives for v2.

#### UI primitives

Under `app/static/dashboard-v2/src/components/ui/`:

- `button.tsx`
- `checkbox.tsx`
- `input.tsx`
- `select.tsx`
- `slider.tsx`
- `switch.tsx`
- `textarea.tsx`

#### Low-level display primitives

Under `app/static/dashboard-v2/src/components/primitives/`:

- `Badge.tsx`
- `KeyboardHint.tsx`

### 2.5 Design System / Theme Files

#### React dashboard-v2 theme

- `app/static/dashboard-v2/src/styles.css`
- `app/static/dashboard-v2/src/theme/ThemeProvider.tsx`
- `app/static/dashboard-v2/tailwind.config.cjs`

Observations:

- tokenized CSS variables for surfaces, borders, text, accent, and status colors
- light/dark theme support through `ThemeProvider`
- layout is mostly custom CSS with Tailwind utility pipeline available
- typography is mostly system stack plus `@fontsource/jetbrains-mono`

#### Legacy dashboard theme

- `app/static/dashboard/styles/tokens.css`
- `app/static/dashboard/styles/dashboard.css`

Observations:

- visually more “productized” than raw v2 in some places
- owns many shell-level interaction patterns that v2 is still rebuilding

### 2.6 Screenshots

Requested screenshots were reviewed against operator-dashboard surfaces, but PNG export from the local desktop was not possible in this sandbox because macOS screen capture was not approved from the environment.

What was visually inspected locally:

- operator shell / dashboard
- pre-booking inbox
- session/thread area
- properties view
- settings view

Files used for visual inspection:

- `app/static/dashboard/index.html`
- `app/static/dashboard-v2/src/routes/*`
- temporary local render of `app/static/dashboard/index.html`

### 2.7 Key Frontend Files

#### Shell and routing

- `app/static/dashboard-v2/src/app/Router.tsx`
- `app/static/dashboard-v2/src/app/Shell.tsx`
- `app/static/dashboard-v2/src/main.tsx`

#### Domain data adapters

- `app/static/dashboard-v2/src/domain/prebooking/*`
- `app/static/dashboard-v2/src/domain/today/*`
- `app/static/dashboard-v2/src/domain/properties/*`
- `app/static/dashboard-v2/src/domain/knowledge/*`
- `app/static/dashboard-v2/src/domain/vendors/*`
- `app/static/dashboard-v2/src/domain/settings/*`

#### Realtime / state

- `app/static/dashboard-v2/src/realtime/RealtimeBridge.tsx`
- `app/static/dashboard-v2/src/realtime/invalidation.ts`
- `app/static/dashboard-v2/src/lib/query/queryClient.ts`
- `app/static/dashboard-v2/src/lib/query/queryKeys.ts`

#### Legacy shell

- `app/static/dashboard/index.html`
- `app/static/dashboard/js/main.js`
- `app/static/dashboard/js/router.js`
- `app/static/dashboard/js/api.js`
- `app/static/dashboard/js/sections/*.js`

## 3. Backend

### 3.1 Backend Dashboard Entry Points

#### Main app boot

- `app/main.py`

Key behavior:

- creates FastAPI app
- mounts API routers
- initializes DB, sessions, observability
- loads operator dashboard endpoints, landing endpoints, mobile guest endpoints, and market APIs together

#### Authenticated operator UI shell

- `app/api/v1/endpoints/operator_app.py`

Key routes:

- `GET /app`
- `GET /app/dashboard`
- `GET /app/v2`
- `GET /app/v2/{path:path}`
- `POST /app/auth/login`
- `POST /app/auth/logout`
- `GET /app/auth/session`

This file is also responsible for many operator APIs that are not in `operator_dashboard_api.py`, including:

- team
- portfolios
- property-link review / binding review flows

### 3.2 API Routes / Endpoints

### Operator dashboard API surface actually used by `dashboard-v2`

#### Pre-booking

- `GET /app/api/messages`
- `GET /app/api/inquiries`
- `GET /app/api/inquiries/stats`
- `POST /app/api/inquiries/{draft_id}/approve`
- `POST /app/api/inquiries/{draft_id}/edit`
- `POST /app/api/inquiries/{draft_id}/reject`
- `POST /app/api/inquiries/{draft_id}/bind-property`
- `GET /app/api/property-links/suggest`
- `GET /app/api/v2/prebooking/bootstrap`
- `GET /app/api/v2/autonomy`
- `PUT /app/api/v2/autonomy`

Primary files:

- `app/api/v1/endpoints/operator_prebooking.py`
- `app/api/v1/endpoints/operator_dashboard_v2_api.py`
- `app/api/v1/endpoints/operator_app.py`

#### Today / sessions / threads

- `GET /app/api/sessions`
- `GET /app/api/sessions/{session_id}`
- `GET /app/api/threads/{guest_thread_id}`
- `GET /app/api/sessions/{session_id}/work-orders`
- `GET /app/api/sessions/{session_id}/actions`
- `POST /app/api/sessions/{session_id}/actions/{action_type}/execute`
- `POST /app/api/sessions/{session_id}/send-update`
- `POST /app/api/sessions/{session_id}/request-feedback`
- `GET /app/api/escalations`

Primary file:

- `app/api/v1/endpoints/operator_dashboard_api.py`

#### Properties

- `GET /app/api/properties/autonomy`
- `GET /app/api/properties/identity-report`
- `GET /app/api/portfolios`
- `GET /app/api/kb-gaps`
- `GET /app/api/kb`
- `GET /app/api/properties/{property_code}/assets`
- `POST /app/api/kb-gaps/{gap_id}/resolve`

Primary files:

- `app/api/v1/endpoints/operator_dashboard_api.py`
- `app/api/v1/endpoints/operator_app.py`

#### Knowledge

- `GET /app/api/kb`
- `POST /app/api/kb`
- `PATCH /app/api/kb/{entry_id}`
- `DELETE /app/api/kb/{entry_id}`
- `POST /app/api/kb/test`
- `GET /app/api/kb-gaps`
- `POST /app/api/kb-gaps/{gap_id}/resolve`
- `POST /app/api/kb-gaps/{gap_id}/dismiss`
- `GET /app/api/settings/ai-guidance`
- `PUT /app/api/settings/ai-guidance`

#### Vendors

- `GET /app/api/vendor-categories`
- `POST /app/api/vendor-categories`
- `GET /app/api/vendors`
- `POST /app/api/vendors`
- `PATCH /app/api/vendors/{vendor_id}`
- `DELETE /app/api/vendors/{vendor_id}`

#### Settings / team / alert routing

- `GET /app/api/settings`
- `PATCH /app/api/settings`
- `GET /app/api/settings/alert-routing`
- `POST /app/api/settings/alert-routing`
- `PATCH /app/api/settings/alert-routing/{contact_id}`
- `POST /app/api/settings/alert-routing/{contact_id}/ooo`
- `POST /app/api/settings/alert-routing/{contact_id}/available`
- `DELETE /app/api/settings/alert-routing/{contact_id}`
- `GET /app/api/team`
- `POST /app/api/team/invite`
- `DELETE /app/api/team/{member_id}`
- `PATCH /app/api/team/{member_id}/role`
- `GET /app/api/team/{member_id}/scopes`
- `PUT /app/api/team/{member_id}/scopes`
- `GET /app/api/portfolios`
- `POST /app/api/portfolios`
- `PUT /app/api/portfolios/{portfolio_id}/properties`

### 3.3 Database Models / Schemas

#### Operator workflow / dashboard data

- `db/models/concierge_sessions.py`
  - `concierge_guest_sessions`
  - `concierge_guest_journeys`
  - `concierge_journey_activities`
  - `concierge_messages`
  - `concierge_notifications`
- `db/models/concierge_escalations.py`
  - `concierge_escalations`
- `db/models/guest_thread.py`
  - `guest_threads`
- `db/models/operator_policy.py`
  - `operator_policies`
  - `operator_integrations`
  - `operator_onboarding`
- `db/models/property_group.py`
  - `property_groups`
  - `property_group_memberships`

#### Knowledge / documents / learning

- `db/models/concierge_knowledge.py`
  - `concierge_knowledge_gaps`
  - `concierge_global_faq`
  - `concierge_maintenance_events`
- `db/models/documents.py`
  - `documents`
  - `extracted_fields`
- `db/models/guest_profiles.py`
  - `guest_profiles`
- `db/models/intelligence_artifacts.py`
  - evidence, snapshots, decision logs, market evidence

#### PMS / integration / market

- `db/models/integrations.py`
  - `integration_connections`
  - `integration_sync_jobs`
  - `integration_raw_records`
- `db/models/signals.py`
  - `signals`
- `db/models/market_events.py`
  - `market_events`
  - `market_registry`

#### Contract / schema files

- `schemas/contracts.py`
- `schemas/signals.py`
- `schemas/canonical_signals.py`
- `app/services/orchestration/messaging_brain_contracts.py`

### 3.4 Services / Agents

#### Operator services

- `dashboard_summary_service.py`
- `prebooking_queue_service.py`
- `escalation_workflow_service.py`
- `escalation_detector_service.py`
- `escalation_action_agent.py`
- `stay_workflow_service.py`
- `stay_action_agent.py`
- `stay_event_service.py`
- `stay_pms_feed_service.py`
- `vendor_intelligence_service.py`
- `scope_service.py`
- `property_asset_service.py`
- `message_retention_service.py`
- `handoff_service.py`
- `work_order_service.py`

#### Messaging brain / concierge core

- `messaging_brain/orchestrator.py`
- `messaging_brain/agents/*`
- `messaging_brain/context/*`
- `messaging/inbound_normalizer.py`
- `messaging/inbound_transport.py`
- `messaging/channel_router.py`
- `messaging/autonomy_gate.py`
- `concierge/ai_concierge.py`
- `concierge/market_brain.py`
- `concierge/operator_learning.py`
- `concierge/thread_property_inheritance.py`

#### PMS / integration / email / voice

- `connectors/*`
- `integrations/email_*`
- `integrations/gmail_*`
- `integrations/ota_*`
- `voice/twilio_integration.py`
- `notifications/sms_service.py`
- `concierge/sms_service.py`

### 3.5 Message Ingestion Pipeline

Primary code path spans:

- `app/services/integrations/email_pipeline.py`
- `app/services/messaging/inbound_normalizer.py`
- `app/services/orchestration/messaging_brain_contracts.py`
- `app/services/messaging_brain/orchestrator.py`
- `app/services/operator/prebooking_queue_service.py`
- `app/services/messaging/message_event_store.py`

Current conceptual flow:

1. Transport receives inbound event.
2. Source-specific parser extracts guest/latest-thread data.
3. `InboundMessageNormalizer` builds `CanonicalInboundMessage`.
4. That normalizes into `InboundGuestMessage`.
5. `GuestMessageBrainOrchestrator`:
   - audits message
   - classifies intent
   - builds context bundle
   - routes to specialists
   - applies response policy
   - composes a reply draft
   - emits module events
   - persists audit/normalization outcome
6. Pre-booking artifacts land in queue/read-model tables and are exposed through `/app/api/messages` and `/app/api/inquiries`.

### 3.6 Classifier / Routing Logic

Primary files:

- `app/services/messaging_brain/orchestrator.py`
- `app/services/messaging_brain/agents/intake_agent.py`
- `app/services/messaging_brain/agents/llm_intake_agent.py`
- `app/services/messaging_brain/agents/agent_router.py`
- `app/services/messaging_brain/agents/deterministic_intake_prefilter.py`
- `app/services/messaging/channel_router.py`

Observed routing architecture:

- deterministic prefilter + optional LLM intake
- intent typed as `IntentType` + `intent_topic`
- multiple specialist agents can contribute
- router chooses specialist set, not just one handler
- policy gate can override specialist recommendations

### 3.7 Context Builder

Primary file:

- `app/services/messaging_brain/agents/context_builder_agent.py`

Context sources:

- canonical/scoped property knowledge
- guidebook evidence retrieval
- operator guidance
- learned preferences
- reservation/stay facts
- prior guest messages
- operator commitments
- market signals

This is one of the stronger architectural pieces in the repo. It is explicit about loaded evidence keys and missing context.

### 3.8 Concierge Decisioning Logic

Primary files:

- `app/services/messaging_brain/orchestrator.py`
- `app/services/messaging_brain/agents/response_policy_agent.py`
- `app/services/messaging/autonomy_gate.py`
- `app/services/concierge/ai_concierge.py`

Decisioning pattern:

- specialists recommend `auto_send`, `draft_only`, or `escalate`
- response policy resolves final action
- autonomy threshold / review mode can downgrade sends
- module events are only dispatched after policy approval

### 3.9 Market Signals / Intelligence Logic

Primary files:

- `app/domain/signals/models.py`
- `app/services/signals/signal_pipeline.py`
- `app/services/signals/*`
- `app/services/market_intelligence/market_intelligence_engine.py`
- `app/services/analytics/market_intelligence.py`
- `schemas/contracts.py`

Important observation:

- the market/signal system is substantial and more mature than its current operator-dashboard exposure
- signals are modeled as a first-class domain, with confidence, scope, source, and lifecycle concepts

### 3.10 PMS / Integration Modules

Primary files:

- `app/services/connectors/pms_connectors.py`
- `app/services/connectors/escapia_connector.py`
- `app/services/connectors/guesty_connector.py`
- `app/services/connectors/track_connector.py`
- `app/services/connectors/adapter_backed_booking_data_provider.py`
- `app/services/messaging/booking_context_adapters.py`
- `app/services/connectors/pms_ingest_worker.py`

Key concept:

- there is a push toward canonical PMS-backed booking/listing facts behind adapters rather than hard-coded concierge context

### 3.11 Twilio / Email / SMS Integration Files

Email:

- `app/services/integrations/email_pipeline.py`
- `app/services/integrations/email_inbound.py`
- `app/services/integrations/email_dispatch.py`
- `app/services/integrations/email_reply.py`
- `app/services/integrations/gmail_inbox_poller.py`
- `app/services/integrations/gmail_push.py`
- `app/services/integrations/ota_email_parsers.py`
- `app/services/integrations/vendor_email_parsers.py`

SMS / messaging:

- `app/services/notifications/sms_service.py`
- `app/services/concierge/sms_service.py`
- `app/services/messaging/rcs_templates.py`

Voice / Twilio:

- `app/services/voice/twilio_integration.py`
- `app/services/voice/voice_session.py`
- `app/services/voice/providers/deepgram_stt.py`
- `app/services/voice/providers/elevenlabs_tts.py`

### 3.12 Background Workers / Jobs

Primary worker locations:

- `workers/analytics/analytics_workers.py`
- `workers/concierge/concierge_workers.py`
- `workers/detectors/detector_workers.py`
- `workers/feedback/feedback_workers.py`
- `workers/ingestion/event_workers.py`
- `workers/ingestion/pms_workers.py`
- `workers/normalization/normalize_workers.py`
- `workers/projections/projection_workers.py`
- `app/workers/celery_app.py`
- `app/workers/tasks.py`

### 3.13 Tests

Test coverage is broad and strong relative to repo complexity.

Notable areas with direct operator-dashboard relevance:

- pre-booking contracts and queue
- context builder
- guidebook ingest
- property reconcile flows
- stay workflow / actions / PMS feed
- dashboard summary service
- vendor intelligence service
- escalation action/workflow services
- operator scope and tenant hardening

## 4. Data Contracts

## 4.1 Inbound Message Object

Primary shape: `InboundGuestMessage` in `app/services/orchestration/messaging_brain_contracts.py`

Key fields:

- `message_id`
- `tenant_id`
- `channel`
- `source_provider`
- `text`
- `full_thread_text`
- `received_at`
- `guest_id`
- `guest_email`
- `guest_phone`
- `guest_name`
- `identity`
- `reservation_id`
- `property_id`
- `property_code`
- `lifecycle`
- `thread_id`
- `session_token`
- `raw_subject`
- `raw_payload_ref`
- `structured_asks`
- `parser_used`
- `parser_confidence`
- `metadata`

Upstream canonical email normalizer: `CanonicalInboundMessage` in `app/services/messaging/inbound_normalizer.py`

## 4.2 Guest Profile / Context Object

Primary files:

- `app/services/concierge/guest_profile_service.py`
- `db/models/guest_profiles.py`

Key context fields exposed or derived:

- guest identity: phone, email, first/last name
- `total_stays`
- `total_nights`
- `avg_party_size`
- `avg_csat`
- `last_csat`
- `csat_trend`
- `recommend_rate`
- `upsells_ever_booked`
- `upsell_count`
- `escalation_count`
- `last_escalation_reason`
- `stay_history`
- `preferences`
- `prompt_snippet`

## 4.3 Property Context Object

Primary file:

- `app/services/concierge/property_context.py`

`PropertyContext` includes:

- `property_code`
- `property_name`
- `address`
- `community`
- `bedrooms`
- `bathrooms`
- `sleeps`
- `wifi_network`
- `wifi_password`
- `lock_type`
- `property_guide_url`
- `check_in_time`
- `check_out_time`
- `check_in_instructions`
- `check_out_instructions`
- amenity/rule booleans such as `has_pool`, `pool_heated`, `pets_allowed`

## 4.4 Reservation / Stay Object

Two important shapes exist:

#### PMS-backed booking context

Primary file:

- `app/services/messaging/booking_context_adapters.py`

Representative fields:

- `reservation_id`
- `status`
- `booking_channel`
- `check_in`
- `check_out`
- `nights`
- `total_amount`
- `nightly_rate`
- `cleaning_fee`
- `taxes`
- `guest_count`
- guest identity fields
- linked property snapshot

#### Operator session/stay workflow shape

Primary files:

- `db/models/concierge_sessions.py`
- `app/services/operator/stay_workflow_service.py`

Representative fields surfaced to UI:

- `session_id`
- `reservation_id`
- `property_code`
- `phase`
- `guest_name`
- `guest_phone`
- lifecycle/stage timing
- work orders
- handoffs
- proactive workflow state

## 4.5 Generated Response Object

Primary shape: `GuestResponseDraft`

Fields:

- `response_text`
- `tone`
- `confidence`
- `confidence_source`
- `final_action`
- `auto_send_allowed`
- `escalation_required`
- `reason_for_escalation`
- `evidence_references`
- `contributing_agents`

## 4.6 Escalation / Exception Object

Escalation data is spread across:

- `db/models/concierge_escalations.py`
- `app/services/operator/escalation_workflow_service.py`

Representative workflow object fields:

- `ticket_id`
- `session_token`
- `property_code`
- `priority`
- `status`
- `reason`
- `summary`
- `last_message`
- `assigned_to`
- `watchers`
- `vendor_name`
- `vendor_status`
- `guest_update_status`
- `resolution_notes`
- `acknowledged_at`
- `resolved_at`
- detector/action/work-order/handoff summaries

## 4.7 Market Signal Object

Primary files:

- `app/domain/signals/models.py`
- `schemas/contracts.py`

Representative fields:

- signal identity
- tenant/scope/geo linkage
- `signal_type`
- `source`
- `value`
- `confidence`
- `time_window`
- `detected_at` or `observed_at`
- metadata / attribution

## 4.8 Operator Dashboard Metrics Object

Primary file:

- `app/services/operator/dashboard_summary_service.py`

Default dashboard summary shape:

- `sessions`
  - `active`
  - `in_stay`
  - `arriving`
  - `total_30d`
- `pre_booking`
  - `pending`
  - `oldest_pending_age_minutes`
  - `replied_30d`
  - `total_30d`
  - `ai_sent_today`
- `escalations`
  - `open`
  - `resolved_30d`
- `properties`
- `kb_entries`
- `kb_gaps`
- `vendors`
- `messages_30d`
- `notifications_unread`
- `inbox`
  - connectivity / polling status fields
- `degraded`

## 5. Backend Capability Matrix

This section focuses on operator-dashboard-relevant capabilities.

| Capability | What it currently does | Endpoint(s) | Frontend currently uses it? | Should be surfaced? | Best UI surface |
| --- | --- | --- | --- | --- | --- |
| Pre-booking queue | lists inbound inquiries, drafts, statuses, property binding, approvals | `/app/api/messages`, `/app/api/inquiries`, `/app/api/inquiries/*` | Yes | Already surfaced | `PreBooking` route |
| Pre-booking autonomy | tenant-level auto-send threshold and pause state | `/app/api/v2/autonomy`, `/app/api/v2/prebooking/bootstrap` | Yes | Already surfaced | `PreBookingAutonomyPopover`, Settings autonomy |
| Property-link suggestions | fuzzy/manual property binding suggestions | `/app/api/property-links/suggest` | Yes | Already surfaced | Pre-booking bind-property flow |
| Session list / Today queue | returns live guest sessions and lifecycle views | `/app/api/sessions` | Yes | Already surfaced | `Today` route |
| Session detail | returns one session’s operational context | `/app/api/sessions/{session_id}` | Yes | Already surfaced | `SessionExpansion` |
| Thread timeline | returns thread/timeline details for a guest thread | `/app/api/threads/{guest_thread_id}` | Yes | Partially | Today thread pane / dedicated thread drawer |
| Stay actions | returns AI-suggested session actions and executes them | `/app/api/sessions/{id}/actions`, `/execute` | Yes | Already surfaced | `SessionExpansion` actions block |
| Work-order summary | exposes work orders tied to a stay | `/app/api/sessions/{id}/work-orders` | Yes | Already surfaced | `SessionExpansion` |
| PMS feed for stay | exposes PMS-backed stay event feed | `/app/api/sessions/{id}/pms-feed` | No | Yes | Today session detail side card |
| Stay event history / import | read and append/import stay events | `/app/api/sessions/{id}/events`, `/events/import-pms` | No | Yes | Today timeline / event rail |
| Escalation list | returns escalations and summary data | `/app/api/escalations` | Yes | Yes | Today + dedicated Escalations route |
| Escalation actions | action agent for triage / assignment / next steps | `/app/api/escalations/{id}/actions`, `/execute` | No | Yes | dedicated Escalation drawer |
| Escalation handoffs | summarizes ownership / routing handoffs | `/app/api/escalations/{id}/handoffs` | No | Yes | Escalation detail rail |
| Escalation work orders | shows work orders attached to an escalation | `/app/api/escalations/{id}/work-orders` | No | Yes | Escalation detail rail |
| Routing preview | previews alert/escalation routing decision | `/app/api/escalations/{id}/routing-preview` | No | Yes | Escalation detail / Settings alert routing |
| Knowledge entries | CRUD for operator/property KB | `/app/api/kb*` | Yes | Already surfaced | `Knowledge` route |
| Knowledge gaps | unresolved knowledge gaps and resolution flow | `/app/api/kb-gaps*` | Yes | Already surfaced | `Knowledge` and `Properties` |
| Operator AI guidance | freeform operator-authored guidance | `/app/api/settings/ai-guidance` | Yes | Already surfaced | `Knowledge` guidance tab |
| Property roster + autonomy | lists property completeness and autonomy state | `/app/api/properties/autonomy` | Yes | Already surfaced | `Properties` route |
| Property autonomy mutation | edit per-property autonomy | `/app/api/properties/{property_id}/autonomy`, `/bulk` | No | Yes | Properties expansion + bulk controls |
| Property identity review | shows property binding/identity quality | `/app/api/properties/identity-report` | Yes | Partially | Properties route, richer review card needed |
| Property assets | document/assets read/write | `/app/api/properties/{property_code}/assets` | Read yes, write not clearly surfaced | Yes | Properties expansion |
| Team management | member list, role updates, scopes | `/app/api/team*` | Yes | Already surfaced | Settings team tab |
| Portfolio management | create portfolio, assign properties | `/app/api/portfolios*` | Yes | Already surfaced | Settings portfolios tab |
| Alert routing | on-call/escalation contacts, OOO, availability | `/app/api/settings/alert-routing*` | Yes | Already surfaced | Settings alert routing tab |
| Vendor categories / vendors | vendor management and property scoping | `/app/api/vendor-categories`, `/app/api/vendors*` | Yes | Already surfaced | `Vendors` route |
| Dashboard summary | consolidated metrics and inbox health | `/app/api/dashboard-summary` | Legacy shell yes, v2 no | Yes | top-level dashboard brief card |
| LLM usage admin | internal model usage metrics | `/app/api/admin/llm-usage` | Not in v2 main routes | Maybe admin-only | admin / analytics |
| Market intelligence | market-level data and signals | `/api/v1/market/*`, `/api/v1/market-intelligence*` | No in v2 | Yes | analytics / market intelligence route |

## 6. Findings

## 6.1 Backend Features Not Surfaced in Frontend

High-value backend capability already exists but is not meaningfully surfaced in `dashboard-v2`:

1. Per-escalation action workflows, handoffs, work orders, and routing previews.
2. Session PMS feed and explicit event history/import APIs.
3. Property autonomy mutation endpoints and bulk autonomy controls.
4. Dashboard summary endpoint with inbox health and aggregate counters.
5. Market intelligence and signal APIs.
6. Admin LLM usage and observability data.
7. Vendor dispatch/session-to-vendor operational flows.

## 6.2 Frontend Screens Not Backed by Real Data

This depends on which dashboard generation is being discussed.

### Legacy shell (`app/static/dashboard`)

Several sections are shell-first and partially synthetic/fail-open:

- `today` and several sidebar sections are designed to load gracefully even before DB connectivity
- some cards default to placeholders or empty states rather than hard failures
- the shell includes a broader nav than the fully production-backed experience

### React `dashboard-v2`

Most primary routes do have real APIs. The weaker spots are:

1. `Components` route is an internal gallery, not a product surface.
2. shell-level counts depend on pre-booking cache hydration rather than a dedicated top-level summary endpoint.
3. properties route is still read-heavy; edit surfaces for autonomy/assets are incomplete relative to backend support.
4. escalations do not yet have a dedicated v2 detail experience even though backend depth exists.

## 6.3 Missing Endpoints

The larger issue is not “missing endpoints” but “missing frontend adoption.” Still, a few gaps stand out:

1. No dedicated `dashboard-v2` bootstrap for Today/Properties/Settings combined summary state.
2. No dedicated thread reply composer endpoint for a richer conversation workspace beyond `send-update`.
3. No clearly unified “operator dashboard home” endpoint for morning brief, summary cards, inbox health, escalations, and lifecycle counts together in v2.
4. No single v2-focused escalation detail bundle endpoint; current frontend would need several calls.

## 6.4 Duplicate / Unused Services and Surfaces

1. `app/static/dashboard/` and `app/static/dashboard-v2/` are parallel dashboard implementations.
2. `operator_dashboard.py` and `operator_dashboard_v2.py` both serve `/operator-dashboard`.
3. `app/services/concierge/property_router.py` and `app/services/agents/property_router.py` duplicate naming and likely conceptual responsibility.
4. `app/services/concierge/concierge_runner.py` and `app/services/orchestration/concierge_runner.py` are overlapping runner abstractions.
5. `app/services/knowledge/indexer.py` and `app/services/knowledge/knowledge_indexer.py` suggest overlapping indexer roles.
6. top-level `services/` folder is a preserved legacy subtree outside `app/services/`.
7. `frontend/dashboard/*.jsx` is an additional dashboard artifact outside the current static/react operator app paths.
8. model definitions are split between `app/models/*` and `db/models/*`, with overlapping entities like properties/markets.

## 6.5 Technical Debt

1. Operator UI fragmentation is the main architectural debt.
2. Route ownership is blurred: some operator APIs live in `operator_app.py`, others in `operator_dashboard_api.py`, others in `operator_prebooking.py`.
3. Public/demo dashboard routes and authenticated operator routes are mixed in the same codebase and naming space.
4. There is a large amount of preserved-but-not-retired legacy concierge code alongside the newer messaging brain.
5. Multiple service families use similar names for different generations of logic.
6. Frontend state/data loading is inconsistent across dashboard generations.
7. The backend has richer read models than the frontend consumes.
8. Startup/runtime still assumes DB connectivity early; local/sandbox dev degrades poorly.

## 6.6 Highest-Value Product Gaps

1. A true operator home/dashboard in v2 using `/app/api/dashboard-summary` plus interrupts/briefing cards.
2. A dedicated escalation workspace in v2, not just session-centered Today rows.
3. A first-class thread workspace that combines:
   - guest thread timeline
   - session metadata
   - PMS stay context
   - actions
   - escalation state
4. Property operations depth:
   - identity review
   - autonomy editing
   - asset/document upload
   - scoped KB coverage
5. Market/operator intelligence exposure:
   - signals
   - trends
   - repeated guest asks
   - unresolved intent clusters
6. One canonical operator frontend, with all other shells retired or clearly scoped.

## 7. Operator Dashboard-Specific Recommendations

### Immediate

1. Make `dashboard-v2` the single strategic operator UI.
2. Add a dedicated v2 home surface using `/app/api/dashboard-summary`.
3. Promote escalations to a first-class route instead of burying them under Today context.
4. Surface PMS feed/events in Today session detail.
5. Wire property autonomy mutations into the Properties route.

### Near-term

1. Create a unified thread workspace route.
2. Collapse operator API ownership into fewer endpoint modules.
3. Remove or quarantine experimental `/operator-dashboard` surfaces.
4. Use one backend bundle endpoint per major v2 route where multiple small calls are currently needed.

### Longer-term

1. Retire legacy dashboard shell after v2 feature parity.
2. Retire duplicated service generations as messaging-brain paths become primary.
3. Surface market/signal intelligence in operator-facing workflows, not just backend/domain code.

## 8. Bottom Line

The operator dashboard is not blocked by missing backend capability. It is blocked by frontend consolidation and prioritization.

The backend already supports a serious operator product:

- queue operations
- session operations
- escalations
- knowledge learning loops
- team and alert routing
- vendor workflows
- property completeness and autonomy
- PMS-backed context

The right next move is not another new dashboard shell. It is to finish `dashboard-v2` as the single operator control plane and pull the existing backend depth into it in this order:

1. dashboard home / summary
2. escalations
3. thread workspace
4. property operations
5. market/operator intelligence
