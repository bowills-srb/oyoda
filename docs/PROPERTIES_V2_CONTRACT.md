# Properties v2 contract audit

**Date:** 2026-05-27  
**Status:** verified-by-code for contracts 1–3; runtime spot-check still needed for contract 4  
**Purpose:** lock the backend/API/data contracts before building the v2 Properties surface

## Summary

The proposed Properties v2 direction is broadly correct:

- there is a substantial v1 Properties surface worth porting
- the core operator-app APIs already exist
- URL ingestion is **not** currently an operator-facing backend capability and should stay as a separate follow-up

The audit also surfaced three places where the v2 build must respect the real contract instead of assuming a simpler one:

1. **KB property reference is flexible, but not arbitrary.**
   The KB service resolves property-scoped entries by **UUID scope target**, **property_code**, or **external_id**.
2. **Document upload is not a generic drop-zone.**
   The backend requires a real combination of `document_type`, `target`, `scope`, and sometimes `property_code`.
3. **Coverage/completeness is not a backend truth today.**
   We can ship a frontend heuristic, but it must be labeled honestly as an estimate.

---

## Contract 1 — KB property reference

### Question

When Properties v2 calls `api.kb.list(...)`, what should it pass so the backend returns the correct property-scoped KB for Beach Habitats?

### Verified code path

The dashboard KB list endpoint is:

- [`app/api/v1/endpoints/operator_dashboard_api.py:614`](../app/api/v1/endpoints/operator_dashboard_api.py)

It passes `property_id` straight through as `property_ref`:

- `list_kb_entries(... property_id: Optional[str] = None ...)`
- `knowledge_service.list_dashboard_entries(... property_ref=property_id)`

The actual resolution happens in:

- [`app/services/messaging_brain/knowledge/dashboard_kb_service.py:48-92`](../app/services/messaging_brain/knowledge/dashboard_kb_service.py)

Verified accepted values for `property_ref`:

- property-scoped knowledge row UUID:
  - `k.scope_target_id::text = :property_ref`
- `properties.property_code`:
  - `p.property_code = :property_ref`
- `properties.external_id`:
  - `p.external_id = :property_ref`
- tenant/all-properties bucket:
  - `__all_properties__`

Creation uses the same dual-resolution pattern:

- [`dashboard_kb_service.py:340-395`](../app/services/messaging_brain/knowledge/dashboard_kb_service.py)

`create_dashboard_entry(...)` resolves either:

- `property_id` as a UUID `properties.id`
- or `property_external_id` matching **either** `property_code` **or** `external_id`
- or `__all_properties__` for tenant-scoped knowledge

### Contract decision

**Properties v2 should key KB lookups by `property_code` when present, and fall back to `external_id` only when `property_code` is blank.**

Reason:

- `property_code` is the one identifier guaranteed to be used consistently across:
  - `/app/api/properties`
  - `/app/api/properties/documents/import`
  - the v1 Properties surface
- the KB service explicitly accepts both `property_code` and `external_id`
- using `property_code || external_id` as a normalized `knowledgeRef` avoids depending on a hidden UUID not present in the base properties payload

### Build implication

Properties v2 should normalize each property row to:

- `propertyCode`
- `externalId`
- `knowledgeRef = propertyCode || externalId`

Then:

- `api.kb.list(knowledgeRef)` for per-property entries
- `api.kb.create({ ..., property_external_id: knowledgeRef })` for new notes

Do **not** assume the row has a canonical property UUID available up front.

---

## Contract 2 — Document upload required field matrix

### Question

Which combinations of `document_type`, `target`, `scope`, `property_code`, `asset_type`, and `asset_name` are valid?

### Verified backend contract

The upload endpoint is:

- [`app/api/v1/endpoints/operator_app.py:2889-3065`](../app/api/v1/endpoints/operator_app.py)

Hard validation:

- `document_type` is required: `Form(...)`
- `scope` must be one of:
  - `property`
  - `portfolio`
- `target` must be one of:
  - `knowledge`
  - `asset`
  - `both`

Required-field rules:

- if `scope == "property"`:
  - `property_code` is required
- if `target in {"asset", "both"}`:
  - `property_code` is required

Therefore:

- `target=asset` + `scope=portfolio` is effectively invalid
- `target=both` + `scope=portfolio` is effectively invalid

Optional-but-inferred:

- `asset_type`
  - inferred from `document_type` when omitted
- `asset_name`
  - inferred from filename when omitted

Inference logic lives in:

- [`operator_app.py:281-325`](../app/api/v1/endpoints/operator_app.py)

### Verified v1 UI contract

The v1 Properties section exposes this explicitly, not as a generic upload:

- [`app/static/dashboard/js/sections/properties.js:288-329`](../app/static/dashboard/js/sections/properties.js)
- [`app/static/dashboard/js/sections/properties.js:674-699`](../app/static/dashboard/js/sections/properties.js)

The operator chooses:

- document type
- target
- scope
- optional asset type
- optional asset name

And v1 sets:

- `propertyCode = ''` only when `scope === 'portfolio'`
- otherwise it sends the selected property code

### Required-field matrix

| target | scope | property_code required | asset_type required | asset_name required | valid |
|---|---|---:|---:|---:|---:|
| `knowledge` | `property` | yes | no | no | yes |
| `knowledge` | `portfolio` | no | no | no | yes |
| `asset` | `property` | yes | no (inferred if blank) | no (inferred if blank) | yes |
| `asset` | `portfolio` | yes | no | no | **no in practice** |
| `both` | `property` | yes | no (inferred if blank) | no (inferred if blank) | yes |
| `both` | `portfolio` | yes | no | no | **no in practice** |

### Contract decision

**Properties v2 must preserve the v1 classification controls for document upload.**

At minimum, commit A needs:

- document type picker
- target picker
- scope picker
- selected-property awareness
- optional asset type/name inputs

What v2 must **not** ship:

- a single generic “upload document” drop-zone with no target/scope/type choices

That would be a regression against both the backend contract and the v1 UX.

### UI constraint

Because the backend requires `property_code` for any `target in {"asset", "both"}`,
the v2 upload form should prevent operators from selecting invalid combinations
instead of letting them discover them via 400s.

Recommended UI rule:

- if `target` is `asset` or `both`, force `scope` to `property`
- if `scope` is switched to `portfolio`, disable `target=asset` and `target=both`

This mirrors the real contract more honestly than a passive validation error.

---

## Contract 3 — Documentation health heuristic

### Question

What signals exist today for a per-property “completeness” or “coverage” score, and how should we weight them?

### Verified backend signals

Identity report endpoint:

- [`app/api/v1/endpoints/operator_app.py:3375-3670`](../app/api/v1/endpoints/operator_app.py)

Per-property signals returned today:

- `property_code`
- `external_id`
- `display_name`
- `marketing_name`
- `preferred_address`
- `community`
- `profile_updated_at`
- `pms_property_ids[]`
- `pms_unit_codes[]`
- `ota_refs{}`
- `aliases[]`
- `knowledge_count`
- `asset_count`
- `review_status{}`

Portfolio summary signals also exist, but the per-property row is the important one for v2.

KB gaps endpoint:

- [`app/api/v1/endpoints/operator_dashboard_api.py:732-828`](../app/api/v1/endpoints/operator_dashboard_api.py)

Important note:

- there is **no server-side property filter parameter today**
- each gap row does include:
  - `property` (sourced from `property_external_id`)
  - `missing_topics[]`
  - `ask_count`
  - `reason`
  - `intent`

So per-property gap counts are available via **client-side grouping**, keyed against property code / external id.

### Contract decision

Ship this as a **frontend heuristic**, not a canonical backend truth.

Recommended operator-facing label:

- **Documentation health (estimate)**

Not:

- “Completeness”
- “Coverage score”

### Recommended heuristic

Clamp final score to `[0, 1]`, display as a percentage, and show a tooltip explaining the inputs.

```text
health =
  0.20 * has_display_name
+ 0.10 * has_marketing_name
+ 0.15 * has_pms_property_id
+ 0.10 * has_pms_unit_code
+ 0.10 * has_any_ota_ref
+ 0.15 * min(knowledge_count, 8) / 8
+ 0.08 * min(asset_count, 4) / 4
+ 0.07 * has_recent_profile_update
+ 0.05 * has_alias
- 0.10 * has_pending_identity_review
- 0.10 * has_open_gap
```

Definitions:

- `has_display_name` = `display_name` present
- `has_marketing_name` = `marketing_name` present
- `has_pms_property_id` = `pms_property_ids.length > 0`
- `has_pms_unit_code` = `pms_unit_codes.length > 0`
- `has_any_ota_ref` = at least one provider in `ota_refs`
- `has_recent_profile_update` = `profile_updated_at` within the last 90 days
- `has_alias` = `aliases.length > 0`
- `has_pending_identity_review` = `review_status.pending > 0`
- `has_open_gap` = grouped KB gaps for this property > 0

Why this shape:

- identity correctness matters, so PMS/OTA refs are material
- knowledge richness matters most for messaging quality, so `knowledge_count` gets a meaningful share
- asset coverage matters, but less than guest-facing knowledge
- a stale but otherwise “complete” property should not collapse to zero
- open gaps and pending identity reviews should visibly drag the estimate down

### UI guidance

Show:

- percentage chip: `62%`
- label: `Documentation health`
- disclosure/tooltip: `Estimate based on identity coverage, knowledge records, assets, recent profile updates, and open gaps.`

Do **not** present it as a backend-certified truth.

### Last updated

Do not label a single timestamp generically as **Last updated** unless you define what it means.

What we actually have today:

- `profile_updated_at` from identity report
- KB entry `updated_at` only if/when those entries are loaded separately
- no single canonical “property last touched” field

Safe commit A choice:

- show `Profile updated` if you use `profile_updated_at`
- defer a unified “last updated” label until we build a proper aggregate timestamp

---

## Contract 4 — 204 Spartina real-data spot-check

### Question

What does Beach Habitats actually have stored today for `204 Spartina Cir`?

### Status

**Verified against live Supabase data on 2026-05-27.**

### Spartina roster (Beach Habitats)

Live Spartina properties for tenant `e07980b2-a990-4b24-91d1-c8cb71ab70e1`:

- `134SC` → `134 Spartina Cir`
- `178SC` → `178 Spartina Cir`
- `204SC` → `204 Spartina Cir`
- `236SC` → `236 Spartina Cir`
- `294SC` → `294 Spartina Cir`
- `359SC` → `359 Spartina Circle`

Notably, there is **no** `201 Spartina` row in production.

### 204 Spartina verified shape

Live property facts for `204SC`:

- `property_code`: `204SC`
- `external_id`: blank
- `address_street`: `204 Spartina Cir`
- `knowledge_count`: `45`
- `asset_count`: `0`
- `pending_identity_reviews`: `0`

### Representative gaps

Open gaps tied directly to `204SC` include:

- `booking_inquiry` about which bedrooms are on the main level and whether
  stairs are required
- `email_prebooking_fallback` follow-up asking for more information on the
  stairs and which level each bedroom is on
- `gmail_prebooking_missing_knowledge` asking about the bed size in the
  lounge area

### Important runtime finding

Some obviously related gaps are still **unbound**:

- layout/bedroom questions exist with blank `property_external_id`
- other related inquiry gaps reference layout ambiguity without a property tag

So the per-property gap count is a **floor**, not a ceiling.

### Design implications confirmed by live data

1. **`knowledgeRef = propertyCode || externalId` is the correct v2 contract.**
   For Beach Habitats, `property_code` is the reliable identifier and
   `external_id` may be blank.
2. **The documentation-health heuristic is safe to ship.**
   A property with 45 KB entries, 0 assets, and open layout gaps should still
   score as “well documented, but not complete.” That is exactly the intended
   behavior of the heuristic.
3. **Per-property gap copy must stay neutral.**
   The UI should say “Gaps tagged to this property” or equivalent, not imply
   that the count is exhaustive.
4. **0 assets is not an error state by itself.**
   The asset section should frame this as an opportunity to upload manuals,
   warranties, or appliance docs, not as a broken property record.
5. **The per-property KB view must handle density.**
   `204SC` already has 45 knowledge rows, so the expansion/detail treatment
   cannot assume a tiny knowledge set.

---

## Review of the proposed two-commit plan

### Agree

- Split into **Commit A (v2 port on existing backend)** and **Commit B (URL ingestion)**.
- Porting the v1 Properties surface to v2 first is the correct move.
- Shipping the documentation-health heuristic in commit A is reasonable **if** it is documented and labeled as an estimate.

### Tighten

Commit A should include only the parts that are already contract-safe:

- Properties route + router entry
- property list/search/filter
- property expansion/detail
- KB list + add/edit note
- KB gaps grouped per property
- document upload **with full v1 controls preserved**
- documentation-health estimate

Commit A should **not** assume:

- a canonical property UUID is available in the base list payload
- a generic upload control is sufficient
- `profile_updated_at` equals a universal “last updated” field

Commit B should own:

- arbitrary URL ingestion
- fetch/crawl/match logic
- property-page normalization
- any backend ingestion endpoint required for pasted websites

---

## Open runtime questions

1. **How often `property_code` is blank in production**
   - contract supports `external_id` fallback, but incidence rate is unverified
2. **How often related gaps remain unbound despite a clear property**
   - confirmed to happen for 204 Spartina-class layout questions, but portfolio-wide incidence is unverified

---

## Safe build contract for commit A

If we start building now, the safe assumptions are:

- use `propertyCode || externalId` as the row’s knowledge reference
- preserve the v1 document-ingest control matrix
- compute and label a frontend-only documentation-health estimate
- treat KB gaps as client-grouped by property reference
- defer URL ingestion to a second commit
