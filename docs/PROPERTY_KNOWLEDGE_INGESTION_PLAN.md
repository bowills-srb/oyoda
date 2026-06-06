# Property knowledge ingestion: scope and order

**Date:** 2026-05-27
**Status:** scoping note; informs Properties page sequencing
**Related:** Phase 2 Pre-Booking work, Properties page (not yet built)

## What this is

A short note capturing the decision about how property knowledge gets into
the system, what's already built, what's not, and the order we'll build
the missing pieces in. Written so the next session doesn't re-litigate
the scoping.

## The operator-facing goal

Operators need a surface where they can:

1. View their property portfolio and the knowledge associated with each
   property (FAQs, notes, policies, layout info, etc.)
2. Add ad-hoc text knowledge inline ("the hot tub was just serviced",
   "guests should park in the back driveway only")
3. Upload structured documents (guidebooks, manuals, PDFs of property
   info) and have them parsed into groundable knowledge
4. Upload spatial/architectural materials (floor plans, layout diagrams)
   and have them inform answers to spatial questions
   ("which level is each bedroom on", "is the second bathroom near the
   kitchen", "are there outdoor outlets")

These goals share a destination — knowledge the brain can ground on
during pre-booking and in-stay messaging — but the ingestion path for
each is different.

## What we already have

A surprising amount, actually. The audit done during the May 27 UI
planning session surfaced this stack:

- **`knowledge_embeddings` table** with pgvector (384-dim,
  `all-MiniLM-L6-v2`), partitioned by tenant
- **`VectorStore`** for embed / upsert / query
  (`app/services/knowledge/vector_store.py`)
- **`KnowledgeIndexer`** that takes property + local-area data and
  produces embeddings (`app/services/knowledge/knowledge_indexer.py`)
- **`LibrarianAgent`** for retrieval, used by Voice Pod and pre-booking
  grounding (`app/services/knowledge/librarian_agent.py`)
- **`ScopedKnowledgeService`** with per-property knowledge entries —
  scope types, target ids, topic registry, versioning, FAQ structure
  (`app/services/messaging_brain/knowledge/scoped_knowledge_service.py`)
- **`guidebook_ingest_service`** that fetches external guidebooks
  (Breezeway), chunks them, and indexes them as scoped knowledge per
  property
  (`app/services/concierge/guidebook_ingest_service.py`)
- **`/operator/properties/reconcile`** endpoint that takes a portfolio
  declaration and writes through the full stack
  (`app/api/v1/endpoints/operator_properties.py`)

That's the storage layer, the retrieval layer, the per-property scoping
model, the topic taxonomy, the URL-based ingestion path, and the
portfolio reconciliation API. The infrastructure is real and good.

## What's missing

- **File upload endpoint.** Nothing handles "operator drops a PDF on a
  property". No multipart upload route bound to property scope, no file
  storage path (S3 / Supabase storage), no PDF parser invocation. The
  guidebook path goes URL → fetch → ingest, not File → parse → ingest.
- **PDF text extraction in production code.** The `pdf` skill exists in
  `/mnt/skills/public/pdf` but no production code path consumes
  uploaded PDFs and feeds the text into the indexer.
- **Floor plan / architectural drawing handling.** A different beast
  than text PDFs. Floor plans are raster or vector drawings; answering
  "which level is each bedroom on" requires either OCR'd annotations on
  the plan or a vision-model pass that turns the drawing into described
  spatial text. Neither exists today.
- **Properties page UI.** No frontend surface for any of this. The
  operator currently has no place in the dashboard to view what's known
  about their properties or add to it.
- **Ad-hoc note UI.** Backend supports it (`ScopedKnowledgeService`),
  no UI ships an operator-facing entry point.

## Why architectural layouts matter

A real and load-bearing operator pain point: a non-trivial fraction of
pre-booking questions are spatial questions about property layout that
no metadata field will answer well. Examples from a single morning's
Beach Habitats inbox:

- "the stairs and which level each bedroom is on" — Lauren Sheffield
- "outside wall outlets to charge the golf cart" — Natalie Horton
- "where is the second bathroom relative to the kitchen" — (hypothetical
  but common)

These cannot be answered from `property_name`, `address`, `min_nights`,
or even a Breezeway guidebook unless the guidebook has explicit
walk-the-floor language. Architectural layouts are the natural source
for this kind of grounded spatial answer.

## Build order

Strict left-to-right. Each step is shippable in isolation and produces
operator-visible value before the next one starts.

### Step 1 — Properties page v0 (UI on existing backend)

No new backend. Surfaces the portfolio + per-property scoped knowledge
that already exists. Lets the operator:

- See the property list
- Click a property to see its current knowledge entries grouped by topic
- Add a free-form text note that writes to `ScopedKnowledgeService`
- Edit existing entries
- See whether the guidebook has been ingested for the property

Estimated scope: one focused UI session. No backend changes. Verifies
the read-side wiring works against the existing services.

### Step 2 — Properties page v1 (KB gap integration)

Wires the existing `knowledge_gap_recorder` + `kb-gaps` API into the
Properties page so each property shows its outstanding knowledge gaps,
and the operator can answer them inline (the answer becomes a scoped
knowledge entry via the same service used in step 1).

This closes the loop on KB gaps that backend agents already record —
right now they get recorded but operators have no surface to triage
them.

### Step 3 — File upload + PDF text extraction

New backend surface. Endpoint accepts a property-scoped PDF upload,
stores the file (Supabase storage), extracts text via the existing pdf
skill or pypdf, chunks it through the same path the guidebook service
uses, and indexes it as scoped knowledge.

Estimated scope: 2–3 focused sessions because it touches storage,
parsing, and ingestion. UI is a single drop-zone affordance on the
Properties page.

### Step 4 — Architectural layout / vision-model pass

The hardest piece and the one that earns the keep. Takes uploaded floor
plans (raster or PDF), runs a vision model over them to produce a
spatial description in text, indexes that text against the property.

Open questions for this step:

- Which vision model. (Anthropic vision via the existing
  `LLMEmailExtractor`-style pattern is the natural first choice.)
- How to handle multi-floor properties (separate uploads per floor vs.
  one multi-page PDF with floor labels).
- How to validate the model's spatial description before storing
  (operators should approve, not blind-trust).
- Cost per property (one-time at ingest, not per query).

Defer until step 3 is real and operators are actively uploading other
property docs. If text-PDF ingestion turns out to cover most operator
questions, step 4 may never need to ship.

## What this note is not

- A commitment to ship all four steps. Each is justified individually.
- A timeline. Step 1 is the next thing to build after Pre-Booking
  cleanup, not a parallel track.
- A design spec for the Properties page UI. That's still TBD when we
  start step 1.

## Reference

Audit notes were captured in the May 27 chat session that produced this
note. Key files inspected (links by repo-relative path):

- `app/services/knowledge/`
- `app/services/messaging_brain/knowledge/scoped_knowledge_service.py`
- `app/services/concierge/guidebook_ingest_service.py`
- `app/api/v1/endpoints/operator_properties.py`
- `app/api/v1/endpoints/knowledge.py`
