-- 100 S Spooky Lane Unit 2D — data correctness audit
--
-- Purpose: trace the gate-code question through the live production data
-- pipeline so we can identify whether the failure is:
--   1. missing KB data
--   2. wrong KB scope
--   3. bad topic normalization / ingest drift
--   4. routing / confidence / gap-recording behavior
--
-- Tenant: e07980b2-a990-4b24-91d1-c8cb71ab70e1 (Beach Habitats 30A)
--
-- Live schema notes (2026-05-27):
--   - properties has address_street, not property_name/display_name
--   - concierge_scoped_knowledge uses:
--       knowledge_entry_id, topic_id, question_text, answer_text, scope_target_id
--   - concierge_knowledge_gaps uses:
--       question_text, detected_intent, confidence_score, metadata
--   - property_ingest_events does not exist in the current prod schema

-- ============================================================
-- 1. Find the property row for 100 S Spooky Lane Unit 2D
-- ============================================================
SELECT
    id,
    property_code,
    external_id,
    address_street,
    community,
    check_in_time,
    check_out_time,
    check_in_instructions,
    check_out_instructions,
    updated_at
FROM properties
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND (property_code ILIKE '%spooky%' OR address_street ILIKE '%spooky%')
ORDER BY updated_at DESC
LIMIT 10;

-- ============================================================
-- 2. Look at the actual inquiry row
-- ============================================================
SELECT
    draft_id,
    received_at,
    guest_email,
    guest_name,
    property_external_id,
    property_external_id_source,
    LEFT(message_text, 500)                AS message_preview,
    LEFT(draft_text, 500)                  AS draft_preview,
    confidence,
    confidence_source,
    parser_source,
    intent,
    blocked_by_gap_topics::text            AS blocked_by_gap_topics,
    status,
    review_verdict,
    intent_confidence,
    draft_confidence
FROM pre_booking_inquiries
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND received_at >= NOW() - INTERVAL '72 hours'
  AND message_text ILIKE '%gate code%'
ORDER BY received_at DESC
LIMIT 10;

-- ============================================================
-- 3. Look at the matching message_normalizations row
-- ============================================================
SELECT
    source_message_id,
    sent_at,
    source_provider,
    parser_used,
    route_outcome,
    draft_source,
    fallback_reason,
    LEFT(latest_guest_turn, 280)           AS latest_guest_turn,
    composer_source
FROM message_normalizations
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND latest_guest_turn ILIKE '%gate code%'
ORDER BY sent_at DESC
LIMIT 10;

-- ============================================================
-- 4. Look at the gap row created for this inquiry
-- ============================================================
SELECT
    gap_id,
    created_at,
    property_external_id,
    LEFT(question_text, 300)               AS question_preview,
    stage,
    channel,
    source,
    detected_intent,
    confidence_score,
    resolved,
    metadata::text
FROM concierge_knowledge_gaps
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND created_at >= NOW() - INTERVAL '72 hours'
  AND (question_text ILIKE '%gate%' OR question_text ILIKE '%code%' OR property_external_id = '100SL2D')
ORDER BY created_at DESC
LIMIT 20;

-- ============================================================
-- 5. Look at every KB entry scoped to this property
-- ============================================================
-- Replace the UUID if step 1 returns a different property id.
SELECT
    knowledge_entry_id,
    scope_type,
    scope_target_id::text,
    topic_id,
    LEFT(question_text, 200)               AS question_preview,
    LEFT(answer_text, 450)                 AS answer_preview,
    source,
    updated_at
FROM concierge_scoped_knowledge
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND scope_target_id = '292ef44a-cd70-4a39-b0d4-6a7dbc6b65c4'::uuid
ORDER BY updated_at DESC
LIMIT 80;

-- ============================================================
-- 6. Look at gate/access/check-in entries across the tenant
-- ============================================================
SELECT
    knowledge_entry_id,
    scope_type,
    scope_target_id::text,
    topic_id,
    LEFT(question_text, 220)               AS question_preview,
    LEFT(answer_text, 400)                 AS answer_preview,
    source,
    updated_at
FROM concierge_scoped_knowledge
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND (
    topic_id ILIKE '%check_in%'
    OR question_text ILIKE '%gate%'
    OR answer_text ILIKE '%gate%'
    OR answer_text ILIKE '%code%'
    OR topic_id ILIKE '%access%'
  )
ORDER BY updated_at DESC
LIMIT 80;

-- ============================================================
-- 7. Audit check-out / TV drift for this property
-- ============================================================
SELECT
    topic_id,
    LEFT(question_text, 180)               AS question_preview,
    LEFT(answer_text, 300)                 AS answer_preview,
    scope_target_id::text,
    source,
    updated_at
FROM concierge_scoped_knowledge
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND scope_target_id = '292ef44a-cd70-4a39-b0d4-6a7dbc6b65c4'::uuid
  AND (
    topic_id ILIKE '%check%out%'
    OR question_text ILIKE '%check%out%'
    OR answer_text ILIKE '%tv%'
    OR answer_text ILIKE '%fire tv%'
  )
ORDER BY updated_at DESC
LIMIT 60;

-- ============================================================
-- 8. Distinct topic ids across the tenant
-- ============================================================
SELECT
    COALESCE(topic_id, '')                 AS topic_id,
    COUNT(*)                               AS entry_count,
    COUNT(DISTINCT scope_target_id)        AS property_count
FROM concierge_scoped_knowledge
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
GROUP BY COALESCE(topic_id, '')
ORDER BY entry_count DESC, topic_id ASC;
