# Operator Knowledge — Current State and Future Convergence

**Source session:** Conversation establishing the messaging tier map; subsequent verification that operator knowledge management, document upload, portfolio/group scoping, and the v2 adapter layer already exist in production.
**Workstream label:** B — Operator Knowledge (documentation + future convergence)
**Estimated scope:** 30 minutes documentation now. Underlying refactor deferred until product work demands it.
**Status going in:** All four capabilities (document upload, property-scoped knowledge, portfolio/group scoping, retrieval contracts) exist in working production code. The adapter layer at `app/static/dashboard-v2/src/api/index.js` is the stable seam between frontend and backend.

---

## The honest framing

The previous version of this brief proposed a Tier 3 → Tier 2 migration of knowledge ownership modules. After verification, that framing was wrong — or at least premature. Here's what's actually true:

**Capabilities that already exist in production:**

1. **Document upload** — `POST /documents/upload` with normalization, OCR, document-type classification, and extraction pipelines for rent_roll, house_manual, adr_history, amenity_list, guest_qa. Lives at `app/api/v1/endpoints/documents.py` and `app/services/documents/`.

2. **Property-scoped knowledge** — `POST /operator/properties/reconcile` ingests guidebook URLs per property, chunks and embeds content, persists scoped knowledge entries. Lives at `app/api/v1/endpoints/operator_properties.py` calling `app/services/concierge/guidebook_ingest_service.py`.

3. **Portfolio (group) scoping** — `/app/api/portfolios` endpoints exist (list, create, updateProperties) and are wired into the v2 frontend api client.

4. **Knowledge CRUD** — `/app/api/kb` (list, create, update, delete, test) and `/app/api/kb-gaps` (list, resolve, dismiss). Property-scoped queries supported via `property_id` query param.

5. **Retrieval contracts** — `scoped_knowledge_service.py` writes; the brain's context builder reads. `knowledge_embeddings` table is the storage substrate.

6. **Adapter layer** — `app/static/dashboard-v2/src/api/index.js` covers all the above and more. `app/static/dashboard-v2/src/adapters/index.js` normalizes responses. This is the stable seam between frontend and backend.

**What this means architecturally:**

The product pathway is already correct:
```
v2 frontend
  ↓
app/static/dashboard-v2/src/api/index.js  (adapter / typed fetch client)
  ↓
FastAPI endpoints (/documents/upload, /operator/properties/reconcile,
                   /app/api/kb, /app/api/portfolios, /app/api/kb-gaps)
  ↓
Backend services (app/services/documents/, app/services/concierge/guidebook_ingest_service.py,
                  app/services/messaging_brain/knowledge/scoped_knowledge_service.py)
  ↓
Storage (knowledge_embeddings, property_evidence, portfolios tables)
  ↓
Brain reads via context_builder_agent
```

The fact that some implementation modules live under `messaging_brain/knowledge/` rather than `messaging/knowledge/` is a layering inconsistency, not a functional problem. The adapter layer abstracts over the inconsistency — frontends and operators don't know or care which package the service module sits in.

---

## What this brief commits to

### Now (immediate, ~30 minutes) — COMPLETE

1. **`docs/architecture/MESSAGING_TIER_MAP.md` updated** with the current-state vs target-state section. The "Known current-state vs target-state inconsistencies" section documents the layering mismatch honestly, names the six concrete triggers that would justify the migration, and explicitly tells contributors to use the adapter layer for new work rather than start the migration speculatively.

2. **v2 frontend `api/index.js` verified** — covers `api.kb.*`, `api.kbGaps.*`, `api.portfolios.*`, `api.properties.*`, `api.settings.aiGuidance.*`, alert routing, sessions, messages, inquiries, escalations, vendors, settings, notifications, and admin observability. Gaps that may surface during the frontend session:
   - `api.documents.*` namespace doesn't exist yet (only `propertyDocuments.upload` and `propertyImports.upload`). A Documents view will need `list`, `delete`, and `detail` methods added to `api/index.js` and corresponding backend endpoints if not already present.
   - Portfolio group management UI doesn't exist on the frontend; backend endpoints (`/app/api/portfolios`) are wired in the api client. Building the UI is straightforward.
   - Knowledge gap resolution flow exists in the api client but may not have a frontend surface yet.
   - AI guidance editor exists in the api client; verify frontend coverage.

   These are the kinds of gaps the deferred-migration framing anticipates: fill them through the adapter layer, not by reorganizing backend modules.

3. **The current-state-vs-target-state framing is captured in the tier map itself**, not in a separate `CURRENT_STATE.md`. The tier map's section is where future contributors look first; a separate file would either duplicate or drift. Keeping it in one place.

### Later (deferred until product work demands it)

The Tier 3 → Tier 2 migration described in the previous version of this brief is preserved as a future option, not a commitment. The triggers that would justify executing it:

- **Reuse pressure** — A second consumer (beyond the brain) needs to read knowledge ownership data, and the current placement makes it awkward
- **Testing friction** — Changes to knowledge ownership require unrelated brain changes because the modules are co-located
- **Permissioning complexity** — Operator-level vs platform-level access control gets hard to enforce because the service boundary doesn't match the responsibility boundary
- **Future intelligence-layer consumption** — Workstream C (operator intelligence) needs to read knowledge as a signal source, and the current placement creates dependency cycles

If none of those become real, the modules can stay where they are. The adapter layer protects the product pathway either way.

---

## Verified capability matrix

For the next session, this is what already works:

| Capability | API surface | Backend service | Storage | v2 frontend wiring |
|---|---|---|---|---|
| Document upload | `POST /documents/upload` | `app/services/documents/` (extractors, normalization) | `PropertyEvidence`, document blobs | needs verification — endpoint exists but `api.documents` may need explicit wiring |
| Property reconciliation | `POST /operator/properties/reconcile` | `guidebook_ingest_service.py` | `knowledge_embeddings`, `properties` | wired via `api.properties.*` plus reconcile endpoint |
| KB CRUD | `/app/api/kb` | `scoped_knowledge_service.py` | `knowledge_entries` (scoped) | wired (`api.kb.list/create/update/delete/test`) |
| KB gaps | `/app/api/kb-gaps` | `gap_recorder.py` | `kb_gaps` | wired (`api.kbGaps.list/resolve/dismiss`) |
| Portfolio groups | `/app/api/portfolios` | (verify which service owns this) | `portfolios` table | wired (`api.portfolios.list/create/updateProperties`) |
| AI guidance per operator | `/app/api/settings/ai-guidance` | (operator_settings extra field) | `operator_settings` | wired (`api.settings.aiGuidance.get/put`) |
| Alert routing per contact | `/app/api/settings/alert-routing` | `messaging/operator_alerts.py` | `operator_alert_contacts` | wired (`api.settings.alertRouting/createAlertContact/etc.`) |

**What's missing from the v2 frontend (verify):**

- Documents view that lists uploaded docs per property and lets operators delete/replace
- Portfolio group management UI (the API is wired but a UI may or may not exist)
- Knowledge gap action UI (resolve / dismiss flow)
- AI guidance editor

These are frontend work, not backend work. They belong in **Workstream A — Frontend v2 Extension**, not in this brief.

---

## What this brief deliberately does not do

- **Does not move any service modules.** The previous version proposed migrating `scoped_knowledge_service.py`, `property_faq.py`, etc., from `messaging_brain/knowledge/` to `messaging/knowledge/`. That work is deferred until a product trigger justifies it.

- **Does not change endpoint contracts.** The adapter layer is the public contract. Backend module placement is internal.

- **Does not introduce portfolio groups as new architecture.** Portfolios already exist in the API. Whatever schema and service backs them stays as-is.

- **Does not require any database migrations.** Current schema is sufficient.

- **Does not block any other workstream.** Frontend extension (Workstream A) can proceed against the existing endpoints. Docs cleanup (Workstream D) doesn't depend on this. Operator intelligence layer (Workstream C) reads from the same substrate either way.

---

## When this work gets revisited

Three scenarios bring the deferred migration back into scope:

1. **Frontend session reveals API gaps.** If Workstream A starts building the Documents view or Portfolio Group management UI and discovers the existing endpoints don't cover what's needed (e.g., bulk document operations, cross-property knowledge views, scope inheritance UI), some of those gaps may be cleaner to fill by restructuring the backend rather than papering over with thin endpoints.

2. **Intelligence layer needs cross-scope reads.** When Workstream C builds amenity value analysis or cross-operator aggregation, it may need to read knowledge data from a stable contract that doesn't depend on brain implementation details. That's the natural trigger for extracting a clean retrieval interface.

3. **Permissioning gets complex.** If operator role/permission work introduces "this user can edit property X's knowledge but not portfolio Y's," the access-control layer benefits from a single ownership surface rather than three scattered service modules.

Until one of those fires, the current state is fine.

---

## Closure criteria (for the documentation-only "now" pass)

1. `MESSAGING_TIER_MAP.md` has the current-state-vs-target-state note
2. This brief documents the endpoint + adapter + service map directly, without introducing a separate `CURRENT_STATE.md`
3. v2 frontend `api/index.js` has the existing knowledge-related endpoints verified, and any known client gaps are called out explicitly here for Workstream A
4. This brief itself is moved to `docs/architecture/knowledge/` once Workstream D's docs cleanup runs

The "later" pass (the actual Tier 3 → Tier 2 migration) has its own brief written when product triggers fire. The earlier version of this doc, with the full 11-commit migration plan, is preserved as a template for that future work.

---

## Bottom line

The system already supports operator-uploaded knowledge, property-scoped knowledge, portfolio-group scoping, retrieval contracts, and a stable adapter layer between frontend and backend. Codex's framing is correct: document the current pathway honestly, mark the long-term ownership target separately, and only execute the underlying refactor when a product trigger justifies it.

No code movement required today.
