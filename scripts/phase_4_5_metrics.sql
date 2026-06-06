-- Canonical production metrics bundle for the Phase 4.5 legacy-to-brain arc.
--
-- This file answers the cross-cutting measurement requirements from
-- PHASE_4_5_LEGACY_TO_BRAIN_BRIEF.md:
--   1. deterministic classifier resolution rate (4.5.A retirement gate)
--   2. deterministic draft resolution rate (4.5.D retirement gate)
--   3. per-tenant auto-send rate
--   4. per-tenant correction rate for auto-sent drafts
--   5. per-override quality score for healer-approved keyword overrides
--
-- Parameters:
--   :tenant -> operator/company UUID, quoted by psql substitution
--   :since  -> lower bound timestamp, quoted by psql substitution
--
-- Example:
--   psql "$DATABASE_URL" \
--     -v tenant="'e07980b2-a990-4b24-91d1-c8cb71ab70e1'" \
--     -v since="'2026-05-01 00:00:00+00'" \
--     -f scripts/phase_4_5_metrics.sql
--
-- Notes:
-- - Keep the inner single quotes around :tenant and :since.
-- - This bundle is tenant-scoped and intended for cutover / retirement evidence.
-- - "Deterministic draft resolution" is distinct from deterministic classifier
--   resolution: it measures whether the draft was completed by D.1-D.4 handlers
--   without entering the LLM draft branch.
-- - Override quality currently measures healer-approved keyword overrides only.
--   Property-alias proposals use a different review path and need separate
--   match telemetry before they can be scored equivalently.

\echo
\echo '=== Metric 1: deterministic classifier resolution and deterministic draft resolution ==='
WITH lane AS (
    SELECT
        pbi.draft_id,
        pbi.gmail_message_id,
        pbi.received_at,
        COALESCE(mn.draft_source, '') AS inquiry_draft_source,
        mn.normalization_id,
        note
    FROM pre_booking_inquiries pbi
    LEFT JOIN message_normalizations mn
      ON mn.tenant_id = CAST(:tenant AS uuid)
     AND mn.source_channel = 'email'
     AND mn.source_message_id = pbi.gmail_message_id
    LEFT JOIN LATERAL (
        SELECT note
        FROM jsonb_array_elements(COALESCE(mn.parser_notes, '[]'::jsonb)) AS note
        WHERE note->>'type' = 'brain_classifier_metadata'
        ORDER BY note->>'type'
        LIMIT 1
    ) classifier_note ON TRUE
    WHERE pbi.company_id = CAST(:tenant AS uuid)
      AND pbi.received_at >= CAST(:since AS timestamptz)
)
SELECT
    COUNT(*) AS inquiry_count,
    COUNT(*) FILTER (WHERE note IS NOT NULL) AS brain_classified_count,
    COUNT(*) FILTER (WHERE note->>'classifier_source' = 'deterministic') AS deterministic_classifier_count,
    ROUND(
        COUNT(*) FILTER (WHERE note->>'classifier_source' = 'deterministic')::numeric
        / NULLIF(COUNT(*) FILTER (WHERE note IS NOT NULL), 0),
        4
    ) AS deterministic_classifier_rate,
    COUNT(*) FILTER (
        WHERE inquiry_draft_source IN (
            'pricing_grounded_policy',
            'portfolio_match_grounded',
            'portfolio_follow_up_required',
            'verification_required',
            'fallback_grounded_property_data',
            'fallback_grounded_faq'
        )
        OR inquiry_draft_source LIKE 'fallback_grounded_guidebook_%'
    ) AS deterministic_draft_count,
    ROUND(
        COUNT(*) FILTER (
            WHERE inquiry_draft_source IN (
                'pricing_grounded_policy',
                'portfolio_match_grounded',
                'portfolio_follow_up_required',
                'verification_required',
                'fallback_grounded_property_data',
                'fallback_grounded_faq'
            )
            OR inquiry_draft_source LIKE 'fallback_grounded_guidebook_%'
        )::numeric
        / NULLIF(COUNT(*), 0),
        4
    ) AS deterministic_draft_rate,
    COUNT(*) FILTER (
        WHERE COALESCE((note->>'resolved_via_override')::boolean, FALSE)
    ) AS resolved_via_override_count
FROM lane;

\echo
\echo '=== Metric 2: auto-send rate ==='
SELECT
    COUNT(*) AS inquiry_count,
    COUNT(*) FILTER (WHERE COALESCE(send_decision, 'review') = 'send_now') AS auto_sent_count,
    ROUND(
        COUNT(*) FILTER (WHERE COALESCE(send_decision, 'review') = 'send_now')::numeric
        / NULLIF(COUNT(*), 0),
        4
    ) AS auto_send_rate,
    COUNT(*) FILTER (WHERE COALESCE(send_decision, 'review') = 'review') AS review_count,
    COUNT(*) FILTER (WHERE COALESCE(send_decision, 'review') = 'hold') AS hold_count
FROM pre_booking_inquiries
WHERE company_id = CAST(:tenant AS uuid)
  AND received_at >= CAST(:since AS timestamptz);

\echo
\echo '=== Metric 3: correction rate for auto-sent drafts ==='
WITH auto_sent AS (
    SELECT
        pbi.draft_id,
        pbi.company_id,
        pbi.received_at
    FROM pre_booking_inquiries pbi
    WHERE pbi.company_id = CAST(:tenant AS uuid)
      AND pbi.received_at >= CAST(:since AS timestamptz)
      AND COALESCE(pbi.send_decision, 'review') = 'send_now'
),
events AS (
    SELECT
        ode.company_id,
        ode.draft_id,
        BOOL_OR(ode.event_type = 'approved_unchanged') AS approved_unchanged,
        BOOL_OR(ode.event_type IN ('edited', 'rejected')) AS corrected
    FROM operator_draft_events ode
    WHERE ode.company_id = CAST(:tenant AS uuid)
    GROUP BY ode.company_id, ode.draft_id
)
SELECT
    COUNT(*) AS auto_sent_count,
    COUNT(*) FILTER (WHERE COALESCE(events.corrected, FALSE)) AS corrected_count,
    ROUND(
        COUNT(*) FILTER (WHERE COALESCE(events.corrected, FALSE))::numeric
        / NULLIF(COUNT(*), 0),
        4
    ) AS correction_rate,
    COUNT(*) FILTER (
        WHERE COALESCE(events.approved_unchanged, FALSE)
          AND NOT COALESCE(events.corrected, FALSE)
    ) AS approved_unchanged_count,
    COUNT(*) FILTER (
        WHERE NOT COALESCE(events.approved_unchanged, FALSE)
          AND NOT COALESCE(events.corrected, FALSE)
    ) AS no_operator_action_count
FROM auto_sent
LEFT JOIN events
  ON events.company_id = auto_sent.company_id
 AND events.draft_id = auto_sent.draft_id;

\echo
\echo '=== Metric 4: healer keyword-override quality score ==='
WITH approved_overrides AS (
    SELECT
        hp.proposal_id,
        hp.reviewed_at AS approved_at,
        hp.reviewed_by,
        hp.proposed_change->>'target_intent' AS target_intent,
        ARRAY(
            SELECT jsonb_array_elements_text(COALESCE(hp.proposed_change->'suggested_keywords', '[]'::jsonb))
        ) AS suggested_keywords
    FROM healer_proposals hp
    WHERE hp.tenant_id = CAST(:tenant AS uuid)
      AND hp.status = 'approved'
      AND hp.proposal_kind = 'intent_classifier_keyword_suggestion'
),
brain_hits AS (
    SELECT
        ao.proposal_id,
        ao.approved_at,
        ao.reviewed_by,
        ao.target_intent,
        ao.suggested_keywords,
        pbi.draft_id,
        pbi.received_at
    FROM approved_overrides ao
    JOIN pre_booking_inquiries pbi
      ON pbi.company_id = CAST(:tenant AS uuid)
     AND pbi.received_at >= ao.approved_at
    JOIN message_normalizations mn
      ON mn.tenant_id = CAST(:tenant AS uuid)
     AND mn.source_channel = 'email'
     AND mn.source_message_id = pbi.gmail_message_id
    JOIN LATERAL (
        SELECT note
        FROM jsonb_array_elements(COALESCE(mn.parser_notes, '[]'::jsonb)) AS note
        WHERE note->>'type' = 'brain_classifier_metadata'
          AND COALESCE((note->>'resolved_via_override')::boolean, FALSE)
          AND note->>'legacy_intent' = ao.target_intent
          AND EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(COALESCE(note->'matched_override_keywords', '[]'::jsonb)) AS matched(keyword)
                WHERE matched.keyword = ANY(ao.suggested_keywords)
          )
        LIMIT 1
    ) matched_note ON TRUE
),
override_events AS (
    SELECT
        ode.company_id,
        ode.draft_id,
        BOOL_OR(ode.event_type = 'approved_unchanged') AS approved_unchanged,
        BOOL_OR(ode.event_type IN ('edited', 'rejected')) AS corrected
    FROM operator_draft_events ode
    WHERE ode.company_id = CAST(:tenant AS uuid)
    GROUP BY ode.company_id, ode.draft_id
)
SELECT
    bh.proposal_id,
    bh.target_intent,
    bh.approved_at,
    bh.reviewed_by,
    bh.suggested_keywords,
    COUNT(*) AS matched_inquiry_count,
    COUNT(*) FILTER (
        WHERE COALESCE(oe.approved_unchanged, FALSE)
          AND NOT COALESCE(oe.corrected, FALSE)
    ) AS correctly_handled_count,
    COUNT(*) FILTER (WHERE COALESCE(oe.corrected, FALSE)) AS corrected_count,
    COUNT(*) FILTER (
        WHERE NOT COALESCE(oe.approved_unchanged, FALSE)
          AND NOT COALESCE(oe.corrected, FALSE)
    ) AS no_operator_action_count,
    ROUND(
        COUNT(*) FILTER (
            WHERE COALESCE(oe.approved_unchanged, FALSE)
              AND NOT COALESCE(oe.corrected, FALSE)
        )::numeric
        / NULLIF(
            COUNT(*) FILTER (
                WHERE COALESCE(oe.approved_unchanged, FALSE)
                   OR COALESCE(oe.corrected, FALSE)
            ),
            0
        ),
        4
    ) AS quality_score_actioned_only
FROM brain_hits bh
LEFT JOIN override_events oe
  ON oe.company_id = CAST(:tenant AS uuid)
 AND oe.draft_id = bh.draft_id
GROUP BY
    bh.proposal_id,
    bh.target_intent,
    bh.approved_at,
    bh.reviewed_by,
    bh.suggested_keywords
ORDER BY bh.approved_at DESC, bh.proposal_id;
