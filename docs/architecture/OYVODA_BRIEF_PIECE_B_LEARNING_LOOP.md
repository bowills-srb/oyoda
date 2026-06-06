# Brief — Piece B: Scope-aware learning loop from operator draft edits

For Claude Code. Build-ready. Read:
- `docs/architecture/OYVODA_MASTER_ROADMAP.md` (knowledge-layer + learning sections)
- `docs/architecture/OYVODA_AUDIT_KNOWLEDGE_INGESTION_LAYER.md`
- `docs/architecture/OYVODA_BRIEF_PIECE_A_SCOPE_AWARE_EDITING.md`

This is the LAST major knowledge/learning brick. Piece A already proved the operator can write
knowledge at property / property_group / tenant scope through the real dashboard path. Piece B
adds the adoption-critical front half: when an operator edits a DRAFT, Oyvoda proposes what to
remember, at what scope, and routes durable knowledge into the existing scoped-knowledge path.

## Grounded findings from the real tree and live DB

These are verified, not assumed:

1. **The blind auto-learn engine is DORMANT, not live — Piece B SUPERSEDES it, does not "stop" it.**
   CORRECTION to an earlier scout pass: the live endpoint
   `app/api/v1/endpoints/operator_prebooking.py` does NOT import or call `operator_learning` /
   `_record_learning_best_effort` (verified by reading the file — approve/edit/reject/regenerate
   handlers contain no learning call). And `app/services/concierge/operator_learning.py` carries an
   explicit header: "preserved for future product surface... NOT currently part of the active brain
   runtime path." And the live DB has 0 `operator_draft_events` rows. So:
   - There is NO live blind durable-write path to disable. Nothing is learning today.
   - `operator_learning.py` is a COMPLETE but DORMANT blind-learning engine: `EditAnalyzer` (diff +
     `EditType` classify), `record_edit` (blind upsert into `operator_learned_preferences`),
     `build_preference_context` (read-side reinjection), platform/operator scope promotion.
   - Piece B builds the PROPOSAL-based engine that supersedes this dormant blind one. The dormant
     engine stays dormant (or gets formally marked superseded) — it is NOT revived and NOT wired.
   - The blind rule it embodies (learn whenever `edit_type != MINOR_POLISH and similarity < 0.95`,
     no scope choice, no one-off, no review) is exactly the philosophy Piece B replaces.

2. **HARVEST the EditAnalyzer / EditType classifier — it is the decomposition Piece B needs.**
   `operator_learning.py`'s `EditAnalyzer.analyze()` already produces the style-vs-fact-vs-oneoff
   split this brief requires:
   - STYLE (route to settings / drop): TONE_SOFTER, TONE_FIRMER, LENGTH_SHORTENED, LENGTH_EXPANDED,
     CTA_CHANGED, MINOR_POLISH
   - DURABLE fact/policy (propose at scope): FACT_ADDED, FACT_CORRECTED, POLICY_CLARIFIED,
     PRICE_ADDED, PRICE_DECLINED
   - ONE-OFF / too-variable (learn nothing): COMPLETE_REWRITE
   REUSE `EditAnalyzer.analyze()` for decomposition. DISCARD `record_edit`'s blind upsert
   (`_upsert_preference`) and `build_preference_context` reinjection. Harvest the classifier, drop
   the auto-write + parallel-store + parallel-reinjection.

3. **The knowledge proposal/review machinery already exists and should be reused.**
   - `app/services/extraction/staging_service.py` is a real scoped proposal pipeline:
     `create_candidate`, `get_pending_candidates`, `approve_candidate`, `reject_candidate`,
     `auto_promote_eligible`.
   - Supports `scope_type in {"property","tenant","property_group"}` (Gap 1 + Piece A).
   - Fact candidates promote into `concierge_scoped_knowledge`; inheritance + provenance proven.
   - Piece B routes durable fact/policy proposals through `extraction_candidates` /
     `ExtractionStagingService`, NOT a second durable-knowledge queue.

4. **ONE knowledge store — do NOT revive `operator_learned_preferences` as a parallel store.**
   The dormant engine wrote durable memory to its OWN tables (`operator_learned_preferences`,
   `platform_intelligence`) and reinjected via `build_preference_context` — a SEPARATE store and a
   SEPARATE read path from `concierge_scoped_knowledge` + `get_effective_knowledge_for_property`.
   Piece B's durable learnings go into `concierge_scoped_knowledge` via staging (Piece A's path),
   read by the SAME inheritance the guest brain already uses. The parallel store + parallel
   reinjection are the second thing discarded. This keeps one knowledge store, not two.

5. **Mechanism-first, not corpus-first.** Beach Habitats has 0 `operator_draft_events` rows. Build
   the mechanism now; real data tunes it later. (Confirms dormancy too — nothing has ever captured.)

6. **Live schema detail that matters:**
   - `operator_draft_events` uses `company_id` (not `tenant_id`). Build against the live shape.
     `operator_draft_events` raw-capture (the `_store_edit_event` shape) MAY be reused as the audit
     log; `operator_learned_preferences` is the dormant store Piece B does NOT extend.

## What Piece B is

When an operator edits and sends a draft:

1. Send still happens immediately.
2. Separately, Oyvoda analyzes the edit diff.
3. It decomposes the edit into one or more candidate learnings.
4. For each candidate, present scope choices:
   - `one_off` -> do not write durable knowledge
   - `property`
   - `property_group` (neighborhood / HOA)
   - `tenant` (portfolio)
5. Approved durable candidates route into the existing scoped-knowledge write path
   through the staging/review pipeline.

This is **not** “auto-learn preferences from every edit.” It is:
- capture edit event
- propose durable memory only when appropriate
- let the operator choose scope
- route through the already-working reviewed knowledge path

## What Piece B is NOT

- NOT a style-learning system. Style remains explicit settings, per roadmap.
- NOT a second durable-knowledge queue separate from `extraction_candidates`.
- NOT synchronous blocking on send. Proposal review is async.
- NOT “analyze historical edits first”; Beach Habitats has no meaningful corpus yet.
- NOT a reason to remove `operator_draft_events`; raw event capture still matters.

## Surface scope: pre-booking edit-learning now; guest-ops is ALSO brain-native (same runtime)

CORRECTED + GROUNDED (verified against the tree): guest-operations was migrated onto the brain.
BOTH operator surfaces generate on `messaging_brain`:
- PRE-BOOKING (email inquiries): drafts via `messaging_brain.pre_booking_retry`.
- GUEST-OPERATIONS (booked / in_stay / post_stay, SMS + mobile chat): inbound ->
  `_run_voice_pod` (mobile_v2) -> `messaging_brain.session_channel_adapter.run_session_channel_
  message` -> `get_messaging_brain_orchestrator().handle_inbound_message(...)`, tagged
  `session_channel_runtime: "messaging_brain"`. The legacy `app/services/knowledge/voice_pod.py`
  now only supplies the `VoicePodResponse` dataclass (a response envelope) — NOT the runtime. The
  name is a leftover; the pathway is brain. (Cleanup nit: rename/retire the VoicePod envelope so
  the legacy name stops implying a legacy runtime — tracked separately, not Piece B.)

So guest-ops is NOT a separate non-brain runtime and there is NO cross-runtime bridge concern.
Both surfaces are brain-native. The ONLY difference is the OPERATOR-INTERACTION MODEL:
- Pre-booking: draft-review-before-send. The operator edits the draft -> that edit is the
  learnable signal. THIS is where edit-decomposition learning applies. Piece B targets it.
- Guest-ops: today the brain replies AUTONOMOUSLY in the webhook cycle (no operator-edit-before-
  send step); human involvement is via ESCALATION. So there is no operator DRAFT EDIT to learn
  from on guest-ops yet — not because of a runtime split, but because the interaction model has no
  edit step.

Implications (operator directive honored: all brain layer, no shim, no legacy reach-in):
1. Piece B's edit-learning is scoped to pre-booking because that's the surface with operator
   draft-editing. This is an interaction-model boundary, NOT a runtime boundary.
2. Build the orchestrator SURFACE-AGNOSTIC: core takes `(original_draft, edited_text, intent,
   property_ref, scope_choice)` and knows nothing about which surface produced the edit. Because
   guest-ops is ALREADY on the brain, wiring this same orchestrator into a future guest-ops
   operator-review step (or any guest-ops edit signal) is a clean in-runtime call — NOT a bridge.
3. Guest-ops also has a native non-edit learning signal: ESCALATION (brain hit something it
   couldn't answer) -> knowledge-gap -> proposed durable answer (existing gap path). That is a
   separate, complementary input to wire later; it flows through the same brain knowledge layer.
4. NO legacy reach-in either way: Piece B writes durable learnings ONLY through
   `messaging_brain/knowledge/scoped_knowledge_service.py` -> `concierge_scoped_knowledge`, and
   replaces the pre-booking endpoint's legacy `_record_learning_best_effort` ->
   `concierge.operator_learning` hook (see integration section). Nothing calls the `concierge/`
   learning layer.

## Required design split: capture vs durable knowledge

Keep these separate:

### A. Raw operator action capture
Still record:
- approved unchanged
- edited and sent
- rejected

This remains the audit / behavior / later-modeling substrate.
`operator_draft_events` survives as the capture log.

### B. Durable knowledge proposals
Only some edits become candidates for memory:
- factual correction
- property fact added
- policy clarified
- pricing rule clarified

These become `extraction_candidates` with explicit scope.

### C. One-off edits
Must be first-class.
If the operator says “this was just for this guest,” nothing durable is written.
This is the main protection the current blind engine lacks.

## Real integration point — replace the legacy learning hook with a brain-layer orchestrator

GROUNDED (verified by reading the full file): `app/api/v1/endpoints/operator_prebooking.py`
DOES call `_record_learning_best_effort(...)` in all three handlers (approve / edit-and-send /
reject). That helper imports `app.services.concierge.operator_learning` (`get_learning_service`
-> record_approval / record_edit / record_rejection). THIS IS THE ONE LEGACY REACH-IN on an
otherwise brain-layer endpoint: draft generation routes through `messaging_brain.pre_booking_
retry` (the brain), but the learning hook reaches sideways into the legacy `concierge/` layer
and its dormant `operator_learned_preferences` store.

Piece B REPLACES those three `_record_learning_best_effort(...)` calls with the brain-layer
orchestrator. The point of replacing them is precisely to REMOVE a brain->legacy call. After
Piece B, the pre-booking action path is fully free of the `concierge/` learning layer (verified:
the learning hook is the ONLY `concierge/`-layer reach-in in this endpoint; everything else is
`messaging_brain.*` / `messaging.*` / `operator.*`).

NO SHIM, NO BRIDGE (operator directive): the new orchestrator and all durable writes live on the
brain layer. Nothing in Piece B may import or call `app.services.concierge.operator_learning` or
any `concierge/`-layer learning/preference store. The dormant `concierge.operator_learning`
engine stays RETIRED — it is neither revived nor bridged. Durable learnings go ONLY through the
brain-native path: `messaging_brain/knowledge/scoped_knowledge_service.py` ->
`concierge_scoped_knowledge` (note: `concierge_scoped_knowledge` is a brain-read TABLE, not the
legacy `concierge/` service layer — the brain's scoped_knowledge_service owns it).

Wire the brain-layer orchestrator into the three handlers (replacing the legacy hook):

- `approve`
  - still capture raw approval event
  - no durable proposal needed

- `reject`
  - still capture raw rejection event
  - optionally create a “needs better handling” non-knowledge signal later, but not in v1

- `edit`
  - capture raw edit event
  - analyze diff
  - if only style/minor polish -> no durable proposal
  - if factual/policy/durable -> create pending knowledge proposal(s)

Important: the send path must stay successful even if proposal creation fails.
Proposal creation is best-effort / async-decoupled from sending.

## Reuse the staging system, don’t bypass it

For durable learnings:
- create `extraction_candidates` of `candidate_type='fact'`
- set:
  - `scope_type` from operator choice
  - `scope_target_id` from chosen property / property_group / tenant
  - `proposed_topic_id` when determinable
  - `proposed_question_text` / `proposed_answer_text`
  - metadata including:
    - `draft_id`
    - `source = operator_draft_edit`
    - original draft
    - final sent text
    - extracted diff evidence
    - selected scope mode

Why this is correct:
- review / approve / reject already exists
- promotion into `concierge_scoped_knowledge` already exists
- verified/provenance semantics already exist
- property_group scope already works end to end

## New Piece-B logic to build

### 1. Edit decomposition layer
Build a deterministic decomposition pass for draft edits that classifies each change as:
- `style_only`
- `fact`
- `policy`
- `pricing_rule`
- `cta_only`
- `unknown`

Do REUSE `EditAnalyzer.analyze()` from operator_learning.py for the classification step (it
already maps an edit to an EditType: style vs fact/policy/pricing vs one-off). Do NOT reuse
`_build_instruction` (the old `EditType -> prompt-instruction` output) — that produced prompt
constraints, not scoped knowledge facts. The decomposition layer = EditAnalyzer's classifier
(harvested) + a new mapping from durable EditTypes to a scoped-knowledge fact (question/answer +
topic + scope), replacing the old instruction-generation.

The decomposition must answer:
- is this durable?
- if durable, what factual/policy statement is being taught?
- what topic does it map to, if any?

Examples:
- “Pool heat is $50/day” -> durable, likely `pricing_rule` / `pool_heat`
- “WaterColor quiet hours are 10pm” -> durable, likely `policy` / `quiet_hours`
- “Thanks so much!” -> style_only, no durable proposal
- “Can’t do early check-in for this guest because cleaners are delayed” -> one_off

### 2. Scope-choice model
For each durable candidate, let the operator choose:
- one-off
- property
- neighborhood (`property_group`)
- portfolio (`tenant`)

Rules:
- if property has no group membership, do not offer `property_group`
- property_group is optional, never fabricated
- the system may suggest a scope, but the operator decides

### 3. Proposal persistence
Persist draft-derived learnings as pending candidates in `extraction_candidates`.

Do NOT auto-promote operator draft edits, even if deterministic.
These are operator-authored proposals and should be explicit/honest in review.

### 4. Review surface
There is backend review machinery already, but no generic operator-facing review surface for
these draft-derived knowledge proposals.

Build the minimum surface needed to review / approve / reject / edit these candidates.
This can be:
- in the Review Drawer flow, or
- a dedicated “what Oyvoda noticed” queue

But it must support:
- candidate text
- evidence from the draft diff
- chosen scope
- approve
- reject
- edit before approval

## Read-side behavior after approval

Once approved, the candidate promotes into scoped knowledge and is inherited normally:
- property
- property_group
- tenant

This means:
- future drafts can benefit via the knowledge system
- future proactive surfacing sees coverage honestly
- Piece A and Piece B share the same durable knowledge substrate

## What to do with `operator_learned_preferences` (the dormant store)

Do not rip it out in this brick, but understand it is DORMANT (nothing writes or reads it on the
live path today — the engine is preserved-but-unwired).

- Do NOT revive it. Piece B does not write to `operator_learned_preferences` and does not wire
  `build_preference_context(...)` back into the brain.
- Durable operator knowledge goes to `concierge_scoped_knowledge` via staging (Piece A's path).
- `operator_draft_events` raw capture may be reused as the audit/behavior log.
- Leave the dormant engine in place (its header already marks it preserved); optionally add a one-
  line note that Piece B supersedes its blind approach. Behavior/trust scoring later can still mine
  `operator_draft_events`.

## Specific implementation guidance

1. Add a new Piece-B service in a brain-aligned location.
   Suggested shape:
   - `app/services/messaging_brain/learning/draft_learning_service.py`

2. The service should expose something like:
   - `record_operator_approval(...)`
   - `record_operator_rejection(...)`
   - `record_operator_edit_and_propose(...)`

3. Internally:
   - write raw `operator_draft_events`
   - for edit path, decompose durable changes
   - create pending `extraction_candidates` for durable items

4. Change `operator_prebooking.py`
   - wire the new service into the approve / edit-and-send / reject handlers (NEW wiring — there is
     no existing `_record_learning_best_effort` call to replace; the endpoint has no learning call today)
   - preserve decoupling from send/reject success

5. REUSE `EditAnalyzer.analyze()` from `operator_learning.py` for edit decomposition (it already
   classifies style vs fact vs one-off via EditType). Do NOT use `OperatorLearningService.
   record_edit()` / `_upsert_preference` (the dormant blind-write path) for durable writes — that is
   the blind behavior being superseded. Harvest the classifier, drop the auto-write.

## Verification

Use the same live-loop discipline that caught the knowledge bugs:

### Scenario A — style-only edit
- Edit tone only
- Send succeeds
- raw `operator_draft_events` row recorded
- NO durable candidate created

### Scenario B — property-scoped durable fact
- Edit adds a property-specific fact
- Send succeeds
- pending candidate created with `scope_type='property'`
- approve candidate
- fact appears in scoped knowledge

### Scenario C — neighborhood-scoped durable policy
- Edit adds an HOA / neighborhood rule for a grouped property
- Send succeeds
- pending candidate created with `scope_type='property_group'`
- approve candidate
- member property inherits it

### Scenario D — one-off
- Edit includes a true one-off exception
- operator chooses one-off
- raw event captured
- no durable knowledge written

## Done when

- Blind auto-learn no longer writes new durable preferences directly from edit send path
- Raw event capture still works for approve / edit / reject
- Durable draft learnings become pending reviewed candidates, not silent writes
- Scope choice includes one-off / property / property_group / tenant
- `property_group` option only appears when real membership exists
- Approved candidates promote through the existing scoped-knowledge path
- Live verification proves:
  - style-only -> no durable write
  - durable property fact -> approved and reused
  - durable neighborhood rule -> approved and inherited
  - one-off -> no durable write

## Why this is now small enough to build

Because the entire substrate underneath it is already real:
- Piece A scope-aware write path
- property_group inheritance
- proactive gap surfacing
- real neighborhood memberships
- staging/review pipeline
- live provenance semantics

Piece B is no longer “build the learning system.”
It is “build a scoped proposal flow on top of a verified knowledge system” — wiring a new
orchestrator into the operator action handlers (there is no live blind helper to replace; the
blind engine is dormant and stays dormant), harvesting the existing edit classifier, and routing
durable proposals through the staging pipeline Piece A already proved.
