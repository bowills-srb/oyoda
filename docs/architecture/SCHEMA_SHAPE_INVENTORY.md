# Schema Shape Inventory — Phase 4.3-I.1

Date: 2026-05-18
Status: Initial regression surface for recent schema-dependent phases
Scope: production-shape assertions and JSONB payload conventions

## Why this exists

Recent phases repeatedly had to verify that production schema matched code
expectations:

- Phase 4.3-L surfaced drift in `operator_policies`
- Phase 4.3-L.1 reconciled `market_id` and canonical `tenant_id` usage
- Phase 4.3-M added new `parser_notes` payload conventions
- Phase 4.3-N added reservation-routing metadata and `operator_settings.extra`
  controls
- Phase 4.4 adds `healer_proposals` and proposal-audit parser notes
- Phase 4.4.A adds `knowledge_gap_drafts` for curator review wiring
- Phase 4.4.C relies on `canonical_property_link_reviews` for unified alias review

This document is the inventory the regression scaffold covers first. It is
deliberately incremental rather than exhaustive.

## Covered tables

### `operator_policies`

Used by Phase 4.3-L.1.

Covered columns:
- `tenant_id`
- `operator_id`
- `market_id`
- `upsell_rates`
- `upsell_rates_configured`
- `created_at`
- `updated_at`

Covered indexes:
- `ux_operator_policies_tenant_id`
- `ix_operator_policies_market_id`

### `operator_settings`

Used by Phase 4.3-M and Phase 4.3-N.

Covered columns:
- `tenant_id`
- `extra`

Covered JSONB keys in `extra`:
- `intent_classifier_escalation_threshold`
- `brain_router_confidence_threshold`
- `reservation_aware_routing_window_days_past`
- `reservation_aware_routing_window_days_future`
- `kb_gap_detection_threshold`
- `review_event_policy`

### `message_normalizations`

Used by Phase 4.3-I, 4.3-M, and 4.3-N.

Covered columns:
- base normalization columns from migration `036_message_normalizations`
- composer metadata columns from migration `054_message_normalizations_composer_metadata`
- especially:
  - `source_channel`
  - `source_message_id`
  - `parser_notes`
  - `route_outcome`
  - `draft_source`
  - `composer_source`
  - `composer_response_text`
  - `composer_notes`

Covered indexes:
- `uq_message_norm_source`
- `idx_msg_norm_tenant_sent`
- `idx_msg_norm_tenant_route`
- `idx_msg_norm_property_match`

Covered `parser_notes` payload types:
- `intent_classifier_metadata`
- `brain_classifier_metadata`
- `reservation_routing_metadata`
- `property_mention_surface_audit`
- `healer_proposal_recorded`

### `canonical_property_link_reviews`

Used by Phase 4.4.C unified property-alias review queue.

Covered columns:
- `review_id`
- `tenant_id`
- `canonical_property_code`
- `provider`
- `ref_kind`
- `ref_value`
- `normalized_ref_value`
- `confidence`
- `status`
- `candidate_payload`
- `metadata`
- `created_at`
- `updated_at`

Covered indexes:
- `idx_canonical_property_link_reviews_status`

### `concierge_knowledge_gaps`

Used by operator dashboards and knowledge-gap persistence.

Covered columns:
- `tenant_id`
- `gap_id`
- `property_external_id`
- `question_text`
- `stage`
- `channel`
- `source`
- `detected_intent`
- `confidence_score`
- `resolved`
- `resolution_notes`
- `metadata`
- `created_at`

Covered indexes:
- `ix_concierge_knowledge_gaps_tenant_created`
- `ix_concierge_knowledge_gaps_tenant_resolved`
- `ix_concierge_knowledge_gaps_tenant_property_external`

### `knowledge_gap_drafts`

Used by Phase 4.4.A KnowledgeCurator wiring.

Covered columns:
- `draft_id`
- `tenant_id`
- `property_code`
- `operator_id`
- `question`
- `answer_hint`
- `gap_ids`
- `occurrence_count`
- `status`
- `indexed_doc_id`
- `reviewed_by`
- `reviewed_at`
- `rejection_reason`
- `created_at`

Covered indexes:
- `ix_knowledge_gap_drafts_tenant_status`
- `ix_knowledge_gap_drafts_property_status`

### `pre_booking_inquiries`

Used by current pre-booking save/update paths.

Covered columns:
- `company_id`
- `tenant_id`
- `draft_id`
- `property_external_id`
- `property_external_id_source`
- `intent`
- `confidence`
- `message_text`
- `gmail_thread_id`
- `gmail_message_id`
- `guest_thread_id`
- `archived_at`
- `archive_reason`

Covered indexes:
- `ix_pre_booking_inquiries_tenant_status_created_at`
- `ix_pre_booking_inquiries_tenant_gmail_thread`
- `idx_inquiries_company_status`
- `idx_inquiries_property`
- `idx_inquiries_platform`
- `idx_pre_booking_inquiries_guest_thread`

### `pms_bookings`

Used by Phase 4.3-N reservation-aware routing.

Covered columns:
- `company_id`
- `external_id`
- `status`
- `guest_email`
- `guest_first_name`
- `guest_last_name`
- `check_in`
- `check_out`

Covered indexes:
- `idx_bookings_checkin`
- `idx_pms_bookings_guest_email`
- `idx_pms_bookings_guest_phone`

### `healer_proposals`

Used by Phase 4.4 Healer Agent Session 1.

Covered columns:
- `proposal_id`
- `tenant_id`
- `proposal_kind`
- `signal_source`
- `dedup_key`
- `summary`
- `evidence`
- `proposed_change`
- `status`
- `confidence`
- `cluster_size`
- `created_at`
- `reviewed_at`
- `reviewed_by`
- `review_notes`

Covered indexes:
- `ix_healer_proposals_tenant_status`
- `ux_healer_proposals_pending_dedup`

## Snapshot refresh workflow

Refresh the offline production-shape fixtures after any schema migration that
changes a covered table:

```bash
set -a
source .env
PYTHONPATH=. .venv/bin/python scripts/capture_production_schema_snapshot.py
```

That command writes one JSON file per covered table to:

`tests/fixtures/production_schema_snapshots/`

Commit the updated JSON alongside the migration or corrective schema work so
reviewers can see the exact shape change.

## Adding a new covered surface

1. Add the table name to `COVERED_TABLES` in the snapshot script.
2. Refresh the snapshots.
3. Add explicit assertions to `tests/integration/test_schema_shape_regression.py`.
4. If the table writes JSONB conventions, add typed models to
   `app/services/messaging/parser_notes_schema.py` or the equivalent registry.
