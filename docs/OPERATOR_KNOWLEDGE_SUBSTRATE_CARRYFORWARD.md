# Operator Knowledge Substrate Carryforward (SUPERSEDED)

**Status:** SUPERSEDED on 2026-05-26
**Replaced by:** `docs/OPERATOR_KNOWLEDGE_CARRYFORWARD.md`

---

## Why this doc was superseded

The original version of this brief proposed an immediate Tier 3 → Tier 2 migration of operator knowledge ownership modules — moving `scoped_knowledge_service.py`, `property_faq.py`, `global_faq.py`, `historical_import.py`, etc., from `messaging_brain/knowledge/` to a new `messaging/knowledge/` package, plus relocating `concierge/guidebook_ingest_service.py` and introducing a `portfolio_groups` schema.

That framing was premature. Verification revealed:

- All four operator knowledge capabilities (document upload, property-scoped knowledge, portfolio/group scoping, retrieval contracts) already exist in production code
- The v2 frontend adapter layer (`app/static/dashboard-v2/src/api/index.js`) is the stable seam between frontend and backend
- The underlying service module placement is a layering inconsistency, not a functional blocker
- Refactoring the modules now would be churn without product value

The corrected approach is to document the current state honestly and defer the underlying refactor until a product trigger fires (reuse pressure, testing friction, permissioning complexity, or intelligence-layer consumption).

See `docs/OPERATOR_KNOWLEDGE_CARRYFORWARD.md` for the current guidance.

---

## What this doc preserves

The original 11-commit migration plan in this doc remains useful as a **template** for when the deferred work is eventually triggered. If a future product driver justifies the Tier 3 → Tier 2 migration, that future session can use this doc as the starting structure: the proposed module layout, the scope model (`KnowledgeScope`, `PortfolioGroup`), the commit-by-commit sequence with re-export shims, the dependency-rule reasoning, and the document upload pipeline design.

Do not execute this plan as-is. Use it as a reference when writing the next iteration of the brief at the time it actually becomes relevant.

---

## When to revisit

Three scenarios bring this deferred migration back into scope:

1. Frontend session (Workstream A) reveals API gaps that are cleaner to fix at the backend service layer than by adding endpoints
2. Intelligence layer (Workstream C) needs cross-scope knowledge reads that benefit from a stable retrieval contract
3. Operator role/permission work introduces access control patterns that need a single ownership surface

Until one of those fires, the current state — operator knowledge management exposed through the adapter layer with implementation modules where they currently sit — is the correct state.

---

## Original content below (for reference only — do not act on as a current plan)

(Original brief content preserved unchanged below this divider so the migration plan template is available when needed.)

---

# [ORIGINAL CONTENT START]

# Operator Knowledge Substrate Carryforward Brief

**Source session:** Conversation establishing the messaging tier map; subsequent question about where operator-uploaded documents, property-scoped knowledge, and portfolio-scoped knowledge should live.
**Workstream label:** B — Operator Knowledge Substrate (Tier 2 build-out)
**Estimated scope:** 2 focused sessions (one for substrate, one for ingestion)

## Principle

```
Knowledge OWNERSHIP lives in Tier 2 — messaging/
Knowledge USAGE lives in Tier 3 — messaging_brain/
```

Operator-owned facts (uploaded documents, property-specific notes, portfolio-group rules, FAQ entries, scope resolution, retrieval contracts) belong in `messaging/`. They describe what the operator knows and how it's stored. They should survive a brain rewrite.

Decisions about *when* to consult that knowledge, *which scopes* matter for a given message, and *how* to ground a response against it belong in `messaging_brain/`. They describe how the brain reasons about knowledge.

## Target state (template for future execution)

```
app/services/messaging/knowledge/         ← OWNERSHIP (Tier 2)
├── __init__.py
├── scope_model.py                        ← tenant / portfolio / property / reservation scopes
├── document_store.py                     ← uploaded document metadata + content addressing
├── chunk_store.py                        ← canonical chunk + citation storage
├── retrieval.py                          ← scope-aware retrieval interface
├── faq_store.py                          ← merged property_faq + global_faq, scope-aware
├── topic_registry.py                     ← moved from messaging_brain/
├── scoped_knowledge_store.py             ← moved & renamed from scoped_knowledge_service.py
├── dashboard_kb_service.py               ← moved (operator-facing knowledge view)
└── ingestion/
    ├── __init__.py
    ├── guidebook_breezeway.py            ← moved from concierge/guidebook_ingest_service.py
    ├── document_upload.py                ← operator file upload pipeline (note: already exists)
    └── historical_import.py              ← moved from messaging_brain/knowledge/

app/services/messaging_brain/knowledge/   ← USAGE (Tier 3) — stays
├── __init__.py
├── faq_answering.py                      ← stays (uses faq_store from Tier 2)
└── gap_recorder.py                       ← stays (records gaps for healer to consume)
```

## Scope model

```python
@dataclass(frozen=True)
class KnowledgeScope:
    scope_type: Literal['reservation', 'property', 'portfolio_group', 'tenant']
    scope_target_id: UUID
```

Resolution order is most-specific-first: property overrides portfolio overrides tenant.

## The 11-commit migration sequence (template)

1. Create `messaging/knowledge/` package skeleton with full tier framing docstring
2. Move `topic_registry.py` from Tier 3 to Tier 2 with re-export shim
3. Move `scoped_knowledge_service.py` → `scoped_knowledge_store.py`
4. Move `property_faq.py` and `global_faq.py`, merge into `faq_store.py`
5. Move `dashboard_kb_service.py`
6. Move `historical_import.py`
7. Move `concierge/guidebook_ingest_service.py` → `messaging/knowledge/ingestion/guidebook_breezeway.py`
8. Create `scope_model.py`, `retrieval.py`, `document_store.py`, `chunk_store.py`
9. (If portfolio_groups schema doesn't exist) Add migration for portfolio_groups + memberships tables
10. Update `context_builder_agent` to use new retrieval interface
11. Remove re-export shims after all imports point to new locations

## Tier 1 ↔ Tier 2 ingestion exception

When this work executes, document the legitimate cross-tier import at the ingestion boundary:

- `integrations/breezeway/guidebook_client.py` — raw API client (Tier 1)
- `messaging/knowledge/ingestion/guidebook_breezeway.py` — calls the client, normalizes into canonical chunks (Tier 2)

This `messaging → integrations` import is the one allowed exception to the strict layering rule, because ingestion is the seam where external data becomes owned data. Document in `MESSAGING_TIER_MAP.md` when this work ships.

## What stays in Tier 3 (do not move when this executes)

- `faq_answering.py` — fast-path decision logic
- `gap_recorder.py` — usage-time knowledge gap recording
- `context_builder_agent.py` — orchestrates when to fetch
- `lazy_context_gates.py` — keyword gates for context fetching

The rule: if a module decides *when* or *how* to use knowledge, it's Tier 3. If a module stores or retrieves knowledge, it's Tier 2.

# [ORIGINAL CONTENT END]
