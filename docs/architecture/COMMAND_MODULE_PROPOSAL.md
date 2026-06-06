# Oyvoda Operator Frontend — Architecture Proposal

**Status:** Approved direction (pending Ship A brief)
**Author:** Claude, working under Hunter's direction
**Date:** May 2026
**Supersedes (if approved):** the section-based information architecture in `app/static/dashboard/`

---

## 0. Frame

This document proposes a ground-up rethink of the Oyvoda operator frontend.

The point of this exercise is not to redesign the existing 15-section dashboard. It is to ask: **what is the right operator interface for the product Oyvoda actually is — anchored in what the backend has been building?**

The proposal has been corrected three times during the conversation it emerged from. Each correction sharpened the design. The current version reflects those corrections.

---

## 1. What Oyvoda is

**Oyvoda is AI-handled guest messaging for vacation rental operators.**

That's the product. No qualifier, no roadmap-flavored hedge, no "operating system for X" positioning. When an operator describes Oyvoda to a peer, that one sentence is the answer.

The product is designed around a simple truth about vacation rental operators: they spend hours every day reading and writing guest messages. Inquiries, check-in questions, in-stay needs, post-stay follow-ups. Oyvoda makes that whole arc happen with AI handling the routine cases, the operator reviewing the ambiguous ones, and the operator's voice and knowledge driving the replies.

### What this means in practice

When the backend determines that handling a guest message fully requires action in the physical world, the backend coordinates that action. A guest reports the A/C is broken; the brain routes the message into a maintenance workflow, dispatches a vendor from the operator's vendor directory, and updates the guest on ETA — without the operator having to leave the conversation. This is still guest messaging. The message gets fully handled. The vendor dispatch is the back half of what "fully handled" means for that class of message.

The frontend surfaces these end-to-end resolutions in the messaging surfaces where they belong contextually (in the guest session detail panel, in the operator's review queue when human approval is needed), not as a separate "operations execution" product. The conversation is the unit; the dispatch is metadata on the conversation.

### What this means for the frontend

We are not building a coordination platform that happens to do messaging. We are building a guest messaging product that's good enough to fully handle messages, including the cases where handling them well requires real-world action. The visual identity, the navigation, the home surface, the empty states all say "messaging." Anything in the codebase that supports the back half of message resolution — vendor coordination, maintenance dispatch, work orders — is built into the messaging workflow at the level it matters, not as a top-level destination.

When operator adoption reveals new dominant patterns (portfolio-scale work order management, multi-operator vendor referrals, market intelligence across geographies), the frontend can elevate those patterns into their own surfaces. Not before.

---

## 2. What the backend already provides

This proposal does not propose new backend work. It proposes a frontend that exposes what the backend has already built, in the shape that matches operator workflows.

For context, the relevant backend surfaces are:

**Messaging brain.** A multi-agent pipeline that handles guest messages across the full lifecycle (`MessagingLifecycle`: pre-booking, pre-arrival, in-stay, post-stay, ops, system) and across operational domains (`MessagingBrainDomain`: messaging, PMS, maintenance, housekeeping, scheduling, pricing, documents, property assets, vendor coordination). Eighteen agents currently — intake, router, composer, escalation, maintenance, house rules, pricing policy, access, verification hold, others. The brain is what makes a guest's A/C report turn into a coordinated response that involves the operator's HVAC vendor.

**Vendor intelligence.** `VendorIntelligenceService` is not a directory. It's a dispatch matching engine. It models manufacturer aliases (Carrier, Trane, Lennox, etc.), warranty providers, service area tags, supported issue tags, system tags, emergency capability, after-hours availability, response SLAs, approval modes, cost tiers, and preferred property bindings. It can take "the Trane unit at 31 Gardenia is making a clicking sound" and find the right vendor in the operator's directory based on manufacturer specialty, geographic coverage, warranty status, and historical preference.

**Work order state machine.** `OperatorWorkOrderService` tracks dispatched work through eleven active statuses (`opened → contacting_vendor → accepted → scheduled → en_route → on_site → work_completed → awaiting_verification → invoice_received → invoice_approved`) plus terminal states. Each work order knows its vendor, its property, its ETA, its tracking URL, its last actor. This is the substrate for AI-handled maintenance dispatch.

**Operational insights.** `OperationalInsightEngine` produces derived recommendations from messaging patterns, knowledge gaps, and (eventually) market signals. Critical contract: raw market data never surfaces directly to operators. Only actionable insights surface, with `action_label` and `action_target` so the operator goes from "noticing" to "doing" in one click.

**Stay workflow.** `StayWorkflowService` joins guest sessions, stay events, proactive nudges, receptiveness signals, and operational state. This is what enables in-stay intelligence — knowing not just that a guest is in a property but that they're receptive to a mid-stay check-in or matching the pattern of guests who extend.

**Safety protocols.** `SafetyProtocolService` classifies messages into severity tiers (`life_safety`, `property_damage`, `security`) with named protocols (`evacuate_now`, `urgent_shutdown`, `call_emergency_services`).

The frontend's job is to expose this thoughtfully — not all at once, not in every navigation destination, but at the right level of contextual depth in the surfaces where operators are already looking.

---

## 3. Operating principles

**1. The product is messaging.** Every primary navigation destination, every home-surface element, every empty state framing reinforces: this is the system that handles your guest messaging. When messaging is fully resolved end-to-end, that resolution includes any back-half coordination (vendor dispatch, work order tracking) — but the framing is always "messaging fully handled," not "operations coordinated."

**2. The operator is the protagonist, not the AI.** The AI's autonomy state, confidence, model selection, and reasoning live in audit and configuration views, not on operational surfaces. Operational surfaces show the operator their work, with the AI's contribution baked into the workflow.

**3. Lifecycle is the spine of the messaging product.** Today (the home surface) plus the four guest-facing lifecycle phases — Pre-Booking, Pre-Arrival, In-Stay, Post-Stay — are the dominant navigation destinations. This matches the operator's mental model and the backend's `MessagingLifecycle` model.

**4. Insights over counters.** The home surface is dominated by `OperationalInsight` items — derived recommendations with clear actions. Raw counts and charts exist but are secondary. The first thing an operator sees when they log in is "what needs my attention next," not "how the system is doing."

**5. Density without congestion.** Operators with hundreds of properties need to see a lot at once. Density comes from typography, alignment, and stratified visual weight — not from cramming. The three-column shell (nav / content / detail) is the load-bearing pattern because it lets dense lists coexist with rich detail.

**6. The detail panel is contextual, not permanent.** It slides in when the operator selects an item and slides out when dismissed. It does not occupy permanent screen real estate on every surface. This keeps the product from feeling crowded on smaller laptops.

**7. Reversibility is the trust mechanism.** Every AI-driven action is one click to undo. Every autonomy escalation (`required → auto`) is one click to roll back. The brain's autonomy is earned in increments; the frontend has to make rollback effortless.

**8. The keyboard is the power surface.** Cmd+K is not polish. It's navigation infrastructure. Power operators do everything by keyboard — property switching, inquiry resolution, mode toggles, KB lookup. Mouse is for browsing; keyboard is for working.

**9. Mobile is for surveillance and approval, not authoring.** Desktop is the workshop. Mobile is what an operator checks between meetings — a different IA, focused on insights, approvals, and alerts.

---

## 4. The shape

### 4.1 The shell

A three-column layout with a contextual third column.

```
┌───────────────────────────────────────────────────────────────────────┐
│  topbar: scope · cmd palette · search · alerts · operator menu        │
├──────────┬────────────────────────────────────────┬───────────────────┤
│          │                                        │                   │
│   nav    │             primary content            │   detail panel    │
│   240px  │                fluid                   │   360–480px       │
│          │                                        │   (slide-in only) │
│          │                                        │                   │
└──────────┴────────────────────────────────────────┴───────────────────┘
```

The detail panel is summoned by selecting an item in the main content area. It is never permanent. On smaller laptop widths, the panel takes over more horizontal space (or full-screen on narrow viewports). This avoids the "always crowded" failure mode.

When a `life_safety` or `security` event from `SafetyProtocolService` lands, a top-of-screen interrupt band appears — full-width, red, persistent until acknowledged. Not dismissible by clicking elsewhere. The only surface that breaks the layout grid, intentionally.

### 4.2 The topbar

Five elements:

- **Scope picker.** Shows current tenant ("Beach Habitats 30A"). Click to switch if the operator manages multiple tenants. Built into the system from day one; visually subtle until a second tenant exists.
- **Command palette trigger (⌘K).** Always visible. Placeholder reads "Search or jump…" Clicking or pressing Cmd+K opens the palette.
- **Property filter** (optional, scope-aware). Filters the entire shell to a single property when active.
- **Alerts bell.** Count of unacknowledged insights, safety events, work orders requiring attention.
- **Operator menu.** Name, role, settings, sign out.

### 4.3 The nav

The nav is the visual statement that this product is messaging. The dominant section header reflects that.

```
GUEST MESSAGING
○ Today                                12
○ Pre-Booking                           8
○ Pre-Arrival                           3
○ In-Stay                              23
○ Post-Stay                             5

YOUR PROPERTIES
○ Properties                           45
○ Knowledge
○ Voice & Persona

ACCOUNT
○ Vendors                              18
○ Audit
○ Settings
```

Counts are *actionable* counts — items needing the operator's attention — not totals. Operators learn to scan the nav as a worklist.

Notable omissions: no "Operations." No "Work Orders." No "Reports." No "Insights" as a top-level destination. No "Market Intelligence." Those exist in the backend codebase but they are not navigation destinations yet. They surface contextually within the messaging product (work orders inside guest session detail panels, insights on the Today surface) or they wait for the adoption signal that warrants their own destination.

Vendors stays in the nav under Account because operators have real vendor directories today, the backend has real vendor intelligence today, and operators add, edit, and reference their vendors as part of running their business. More on this in §4.8.

### 4.4 Today (the home surface)

The home surface is a triage view, framed entirely around guest messaging. Four zones:

**Active interrupts (top, conditional).** Empty by default. Appears when an open safety event, an inquiry stuck past SLA, or an AI-dispatched action that hasn't received vendor acknowledgment in expected time needs the operator's attention. Each item has a clear action button and a snooze option.

**Insights for today.** Up to three `OperationalInsight` cards. Each card states the insight in operator-actionable language with provenance accessible on click:

> **Parking questions spiking near Rosemary Beach.**
> 14 inquiries this week asked about parking at the four Rosemary properties. None of them have parking details in their Knowledge.
> [ Add knowledge for these properties ]   [ Dismiss ]

Insights are scoped to messaging patterns from this operator's own data. Market intelligence is built into the engine architecturally but does not surface in operator UI until multi-operator density makes it valuable.

**Today's flow (lifecycle strip).** A horizontal four-column strip showing today's messaging work across all four guest phases. Each column shows the actionable count and the next 1–3 items. Click an item → opens it in the detail panel. Click the column header → deep-navigate to that lifecycle view.

**Portfolio glance.** Compressed metrics row: total properties, active reservations, today's arrivals, today's departures, occupancy %, average response time, AI auto-rate. Dense, tabular, one row. Click any metric to deep-link to its analytics view (when those views exist).

### 4.5 The lifecycle views (Pre-Booking, Pre-Arrival, In-Stay, Post-Stay)

Each is a dedicated view with a consistent shape:

- **List on the left (~60% of primary content):** virtualized table of items at that lifecycle stage. Columns vary by stage. Filterable, sortable, bulk-selectable.
- **Detail panel on the right (slide-in):** full context for the selected item.

The lifecycle views are the operator's daily work surface. The Pre-Booking view is the highest-traffic surface — it's the operator's primary reason for opening Oyvoda today.

### 4.6 The detail panel — extensible by design

This is where the unified-messaging frame becomes concrete. The detail panel is composed of stackable sections, only the relevant ones rendered for any given item:

1. **Identity** — guest name, contact, reservation ID, source (Vrbo, Airbnb, Booking.com, direct).
2. **Conversation** — the full message thread, with AI and operator messages distinguishable.
3. **AI signal** — what the brain decided (auto-send, clarify, escalate, dispatch). Confidence, action label.
4. **Property context** — property facts relevant to the conversation. Sleeps, amenities, current state.
5. **Active work** — any active work order, dispatch, or coordinated action attached to this guest's session. Vendor assigned, ETA, status, latest update. Appears only when there's active coordination; absent otherwise.
6. **Suggested replies and actions** — the AI's drafted reply (editable), plus action buttons. For maintenance-class messages, "Dispatch vendor" appears as an action that previews the matched vendor before sending.
7. **Related entities** — other open inquiries from this guest, history at this property.

The panel is the same primitive across all lifecycle views and across the Properties view. Sections show or hide based on the item's state. This is what lets the same surface host a pre-booking inquiry, an in-stay maintenance request, and a post-stay damage review without redesign.

### 4.7 Properties

A virtualized data table, not a card grid. Solves the congestion complaint.

```
☐  Name                    Code      Stage      Open    Mode      Knowledge   Last guest
☐  Sea La Vie              111VW     In-Stay    1       Auto      28          today
☐  517 Eastern Lake        517EL     Pre-Book   2       Required  34          today
☐  31 Gardenia             31GARD    Empty      0       Required  35          Mar 14
☐  116 W Summersweet       116ss     Pre-Arr    1       Required  32          today
...
```

Sort and filter on every column. Bulk select to switch mode, bulk-edit knowledge, generate reports. Click a row → detail panel showing the property profile, current stage, all open inquiries / sessions / active work for that property, knowledge entries, PMS sync status.

Saved views ("My Rosemary properties", "All AUTO-mode", "Properties needing knowledge work") for portfolio-scale operators.

### 4.8 Vendors

Vendors are real in the operator's world today. Most operators have their own — A/C techs and HVAC guys who've worked their properties for years, cleaners they trust, handymen, private chefs, crib rental businesses, pool service, lawn service. The backend's `VendorIntelligenceService` already models the depth — manufacturer aliases, warranty handling, service areas, emergency capability, SLAs, cost tiers. The existing `sections/vendors.js` already exposes a directory with categories.

Vendors is two things at once, and naming both is important because they're the actual strategic value of the surface:

1. **The operator's directory.** A place to add, edit, and reference the vendors they already work with. Categories, contact info, specialties, coverage areas. This is the operator-facing job.
2. **The matching substrate for AI dispatch.** When the messaging brain determines a guest message requires real-world action — "the A/C is making a clicking sound at 31 Gardenia" — it queries the vendor directory using the structured intelligence in `VendorIntelligenceService`: manufacturer aliases match the Trane unit to vendors with Trane specialty, service area tags confirm coverage at Gardenia, warranty handling routes appropriately, response SLAs and emergency capability factor into who to call first. The directory is what makes AI-handled dispatch possible. Without it, the brain has nothing to dispatch *to*.

This dual role is the strategic argument for treating Vendors as a first-class surface even before AI dispatch is a routine flow operators rely on daily. Every vendor an operator adds today is a vendor the AI can dispatch to tomorrow. The directory builds the substrate; the messaging brain consumes it.

The Vendors surface in the redesigned product is:

- **Directory by category.** HVAC, plumbing, cleaning, handyman, pool, lawn, pest, private chef, baby gear, etc. — operator-configurable categories. Each category lists the operator's vendors with their specialties, coverage areas, SLAs, and contact info.
- **Vendor detail panel.** Click a vendor → see their full profile: manufacturer specialties (Carrier-certified, Trane-certified, etc.), service areas (which property codes they cover), warranty handling, response SLA, after-hours availability, cost tier, recent dispatch history, guest impact metrics.
- **Add vendor.** Standard form. Operators bring their own vendors. Categories, specialties, service areas, contact info — all editable. The structured fields are the same ones the matching substrate consumes, so adding a vendor well today is what makes AI dispatch accurate later.

What Vendors is **not**, in this ship:

- Not a work order kanban. (Dispatched work surfaces in the guest message detail panel where the dispatch was triggered.)
- Not a marketplace. (Cross-operator vendor referrals are a future expansion, gated on multi-operator density. The data model supports the extension; the UI does not yet expose it.)
- Not a coordination dashboard. (Active work coordination lives where the messaging that spawned it lives.)

This positioning keeps Vendors visible (operators need it; operators are asking for it) without elevating it into a separate operations-execution product. The backend depth is honored; the frontend respects the messaging-first frame.

When AI-handled vendor dispatch becomes a routine flow operators rely on daily, and they start saying "show me all dispatched work across all my properties," a work orders surface gets added as its own destination. For now, dispatch context lives where it belongs: in the conversation that triggered it.

### 4.9 Knowledge

Three tabs:

- **Entries:** canonical knowledge base, organized by property or global. Inline editing. Diff history. Usage counts.
- **Gaps:** unanswered questions ranked by frequency, with AI-suggested answers awaiting operator approval. The highest-leverage surface in the product — every gap closed makes the AI smarter for dozens of future inquiries.
- **Voice & Persona:** the operator's voice profile, example replies, banned phrases. What makes the AI sound like Lanier instead of a corporate help center.

### 4.10 Audit

Every AI decision, every operator action, every mode change, every approval — logged with timestamps, actors, outcomes. Filterable by entity (this property, this inquiry, this work order). Exportable for compliance.

Not aimed at daily use. Aimed at the moment a property owner asks "why did the AI say that?" or a regulator asks for a decision trail.

### 4.11 Settings

Operator profile, team and permissions, AI autonomy defaults, channel connectors (Gmail, PMS, SMS, voice), billing, security (MFA, audit retention).

Not glamorous. Has to be excellent — operators only touch it during onboarding and quarterly reviews, but failures here destroy trust.

---

## 5. Command palette (⌘K)

The keystroke that makes everything feel fast.

### 5.1 What it indexes

- **Entities:** properties (by name, code, address), inquiries (by guest name, message snippet), guests (by name, phone, email), reservations (by ID or guest), vendors (by name or category), knowledge entries, team members.
- **Pages:** every nav destination, every settings page, every saved view.
- **Actions:** "switch to auto for [property]", "find HVAC vendor for [property]", "add knowledge entry for [property]", "open today's queue", "snooze all low-priority insights".
- **Recents:** the last 10 things the operator opened.

### 5.2 How it works

Single keyboard shortcut, single input. Fuzzy match across all indexed surfaces. Results grouped by type. Up/down + Enter to navigate or execute. Esc to close.

For actions, the palette parses a small grammar. Typing "auto 111VW" with the right pattern previews "Switch Sea La Vie (111VW) to AUTO mode" and Enter executes. This is the polish level that makes operators love a tool.

### 5.3 Sequencing

Ships after the shell exists and one real workflow has landed (per Hunter's correction). Specifically, it ships *after* Pre-Booking is redesigned, so the palette can index real data from the new pattern instead of being retrofitted later.

---

## 6. Style

### 6.1 Aesthetic posture

References:
- **Linear** for keyboard discipline, density, and confident defaults
- **Stripe Dashboard** for tabular precision and trustworthy financial-grade typography
- **Front** for the specific problem of making a high-volume shared messaging surface feel professional and powerful
- **Attio** for CRM-style detail panels and contextual depth

Avoided:
- Apple marketing language (this is operational software, not lifestyle product)
- Crypto-dashboard aesthetics (gradients, glassmorphism, neon)
- Consumer SaaS playfulness (no fun empty states, no mascots, no "you're awesome" microcopy)
- OS-shaped aesthetic restraint (Notion, Coda) — we're not there yet; aesthetic confidence is appropriate for a focused messaging product

### 6.2 Color, type, motion

Tokens defined in `DESIGN_SYSTEM.md`. Short version:

- Light-mode-first. Off-white page, white raised surfaces, surgical brand amber for primary actions and active states only.
- Inter for everything operational, JetBrains Mono for IDs and timestamps, Cormorant Garamond reserved for marketing.
- Type scale: 22/17/14/14/13/12. Body at 14px because operators read a lot of text.
- Motion under 300ms always.

### 6.3 What we don't ship

- No charts on the home surface. Charts live in dedicated analytics views.
- No multi-line empty states with illustrations. One informative sentence and a clear next action.
- No emoji in operational UI. Emoji are content the guest used.
- No badges that exist for decoration.

---

## 7. Multi-tenant scope

Built into the model from day one. UI subtle until a second operator exists.

For multi-tenant operators when they arrive:

- **Scope picker in the topbar** switches between tenants without leaving the page.
- **All-tenant aggregated view** for super-admins (visit "All Tenants" mode).
- **Voice-aware:** each tenant's voice profile is honored even when the operator works across tenants.

For single-tenant operators (today's case), the scope picker is present but visually quiet — a small label showing the tenant name, no chevron, no switcher chrome.

---

## 8. What is explicitly not in scope for this proposal

- Mobile design (deserves its own document — surveillance and approval, not authoring)
- Onboarding flow (first-time operator journey, deserves its own document)
- Pricing module UX (backend supports it; not in immediate ship plan)
- Reports module (important for chains; secondary surface, ships later)
- Public surfaces (guest-facing chat, marketing site, signup — already exist)
- Voice console (when voice channel comes online, separate console surface)

---

## 9. Sequenced delivery

Twelve ships. Order revised per Hunter's feedback to land Today early (it teaches the whole product posture) and Pre-Booking before Cmd+K (palette indexes real workflow data).

**Ship A — Foundations.** Rewrite `tokens.css` with the light-mode-first palette. Add primitive component classes to `dashboard.css` (`.btn-*`, `.badge-*`, `.data-table`, `.detail-panel`, `.empty-state`, `.stat-card`). Every existing section module inherits the new look at deploy. No section logic changes. Lock in the shell rules (three-column layout, contextual detail panel, topbar structure). Lock in one canonical table-plus-detail-panel pattern as the reference implementation. *Risk: low. Visible change: significant.*

**Ship B — Shell + nav restructure.** New three-column shell with the lifecycle-spine navigation. Topbar with scope picker (subtle), command palette trigger (stubbed), alerts bell. Existing section pages remain accessible but get re-anchored under the new nav. Stub Today as the new home (rendering a "coming next" placeholder is fine for one ship). *Risk: medium. Visible change: foundational.*

**Ship C — Today.** Replace overview with the insights-and-worklist home. Active interrupts band. Insights for today (three cards max). Lifecycle strip (four columns). Portfolio glance row. *Risk: low. Visible change: redefines the daily experience and teaches the product posture.*

**Ship D — Pre-Booking redesigned.** The signature lifecycle view rebuilt under the new pattern. Real data from existing `/app/api/messages?stage=pre_booking`. New filter tabs, new detail panel, new keyboard shortcuts. *Risk: low (existing endpoints, existing data). Visible change: signature surface refresh — the surface operators spend most of their time in.*

**Ship E — Command palette (⌘K).** Cross-entity search and action execution. Indexes: properties, inquiries, vendors, knowledge entries, pages, recents. Action grammar for common operations. *Risk: medium. Visible change: transformational for power users.*

**Ship F — Properties redesigned.** Card grid → virtualized data table + detail panel. Saved views, bulk operations. Property profile detail panel showing all entities (inquiries, sessions, knowledge, active dispatches) for the property. *Risk: low. Visible change: solves the congestion complaint.*

**Ship G — In-Stay redesigned.** The second lifecycle view, same pattern as Pre-Booking. In-Stay is where vendor dispatch flows live contextually — the detail panel "Active work" section earns its keep here. *Risk: medium. Visible change: completes the highest-value half of the lifecycle spine.*

**Ship H — Knowledge + Voice & Persona redesigned.** Three-tab knowledge surface (entries, gaps, voice). Voice editor as a first-class surface, not buried in settings. *Risk: low. Visible change: makes the AI feel like the operator's own.*

**Ship I — Vendors redesigned.** Directory + intelligence surface. Vendor detail panel showing manufacturer specialties, service areas, warranty handling, dispatch history. Built such that the data model supports cross-operator vendor referrals in the future without UI rework. *Risk: low. Visible change: honors the depth of `VendorIntelligenceService` and the operators' real-world vendor relationships.*

**Ship J — Pre-Arrival, Post-Stay redesigned.** The remaining lifecycle views. Each a self-contained ship; same pattern as Pre-Booking and In-Stay. *Risk: low per ship. Visible change: completes the lifecycle spine.*

**Ship K — Audit redesigned.** Standalone surface for the why-did-the-AI-do-that workflow. Filterable timeline view. *Risk: low. Visible change: deepens trust in the system.*

**Ship L — Legacy retirement.** Delete `frontend/dashboard/oyvoda-v10.jsx`, `scripts/build-dashboard.js`, the v10 compiled bundle, `_dashboard_html.py`, `operator_dashboard.py`. Remove the `/operator-dashboard` mount. Drop the `build:dashboard` script. Kills the drift surface for good. Can ship in parallel with E–K; not blocking. **Note:** v10 hosts the Queue V2 preview at `/operator-dashboard#queue-v2`, which serves as the visual reference for the redesigned pre-booking queue. Ship L must happen *after* Ship D (Pre-Booking redesigned) ships and supersedes Queue V2, or Queue V2 has to be ported into `app/static/dashboard/` first. *Risk: very low after Ship D. Visible change: none, but kills drift.*

**Ship M — Multi-tenant scope (when second operator approaches).** Topbar scope picker becomes visible. Cross-tenant insights view for management companies. Per-tenant voice honored on shared operator surfaces. *Risk: medium. Visible change: enables the chain segment.*

### What's not in the ship plan

- **Work Orders as a dedicated surface.** When operator adoption shows dispatch volume that warrants its own destination, this gets added. Not before. In the meantime, dispatch context surfaces inside the guest message detail panel where it belongs (Ship G renders this contextually inside In-Stay).
- **Insights as a dedicated surface.** Same reasoning. Insights surface on Today. A historical/archive surface gets added when the volume justifies it.
- **Market Intelligence.** Gated on multi-operator geographic density. The `OperationalInsightEngine` produces market-derived insights architecturally; those insights do not surface in operator UI until they have signal from real cross-operator data.
- **Reports.** When operator chains ask for portfolio-level reporting, this becomes a real ship. Until then, the portfolio glance row on Today and individual property detail panels are enough.

---

## 10. What I'm committing to with this proposal

A coherent shape for the operator interface, anchored in what the backend has built, positioned as a guest messaging product (because that's what it is), with the depth in vendor coordination, work orders, insights, and stay workflows surfacing contextually inside messaging surfaces (because that's where it belongs operationally).

The sequenced delivery starts with foundations (tokens, primitives, shell rules, one canonical pattern) and converges toward a complete operator command surface for the messaging product Oyvoda actually is today.

Backend roadmap items (operations execution as a co-equal pillar, market intelligence as a surface, cross-operator vendor referrals) are accommodated by the data model and UI primitives but not surfaced in navigation until adoption signal warrants it.

---

## 11. Next move

Ship A brief. Narrow, executable, Codex-shaped:

- Token rewrite (`app/static/dashboard/styles/tokens.css`)
- Primitive component classes (extensions to `app/static/dashboard/styles/dashboard.css`)
- Shell rule definitions (three-column layout, contextual detail panel behavior, topbar structure)
- One canonical table + detail panel reference pattern (drop-in for `sections/messages.js` to consume in Ship D)

The brief lists deliverables file by file, no architecture rehash, no rationale beyond what's needed to execute correctly. Codex reads it, executes it, ships it.

---

*— Claude, May 2026*
