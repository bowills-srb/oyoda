-- Post-cutover verification bundle for pre-booking brain rollouts.
--
-- This file is for the moment of cutover:
--   1. pre_booking_inquiries since cutover
--   2. message_normalizations since cutover
--   3. rich_context_shadow_observations since cutover
--   4. cross-table verification for the same inquiry
--
-- Relationship to scripts/prebooking_review_metrics.sql:
--   - this file answers "is the rollout live yet?"
--   - the metrics file answers "how is the rollout performing over time?"
--
-- See:
--   docs/MESSAGING_BRAIN_PREBOOKING_BEACH_HABITATS_ROLLOUT.md
--
-- Parameters:
--   :tenant   -> operator/company UUID, quoted by psql substitution
--   :cutover  -> rollout enablement timestamp, quoted by psql substitution
--
-- Example:
--   psql "$DATABASE_URL" \
--     -v tenant="'e07980b2-a990-4b24-91d1-c8cb71ab70e1'" \
--     -v cutover="'2026-05-02 20:11:03+00'" \
--     -f scripts/prebooking_cutover_verification.sql
--
-- Note: -v values must be SQL-quoted. Keep the inner single quotes.
--
-- Canonical joins on this lane:
--   message_normalizations:
--     tenant_id + source_channel = 'email' + source_message_id = pbi.gmail_message_id
--   rich_context_shadow_observations:
--     tenant_id (text) + message_id = pbi.message_id
--
-- Pre-booking inquiries arrive through the email dispatch path, which
-- normalizes them under source_channel = 'email' even when the mailbox
-- provider is Gmail. Despite the column name,
-- pre_booking_inquiries.gmail_message_id is the canonical inbound email
-- message id used for attribution on this lane.

\echo
\echo '=== Q1: pre_booking_inquiries since cutover ==='
SELECT
    draft_id,
    message_id,
    gmail_message_id,
    status,
    received_at,
    intent
FROM pre_booking_inquiries
WHERE company_id = CAST(:tenant AS uuid)
  AND received_at >= CAST(:cutover AS timestamptz)
ORDER BY received_at;

\echo
\echo '=== Q2: message_normalizations since cutover ==='
SELECT
    source_message_id,
    source_channel,
    draft_source,
    route_outcome,
    sent_at
FROM message_normalizations
WHERE tenant_id = CAST(:tenant AS uuid)
  AND source_channel = 'email'
  AND sent_at >= CAST(:cutover AS timestamptz)
ORDER BY sent_at;

\echo
\echo '=== Q3: rich_context_shadow_observations since cutover ==='
SELECT
    tenant_id,
    message_id,
    property_code,
    intent,
    recorded_at
FROM rich_context_shadow_observations
WHERE tenant_id = :tenant
  AND recorded_at >= CAST(:cutover AS timestamptz)
ORDER BY recorded_at;

-- Success signal:
--   draft_source = 'messaging_brain'
--   AND shadow_observation_present = 'yes'
--
-- Fallback signal:
--   draft_source = 'model'
--   AND shadow_observation_present = 'no'
\echo
\echo '=== Q4: cross-table cutover verification ==='
SELECT
    pbi.draft_id,
    pbi.message_id,
    pbi.gmail_message_id,
    pbi.received_at,
    pbi.status,
    mn.draft_source,
    mn.route_outcome,
    CASE WHEN rcso.id IS NOT NULL THEN 'yes' ELSE 'no' END AS shadow_observation_present,
    rcso.recorded_at AS shadow_recorded_at
FROM pre_booking_inquiries pbi
LEFT JOIN message_normalizations mn
  ON mn.tenant_id = pbi.company_id
 AND mn.source_channel = 'email'
 AND mn.source_message_id = pbi.gmail_message_id
LEFT JOIN rich_context_shadow_observations rcso
  ON rcso.tenant_id = CAST(pbi.company_id AS text)
 AND rcso.message_id = pbi.message_id
WHERE pbi.company_id = CAST(:tenant AS uuid)
  AND pbi.received_at >= CAST(:cutover AS timestamptz)
ORDER BY pbi.received_at;
