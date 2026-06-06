# Architecture Reconciliation Tracker

Coordination artifact tracking forward-work items identified by
architecture audits. Aggregates recommendations and open questions
from each committed audit so reconciliation work can be sequenced
and progress is visible without re-reading every audit.

## Purpose and use

This document is the index to architecture reconciliation work. The
audits remain the substantive artifacts. This tracker exists to
ensure findings translate into completed work rather than accumulating
as audit debt.

**When items get added:** Whenever an audit identifies a forward-work
recommendation or open question, the item is added here as part of
the same commit (or a follow-up commit) that adds the audit. The
tracker is updated alongside audit artifacts, not separately.

**When items get updated:** Status moves as work happens. When a
session begins addressing an item, status moves to "in progress."
When the work ships, status moves to "completed" with the closing
SHA recorded. When work is deliberately deferred, status moves to
"deferred" with a reason.

**When items get removed:** Items are not removed. Completed items
move to the "Recently completed" section and remain on record. This
preserves audit history.

**Source attribution:** Every item carries the source audit so the
underlying analysis is one click away. If an item's classification
changes, the source audit is the authority — this tracker should
reflect what audits established, not contradict them.

## Status legend

- **Pending** — identified, not started, no blockers known
- **Blocked** — identified, cannot proceed until a dependency resolves
- **In progress** — active work session is addressing this
- **Deferred** — deliberately not being worked on, with a recorded reason
- **Completed** — work has shipped; closing SHA recorded

## Open items

Items aggregated across all current audit artifacts. Grouped by
broad workstream. Within each group, items are sequenced when
dependencies exist.

### Workstream A — Canonical persistence reliability

The most urgent workstream. Issue 3 (canonical persistence outage
identified 2026-05-03) blocks several other items. Resolution
unblocks Path 1 adaptation, makes attribution metrics trustworthy,
and removes risk from any code changes touching the canonical seam.

| ID | Item | Status | Source | Notes |
|----|------|--------|--------|-------|
| A1 | Diagnose root cause of canonical persistence outage from logged exception | Blocked | Diagnostic followup 2026-05-03 | As of 2026-05-04, canonical persistence appears self-healed; no matching errors observed post-`a9b09ef`; normalization rows resumed. Failure may be intermittent. Diagnostic remains open pending recurrence or sustained healthy watch period. **Watch-period rule: if 14 consecutive days pass with zero canonical-persistence error logs and no new attribution gaps in the watch queries, A1 moves to "Deferred — appears self-resolved; no root cause captured; reopen on recurrence." Downstream items unblock on observed stability, not on diagnosis.** D8 audit (`bf944c2`) reinforced A1's priority for parser-provenance visibility: parser audits cannot reach conclusive findings until normalization-row persistence is reliable. |
| A2 | Ship fix for canonical persistence based on diagnosed root cause | Blocked | Diagnostic followup 2026-05-03 | Depends on A1 |
| A3 | Backfill or document partial-attribution period in metrics | Pending | Diagnostic followup 2026-05-03 | Cosmetic; can wait until A2 ships |

### Workstream B — Canonical migration across intake and immediate downstream seams

Originally identified by intake path reconciliation audit; expanded by
downstream uniformity audit. Multiple paths and downstream components
operate on pre-canonical or source-aware contracts. Each requires
disposition.

| ID | Item | Status | Source | Notes |
|----|------|--------|--------|-------|
| B1 | Decide adaptation vs replacement for `_save_inquiry` (Path 1) | Blocked | `8a425df` Path 1 next actions | Blocked on A2 (do not adapt against unreliable seam) |
| B2 | Migrate `PreBookingInquiryInput` upstream of `_save_inquiry` | Blocked | `8a425df` Path 1 next actions | Blocked on B1 (sequencing) |
| B3 | Preserve attribution semantics through any Path 1 adaptation | Blocked | `8a425df` Path 1 next actions | Sequenced with B1/B2 |
| B4 | Resolve worker-tier topology to determine Path 2 activity | Pending | `8a425df` Path 2 next actions | Independent of A1; surfaced in `cf868ea` topology snapshot |
| B5 | Verify Path 2 (`_save_draft`) inbound activity at runtime | Blocked | `8a425df` Path 2 next actions | Blocked on B4 |
| B6 | Decide Path 2 disposition (adapt / retire / keep per-operator) | Blocked | `8a425df` Path 2 next actions | Blocked on B5 |
| B7 | Re-run `_save_draft` call-site trace before `ON CONFLICT` patch ships | Pending | `2ecd629` §7.1 | Mandatory pre-implementation re-check: confirm no new callers of `_save_draft` have appeared with refresh intent. Cheap (`rg -n "_save_draft\\(" app/ --glob "*.py"`) but load-bearing — if new refresh-intent callers exist, the B7 decision re-opens before implementation proceeds |
| B13 | Implement `ON CONFLICT DO NOTHING` convention in Path 2 (`_save_draft`) | Blocked | `2ecd629` §8 | Former B7.b follow-on. ~5-line patch changing Path 2's `ON CONFLICT (thread_id, message_id) DO UPDATE SET ...` to `DO NOTHING`. Should ship in its own commit. Blocked on B7's §7.1 re-trace |
| B14 | Codebase sweep for `DO UPDATE SET.*status` and similar conflict-mutation patterns | Pending | `2ecd629` §8 | Former B7.c follow-on. Brief audit: grep for other writers that mutate row state via `ON CONFLICT DO UPDATE`. Independent of B13 and can run in parallel; may surface additional safety concerns of the same shape |
| B8 | Migrate Path 3 (`_save_fallback_pre_booking_inquiry`) to canonical interface | Blocked | `8a425df` Path 3 next actions | Blocked on B1 (must come after primary path is stable) |
| B9 | Audit Path 3 fallback trigger frequency over time | Pending | `8a425df` Path 3 notes | Already verified zero in current data; revisit periodically |
| B10 | Migrate routing surfaces to consume canonical messages | Blocked | `eb13f1f` Priority 2 item 4 | Blocked on A2 (canonical seam reliability); independent of brain-path safety items |
| B11 | Decide legacy `pre_booking_auto_send` orchestration disposition (retire vs canonical migration) | Pending | `eb13f1f` Priority 2 item 5 | Architectural decision; informs G1-G4 sequencing |
| B12 | Resolve queue read model legacy fields (e.g. `platform`) | Pending | `eb13f1f` Priority 2 item 6 | Small consistency item; can proceed independently |

### Workstream C — Closed-world reasoning enforcement

Identified by closed-world reasoning audit. Three layers of work:
data model, reasoning sites, onboarding. Strict sequencing.

| ID | Item | Status | Source | Notes |
|----|------|--------|--------|-------|
| C1 | Decide where exhaustiveness mark lives (per-property, JSONB-embedded, or per-collection column) | Pending | `b506a60` Layer A item 1 | Design decision; no dependency |
| C2 | Add schema for amenity exhaustiveness | Blocked | `b506a60` Layer A item 1 | Blocked on C1 (need design); secondary block on A2 (writes flow through canonical seam) |
| C3 | Preserve uncertainty through canonicalization and `PropertyContext` projection | Blocked | `b506a60` Layer A item 2 | Blocked on C2 |
| C4 | Define semantics for included items / included services as a structured collection | Pending | `b506a60` Layer A item 3 | Independent design question |
| C5 | Update reasoning sites to check exhaustiveness flag | Blocked | `b506a60` Layer B item 4 | Blocked on C2/C3 |
| C6 | Resolve prompt-layer contradiction (`pre_booking_auto_send.py:1310`) | Blocked | `b506a60` Layer B item 5 | Blocked on C5 (data must lead, prompt follows) |
| C7 | Audit existing reasoning for accidental closed-world beyond enumerated sites | Blocked | `b506a60` Layer B item 6 | Blocked on C5 (regression check after primary work) |
| C8 | Resolve `has_pool` flat-column vs `amenities` JSONB duplication | Pending | `b506a60` Open Question 4 | Surfaces during C2 design; should be decided then |
| C9 | Determine exhaustiveness migration default for existing operators | Pending | `b506a60` Open Question 3 | Surfaces during C2 design |
| C10 | Design onboarding contract for closed-world acceptance | Blocked | `b506a60` Layer C | Blocked on C2 (no storage for acceptance otherwise) |

### Workstream D — Architecture gaps not yet audited

The architecture doc named several gaps that haven't been audited
yet. Each is a candidate for a Phase 1b session.

| ID | Item | Status | Source | Notes |
|----|------|--------|--------|-------|
| D1 | Phase 1b audit of hierarchical property data model | Pending | `9ad2dc5` Section 8 | Logical successor to closed-world audit |
| D2 | Phase 1b audit of generate-and-check pattern enforcement | Pending | `9ad2dc5` Section 8 | Adversarial review consistency. Partially addressed by `eb13f1f` Finding 2 — narrower follow-up may suffice |
| D3 | Phase 1b audit of downstream uniformity (consumer side) | Completed | `9ad2dc5` Section 8 | Closed by `eb13f1f` |
| D4 | Phase 1b audit of objective vs subjective question handling | Pending | `9ad2dc5` Section 8 | Less concrete; may need design framing first. Not addressed by recent audits |
| D5 | Phase 1b audit of Layer 2 / Layer 3 knowledge integration | Pending | `9ad2dc5` Section 8 | Larger scope; Google Places + lat/long + events |
| D6 | Design the learning loop subsystem | Pending | `9ad2dc5` Section 8 | Largest remaining gap; design-heavy work |
| D7 | Design the Oyvoda intelligence layer aggregation infrastructure | Pending | `9ad2dc5` Section 8 | Greenfield; dependencies on D6 |
| D9 | Investigate `pre_booking_transport_adapter` parser surface | Pending | `bf944c2` Finding 5 | Third parser surface surfaced by D8. Role, scope, and relationship to OTA parser and generic parser unknown. Small follow-on audit shape, similar to D8 but smaller. |

### Workstream E — Operational and infrastructure

Items not directly architecture-shaped but affecting architectural
work.

| ID | Item | Status | Source | Notes |
|----|------|--------|--------|-------|
| E1 | Worker tier topology investigation and remediation | Pending | `cf868ea` topology snapshot | Blocks B4-B6; potentially affects D6 (learning loop background processing) |
| E2 | Channel convention mismatch resolution (`'email'` vs `'gmail'`) | Pending | Diagnostic followup 2026-05-03 Issue 4 | Independent small fix |
| E3 | Watch window evaluation when threshold reached (50 brain drafts or 7 days) | Pending | Session 14 rollout doc | Triggered by traffic; passive accumulation |
| E5 | Audit observability for additional reasoning surfaces (`app/api/`, `app/workers/`, frontend) | Pending | `b506a60` Open Question 5 / `eb13f1f` Open Question 5 | Companion check after C5; reinforced by downstream uniformity audit's parallel finding |

### Workstream F — Operator engagement

Not strictly audit-driven, but materially informs prioritization of
several other items.

| ID | Item | Status | Source | Notes |
|----|------|--------|--------|-------|
| F1 | Beach Habitats operator check-in conversation | Pending | Operational backlog | Validates whether audit-identified gaps match operator-felt gaps |
| F2 | Confirm Beach Habitats operator dashboard access | Pending | Operational backlog | Stated as needed in initial rollout brief |

### Workstream G — Safety control symmetry

Identified by downstream uniformity audit. The newer brain path
produces drafts without the adversarial review and policy enforcement
that exist on the legacy concierge path. As of 2026-05-04, brain-path
exposure is limited (7 of 266 inquiries in last 30 days, concentrated
on 2026-05-03) but real and live. This workstream addresses the
asymmetry as a distinct concern from ordinary canonical migration.

| ID | Item | Status | Source | Notes |
|----|------|--------|--------|-------|
| G1 | Verify adapter shape for brain-path adversarial review wiring before Option A implementation | Pending | `c45a0e6` §6.7 | Confirm legacy reviewer can accept brain output via small structural adaptation; if not, split G1/G2 into independent implementation tracks |
| G2 | Verify adapter shape for brain-path policy enforcement wiring before Option A implementation | Pending | `c45a0e6` §6.7 | Confirm legacy policy checker can accept brain output via small structural adaptation; may remain bundled with G1 if adapter shape is genuinely parallel |
| G3 | Implement near-term Option A wiring for brain-path adversarial review | Blocked | `c45a0e6` §5 | Blocked on G1 adapter-shape verification |
| G4 | Implement near-term Option A wiring for brain-path policy enforcement | Blocked | `c45a0e6` §5 | Blocked on G2 adapter-shape verification |
| G5 | Architectural decision — is property identity a permitted exception? | Pending | `eb13f1f` Priority 3 / Open Question 1 | Independent of G1-G4; resolves whether property resolution's source-aware classification is debt or documented exception |
| G6 | Implement canonical-typed review and policy modules | Deferred | `c45a0e6` §6.6 | Long-term target after Option A near-term wiring. Required tracker item to preserve Option B as an explicit follow-on rather than an implicit someday intention |

### Workstream H — Pipeline coordination follow-ups

Identified by the 2026-05-03 coordination observations and reframed by
the 2026-05-04 addendum. These items are about channel-specific reply
mechanics, thin-grounding behavior, mixed intake streams, and
deployment seams rather than pure canonical migration.

| ID | Item | Status | Source | Notes |
|----|------|--------|--------|-------|
| H1 | Characterize thin-grounding draft behavior independent of hold-draft heuristic firing | Pending | `docs/PIPELINE_COORDINATION_ADDENDUM_2026_05_04.md` Workstream 1 | Reframes former §6.1/§6.4 question. Jackie Lee case is motivating example, but the target is broader: when grounding is thin, what does the model output and what actually constrains it? |
| H2 | Verify Airbnb reply-channel mechanics and `reply.airbnb.com` behavior for pre-booking threads | Pending | `docs/PIPELINE_COORDINATION_ADDENDUM_2026_05_04.md` Workstream 2 | Includes `_adapt_ota_inquiry` reply-target behavior and whether `_is_platform_automation_email` suppresses valid Airbnb reply targets |
| H3 | Add near-term intake hygiene for known non-guest senders, including operator-owned domains | Pending | `docs/PIPELINE_COORDINATION_ADDENDUM_2026_05_04.md` Workstream 3 | Cheap additive filter/blocklist step. Explicitly includes operator-domain traffic, which currently risks being treated as guest traffic |
| H4 | Design channel-aware thread-state handling where reply visibility differs by platform | Pending | `docs/PIPELINE_COORDINATION_ADDENDUM_2026_05_04.md` Workstream 4 | Depends partly on H2; especially important if Airbnb replies do not reliably surface through Gmail |
| H5 | Re-run hold-rate analysis with channel-aware filtering instead of using generic parser as failure proxy | Pending | `docs/PIPELINE_COORDINATION_ADDENDUM_2026_05_04.md` Workstream 5 | Scheduled for 2026-05-11 per addendum; direct-channel guest traffic makes `generic_gmail_parser` an unsafe standalone failure indicator |
| H6 | Add deployment guardrails for multi-service seams (`oyvoda` vs `oyvoda-worker`) | Pending | `docs/PIPELINE_COORDINATION_ADDENDUM_2026_05_04.md` Workstream 6 | Prompted by stale worker code after read-state fix shipped to app tier only |

## Dependencies and sequencing

Cross-workstream dependencies that constrain ordering:

```
A1 → A2 → unblocks B1, B10, C2 (canonical seam reliability)
                ↓
              B1 → B2, B3, B8 (Path 1 adaptation cascade)
              B10 (routing canonicalization)
              C2 → C3 → C5 → C6, C7, C10 (closed-world cascade)

B4 → B5 → B6 (Path 2 disposition cascade)

B11 → informs G1, G2 (legacy orchestration disposition affects the
                       tradeoff between "wire brain to legacy
                       reviewer" vs "promote reviewer to canonical";
                       soft dependency, not a blocker)

G1 → G3 (adversarial review disposition)
G2 → G4 (policy enforcement disposition)

C1 + C8 + C9 → C2 (design decisions feed schema)

E1 → B4 (worker tier blocks Path 2 verification)
```

What this implies for "what's next":

- **Items that can proceed independently right now** (no blockers):
  A3, B4, B7, B9, B11, B12, C1, C4, C8, C9, D1, D2, D4, D5, D6, D7,
  D9, E1, E2, E5, F1, F2, G1, G2, G5, H1, H2, H3, H5, H6
- **Items waiting on Issue 3 (A1+A2)**: B1, B2, B3, B8, B10, C2 (and
  cascading C3, C5, C6, C7, C10)
- **Items waiting on worker tier (E1)**: B4 chain (B5, B6)
- **Items waiting on G1/G2 decisions**: G3, G4
- **Items requiring design work before implementation**: C1, C4, C8,
  C9, B11, G1, G2, G5

The biggest unblocker right now is Issue 3 resolution (A1/A2). Until
the next exception fires and we diagnose, several workstreams are
stalled. While waiting, items in Workstream D, design items in
Workstreams C and G, and items in B/E/F can proceed.

## Recently completed

Items closed by audits and patches shipped through 2026-05-04.

| ID | Item | Closing SHA | Source |
|----|------|-------------|--------|
| — | Define messaging architecture commitments | `9ad2dc5` | Architecture doc itself |
| — | Audit intake paths against canonical contract | `8a425df` | Phase 1b audit |
| — | Audit closed-world reasoning state | `b506a60` | Phase 1b audit |
| — | Audit downstream uniformity (consumer side) | `eb13f1f` | Phase 1b audit |
| — | Improve canonical persistence layer observability | `a9b09ef` | Diagnostic followup patch |
| — | Improve inquiry persistence exception path observability | `c7f463f` | Within-writer audit follow-up |
| — | Safety control decision draft (G1/G2) | `91eff2c` | Decision draft; G1/G2 remain Pending until confirmation |
| — | Investigate Airbnb parser fallback-to-generic rate and coverage gap | `bf944c2` | Phase 1b audit; deeper Airbnb investigation deferred per audit's forward-work item 1 |
| — | `ON CONFLICT` divergence reconciliation (B7 audit) | `20b4e6e` | Reconciliation note documenting Path 1 (DO NOTHING) vs Path 2 (DO UPDATE) divergence and operator-state safety concern; recommendation to converge both paths on DO NOTHING; implementation deferred pending B7 confirmation |
| — | Confirm safety control decision (G1/G2) | `c45a0e6` | Confirms near-term Option A wiring, long-term Option B target, and requires §6.6 tracker item plus §6.7 adapter-shape verification before implementation |
| — | Confirm `ON CONFLICT` divergence decision (B7) | `2ecd629` | Confirms both paths use `DO NOTHING`; supersedes reconciliation note `20b4e6e` with call-site trace findings. §7.1 requires re-running the trace before implementation; former B7.c sweep is independent and parallel-runnable |
| — | Decide disposition of `docs/CHANNEL_ARCHITECTURE_QUESTIONS.md` | (no SHA) | Resolved at worktree level on 2026-05-04; file was never tracked, removed from local filesystem |
| — | Record pipeline coordination addendum and next-session resume | (workspace) | Adds corrected framing for §§3.2/5/6.x, captures new intake and Airbnb findings, and materializes the referenced 2026-05-05 resume artifact |

## How updates happen

The tracker is updated when:

1. A new audit lands. Forward-work items from the audit get added
   to the appropriate workstream section. Update happens in the same
   commit as the audit, or a follow-up commit referenced by the
   audit's commit message.

2. A reconciliation session ships work. The relevant items move to
   "Recently completed" with closing SHA. Updates happen in the same
   commit as the reconciliation work or a follow-up commit.

3. A blocking dependency resolves. Items previously blocked move to
   "Pending." Update happens when the unblocking work ships.

4. A status changes deliberately. Items moving to "Deferred" record
   the reason. Items moving to "In progress" can do so in the
   tracker before work begins, signaling to anyone reading that this
   item is actively being addressed.

The discipline: the tracker reflects current reality. It is not a
plan; it is a status board. If the tracker disagrees with the
codebase or the audits, the codebase and audits are authoritative —
the tracker gets corrected.

## Out of scope

This document does not:

- Re-classify findings from source audits (they remain authoritative)
- Add new architectural analysis (this is aggregation only)
- Set deadlines or milestones (sequencing is dependency-driven, not
  time-driven)
- Manage non-architecture work (operator conversations, infrastructure
  outside the message-processing surface, product roadmap items)
- Replace the architecture doc as the target-state reference
