## Production Metrics Queries

Phase 4.5 needs retirement evidence, not just green tests. This document is the
canonical measurement companion to the legacy-to-brain migration arc.

Use [phase_4_5_metrics.sql](/Users/dhuntermckenzie/Downloads/oyvoda/scripts/phase_4_5_metrics.sql)
to generate the cross-cutting metrics named in
[PHASE_4_5_LEGACY_TO_BRAIN_BRIEF.md](/Users/dhuntermckenzie/Downloads/oyvoda/PHASE_4_5_LEGACY_TO_BRAIN_BRIEF.md).

### What it measures

1. `deterministic_classifier_rate`

This is the 4.5.A metric. It answers: of the inquiries that produced a
`brain_classifier_metadata` parser-note row, what share resolved in the
deterministic pre-filter instead of escalating to LLM?

Source of truth:
- `message_normalizations.parser_notes`
- note type `brain_classifier_metadata`
- field `classifier_source`

2. `deterministic_draft_rate`

This is the 4.5.D metric. It is intentionally different from classifier rate.
It answers: of all pre-booking inquiries in the window, what share completed in
deterministic draft handlers without entering the LLM draft branch?

Source of truth:
- `pre_booking_inquiries.draft_source`
- deterministic draft-source set:
  - `pricing_grounded_policy`
  - `portfolio_match_grounded`
  - `portfolio_follow_up_required`
  - `verification_required`
  - `fallback_grounded_property_data`
  - `fallback_grounded_faq`
  - `fallback_grounded_guidebook_*`

3. `auto_send_rate`

This is the cross-cutting automation metric. It answers: what share of
pre-booking inquiries were auto-sent vs held for review/hold?

Source of truth:
- `pre_booking_inquiries.send_decision`

4. `correction_rate`

This is the precision signal. It answers: of the inquiries auto-sent by the
pipeline, what share later received an operator correction or rejection?

Source of truth:
- `pre_booking_inquiries.send_decision = 'send_now'`
- `operator_draft_events.event_type IN ('edited', 'rejected')`

5. `quality_score_actioned_only`

This is the healer override quality metric. It currently measures
`intent_classifier_keyword_suggestion` approvals only. It answers: after an
approved keyword override lands, how often did inquiries that actually matched
that override get approved unchanged vs corrected?

Source of truth:
- `healer_proposals`
- `message_normalizations.parser_notes -> brain_classifier_metadata`
- `matched_override_keywords`
- `operator_draft_events`

### Why the override metric needed new plumbing

The original 4.5 brief asked for per-override quality, but the shipped
`brain_classifier_metadata` shape did not say whether an approved override had
actually fired on a later inquiry.

That is now fixed. The parser-note payload includes:
- `matched_terms`
- `matched_override_keywords`
- `resolved_via_override`

Without those fields, "override quality" would have been an approximation. With
them, the metric is tied to the actual override hit path.

### Scope limit

The current override-quality query is intentionally limited to healer-approved
intent keyword overrides.

Property-alias suggestions are approved through the canonical property-link
review path and need separate "alias actually matched later" telemetry before
they can be scored the same way. Do not infer alias quality from this query.

### Runbook

Example for Beach Habitats:

```bash
set -a
source .env
PGURL=${DATABASE_URL/postgresql+asyncpg:/postgresql:}
psql "$PGURL" \
  -v tenant="'e07980b2-a990-4b24-91d1-c8cb71ab70e1'" \
  -v since="'2026-05-01 00:00:00+00'" \
  -f scripts/phase_4_5_metrics.sql
```

Suggested windows:
- retirement gate: last 24-48 hours after enabling a flag
- baseline comparison: last 30 days
- healer quality follow-up: since the approval timestamp

### Retirement use

Use these metrics as the evidence source when updating
[LEGACY_RETIREMENT_PLAN.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/LEGACY_RETIREMENT_PLAN.md).

- 4.5.A deletion gate: `deterministic_classifier_rate >= 0.60` and stable
  production behavior with `BRAIN_INTAKE_PRIMARY` enabled
- 4.5.D deletion gate: deterministic draft-handler rate measured and stable
- healer keyword overrides: `quality_score_actioned_only` stays healthy after
  approval

### Baseline snapshot

Baseline run date: `2026-05-18`

Window used for first baseline:
- tenant: `e07980b2-a990-4b24-91d1-c8cb71ab70e1`
- since: `2026-05-01 00:00:00+00`

Initial expectations for this first run:
- classifier metrics may show zero Brain-path samples if no organic inquiries
  have landed since the 4.5 canary enablement
- auto-send / correction metrics should still produce historical lane data
- override quality may be empty if there are no approved healer keyword
  overrides yet

Observed baseline:
- `inquiry_count = 265`
- `brain_classified_count = 0`
- `deterministic_classifier_count = 0`
- `deterministic_draft_count = 0`
- `auto_sent_count = 0`
- `review_count = 265`
- `hold_count = 0`
- `corrected_count = 0`
- healer keyword override quality rows: `0`

Interpretation:
- the Beach Habitats canary had not yet seen an organic inquiry in the measured
  window at the time of the first run
- the measurement bundle is working, but the retirement gates cannot fire until
  live post-cutover traffic produces Brain-classified samples
