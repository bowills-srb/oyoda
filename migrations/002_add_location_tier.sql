-- Migration: Add location tier and property type for accurate ADR attribution
-- Run with: psql postgresql://rental:rental@localhost:5433/rental_revenue -f this_file.sql

-- 1. Add property classification columns
ALTER TABLE properties ADD COLUMN IF NOT EXISTS property_type VARCHAR(50);
ALTER TABLE properties ADD COLUMN IF NOT EXISTS location_tier INTEGER;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS view_type VARCHAR(50);

-- 2. Update property types based on patterns in property_code
-- Condos (have unit numbers like 303-1680, 104-1785, or CP in name)
UPDATE properties 
SET property_type = 'condo'
WHERE property_type IS NULL 
  AND (
    property_code ~ '^[0-9]+-' 
    OR property_code LIKE '%CP%'
    OR property_code LIKE '%SSL%'
    OR address_street LIKE '%Unit%'
    OR address_street LIKE '%#%'
  );

-- Single family homes (everything else)
UPDATE properties 
SET property_type = 'single_family'
WHERE property_type IS NULL;

-- 3. Set view types based on property codes
-- VW = View properties (premium gulf view)
UPDATE properties 
SET view_type = 'gulf_view'
WHERE property_code LIKE '%VW%';

-- WLD = Western Lake Drive (lakefront)
UPDATE properties 
SET view_type = 'lake_view'
WHERE property_code LIKE '%WLD%';

-- SWC = Seawalk Circle (beachfront)
UPDATE properties 
SET view_type = 'gulf_front'
WHERE property_code LIKE '%SWC%';

-- Default to standard
UPDATE properties 
SET view_type = 'standard'
WHERE view_type IS NULL;

-- 4. Set location tiers (1 = best, 4 = standard)
-- Tier 1: Gulf front or premium view
UPDATE properties 
SET location_tier = 1
WHERE view_type IN ('gulf_front', 'gulf_view');

-- Tier 2: Lakefront
UPDATE properties 
SET location_tier = 2
WHERE view_type = 'lake_view';

-- Tier 3: Premium communities, single family
UPDATE properties 
SET location_tier = 3
WHERE location_tier IS NULL 
  AND property_type = 'single_family'
  AND community IN ('rosemary_beach', 'alys_beach', 'watercolor', 'seaside');

-- Tier 4: Everything else (condos, other communities)
UPDATE properties 
SET location_tier = 4
WHERE location_tier IS NULL;

-- 5. Verify the updates
SELECT 
    property_type,
    view_type,
    location_tier,
    COUNT(*) as count,
    ROUND(AVG(pr.adr)::numeric, 0) as avg_adr
FROM properties p
LEFT JOIN (
    SELECT property_code, AVG(adr) as adr 
    FROM property_pricing 
    WHERE adr > 0 
    GROUP BY property_code
) pr ON p.property_code = pr.property_code
GROUP BY property_type, view_type, location_tier
ORDER BY location_tier, avg_adr DESC;
