-- Pre-booking review-mode metrics for Session 14 rollouts.
--
-- This file contains:
--   1. Approval rate
--   2. Edit rate and edit magnitude
--   3. Rejection rate
--   4. Time to decision
--   5. Brain-branch failure-rate note (log-derived, not SQL-derived)
--   6. Attribution coverage diagnostic
--
-- Parameters:
--   :company_id  -> operator/company UUID, quoted by psql substitution
--   :since       -> lower bound timestamp, quoted by psql substitution
--
-- Example:
--   psql "$DATABASE_URL" \
--     -v company_id="'e07980b2-a990-4b24-91d1-c8cb71ab70e1'" \
--     -v since="'2026-05-02 00:00:00+00'" \
--     -f scripts/prebooking_review_metrics.sql
--
-- Note: -v values must be SQL-quoted. Keep the inner single quotes
-- around the UUID and timestamp or the casts below will fail.
--
-- Canonical attribution join:
--   pre_booking_inquiries pbi
--   LEFT JOIN message_normalizations mn
--     ON mn.tenant_id = CAST(:company_id AS uuid)
--    AND mn.source_channel = 'email'
--    AND mn.source_message_id = pbi.gmail_message_id
--
-- Pre-booking inquiries arrive through the email dispatch path, which
-- normalizes them under source_channel = 'email' even when the mailbox
-- provider is Gmail.
-- Despite the column name, pre_booking_inquiries.gmail_message_id is the
-- canonical inbound email message id used for attribution on this lane.
--
-- Source labels used in the queries below:
--   brain  = mn.draft_source = 'messaging_brain'
--   legacy = mn.draft_source = 'model'

-- =====================================================================
-- Metric 1: Approval rate
-- What it measures:
--   Share of operator actions that were approved unchanged.
-- Source of truth:
--   operator_draft_events.event_type = 'approved_unchanged'
--   joined to pre_booking_inquiries and message_normalizations.
-- =====================================================================
\echo
\echo '=== Metric 1: Approval rate (brain vs legacy) ==='
WITH classified AS (
    SELECT
        pbi.draft_id,
        ode.event_type,
        CASE
            WHEN mn.draft_source = 'messaging_brain' THEN 'brain'
            WHEN mn.draft_source = 'model' THEN 'legacy'
            ELSE 'other'
        END AS draft_origin
    FROM pre_booking_inquiries pbi
    JOIN operator_draft_events ode
      ON ode.company_id = pbi.company_id
     AND ode.draft_id = pbi.draft_id
    LEFT JOIN message_normalizations mn
      ON mn.tenant_id = CAST(:company_id AS uuid)
     AND mn.source_channel = 'email'
     AND mn.source_message_id = pbi.gmail_message_id
    WHERE pbi.company_id = CAST(:company_id AS uuid)
      AND pbi.received_at >= CAST(:since AS timestamptz)
      AND ode.event_type IN ('approved_unchanged', 'edited', 'rejected')
)
SELECT
    draft_origin,
    COUNT(*) FILTER (WHERE event_type = 'approved_unchanged') AS approved_unchanged_count,
    COUNT(*) FILTER (WHERE event_type IN ('approved_unchanged', 'edited', 'rejected')) AS total_actioned_count,
    ROUND(
        COUNT(*) FILTER (WHERE event_type = 'approved_unchanged')::numeric
        / NULLIF(COUNT(*) FILTER (WHERE event_type IN ('approved_unchanged', 'edited', 'rejected')), 0),
        4
    ) AS approval_rate
FROM classified
WHERE draft_origin IN ('brain', 'legacy')
GROUP BY draft_origin
ORDER BY draft_origin;

-- =====================================================================
-- Metric 2: Edit rate and edit magnitude
-- What it measures:
--   How often operators edit drafts, and how large those edits are.
-- Source of truth:
--   operator_draft_events preserves original_draft, edited_text, and
--   similarity_score even though pre_booking_inquiries overwrites
--   draft_text on edit.
-- =====================================================================
\echo
\echo '=== Metric 2: Edit rate and edit magnitude (brain vs legacy) ==='
WITH classified AS (
    SELECT
        pbi.draft_id,
        ode.event_type,
        ode.original_draft,
        ode.edited_text,
        ode.similarity_score,
        CASE
            WHEN mn.draft_source = 'messaging_brain' THEN 'brain'
            WHEN mn.draft_source = 'model' THEN 'legacy'
            ELSE 'other'
        END AS draft_origin
    FROM pre_booking_inquiries pbi
    JOIN operator_draft_events ode
      ON ode.company_id = pbi.company_id
     AND ode.draft_id = pbi.draft_id
    LEFT JOIN message_normalizations mn
      ON mn.tenant_id = CAST(:company_id AS uuid)
     AND mn.source_channel = 'email'
     AND mn.source_message_id = pbi.gmail_message_id
    WHERE pbi.company_id = CAST(:company_id AS uuid)
      AND pbi.received_at >= CAST(:since AS timestamptz)
      AND ode.event_type IN ('approved_unchanged', 'edited', 'rejected')
)
SELECT
    draft_origin,
    COUNT(*) FILTER (WHERE event_type = 'edited') AS edited_count,
    COUNT(*) FILTER (WHERE event_type IN ('approved_unchanged', 'edited', 'rejected')) AS total_actioned_count,
    ROUND(
        COUNT(*) FILTER (WHERE event_type = 'edited')::numeric
        / NULLIF(COUNT(*) FILTER (WHERE event_type IN ('approved_unchanged', 'edited', 'rejected')), 0),
        4
    ) AS edit_rate,
    ROUND(AVG(similarity_score) FILTER (WHERE event_type = 'edited'), 4) AS avg_similarity_score,
    ROUND(
        AVG(ABS(LENGTH(COALESCE(edited_text, '')) - LENGTH(COALESCE(original_draft, '')))) FILTER (WHERE event_type = 'edited'),
        2
    ) AS avg_abs_char_delta,
    ROUND(
        AVG(LENGTH(COALESCE(edited_text, '')) - LENGTH(COALESCE(original_draft, ''))) FILTER (WHERE event_type = 'edited'),
        2
    ) AS avg_signed_char_delta
FROM classified
WHERE draft_origin IN ('brain', 'legacy')
GROUP BY draft_origin
ORDER BY draft_origin;

-- =====================================================================
-- Metric 3: Rejection rate
-- What it measures:
--   Share of operator actions that ended in rejection.
-- Source of truth:
--   operator_draft_events.event_type = 'rejected'
--   joined to pre_booking_inquiries and message_normalizations.
-- =====================================================================
\echo
\echo '=== Metric 3: Rejection rate (brain vs legacy) ==='
WITH classified AS (
    SELECT
        pbi.draft_id,
        ode.event_type,
        CASE
            WHEN mn.draft_source = 'messaging_brain' THEN 'brain'
            WHEN mn.draft_source = 'model' THEN 'legacy'
            ELSE 'other'
        END AS draft_origin
    FROM pre_booking_inquiries pbi
    JOIN operator_draft_events ode
      ON ode.company_id = pbi.company_id
     AND ode.draft_id = pbi.draft_id
    LEFT JOIN message_normalizations mn
      ON mn.tenant_id = CAST(:company_id AS uuid)
     AND mn.source_channel = 'email'
     AND mn.source_message_id = pbi.gmail_message_id
    WHERE pbi.company_id = CAST(:company_id AS uuid)
      AND pbi.received_at >= CAST(:since AS timestamptz)
      AND ode.event_type IN ('approved_unchanged', 'edited', 'rejected')
)
SELECT
    draft_origin,
    COUNT(*) FILTER (WHERE event_type = 'rejected') AS rejected_count,
    COUNT(*) FILTER (WHERE event_type IN ('approved_unchanged', 'edited', 'rejected')) AS total_actioned_count,
    ROUND(
        COUNT(*) FILTER (WHERE event_type = 'rejected')::numeric
        / NULLIF(COUNT(*) FILTER (WHERE event_type IN ('approved_unchanged', 'edited', 'rejected')), 0),
        4
    ) AS rejection_rate
FROM classified
WHERE draft_origin IN ('brain', 'legacy')
GROUP BY draft_origin
ORDER BY draft_origin;

-- =====================================================================
-- Metric 4: Time to decision
-- What it measures:
--   Elapsed minutes from inquiry receipt to operator action.
-- Source of truth:
--   operator_draft_events.created_at is the action timestamp.
-- =====================================================================
\echo
\echo '=== Metric 4: Time to decision in minutes (brain vs legacy) ==='
WITH classified AS (
    SELECT
        pbi.draft_id,
        ode.event_type,
        pbi.received_at,
        ode.created_at AS decision_at,
        CASE
            WHEN mn.draft_source = 'messaging_brain' THEN 'brain'
            WHEN mn.draft_source = 'model' THEN 'legacy'
            ELSE 'other'
        END AS draft_origin
    FROM pre_booking_inquiries pbi
    JOIN operator_draft_events ode
      ON ode.company_id = pbi.company_id
     AND ode.draft_id = pbi.draft_id
    LEFT JOIN message_normalizations mn
      ON mn.tenant_id = CAST(:company_id AS uuid)
     AND mn.source_channel = 'email'
     AND mn.source_message_id = pbi.gmail_message_id
    WHERE pbi.company_id = CAST(:company_id AS uuid)
      AND pbi.received_at >= CAST(:since AS timestamptz)
      AND ode.event_type IN ('approved_unchanged', 'edited', 'rejected')
)
SELECT
    draft_origin,
    event_type,
    COUNT(*) AS action_count,
    ROUND(
        AVG(EXTRACT(EPOCH FROM (decision_at - received_at)) / 60.0),
        2
    ) AS avg_minutes_to_decision,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (decision_at - received_at)) / 60.0
        ),
        2
    ) AS median_minutes_to_decision
FROM classified
WHERE draft_origin IN ('brain', 'legacy')
GROUP BY draft_origin, event_type
ORDER BY draft_origin, event_type;

-- =====================================================================
-- Metric 5: Brain-branch failure rate
-- What it measures:
--   Cases where runtime was enabled but the brain path raised and
--   dispatch_pre_booking fell back to the legacy pipeline.
-- Source of truth:
--   Production logs, not SQL. Search for:
--   [EmailDispatch] Brain pre-booking draft failed, falling back to legacy path
--
-- This metric remains log-derived for Session 14. See Known Debt in
-- docs/MESSAGING_BRAIN_PREBOOKING_BEACH_HABITATS_ROLLOUT.md.
-- =====================================================================
\echo
\echo '=== Metric 5: Brain-branch failure rate ==='
SELECT
    'log-derived' AS metric_source,
    '[EmailDispatch] Brain pre-booking draft failed, falling back to legacy path' AS log_line,
    'Not queryable from SQL in Session 14; review Railway/application logs for the same time window.' AS note;

-- =====================================================================
-- Diagnostic: attribution coverage
-- What it measures:
--   Whether the message_normalizations join is classifying the full
--   inquiry set in the window, or whether rows are dropping into
--   "other" due to missing/late/unexpected attribution.
--   This is the only query in the file that includes inquiries with no
--   operator action yet.
-- Source of truth:
--   pre_booking_inquiries joined to message_normalizations.
-- =====================================================================
\echo
\echo '=== Diagnostic: attribution coverage ==='
WITH classified AS (
    SELECT
        pbi.draft_id,
        pbi.status,
        CASE
            WHEN mn.draft_source = 'messaging_brain' THEN 'brain'
            WHEN mn.draft_source = 'model' THEN 'legacy'
            ELSE 'other'
        END AS draft_origin
    FROM pre_booking_inquiries pbi
    LEFT JOIN message_normalizations mn
      ON mn.tenant_id = CAST(:company_id AS uuid)
     AND mn.source_channel = 'email'
     AND mn.source_message_id = pbi.gmail_message_id
    WHERE pbi.company_id = CAST(:company_id AS uuid)
      AND pbi.received_at >= CAST(:since AS timestamptz)
)
SELECT
    draft_origin,
    COUNT(*) AS inquiry_count,
    COUNT(*) FILTER (WHERE status = 'pending_review') AS pending_review_count,
    COUNT(*) FILTER (WHERE status = 'replied') AS replied_count,
    COUNT(*) FILTER (WHERE status = 'rejected') AS rejected_count
FROM classified
GROUP BY draft_origin
ORDER BY draft_origin;
