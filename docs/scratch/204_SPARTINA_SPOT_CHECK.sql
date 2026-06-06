-- 204 Spartina Cir spot-check
--
-- Purpose: confirm what Beach Habitats has stored today for one real
-- property, so Properties v2 builds against real data shape, not
-- assumptions. Required before commit A.
--
-- Tenant: e07980b2-a990-4b24-91d1-c8cb71ab70e1 (Beach Habitats 30A)
--
-- Run in order. After step 1, plug the returned property_code and
-- external_id into the :property_code and :external_id placeholders
-- in steps 2-5. If any section returns zero rows, that's a real signal
-- (e.g. property has no KB entries today) — note it rather than
-- treating it as an error.

-- ============================================================
-- 1. Base property row
-- ============================================================
SELECT
    property_code,
    external_id,
    property_name,
    display_name,
    address_street,
    address_city,
    community,
    bedrooms,
    bathrooms,
    sleeps,
    profile_updated_at,
    created_at
FROM properties
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND (
    property_code ILIKE '%204%spartina%'
    OR property_name ILIKE '%204%spartina%'
    OR address_street ILIKE '%204%spartina%'
  )
LIMIT 5;

-- ============================================================
-- 2. Identity/coverage signals for this property
-- (mirrors what /properties/identity-report returns)
-- ============================================================
SELECT
    p.property_code,
    p.external_id,
    p.display_name,
    p.profile_updated_at,
    (SELECT COUNT(*) FROM pms_listings pl
       WHERE pl.tenant_id = p.tenant_id
         AND pl.property_external_id = p.property_code) AS pms_listing_count,
    (SELECT COUNT(*) FROM property_aliases pa
       WHERE pa.tenant_id = p.tenant_id
         AND pa.property_code = p.property_code) AS alias_count
FROM properties p
WHERE p.tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND p.property_code = :property_code;

-- ============================================================
-- 3. KB entries scoped to this property
-- ============================================================
SELECT
    ke.id,
    ke.category,
    LEFT(ke.question, 80) AS question_preview,
    LEFT(ke.answer, 80)   AS answer_preview,
    ke.confidence,
    ke.usage_count,
    ke.scope_target_id,
    ke.updated_at
FROM knowledge_embeddings ke
WHERE ke.tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND (
    ke.scope_target_id::text = :property_code
    OR ke.scope_target_id::text = :external_id
    OR ke.scope_target_id IN (
      SELECT id FROM properties WHERE property_code = :property_code
    )
  )
ORDER BY ke.updated_at DESC NULLS LAST
LIMIT 25;

-- ============================================================
-- 4. KB gaps tagged to this property
-- ============================================================
SELECT
    kg.id,
    LEFT(kg.question, 80) AS question_preview,
    kg.category,
    kg.missing_topics,
    kg.ask_count,
    kg.resolved,
    kg.property_external_id,
    kg.created_at
FROM concierge_knowledge_gaps kg
WHERE kg.tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND kg.property_external_id IN (:property_code, :external_id)
ORDER BY kg.created_at DESC NULLS LAST
LIMIT 25;

-- ============================================================
-- 5. Asset records for this property
-- ============================================================
SELECT
    pa.asset_type,
    pa.asset_name,
    pa.manufacturer,
    pa.model_number,
    pa.status,
    pa.warranty_end_date,
    pa.install_date,
    pa.updated_at
FROM property_assets pa
WHERE pa.tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND pa.property_code = :property_code
ORDER BY pa.updated_at DESC NULLS LAST
LIMIT 25;

-- ============================================================
-- 6. Population check for runtime questions 2 and 3
-- ============================================================

-- Q2: How many properties in this tenant have a blank/null property_code?
SELECT
    COUNT(*) FILTER (WHERE property_code IS NULL OR property_code = '') AS blank_code,
    COUNT(*) FILTER (WHERE property_code IS NOT NULL AND property_code <> '') AS has_code,
    COUNT(*) AS total
FROM properties
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1';

-- Q3: Does every KB gap's property_external_id match a real property_code?
SELECT
    COUNT(*) FILTER (WHERE p.property_code IS NOT NULL) AS gap_matches_code,
    COUNT(*) FILTER (WHERE p.property_code IS NULL AND kg.property_external_id IS NOT NULL AND kg.property_external_id <> '') AS gap_has_value_no_match,
    COUNT(*) FILTER (WHERE kg.property_external_id IS NULL OR kg.property_external_id = '') AS gap_has_no_property,
    COUNT(*) AS total_gaps
FROM concierge_knowledge_gaps kg
LEFT JOIN properties p
       ON p.tenant_id = kg.tenant_id
      AND p.property_code = kg.property_external_id
WHERE kg.tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
  AND kg.resolved = FALSE;
