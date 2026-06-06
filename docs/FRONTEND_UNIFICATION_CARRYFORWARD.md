# Carryforward Brief: Frontend Unification + PMS Integration Surfaces

**Source session:** Conversation completing pre-booking closeout, lifecycle convergence, healer loop activation, gate hardening, and persistence seam fix. See `LEGACY_CLOSEOUT_EXECUTION.md`, `LIFECYCLE_CONVERGENCE_EXECUTION.md`, and recent commits `18f055d`, `bfb17d7`, `5d132c2`, `ee9dec3`, `c7237a9`, `759c83e`, `d49c186`, `65d3b54`, `55143ad`, `b20fa31`, `25fafa5`.

**Why this brief exists:** Backend is now one unified brain pathway with one DB session pattern, identity-aware routing across all four lifecycle stages, and a closed learning loop via the healer system. The next workstream is extending the existing v2 frontend to wrap that machinery cleanly. This is product/UX-shaped work, not pipeline-shaped, and deserves its own focused context window.

---

## 1. The frontend you're extending (not building from scratch)

**The operator-facing surface is `app/static/dashboard-v2/`.** It is a real TypeScript + Vite + React + Tailwind application served by FastAPI as static assets via `operator_dashboard_v2.py`. The framework decisions are already made. The architectural skeleton is already in place. The next session extends this, doesn't replace it.

### What's already built in v2

**Stack:**
- Vite + React 18 with `react-jsx` transform
- TypeScript with strict mode (`tsconfig.json` strict: true)
- Tailwind + PostCSS for styling
- Custom store layer with hooks (`src/store/index.js`, `src/store/hooks.ts`)
- ThemeProvider supporting light/dark/system modes

**Existing layers:**
- `src/api/index.js` — backend client
- `src/adapters/index.js` — payload normalizers (e.g., `normalizeMessageFeed`)
- `src/store/` — state management foundation with hooks (`useStoreKey`)
- `src/components/primitives/` — Badge, Button, KeyboardHint (design system primitives)
- `src/components/system/` — ErrorBoundary, InlineError (resilience layer)
- `src/theme/ThemeProvider.tsx`

**App.tsx already has:**
- Typed bootstrap payloads (`SessionPayload`, `AutonomyPayload`, `BootstrapPayload`)
- Cached session state with `localStorage` keys (`oyvoda.v2.prebooking.bootstrap`, `oyvoda.v2.prebooking.ui`)
- Queue UI state typed as a real domain model: `QueueTab`, `QueueScope`, `QueueDepth`, `QueueMetricFocus`
- `useDeferredValue` for input performance
- Bootstrap cache snapshot mechanics

**Build pipeline:**
- `vite.config.ts` — base path `/static/dashboard-v2/dist/`, outputs to `dist/`
- Backend serves `dist/index.html` and assets through static routing

### What v2 already covers (operator-facing today)
- Pre-booking queue with the four tabs (action/sent/held/closed)
- Property filter, search, scope (all/mine/unassigned), queue depth controls, focused metrics
- Inquiry selection state with persistence across reloads
- Tenant-aware autonomy state (`auto_enabled`, `confidence_threshold`)
- Theme switching with persistence

### What's elsewhere (deprecated or legacy paths to ignore)
- `frontend/dashboard/oyvoda-v10.jsx`, `frontend/dashboard/QueueReview.jsx` — prior single-file iterations, do not extend
- `frontend/demo/index.html` — sandbox, ignore
- `app/api/v1/endpoints/operator_dashboard.py`, `operator_dashboard_v2.py`, `mobile.py`, `mobile_v2.py`, `mobile_v3.py` — earlier server-side dashboard variants; v2 is the post-consolidation target
- The `frontend/` directory at repo root is probably worth archiving or deleting once v2 is fully built out

---

## 2. What the frontend is wrapping (the backend you can rely on)

### One brain, one decision plane
Every inbound guest message — regardless of channel (Gmail/Vrbo/Airbnb relay/web session/future SMS/future PMS-native) — flows through `GuestMessageBrainOrchestrator`. Every proactive outbound trigger flows through `handle_proactive_trigger` on the same brain. No parallel decision pipeline.

- Pre-booking: `email_dispatch.dispatch_pre_booking` → `run_brain_pre_booking_lifecycle` → brain → persistence in `pre_booking_inquiries`
- In-stay/pre-arrival/post-stay: `session_channel_adapter.run_session_channel_message` → brain → persistence in session message tables
- Proactive: `operator/stay_proactive_runtime.py` → stay workflow/action queue → `compose_proactive_draft` → brain → outbound transport

**Module layout note.** "One decision plane" refers to the brain owning every classify/route/compose/ground/review decision. It does NOT mean every messaging-related module lives under `messaging_brain/`. The `app/services/messaging/` directory still exists alongside `messaging_brain/` and holds layer-agnostic plumbing the brain calls into:

- `messaging/identity_resolver.py` — `GuestIdentityResolution` dataclass (imported by `messaging_brain/pre_booking.py` among others)
- `messaging/inbound_normalizer.py` — `CanonicalInboundMessage` contract
- `messaging/inbound_transport.py` — transport-layer normalization
- `messaging/inbox_adapters.py` — outbound reply adapter (Gmail, Microsoft 365)
- `messaging/channel_router.py` — outbound channel selection
- `messaging/message_event_store.py` — canonical message persistence
- `messaging/autonomy_gate.py` — autonomy threshold check primitives
- `messaging/operator_alerts.py` — alert dispatch primitives (distinct from `messaging_brain/notifications/operator_alerts.py`, which handles brain-internal alerts)
- `messaging/parser_notes_schema.py`, `guest_messaging.py`, `human_feel.py`, `coverage_monitor.py`, `rcs_templates.py`, `booking_context_adapters.py`

These are not duplicates of brain functionality. They're the substrate the brain runs on top of: transport normalization happens before the brain sees a message, identity resolution feeds the brain's specialist eligibility logic, outbound channel adapters carry brain-composed drafts back to the guest. Keep this split when reasoning about the architecture — "the brain is the single conductor of guest message handling, calling into messaging/ for plumbing" is the accurate framing.

### Identity model the frontend must reflect
`GuestIdentityResolution.state` ∈ `{identified, linked, pseudonymous, anonymous}`. This drives:
- Specialist eligibility (`LateCheckoutAgent`, `AccessAgent` identified-only; `MaintenanceAgent` identified-or-linked)
- Autonomy gate (currently pinned at `autonomy_threshold=1.0` for Lanier — every message reviewed)
- Which fields the brain has access to (reservation_id, guest_email, guest_phone only when identified/linked)

### Confidence contract on every row
`confidence_source` is a Postgres enum the frontend should treat as authoritative:
- `model_composer` — brain composer produced this draft
- `gap_blocked` — knowledge gap held this inquiry (draft_confidence = NULL by contract)
- `held_for_review` — adversarial reviewer held it (draft_confidence = NULL)
- `exception_fallback` — brain runtime crashed
- `intent_only` — no brain draft confidence resolved
- `faq_fast_path` — FAQ matched ≥ 0.90 confidence
- `escalation_routed` — escalation fast-path fired
- `gate_code_intercept` — deterministic gate code response
- `session_composer` — in-stay/pre-arrival composer
- `proactive_trigger` — proactive outbound

`review_verdict` ∈ `{pass, revise, hold}` from the adversarial reviewer. Read this alongside `confidence_source` when rendering "should the operator look at this carefully?"

### Token-isolation guarantee
Multiple guests on one property each get an independent session token (`gh_xxxxxxxx`). The frontend must respect this: every action, every audit lookup, every history view is keyed off the token's identity, never the property. Verified end-to-end in `tests/unit/test_session_channel_token_isolation.py`.

### Healer loop is live
Daily 05:00 UTC scan. Three proposal kinds:
- `property_alias_suggestion` — durable alias additions to canonical_property_identities
- `intent_classifier_keyword_suggestion` — keyword overrides per tenant in `operator_settings.extra`
- `prefilter_drop_pattern_suggestion` — runtime drop overrides in `operator_settings.extra.inbound_prefilter_drop_overrides`

All write into `healer_proposals` with `status='pending'` for human review. API at `app/api/v1/endpoints/healer.py`. **A v2 surface for healer approval doesn't exist yet** — proposals are currently approved via direct API call. This is one of the gaps to close.

---

## 3. The API surface v2 wraps

50+ endpoints in `app/api/v1/endpoints/`. The ones most relevant to v2 extension:

**Pre-booking operator surface (already integrated in v2):**
- `operator_prebooking.py` — approve/edit/reject/regenerate inquiries
- `operator_dashboard_v2_api.py` — bootstrap payloads, queue feed, tenant state
- `operator_dashboard_v2.py` — page route

**Property + operator config:**
- `operator_properties.py` — property CRUD, FAQ entries, knowledge upload triggers
- `operator_policies.py` — operator-level config (gate codes, channel preferences)
- `operator_signup.py`, `operator_tour.py` — onboarding flows

**Healer surface (no v2 frontend yet):**
- `healer.py` — proposal list, approve, reject, evidence inspection

**PMS + integrations:**
- `escapia_unified.py` (in `app/services/concierge/`, not endpoints) — Escapia ENET connector
- Connector wiring lives in services, not endpoints; the operator UI for PMS setup is one of the gaps

**Document upload (backend exists, no UI):**
- `documents.py` — upload endpoints
- `guidebook_ingest_service.py` — ingestion pipeline

**Other operator-relevant:**
- `agents.py` — agent invocation surface
- `alert_contacts.py` — operator notification contacts
- `audit.py` — audit log queries
- `knowledge.py` — knowledge base queries
- `concierge.py` — concierge session endpoints
- `market_intelligence.py` — market signal data

---

## 4. The four workstreams for the next session

### Workstream A: Extend v2 with the missing operator surfaces (largest)
**Goal:** v2 today covers pre-booking queue cleanly. Add the surfaces that complete the operator's daily workflow.

**Surfaces to add:**

1. **Session conversations view (in-stay / pre-arrival / post-stay)**
   - Per-token threaded view of session messages
   - Identity state visible (identified/linked/pseudonymous/anonymous badge)
   - `quick_answer_source` rendered when a fast-path fired (FAQ / gate code / escalation)
   - Live-updating as new messages arrive (SSE or polling — pick during session)
   - Respects token isolation — each token is a separate thread, never aggregated by property
   - Operator can interject / take over / add internal notes

2. **Property roster + knowledge surface**
   - Reads `canonical_property_identities` + PMS sync state
   - Property metadata CRUD
   - Operator-curated FAQ entries (feeds the FAQ fast-path the brain uses)
   - **Knowledge gap surface** — what the brain wanted but didn't have, per property, with one-click "answer this so brain can use it next time"
   - Per-property message volume, recent activity, common intents

3. **Document upload UI**
   - New surface, no current operator-facing path
   - Operators upload property guides, house manuals, FAQs, local recommendations
   - Backend ingestion via `guidebook_ingest_service.py` already exists
   - Frontend needs: upload UI, ingestion status tracking, preview of what brain will retrieve, ability to delete/replace

4. **PMS integration setup panel**
   - Credential entry (Escapia ENET, future Guesty, future Track)
   - Sync status (last successful pull, error states)
   - Property-mapping view (which PMS property maps to which canonical property)
   - First-time setup wizard

5. **Healer proposal approval surface**
   - Reads `healer_proposals` pending queue
   - Renders proposal type, evidence chain, confidence, cluster size
   - One-click approve / reject with note
   - History view of approved aliases / keywords / drop patterns
   - Critical for operationalizing the daily 05:00 UTC scan output

6. **Settings + autonomy**
   - Current autonomy threshold (pinned at 1.0 for Lanier today)
   - Channel preferences (which channels send proactive touches)
   - Operator profile, alert contacts
   - Theme preferences (already in v2)

### Workstream B: PMS integration completion (medium)
**Goal:** Confirm every PMS data path the frontend depends on is actually wired end-to-end before the v2 frontend depends on it.

- Escapia: `escapia_unified.py` exists, ENET connector built. Verify booking-sync, reservation-detail, property-detail flows write to the canonical tables the brain reads from.
- Guesty and Track: scaffolded but likely incomplete. Decide whether to ship these in this session or defer.
- PMS-mediated reply path: brain composes replies; outbound dispatch for PMS-channel guests goes through `inbox_adapters.build_reply_adapter`. Confirm Escapia reply-send is operational.
- Document upload → knowledge ingestion → brain retrieval pipeline: verify round-trip works end-to-end before frontend depends on it.

### Workstream C: Admin observability surface (internal, can defer)
**Goal:** Oyvoda-internal admin dashboard. Healer-first framing. Separate from the operator-facing v2.

- Section 1: Healer loop status (proposals, approvals, time-to-approval, efficacy delta)
- Section 2: Deterministic layer health (LLM vs deterministic hit rates, surface-audit disagreement rates, prefilter drop coverage)
- Section 3: Brain pipeline stages (per-stage latency, confidence distributions, error rates)
- Section 4: Failure modes (gmail_fallback reason breakdown, exception_fallback occurrences, gate failure status code distribution)
- Section 5: Provider/dependency health (Anthropic, Groq, Gemini status, rate limits, costs)

Internal-only, not in tenant nav. Could be a separate v2 subroute (`/admin/brain-health`) gated by an admin-allowlist, or a separate small Vite app served at `/static/admin-v1/dist/` with the same stack as v2 (Vite + React + TS + Tailwind, copy the skeleton).

### Workstream D: Tidy-up
**Goal:** Reduce confusion for everyone who comes after.

- Archive or delete `frontend/dashboard/`, `frontend/demo/`, and the top-level `frontend/` directory once v2 fully replaces them
- Decide whether `operator_dashboard.py`, `mobile.py`, `mobile_v2.py`, `mobile_v3.py` can be removed (or kept for legacy mobile routes if those still serve traffic)
- Move or commit the `PHASE_4_*` briefs at repo root; they're untracked notes
- Settle the `LEGACY_*` and `LIFECYCLE_*` doc tracking state

---

## 5. The decisions worth making first in the next session

The framework choice is settled (Vite + React + TS + Tailwind). What's open:

1. **State management beyond the current store layer** — v2's store is a custom hooks-based pattern. For server state in particular, decide: TanStack Query? SWR? Continue with the custom adapter pattern? The current `adapters/index.js` with `normalizeMessageFeed` works for pre-booking but will need to scale to sessions, properties, documents, healer proposals.

2. **Live updates strategy** — Session conversations need to feel like SMS. Server-Sent Events (SSE), WebSocket, or short-interval polling? SSE is simplest and FastAPI supports it cleanly.

3. **Routing inside v2** — App.tsx today is a single page focused on pre-booking. Adding sessions/properties/documents/PMS/healer/settings means routing. React Router? Or per-page bootstrap with server-side route dispatch? React Router is the conventional answer.

4. **Component library expansion** — `components/primitives/` has Badge, Button, KeyboardHint. The new surfaces need: Dialog, Drawer, Tabs, Table, Form primitives, Toast, Tooltip. Build these in-house following the existing primitive style, or pull in shadcn/ui? Both are reasonable.

5. **Type generation for API responses** — Currently types are hand-written in App.tsx (`BootstrapPayload`, etc). Worth generating from FastAPI's OpenAPI schema (`openapi-typescript` or similar) to stay in sync as backend evolves.

These decisions shape the next 4-6 commits. Pin them early.

---

## 6. State of the backend the frontend depends on (snapshot at session end)

### Production-ready surfaces
- ✅ Pre-booking inquiry pipeline (brain composer, adversarial review, confidence persistence)
- ✅ Session message pipeline (identity-aware routing, fast-paths, lazy context)
- ✅ Proactive trigger pipeline (cadence + brain composition)
- ✅ Healer loop (daily scan, three proposal kinds, approval API)
- ✅ Gate path resilience (retry on transient failures, deterministic admit fallback)
- ✅ Confidence persistence (defensive fallback chain)
- ✅ Operator approve/edit/reject/regenerate endpoints (`operator_prebooking.py`)

### Functioning but underused
- 🟡 Document ingestion (`guidebook_ingest_service.py`) — backend exists, no v2 frontend
- 🟡 Knowledge gap recording — backend exists, no v2 surface for operators to act on gaps
- 🟡 BD insight nudges (`bd_insight_service.py`) — fire conditions exist, no v2 surface
- 🟡 Market intelligence (`market_brain.py`) — backend exists, partial endpoint surface, no v2 surface
- 🟡 Healer proposal approval — API exists, no v2 surface

### Scaffolded, may need completion
- 🟠 PMS integrations beyond Escapia
- 🟠 Direct SMS inbound/outbound (Twilio surface exists, integration completeness unclear)
- 🟠 Group session handling (`group_session.py` exists)

### Known issues to communicate to the next session
1. **`autonomy_threshold` pinned at 1.0 for Lanier** — every brain-composed message is operator-reviewed. v2 should make review fast because review volume is 100% right now. Lowering the threshold is a separate operator-facing rollout decision.
2. **`brain_draft_confidence` persistence fix (`b20fa31`) is deployed but production verification pending** — first fresh inquiry after deploy should land with `confidence_source='model_composer'` and `draft_confidence > 0`. v2 should handle all `confidence_source` values cleanly regardless.
3. **Sea La Vie healer proposal pending** — single property alias still awaiting approval. The v2 healer approval surface will make this easy; right now it's a direct API call.
4. **Multiple untracked docs at repo root** — multiple `PHASE_4_*` briefs and several `LEGACY_*` / `LIFECYCLE_*` docs at various tracking states. Tidy-up pass worth doing.

---

## 7. Architectural rules v2 must continue to honor

1. **Brain is the only decision plane.** v2 never makes message-routing or specialist-selection decisions client-side. Display state; don't compute it.
2. **Identity-state determines what's visible.** Pseudonymous guests don't have reservation details to show. Identified guests do. Don't render fields the brain doesn't have access to.
3. **Confidence source is authoritative.** Don't compute "should this be auto-sent" client-side; the brain's `recommended_action` field already says.
4. **Healer proposals require human approval.** v2 doesn't auto-approve. The approval surface should make evidence inspection easy.
5. **Per-token isolation must hold at the UI layer.** Property-level views are aggregations; individual conversations are per-token. Never mix.
6. **Operator review is the default.** The system can technically auto-send (autonomy_threshold logic exists); production policy is currently "review everything." v2 should make review fast, not bypass it.

---

## 8. Recommended next-session opener

When you pick this up:

1. **Open `app/static/dashboard-v2/src/App.tsx` and understand the existing patterns.** This is the foundation. Read the store, the adapters, the primitives, the theme provider. Internalize the typing pattern.
2. **Run the existing v2 dev build** — `cd app/static/dashboard-v2 && npm run dev` (or whatever the actual script is in the parent `package.json`). Confirm it renders and bootstraps against a local backend.
3. **Pin the open decisions in section 5** — server state library, live updates strategy, routing, component library extensions, type generation.
4. **Scope v1.5 of v2** — Pick which surfaces from Workstream A to add first. Recommended order: Session conversations → Healer approval → Property roster + knowledge → Document upload → PMS setup → Settings polish.
5. **Workstream B (PMS), C (admin observability), D (tidy-up) get their own briefs** once Workstream A is in motion.

---

## 9. What was deliberately not done in the source session

To set the next session's expectations:

- No frontend changes. The source session was all backend.
- No production verification of `b20fa31` yet (pending fresh inquiry after deploy).
- No production verification of `25fafa5` yet (pending fresh inquiry + 24h for healer to produce first prefilter proposals).
- No approval of Sea La Vie healer proposal.
- No tidy of untracked docs in repo root.
- No admin observability dashboard built (deferred to Workstream C).

The source session intentionally stopped at "backend convergence + learning loop closed" so the frontend session could start with a meaningful, stable API to wrap.

---

## 10. The single most important thing to carry forward

**The backend is now one system, not two — and v2 is the frontend that matches it.** Every architectural choice the next session makes should reinforce that. One operator app. One per-tenant config surface. One conversation thread view that works for every lifecycle stage. One confidence model the UI renders consistently. One healer review queue.

v2 already started this consolidation on the frontend side before the backend convergence finished. The next session's job is to complete it — extend v2 to cover the surfaces it doesn't yet, archive the legacy variants, and end up with one operator app that mirrors the unified brain underneath.

The hard architectural decisions are behind you. The framework decisions are behind you. What's left is product.
