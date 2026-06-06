# Docs Cleanup Carryforward Brief

**Source session:** Conversation completing pre-booking closeout, lifecycle convergence, healer wiring, gate hardening, persistence fix, and the messaging tier map.
**Workstream label:** D — Docs Cleanup
**Estimated scope:** 1 focused session (1.5–2 hours)
**Status going in:** `docs/architecture/MESSAGING_TIER_MAP.md` landed. Per-tier `__init__.py` docstrings landed. The rest of `docs/` is unreviewed since the closeout.

---

## Goal

Make `docs/` a self-explanatory front door for the Oyvoda codebase as it exists today. Quarantine predecessor-product docs, file historical execution briefs without losing them, and label every doc with its current status so contributors don't confuse roadmap thinking with active architecture.

Do not delete anything by default. Some of the "stale" docs encode real future direction worth preserving.

---

## The five-bucket classification

Every doc in `docs/` and `docs/architecture/` gets exactly one bucket. The bucket determines where the doc lives and what header it carries.

### Bucket 1 — Current Oyvoda Architecture (stays prominent)

Lives in: `docs/architecture/` (top level)

These describe the system as it works today. Status header: `Status: current`.

Likely members (verify before committing):
- `MESSAGING_TIER_MAP.md` (just landed)
- `HEALER_AGENT.md`
- `INTENT_CLASSIFICATION_LAYERS.md`
- `INBOUND_MESSAGE_GATE.md`
- `MESSAGING_ARCHITECTURE.md` (currently at `docs/` root — consider moving to `docs/architecture/`)
- `CANONICAL_OPERATOR_KNOWLEDGE_MODEL.md`
- `PROPERTY_MENTION_SURFACE_AUDIT.md` (if still operationally relevant)

A doc is current iff: it describes runtime behavior that matches what's in `app/services/` today, AND a new contributor reading it would form a correct mental model.

### Bucket 2 — Future Strategic Architecture (preserved, not active)

Lives in: `docs/architecture/future/`

These describe roadmap work that hasn't shipped but is intended. Includes the operator intelligence / BD / pricing arc explicitly:
- Pricing modules
- Supply/demand signals (events, bookings, daily pricing aggregation)
- Cross-operator intelligence and benchmarking
- Amenity value analysis
- Portfolio expansion recommendations
- Anything labeled "intelligence layer" that describes future operator-facing analytics

Status header:
```
Status: future
Scope: <one-line scope>
Depends on: <one-line dependencies — e.g. PMS booking feed, event feed, multi-tenant data>
```

Likely candidates from existing docs:
- Anything from the RentalRevenue.ai predecessor docs that describes pricing intelligence, market signals, or operator BD tooling (extract into Oyvoda-branded future docs; retire the originals to legacy)
- `CONSOLIDATION_PLAN.md` and `DUPLICATION_ANALYSIS.md` *if* they describe signal/intelligence work that's still intended (otherwise they go to history or subsystem bucket)

### Bucket 3 — Historical Execution Records (preserved, archived)

Lives in: `docs/architecture/history/`

These document completed work. Useful for archaeology, not for current architecture understanding. Status header: `Status: historical (shipped <SHA or date>)`.

Likely members:
- `LEGACY_CLOSEOUT_EXECUTION.md`
- `LIFECYCLE_CONVERGENCE_EXECUTION.md`
- The `PHASE_*` and `SHIP_*` briefs in `docs/architecture/`
- `SESSION_*` resume docs
- Incident reports (`INCIDENT_2026_05_05_*`) — these could alternatively go to `docs/incidents/` if you want them separated from architecture history; either way works
- Dated audit docs (`AIRBNB_PARSER_GAP_AUDIT_2026_05_04`, `DOWNSTREAM_UNIFORMITY_AUDIT_2026_05_04`, etc.)

### Bucket 4 — Subsystem-Specific Architecture

Lives in: `docs/architecture/<subsystem>/`

These describe Oyvoda subsystems other than messaging. Rename or folder by subsystem so scope is obvious. Status header: `Status: current` or `Status: future` depending on whether the subsystem is live.

Likely subsystems:
- `docs/architecture/signals/` — signal architecture (if any docs survive review as current)
- `docs/architecture/intelligence/` — operator intelligence layer (mostly bucket 2 content, but as the layer matures, current-state docs live here)
- `docs/architecture/onboarding/` — operator signup, tour, etc.
- `docs/architecture/pms/` — PMS integration architecture
- `docs/architecture/knowledge/` — operator knowledge substrate (anticipating the workstream from `OPERATOR_KNOWLEDGE_SUBSTRATE_BRIEF.md`)

### Bucket 5 — Predecessor / Wrong-Brand Legacy

Lives in: `docs/legacy/predecessor/`

These describe a different product (`RentalRevenue.ai`) or use defunct concepts that don't map to Oyvoda. Status header: `Status: legacy (predecessor product)`.

Confirmed members (verify each):
- `docs/ARCHITECTURE.md` — describes RentalRevenue.ai
- `docs/REFACTORED_ARCHITECTURE.md` — references `IntelligenceRunner`, `PricingExecutor`, etc.
- `docs/DEVELOPER_GUIDEBOOK.md` — RentalRevenue.ai branded

**Important:** Before moving to `docs/legacy/predecessor/`, do a one-pass extraction. If any of these docs contain reusable architectural ideas for the operator intelligence layer (pricing patterns, market signal shapes, BD intelligence framings), extract those sections into a fresh `docs/architecture/future/<topic>.md` doc with proper Oyvoda framing. Only after extraction does the original move to legacy.

---

## Execution steps

### Step 1 — Inventory (30 min)

For each file in `docs/` and `docs/architecture/`, produce a one-line classification:

```
docs/ARCHITECTURE.md                 → bucket 5 (predecessor; extract pricing/intel concepts before move)
docs/MESSAGING_ARCHITECTURE.md       → bucket 1 (move to docs/architecture/)
docs/CONSOLIDATION_PLAN.md           → bucket 4 signals (verify shipped; if shipped → bucket 3)
docs/architecture/HEALER_AGENT.md    → bucket 1 (current)
docs/architecture/PHASE_4_5_E_BRIEF  → bucket 3 (historical)
...
```

Commit this as `docs/DOCS_CLEANUP_INVENTORY_<date>.md`. It's the artifact the cleanup pass reads from. Once cleanup ships, this inventory itself goes to history.

### Step 2 — Create the new directory structure (5 min)

```
docs/
├── README.md                           ← front door (Step 4)
├── architecture/
│   ├── future/
│   ├── history/
│   ├── knowledge/                      ← anticipated by Workstream B
│   ├── intelligence/                   ← anticipated by Workstream C
│   ├── signals/                        ← if any signal docs are current
│   └── (current architecture docs at top level)
├── legacy/
│   └── predecessor/
└── (operational docs: runbooks, security, etc.)
```

`mkdir -p` everything. Empty directories tracked via a `.gitkeep` or a one-line README per directory describing its purpose.

### Step 3 — Bulk move with status headers (45 min)

For each doc, in inventory order:
1. Add status header at the top:
   ```markdown
   ---
   Status: current | future | historical | legacy
   Last verified: 2026-05-26
   ---
   ```
   Future docs additionally get `Scope:` and `Depends on:` lines.
   Historical docs additionally get `Shipped:` (SHA or date).
2. `git mv` to the bucket directory.
3. Commit per-bucket: one commit for current docs, one for future, one for history, one for legacy, one for subsystem moves.

Five clean commits, each with a clear scope. Easy to revert if anything classifies wrong.

### Step 4 — Front door `docs/README.md` (20 min)

Write the top-level README that maps the directory. Suggested skeleton:

```markdown
# Oyvoda Documentation

Oyvoda is a B2B platform for short-term rental operators: AI concierge for
guest messaging, with an operator-facing dashboard and an emerging operator
intelligence layer.

## Where to start

- **New to the codebase?** Read `architecture/MESSAGING_TIER_MAP.md` first.
- **Adding a new module?** The tier map names which directory it belongs in.
- **Understanding a past decision?** See `architecture/history/`.
- **Working on roadmap items?** See `architecture/future/`.

## Current architecture (top of `architecture/`)

- `MESSAGING_TIER_MAP.md` — the four-tier model and dependency rules
- `MESSAGING_ARCHITECTURE.md` — canonical message contract
- `HEALER_AGENT.md` — the learning loop
- `INTENT_CLASSIFICATION_LAYERS.md` — brain intake
- `INBOUND_MESSAGE_GATE.md` — gate behavior and resilience
- (etc.)

## Subsystem architecture

- `architecture/knowledge/` — operator knowledge substrate (uploads, scoping, retrieval)
- `architecture/intelligence/` — operator intelligence layer (pricing, BD, cross-operator signals)
- `architecture/signals/` — signal pipeline
- `architecture/pms/` — PMS integration

## Roadmap and future work

- `architecture/future/` — strategic architecture for work not yet shipped

## History

- `architecture/history/` — completed execution plans, phase briefs, ship docs
- `incidents/` (if separated) — production incident reports

## Legacy / predecessor

- `legacy/predecessor/` — docs from the predecessor product (RentalRevenue.ai),
  preserved for occasional reference, not authoritative for Oyvoda

## Other operational docs

- `RAILWAY_OPERATIONAL_NOTES.md`, `SECURITY_COMPLIANCE.md`, `SCHEMA_MIGRATION_POLICY.md`, etc.

## Doc discipline

When adding a doc, pick a bucket and a status header. When a doc becomes
obsolete, move it to `architecture/history/` rather than deleting. When a
doc spans subsystems, file it under the primary subsystem and cross-link
the others.
```

Adapt the bullet lists once you have the actual current/future/historical inventory.

### Step 5 — Tracker update (5 min)

`docs/ARCHITECTURE_RECONCILIATION_TRACKER.md` already exists and tracks audit follow-ups. Add an entry recording the docs cleanup pass and what it produced.

---

## Risks and how to handle them

**Risk:** Moving a doc breaks a hardcoded link from code or another doc.
- Mitigation: Before the bulk move, grep `docs/` and `app/` for any links into the docs being moved. Update links in the same commit as the move.
- `rg -n "docs/ARCHITECTURE\.md|docs/REFACTORED_ARCHITECTURE\.md|docs/DEVELOPER_GUIDEBOOK\.md" app/ docs/`

**Risk:** A doc classified as "historical" turns out to still be operationally referenced.
- Mitigation: Status header makes the classification visible. If wrong, fix the header and move; that's a single commit.

**Risk:** Bucket 2 (future) content gets extracted from predecessor docs imperfectly.
- Mitigation: Don't auto-extract. The first pass classifies. A separate session does the future-doc extraction with care, after the cleanup pass establishes the directory structure.

---

## Closure criteria

1. Every doc has a status header
2. `docs/README.md` exists and points to the canonical current architecture refs
3. `docs/architecture/` top level has only `Status: current` docs
4. `docs/architecture/future/`, `history/`, `legacy/predecessor/` exist and contain everything else
5. No `RentalRevenue.ai` branded docs at the top of `docs/`
6. The inventory doc itself is moved to `architecture/history/` after the cleanup ships

---

## What not to do in this session

- Don't extract future content from predecessor docs. Classify first, extract in a follow-up.
- Don't rewrite current architecture docs. The tier map is the new canonical; if existing docs are accurate, they stay.
- Don't delete anything. Quarantine first; deletion is a separate decision once the layout is stable.
- Don't touch `MESSAGING_TIER_MAP.md` or the `__init__.py` docstrings. Those just landed and are correct.
