# Capability Inventory — Schema

**Status:** durable schema doc. Governs every inventory pass.
**Created:** 2026-05-28
**Companion:** `CAPABILITY_INVENTORY_PASS_1.md` (the first applied pass), and any subsequent `CAPABILITY_INVENTORY_PASS_N.md` files.
**Authority boundary:** This schema describes how the inventory is structured. It does NOT describe the messaging architecture. For that, read `docs/architecture/MESSAGING_TIER_MAP.md`.

---

## Why this document exists

The codebase has been built ahead of its UI. Capabilities exist on disk — proactive lead-time logic, brain composition paths, compliance rules, knowledge scoping, retention policy, super-admin scope-switching — that no current operator surface fully exposes. Re-deriving these in conversation has been the dominant failure mode of recent design work: we keep proposing things that already exist.

The capability inventory exists to **prevent that re-derivation**. It is a cross-cutting ledger of what's on disk, what state it's in, and how the frontend currently relates to it. Used right, every future surfacing decision starts with "check the inventory" instead of "design from scratch."

What this document is **not**:

- It is not an architecture map. `docs/architecture/MESSAGING_TIER_MAP.md` is the authority on messaging architecture. The inventory cites it via `defers_to`, never duplicates it.
- It is not a prioritization or roadmap. The inventory records status, not what to do first.
- It is not a wishlist. Every row cites file:line evidence; assertions without citations don't belong in the inventory.

---

## The unit: a capability

A **capability** is a backend behavior or data primitive that has a discoverable presence in the codebase. Examples:

- "Proactive lead-time-aware activity planning" (a behavior — now canonically carried by `operator/stay_proactive_service.py`, with older origin recorded separately if relevant)
- "Tenant scope-switching for super-admin" (a behavior — exists in `operator_app.py`)
- "Notification body content on session detail payload" (a data primitive — *does not* exist; would be a `substantive-gap-not-built` row)
- "ESA/service animal compliance rule logic" (a behavior — exists in `platform_compliance.py`)

A capability is the granularity at which a frontend surface might consume something. If it's too small (one function), it probably belongs as a note on a larger row. If it's too big ("the brain"), it should be split.

Each capability gets one row.

---

## Row shape

Every row in the inventory carries these fields. Missing fields are not optional — they're explicit "not yet known" markers (use `—`).

### `capability`
Short, specific name of the behavior or primitive. Avoid jargon that isn't already in the codebase. Examples: "Lead-time-aware activity planning (proactive)", "ESA/service animal compliance rules", "Notification body on session detail payload".

### `domain`
Which high-level area this lives in. The current domain vocabulary (extend deliberately, not casually):

- `messaging` — anything inside `app/services/integrations/`, `app/services/messaging/`, `app/services/messaging_brain/`, `app/services/agents/` (the four tiers from `MESSAGING_TIER_MAP.md`)
- `concierge` — `app/services/concierge/` (knowledge_gap_recorder, message_history, operator_learning, etc.)
- `operator` — `app/services/operator/` (stay_proactive_service, stay_action_agent, message_retention_service, etc.)
- `workers` — `app/workers/` (Celery tasks, schedulers)
- `mcp` — `app/mcp/` (MCP server tools)
- `vault` — `app/services/vault/` (secret management)
- `onboarding` — `app/services/agents/onboarding/` (operator onboarding)
- `frontend` — `app/static/dashboard-v2/` (routes, adapters, components)
- `cross-system` — capabilities that span multiple domains or describe a gap that doesn't live in any one domain (e.g. extraction-before-purge)

### `bucket` — what the thing IS
Five values. The bucket describes the capability's current state on disk. Buckets are stable; they describe reality.

- **`live-on-canonical-path`** — the capability is wired into the live runtime path and is the system's chosen, definitive way of doing this. Each capability has **exactly one** canonical path. If lingering legacy code still exists for the same behavior, that is residue (tracked in `cleanup_residue`), not a parallel valid implementation. Example: `stay_proactive_service` for stay-workflow proactive eligibility.
- **`complete-but-unwired`** — fully implemented code that isn't called by any live runtime path. Surfacing or wiring would activate it. Example: components-route in `dashboard-v2/src/routes/Components/` (design gallery, chrome-less, deliberately excluded from nav).
- **`retired/superseded`** — code that exists on disk but has been intentionally replaced by something else; lighting it up would be regression. Must cite the retirement decision. Example: `kb_gap_manager` (retired per `docs/architecture/LEGACY_RETIREMENT_PLAN.md`).
- **`scaffolded-and-pending`** — code that's stubbed deliberately, often with a throw or a placeholder, awaiting the surface or contract it will serve. Example: `classifyForArrivals` in `windows.ts` (throws on purpose).
- **`substantive-gap-not-built`** — the capability does NOT exist and should. This is the inventory's "real architectural hole" bucket. Example: canonical raw-to-structured extraction pipeline guaranteeing structured signal is captured before raw retention closes.

**One canonical path per capability — a hard rule.** The inventory does not legitimize parallel implementations. If two paths currently cover the same behavior, exactly one is the canonical row (`live-on-canonical-path`); the other is either residue (note it in `cleanup_residue` on the canonical row) or a separate `retired/superseded` row if its retirement is formally documented. Never both as valid alternatives. Drift starts the moment "secondary but still live" becomes an accepted category.

### `action_type` — what to DO about it
Four values. The action describes the recommended next move. Actions can change over time without the bucket changing — that's why these are separate fields.

- **`surface`** — capability exists and isn't fully exposed in the operator UI; the work is rendering/routing/wiring to the frontend. Most `live-on-canonical-path` and `complete-but-unwired` rows have this action.
- **`leave alone`** — capability exists but should not be reactivated, surfaced, or extended. Almost always `retired/superseded`.
- **`build`** — capability doesn't exist and should. Almost always `substantive-gap-not-built`. May also apply to `scaffolded-and-pending` rows where the surface they're waiting for is now being built.
- **`defer`** — capability exists or doesn't, but action is intentionally postponed; trigger conditions are documented elsewhere. Example: operator knowledge migration (deferred per `MESSAGING_TIER_MAP.md` with explicit triggers listed).

The bucket says what the thing IS; the action says what to do next. A `live-on-canonical-path` capability can have action `surface` (UI gap), `leave alone` (no UI needed), or even `defer` (the migration to its long-term home is gated on a trigger). Keep them separate.

### `frontend_status`
How the operator-facing UI (`dashboard-v2`) currently relates to this capability. Five values:

- **`consumed`** — at least one v2 route renders this capability's output as a first-class element.
- **`partially-consumed`** — v2 renders some of the capability's data but throws away meaningful parts (e.g., Today expansion renders some `journey` fields but ignores activities and notifications-body).
- **`exposed-but-unconsumed`** — the API endpoint exists and `api.index.js` exposes it, but no route calls it.
- **`no-endpoint-yet`** — backend capability exists but has no v2 API surface; would need an endpoint before any UI work.
- **`n/a`** — capability isn't UI-relevant (e.g., a worker, a retention job, an internal contract).

### `source_of_truth`
A file:line citation that someone has actually read. Required. Examples:
- `app/services/operator/stay_proactive_service.py:28`
- `app/static/dashboard-v2/src/api/index.js:329`
- `docs/architecture/LEGACY_RETIREMENT_PLAN.md:169`

If multiple files together establish the capability, cite the *primary* one and add the others to `notes`. If the assertion is supported by a doc rather than code (e.g., for retired things), cite the doc.

**The rule:** if you can't cite, you can't claim. No row goes in without a citation that has been verified by file-read.

### `defers_to`
For any capability whose architecture is documented elsewhere, cite the authoritative doc. This is the anti-drift guardrail. Examples:

- A `messaging`-domain capability → `defers_to: docs/architecture/MESSAGING_TIER_MAP.md` (and optionally a section anchor)
- A retired capability → `defers_to: docs/architecture/LEGACY_RETIREMENT_PLAN.md`
- A capability with explicit deferral triggers → cite the doc that lists the triggers

For capabilities with no architectural doc yet, use `—`. (A repeated `—` in this column across a domain is a signal that domain needs an architecture doc.)

### `last_verified`
The ISO date someone read the `source_of_truth` and confirmed the row's assertions are still accurate. Required. A row with no `last_verified` is not in the inventory.

The inventory rots if this isn't maintained. Default expectation: any row older than ~90 days should be re-checked before being cited as authoritative in a build conversation. (Not a hard rule; a soft signal.)

### `upstream_origin`
Optional. If the canonical capability's logic was originally homed in an older location before being absorbed into the canonical path, cite that origin here. This preserves useful historical context ("this idea came from `concierge/proactive/guest_journey.py`") without granting the origin legitimacy as a parallel implementation. Use `—` if not applicable.

The rule: useful logic from old areas should be re-homed into the canonical path, then the old side retired. `upstream_origin` records where the idea came from; `cleanup_residue` records what still needs to be deleted.

### `cleanup_residue`
Optional. If legacy code for this capability still exists on disk and is still being called (e.g., by Celery, MCP, an older endpoint), enumerate the residue here with file:line citations. This is the migration backlog for the capability. Use `—` if none.

Three categories of residue to record:
- **Migration problem:** old code is still being called for the behavior. The call sites must be moved to the canonical path.
- **Deletion problem:** old code is no longer called but still exists. Remove it.
- **Re-home-then-retire problem:** old code has useful logic not yet moved. Absorb into canonical, then retire.

A capability with residue is not in a stable state. The bucket can still be `live-on-canonical-path` if the canonical path is the system's chosen way — but `cleanup_residue` makes the unfinished migration visible.

### `notes`
Optional. A sentence or two for context that doesn't fit the structured fields. Good uses: relationship to other rows, known limitations, secondary citations, trigger conditions for deferral, "watch this" markers.

Bad uses: opinions, recommendations, future-tense speculation. The inventory is descriptive, not prescriptive.

---

## What goes in vs. what stays out

**In:** discoverable capabilities with file:line evidence. Both backend and frontend. Both fully-built and explicitly-gapped (the `substantive-gap-not-built` bucket).

**Out:** anything not citable. Anything in the inventory's *recommendation* column rather than its *status* column (recommendations go in build specs, not the inventory). Architecture explanations that belong in the tier map. Per-feature design rationale that belongs in a design doc.

**Boundary cases:**
- A capability that has competing implementations does NOT get a row per implementation. Per the hard rule above: there is one canonical path. The non-canonical implementation is recorded as `cleanup_residue` on the canonical row, or as a separate `retired/superseded` row if its retirement is formally documented. Never both as parallel rows.
- A capability that crosses domains (e.g., extraction-before-purge spans `operator/`, `concierge/`, and retention) goes in `cross-system` with notes naming the touched domains.
- A capability that's about to change shape from a known commit gets a `notes: pending change per <ref>` and a `last_verified` date that the next reader will see as soon enough to recheck.

---

## Passes and partialness

The inventory is built in **passes**. Each pass covers some domains in depth and leaves others as explicit "Not yet inventoried" sections.

The structure of every pass document:

1. **Header**: pass number, date, domains covered, domains explicitly deferred.
2. **Inventory rows**: organized by domain, all required fields filled.
3. **Not yet inventoried**: section headings for every domain the pass didn't cover, with one line stating *why* (out of scope this pass, awaiting trace, etc.). A reader who scans only this section knows what the inventory is silent about.
4. **Cross-system gaps**: rows for substantive-gap-not-built items that cross domains.
5. **Provenance notes**: which rows are verified by file-read in this pass versus inherited from earlier traces. This is the schema's honesty floor — a row's `last_verified` date should match a real read event, and if a row was carried forward from a previous pass without re-checking, that should be visible.

**Partial coverage is fine. Invisible partial coverage is dangerous.** A pass that covers three domains and explicitly names the rest as "Not yet inventoried" is honest. A pass that covers three domains and looks like it covers ten is misleading.

---

## Anti-patterns

The inventory will rot if it does any of these. Reviewers should reject rows that exhibit them.

1. **Restating the tier map.** If a row's content is "this is in Tier 2 of the messaging map and does X" — that's the tier map's job. The row should carry only additive facts: frontend coupling, surfacing status, retirement flag, gap call-out, residue.
2. **Speculative rows.** "We should probably also build…" — that's a build spec, not an inventory row. The inventory describes what *is*, including the explicit "is-not-yet" case (substantive-gap-not-built), but it doesn't speculate about what might be added.
3. **Citations without reads.** A row's `source_of_truth` must point at a file:line someone has actually opened. Inferring from a name (e.g., "there's probably something called `super_admin.py`") doesn't count. A row whose source can't be pinned to a real read does not belong in the canonical row set; if it must be recorded at all, put it in a clearly separate "unverified leads" appendix, never mixed into the inventory rows.
4. **Bucket/action drift.** If a row's action changes (e.g., "surface" → "defer" because a trigger condition shifted), update the action and bump `last_verified`. Don't change the bucket unless the underlying capability state changed.
5. **Defers-to omission for messaging rows.** Every `messaging`-domain row should have a `defers_to` pointing at the tier map. If it doesn't, the row is either out of scope or is duplicating the map's job.
6. **Comprehensive-looking partial passes.** Every pass must have a visible "Not yet inventoried" section listing the domains it didn't touch. Without that, the pass implies a completeness it doesn't have.
7. **Parallel-implementation rows.** Never inventory two implementations of the same capability as if both were valid. There is one canonical path. Older code covering the same behavior is residue (tracked in `cleanup_residue`) or formally retired (`retired/superseded` with citation), never "secondary but legitimate."
8. **Mixed buckets or actions on one row.** Each row has exactly one `bucket` and one `action_type`. If a capability has live pieces AND a missing unified primitive, that's two rows: one for what exists (canonical or scaffolded), one for the gap (`substantive-gap-not-built`).

---

## Updates and bit-rot

The inventory is a living document. Two update disciplines keep it honest:

**Per-pass updates.** A new pass either adds new rows or refreshes existing ones. When refreshing, `last_verified` gets bumped to the current date *only if* the file was re-read. Bumping `last_verified` without re-reading is a lie.

**Triggered updates.** When a PR meaningfully changes a domain that has inventory rows (refactor, retirement, new capability), the PR should touch the inventory or at minimum flag the affected rows for next-pass re-verification. The lightest-weight version of this is a `notes: changed by <commit-ref>, needs re-verify` marker on the affected rows.

If neither happens, expect the inventory to be 30–60% stale within six months. That's not a failure of the document; it's the rate at which an unmaintained living doc decays. The schema makes the decay *visible* (via `last_verified`) rather than hiding it.

---

## Relationship to other docs

The inventory sits in a specific position in the doc landscape:

- **Architecture docs** (e.g., `MESSAGING_TIER_MAP.md`) — describe *what the system is*. Authoritative on structure. The inventory cites these via `defers_to`.
- **Design specs** (e.g., the journey view spec, the reshape spec) — describe *what we're building*. The inventory may eventually cite a finished spec as the `source_of_truth` for a built capability, but specs aren't the inventory's primary fuel.
- **The inventory** — describes *what currently exists, in what state, with what UI relationship*. Cross-cutting. Doesn't restate either.

A new architectural doc should generally be born in the architecture folder, not in the inventory. The inventory points at it.

---

## Closing

The inventory is an index, not a map. Its discipline is citation-backed status reporting. Its honesty is `last_verified` dates and visible partialness. Its anti-drift guardrail is `defers_to` and the no-restatement-of-the-tier-map rule.

Used right, it makes every future "do we have something for X?" conversation a 30-second lookup instead of a 2-hour rederivation. That's the entire point.
