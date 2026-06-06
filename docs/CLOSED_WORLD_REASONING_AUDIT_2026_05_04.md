# Closed-World Reasoning Audit — 2026-05-04

Reconciliation note auditing the data model and reasoning layer for the
closed-world reasoning commitment defined in
`docs/MESSAGING_ARCHITECTURE.md` Section 6.

This is a Phase 1b audit. It produces a mapping artifact, not code
changes. Subsequent sessions execute against the findings here.

## Purpose

The architecture document commits to closed-world reasoning on Layer 1
(operator-provided property data) collections marked exhaustive:
absence of an attribute means the attribute is not present. This
commitment requires three structural pieces:

1. A schema-level mark distinguishing exhaustive from partial
   collections
2. A reasoning-layer enforcement that applies closed-world inference
   only on collections marked exhaustive
3. An onboarding contract where operators explicitly accept the
   closed-world assumption for marked collections

This note audits the first two. Onboarding contract is out of scope
(separate workstream).

## Scope

**In scope (collections):**
- Amenity lists
- Included items
- House rules
- Pet policies
- Parking arrangements

**Conditionally in scope:** Included services, if present as a
structured collection in the data model.

**Out of scope (collections):**
- Narrative descriptions
- Photos / media
- Freeform local recommendations
- House manuals (when modeled as broad documents)

These are open-world by nature; absence-as-evidence does not apply.

**In scope (audit dimensions):**
- Schema state: how each in-scope collection is currently modeled
- Reasoning state: where code reasons about each collection and
  whether any path currently assumes completeness

**Out of scope (audit dimensions):**
- Onboarding flow design
- Operator UX for closed-world acceptance
- Layer 2 (location) or Layer 3 (event) reasoning
- Implementation design of any closed-world enforcement mechanism

## Classification legend

Each collection is tagged on two axes.

**Schema state:**
- **Structured-with-flag** — modeled as a discrete collection AND has
  an exhaustive/partial mark
- **Structured-no-flag** — modeled as a discrete collection but no
  completeness mark
- **Semi-structured** — present as JSONB, free text, or list field
  without a discrete schema
- **Absent** — no schema representation found

**Reasoning state:**
- **Closed-world enforced** — reasoning code checks completeness
  before treating absence as informative
- **Closed-world implicit** — reasoning code treats absence as
  informative without an explicit completeness check (working
  correctly only when data happens to be complete)
- **Open-world** — reasoning code does not infer from absence
- **No reasoning found** — no code path reasons about this
  collection in the audited surface

## Method

The audit proceeds in two rounds:

**Round 1 — Schema state.** Grep across migrations (`db/migrations/`),
ORM models (`app/models/`, `app/db/`), and existing completeness
markers anywhere in the codebase. Establishes how each in-scope
collection is currently represented and whether any exhaustive flag
exists today.

**Round 2 — Reasoning layer.** Grep across reasoning surfaces
(`app/services/concierge/`, `app/services/messaging_brain/`) for code
paths that read each in-scope collection. Classifies each reasoning
site as closed-world enforced, closed-world implicit, open-world, or
no reasoning found.

For each collection, classification combines schema state and
reasoning state. Gaps surface where reasoning treats absence as
informative without a schema-backed completeness check.

## Collection inventory

The audit identified five in-scope collections. Each is classified
against schema state and reasoning state.

### Amenities

**Schema state:** Structured-no-flag (JSONB blob)

`app/models/property.py` defines `amenities` as a JSONB column with
no completeness mark. Migration `003_create_properties.py` provides
both flat boolean columns (`has_pool`, `has_hot_tub`, etc.) and a
JSONB `amenities` field with `server_default='{}'`. The model's
`has_amenity()` helper returns `bool(self.amenities.get(amenity))` —
absence of a key produces `False` indistinguishably from explicit
non-presence.

**Reasoning state:** Closed-world implicit

Multiple call sites read amenity presence as boolean truth without
checking whether the underlying collection is complete:

- `property_canonical_service.py` lines 429-433 build canonical
  property records using `bool(amenities.get("pool"))`,
  `bool(amenities.get("hot_tub"))`, `bool(amenities.get("waterfront"))`,
  `bool(amenities.get("pet_friendly"))`
- `onboarding_agent.py` lines 1225-1230 do the same coercion during
  onboarding-driven property record construction
- `property_import_service.py:1509` checks `if amenities.get("pool")`
  during import normalization
- `concierge/property_context.py` defines `PropertyContext` with
  hardcoded boolean defaults (`has_pool: bool = False`,
  `pets_allowed: bool = False`, `has_hot_tub: bool = False`, etc.)

The pattern flattens three semantically distinct states into one
boolean:

- "Operator said no" (key present with falsy value)
- "Operator never answered" (key absent)
- "Source data omitted it" (key absent because the source upstream
  did not include it)

Downstream consumers of `PropertyContext` see `False` and cannot
distinguish "no" from "unknown."

**Notable contradiction:**
`pre_booking_auto_send.py:1310` contains explicit prompt guidance to
the agentic layer: *"Reasoning note: answer from the retrieved
property evidence only. If the evidence describes the amenity as
included, say so clearly. If not, do not invent it."* This is
open-world behavior at the prompt layer compensating for closed-world
behavior at the data layer. The two layers are working at cross
purposes: the data has already collapsed uncertainty into booleans;
the prompt then asks the agent not to claim certainty.

### House rules

**Schema state:** Semi-structured (sparse dict, no completeness mark)

House rules are not a discrete schema column. They flow through the
system as a Python dict, populated by `context_builder_agent.py` from
overlay sources:

```python
house_rules: dict[str, Any] = {}
...
overlay_house_rules = overlay.get("house_rules") or {}
if isinstance(overlay_house_rules, dict):
    for key, value in overlay_house_rules.items():
        if value not in (None, "", [], {}):
            house_rules[key] = value
```

Only populated keys survive. No boolean flattening. No completeness
marker.

**Reasoning state:** Open-world cautious

`house_rules_agent.py` treats missing data as unknown and defers
explicitly:

- When no FAQ data is available in context: `answer_summary="No FAQ
  available in context for house-rules question; deferring to
  operator."`, `missing_info=["property_knowledge.faq"]`,
  `recommended_action=RecommendedAction.DRAFT_ONLY`
- When FAQ exists but no match: `answer_summary="House-rules question
  did not match any FAQ entry; deferring to operator."`,
  `missing_info=["faq_match_for_question"]`,
  `recommended_action=RecommendedAction.DRAFT_ONLY`

This is correct open-world behavior: missing data does not produce
fabricated answers. The agent defers to operator review rather than
inferring from absence.

### Pet policies

**Schema state:** Flat column, not a collection

`pet_friendly BOOLEAN DEFAULT FALSE` (migration `018_pre_booking_pipeline.py`)
is a single boolean column on the property table. It is not a
collection in the architectural sense; closed-world reasoning does
not apply to single-valued fields.

**Reasoning state:** Closed-world implicit (by data shape)

`pre_booking_auto_send.py:851-852` reads
`operator_policies.get("pet_policy") == "allowed"` to decide pet
inquiries. Multiple connectors (Track, Guesty, Escapia) coerce
free-text amenity strings into the boolean during import. The boolean
collapses unknown into False at every layer.

The architectural gap here is different from amenities: pet policy
isn't a list with absent items, it's a single statement. The audit's
closed-world commitment doesn't fully apply. What does apply is the
broader principle of distinguishing "no" from "unknown" — a NULL
state separate from `True`/`False` would be more accurate, but that
is data modeling work outside this audit's scope.

### Parking arrangements

**Schema state:** Flat columns, not a collection

`parking_spaces INTEGER` and `parking_instructions TEXT` (migration
`003_create_properties.py`). Both nullable. Same pattern as pet
policy: not a collection, single-valued fields, closed-world
reasoning does not directly apply.

**Reasoning state:** Open-world (by data shape)

Code reads parking fields as direct values
(`prop_row.get("parking_instructions")`, `prop_row.get("parking_spaces")`).
NULL is preserved through retrieval; downstream consumers can
distinguish "operator provided this" from "operator did not."
Reasoning treats absence as absence-of-information rather than
absence-of-feature.

### Included items / included services

**Schema state:** Absent

No grep evidence of these as structured collections in the data
model or service layer. They do not currently exist as first-class
schema entities. Operators may capture this information in narrative
fields or amenities, but there is no structured collection
representation.

**Reasoning state:** No reasoning found

No code path was identified that reasons specifically about included
items as a collection. Any reasoning about what is included happens
indirectly through amenities or narrative content.

The architectural gap for this collection is that it does not exist.
Future work to support closed-world reasoning on "what's included"
would require designing the collection from scratch, including
deciding the granularity (line-by-line items vs. categorized lists
vs. amenity overlap).

## Current state read

The audit reveals four distinct findings, each with different
architectural implications.

**Finding 1: No collection has an exhaustiveness mark.**

Across all in-scope collections, no schema entity carries an
explicit "this collection is exhaustive" or "this collection is
partial" flag. Closed-world reasoning, where it occurs, is implicit
in code rather than backed by data.

**Finding 2: Reasoning behavior is inconsistent by collection.**

The system is not uniformly closed-world or uniformly open-world.
It is inconsistent:

- Amenities: closed-world implicit (booleans collapse uncertainty,
  reasoning treats absence as no)
- House rules: open-world cautious (missing data defers to operator)
- Pet policy: closed-world implicit (boolean collapses uncertainty,
  but field is single-valued so the gap is data-modeling, not
  collection-completeness)
- Parking: open-world (NULL preserved, downstream distinguishes)
- Included items: no representation

The same property-knowledge surface produces different reasoning
guarantees depending on which collection is queried. From an
operator's perspective, this is unpredictable behavior: the system
might confidently claim "no pool" while cautiously deferring on a
house-rules question, with no visible reason for the difference.

**Finding 3: Canonicalization actively destroys uncertainty for
amenities.**

The most consequential gap is in `property_canonical_service.py` and
`PropertyContext`: even if upstream data carried completeness
information (it doesn't today, but it could), the canonicalization
step would flatten it to booleans. The architectural commitment to
distinguish exhaustive from partial collections cannot be enforced
downstream unless the canonical types carry that distinction
through.

**Finding 4: Cross-layer contradiction at the prompt seam.**

`pre_booking_auto_send.py:1310` instructs the agent to behave
open-world ("if not, do not invent it") on data the canonicalization
layer has already coerced into closed-world booleans. The prompt is
trying to compensate for what the data model has lost. This is a
hidden source of brittleness: prompt updates that lose the cautious
guidance would silently regress operator-trust guarantees.

## Gap analysis

The architectural commitment requires three pieces. Their current
state:

**Piece 1: Schema-level exhaustiveness mark.** Absent for every
in-scope collection. The closest existing concept is
`completeness_pct` in the normalization layer, but that is a
data-quality metric for ingested PMS listings, not a per-collection
exhaustiveness flag for operator-provided knowledge.

**Piece 2: Reasoning-layer enforcement.** Inconsistent. Some
collections (house rules, parking) reason cautiously by default;
others (amenities) coerce to closed-world without checking
completeness. No code path checks any completeness flag because no
flag exists.

**Piece 3: Onboarding contract.** Out of scope for this audit, but
the gap is identifiable: there is currently no point in the
operator onboarding flow where the operator is asked "is this list
complete?" for any collection.

## Recommended forward work

The forward work splits into two layers, with sequencing constraints
between them.

### Layer A — Data model

Before reasoning enforcement can work, the data model must carry the
exhaustive/partial distinction:

1. **Decide where the exhaustiveness mark lives.** Options:
   - Per-property metadata table (one row per
     property/collection/exhaustiveness)
   - Embedded in JSONB structure (e.g., `amenities.__exhaustive: true`)
   - Per-collection schema column (e.g., `amenities_exhaustive BOOLEAN`)

   Each has trade-offs. The decision is design work, not audit work.

2. **Preserve uncertainty through canonicalization and context
   projection.** The current pattern (`bool(amenities.get("pool"))`
   collapsing three semantic states into one boolean) discards
   information needed downstream. Canonicalization and
   `PropertyContext` must carry a representation that distinguishes
   "operator said no," "operator never answered," and "source data
   omitted it." Representation TBD; the architectural requirement
   is preserving the distinction, not the specific mechanism.

3. **Define semantics for included items / included services.**
   Separate design question: do these become a structured collection,
   or remain implicit in amenities? If structured, the design
   includes exhaustiveness from the start.

### Layer B — Reasoning enforcement

Once the data model carries exhaustiveness:

4. **Update reasoning sites to check the flag.** Every site that
   currently does `bool(amenities.get(...))` must change to
   distinguish "absent because the list is exhaustive and this isn't
   in it" from "absent because the list is partial and we don't
   know." Specific call-site shape depends on the representation
   chosen in Layer A; the architectural requirement is that
   absence-as-evidence applies only when exhaustiveness is asserted.

5. **Resolve the prompt contradiction.** Prompt-layer guidance like
   the `pre_booking_auto_send.py:1310` "do not invent it" instruction
   becomes secondary safety rather than primary truth-maintenance.
   Primary truth-maintenance moves to the data and reasoning layers.

6. **Audit existing reasoning for accidental closed-world.** Beyond
   the call sites enumerated in this audit, additional places may
   silently rely on amenity coercion. A targeted observability
   pass after data-model changes ship would catch regressions.

### Layer C — Onboarding (out of scope)

7. **Design the operator-acceptance flow.** Separate workstream:
   how does the operator commit to "this list is complete"?
   What's the UX? When does the system prompt for re-confirmation?

These cannot proceed before Layer A. Even if onboarding flow design
were complete, there would be nowhere to store the operator's
acceptance.

### Sequencing summary

```text
Layer A (data model) → Layer B (reasoning) → Layer C (onboarding)
```

Skipping or parallelizing these inverts the dependency graph:
reasoning enforcement against missing schema cannot work; onboarding
acceptance with no storage location is meaningless.

## Open questions

The audit identifies the following questions that this note cannot
resolve:

1. **Should `included_items` exist as a structured collection?**
   Operators may capture this in narrative or amenities today.
   Promoting it to first-class status is a product decision before
   it is a data-model decision.

2. **What is the right granularity for exhaustiveness?**
   Per-collection (the amenity list as a whole is exhaustive)?
   Per-category (kitchen amenities exhaustive, outdoor amenities
   partial)? Per-item (each amenity individually marked)? Different
   choices have different operator burden and different reasoning
   value.

3. **How do existing operator records get migrated?** Beach Habitats
   has property data today. When exhaustiveness flags ship, what is
   the default — exhaustive (operators must opt out) or partial
   (operators must opt in)? Each default has implications for the
   accuracy of historical reasoning.

4. **What happens at the boundary between amenity booleans and the
   JSONB structure?** Migration `003_create_properties.py` defined
   both flat columns (`has_pool`) and the JSONB (`amenities`).
   They duplicate information. Closed-world enforcement must decide
   which is canonical and how the flat columns relate to the JSONB
   in the new model.

5. **Are there reasoning sites this audit missed?**
   The audit covered `app/services/concierge/`,
   `app/services/messaging_brain/`, and adjacent service surfaces.
   It did not exhaustively audit `app/api/`, `app/workers/`, or
   frontend code. Reasoning sites in those surfaces would need
   separate investigation.

## Out of scope

This note does not:

- Make code or schema changes
- Design the implementation of closed-world enforcement
- Specify onboarding flow changes
- Audit Layer 2 or Layer 3 knowledge handling
- Resolve outstanding items from prior audits (intake path
  reconciliation, observability gaps, worker-tier topology)
- Decide which exhaustive collections operators must accept versus
  which are optional
