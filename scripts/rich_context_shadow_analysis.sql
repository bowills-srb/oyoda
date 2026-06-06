-- Rich-context shadow observation analysis.
--
-- Evaluates the shadow data accumulated under
-- MESSAGING_BRAIN_RICH_CONTEXT_SHADOW against the cutover criteria
-- defined in docs/MESSAGING_BRAIN_RICH_CONTEXT_ROLLOUT.md.
--
-- Run with:
--     psql "$DATABASE_URL" \
--         -v tenant_id="'<company-uuid>'" \
--         -v since="'2026-01-01 00:00:00+00'" \
--         -f scripts/rich_context_shadow_analysis.sql
--
-- Note the doubled quoting on -v values: psql variable substitution is
-- textual, so the value must include the SQL quotes. The :tenant_id
-- and :since references in the queries below appear unquoted on
-- purpose -- the substitution provides the quotes.
--
-- All criteria are evaluated against rows where:
--     tenant_id = :tenant_id AND recorded_at >= :since
--
-- See the rollout doc for criteria definitions and gate semantics.

-- =====================================================================
-- Header: parameter echo and observation window summary
-- =====================================================================
\echo
\echo '=== Parameters and window ==='
SELECT
    :tenant_id AS tenant_id,
    :since AS since,
    COUNT(*) AS total_observations,
    MIN(recorded_at) AS earliest_observation,
    MAX(recorded_at) AS latest_observation
FROM rich_context_shadow_observations
WHERE tenant_id = :tenant_id
  AND recorded_at >= :since;

-- =====================================================================
-- Criterion 1: Volume
-- Gate: total_observations >= 500.
-- =====================================================================
\echo
\echo '=== Criterion 1: Volume (gate: >= 500) ==='
SELECT
    COUNT(*) AS total_observations,
    CASE WHEN COUNT(*) >= 500
        THEN 'PASS' ELSE 'FAIL' END AS gate
FROM rich_context_shadow_observations
WHERE tenant_id = :tenant_id
  AND recorded_at >= :since;

-- =====================================================================
-- Criterion 2: Intent spread and dominance
-- Gates:
--   - at least 5 distinct intent values
--   - no single intent > 60% of observations
-- One per-intent distribution answers both gates. Read the row count
-- for the spread gate; read the share column for the dominance gate.
-- =====================================================================
\echo
\echo '=== Criterion 2: Intent distribution ==='
\echo '  Spread gate:    >= 5 distinct intents (count rows below)'
\echo '  Dominance gate: no share > 0.60'
SELECT
    intent,
    COUNT(*) AS observations,
    ROUND(
        COUNT(*)::numeric
        / NULLIF(SUM(COUNT(*)) OVER (), 0),
        4
    ) AS share
FROM rich_context_shadow_observations
WHERE tenant_id = :tenant_id
  AND recorded_at >= :since
GROUP BY intent
ORDER BY observations DESC;

-- =====================================================================
-- Criterion 3: Property spread
-- Gate: at least 10 distinct property_code values.
-- NULL property_code values (if any) are excluded from the count;
-- the spread criterion is about distinct identified properties.
-- =====================================================================
\echo
\echo '=== Criterion 3: Property spread (gate: >= 10 distinct) ==='
SELECT
    COUNT(DISTINCT property_code) AS distinct_properties,
    COUNT(*) FILTER (
        WHERE property_code IS NULL
    ) AS null_property_observations,
    CASE WHEN COUNT(DISTINCT property_code) >= 10
        THEN 'PASS' ELSE 'FAIL' END AS gate
FROM rich_context_shadow_observations
WHERE tenant_id = :tenant_id
  AND recorded_at >= :since;

-- =====================================================================
-- Criterion 4: Exception rate per sub-computation
-- Gate: each sub-computation share < 0.01.
-- shadow_exceptions is JSONB keyed by sub-computation name. A
-- non-empty value at a key means that sub-computation raised for that
-- observation.
--
-- This query is structured so that the three sub-computation rows
-- always appear, even when there are zero observations. The keys
-- table is the left side; counts are computed via correlated
-- aggregates that return 0 against an empty observation set, and
-- total_observations is computed independently so NO_DATA is
-- correctly attributed.
-- =====================================================================
\echo
\echo '=== Criterion 4: Per-sub-computation exception rate (gate: each < 0.01) ==='
WITH totals AS (
    SELECT COUNT(*) AS total
    FROM rich_context_shadow_observations
    WHERE tenant_id = :tenant_id
      AND recorded_at >= :since
)
SELECT
    keys.key AS sub_computation,
    (
        SELECT COUNT(*)
        FROM rich_context_shadow_observations
        WHERE tenant_id = :tenant_id
          AND recorded_at >= :since
          AND shadow_exceptions ? keys.key
    ) AS exception_count,
    totals.total AS total_observations,
    CASE
        WHEN totals.total = 0 THEN NULL
        ELSE ROUND(
            (
                SELECT COUNT(*)
                FROM rich_context_shadow_observations
                WHERE tenant_id = :tenant_id
                  AND recorded_at >= :since
                  AND shadow_exceptions ? keys.key
            )::numeric
            / totals.total,
            4
        )
    END AS share,
    CASE
        WHEN totals.total = 0 THEN 'NO_DATA'
        WHEN (
            SELECT COUNT(*)
            FROM rich_context_shadow_observations
            WHERE tenant_id = :tenant_id
              AND recorded_at >= :since
              AND shadow_exceptions ? keys.key
        )::numeric / totals.total < 0.01 THEN 'PASS'
        ELSE 'FAIL'
    END AS gate
FROM (VALUES ('richness'),
             ('evidence'),
             ('preferences')) AS keys(key)
CROSS JOIN totals
ORDER BY sub_computation;

-- =====================================================================
-- Criterion 5: Cumulative exception rate
-- Gate: share of observations with any non-empty shadow_exceptions
--       < 0.02.
-- "Non-empty" means the JSONB object has at least one key. The default
-- is '{}'::jsonb so empty is the no-exception state.
-- =====================================================================
\echo
\echo '=== Criterion 5: Cumulative exception rate (gate: < 0.02) ==='
SELECT
    COUNT(*) FILTER (
        WHERE shadow_exceptions <> '{}'::jsonb
    ) AS observations_with_any_exception,
    COUNT(*) AS total_observations,
    ROUND(
        COUNT(*) FILTER (
            WHERE shadow_exceptions <> '{}'::jsonb
        )::numeric
        / NULLIF(COUNT(*), 0),
        4
    ) AS share,
    CASE
        WHEN COUNT(*) = 0 THEN 'NO_DATA'
        WHEN COUNT(*) FILTER (
                 WHERE shadow_exceptions <> '{}'::jsonb
             )::numeric / COUNT(*) < 0.02 THEN 'PASS'
        ELSE 'FAIL'
    END AS gate
FROM rich_context_shadow_observations
WHERE tenant_id = :tenant_id
  AND recorded_at >= :since;
