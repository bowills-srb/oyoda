-- ============================================================================
-- ADD 4 NEW PROPERTIES FROM WEBSITE (not in UNIT INFO.xlsx)
-- Generated: 2026-02-15
-- 
-- These properties exist on beachhabitats30a.com but were not in the Excel file.
-- Run this SQL to add them to the database.
-- ============================================================================

-- Casa Blanco (casa-blanco)
-- 8BR/9.5BA in Rosemary Beach, Sleeps 22
INSERT INTO properties (
    property_code,
    name,
    bedrooms,
    bathrooms,
    sleeps,
    community,
    beds_config,
    amenities,
    created_at,
    updated_at
) VALUES (
    'CASAB',
    'Casa Blanco',
    8,
    9.5,
    22,
    'Rosemary Beach',
    '{"king": 3, "queen": 0, "full": 0, "twin": 0, "bunk": 0}'::jsonb,
    '{"has_pool": true, "pool_type": "shared", "pool_heated": false, "has_hot_tub": false, "has_grill": true, "has_bikes": true, "bike_count": null, "has_golf_cart": false, "golf_cart_seats": null, "has_beach_gear": true, "has_washer_dryer": true, "has_wifi": true, "has_watercolor_access": false, "wristband_count": null}'::jsonb,
    NOW(),
    NOW()
) ON CONFLICT (property_code) DO UPDATE SET
    name = EXCLUDED.name,
    bedrooms = EXCLUDED.bedrooms,
    bathrooms = EXCLUDED.bathrooms,
    sleeps = EXCLUDED.sleeps,
    community = EXCLUDED.community,
    beds_config = EXCLUDED.beds_config,
    amenities = EXCLUDED.amenities,
    updated_at = NOW();


-- Emerald Bliss (emerald-bliss)
-- 4BR/3.5BA in Naturewalk, Sleeps 9
INSERT INTO properties (
    property_code,
    name,
    bedrooms,
    bathrooms,
    sleeps,
    community,
    beds_config,
    amenities,
    created_at,
    updated_at
) VALUES (
    'EMERBLS',
    'Emerald Bliss',
    4,
    3.5,
    9,
    'Naturewalk',
    '{"king": 2, "queen": 1, "full": 0, "twin": 0, "bunk": 0}'::jsonb,
    '{"has_pool": true, "pool_type": "shared", "pool_heated": false, "has_hot_tub": false, "has_grill": true, "has_bikes": true, "bike_count": 4, "has_golf_cart": true, "golf_cart_seats": 6, "has_beach_gear": true, "has_washer_dryer": true, "has_wifi": true, "has_watercolor_access": false, "wristband_count": null}'::jsonb,
    NOW(),
    NOW()
) ON CONFLICT (property_code) DO UPDATE SET
    name = EXCLUDED.name,
    bedrooms = EXCLUDED.bedrooms,
    bathrooms = EXCLUDED.bathrooms,
    sleeps = EXCLUDED.sleeps,
    community = EXCLUDED.community,
    beds_config = EXCLUDED.beds_config,
    amenities = EXCLUDED.amenities,
    updated_at = NOW();


-- Main St. Getaway (main-st-getaway)
-- 2BR/2.5BA in Rosemary Beach, Sleeps 6
INSERT INTO properties (
    property_code,
    name,
    bedrooms,
    bathrooms,
    sleeps,
    community,
    beds_config,
    amenities,
    created_at,
    updated_at
) VALUES (
    'MAINST',
    'Main St. Getaway',
    2,
    2.5,
    6,
    'Rosemary Beach',
    '{"king": 1, "queen": 1, "full": 0, "twin": 0, "bunk": 0}'::jsonb,
    '{"has_pool": true, "pool_type": "shared", "pool_heated": false, "has_hot_tub": false, "has_grill": false, "has_bikes": true, "bike_count": null, "has_golf_cart": false, "golf_cart_seats": null, "has_beach_gear": true, "has_washer_dryer": true, "has_wifi": true, "has_watercolor_access": false, "wristband_count": null}'::jsonb,
    NOW(),
    NOW()
) ON CONFLICT (property_code) DO UPDATE SET
    name = EXCLUDED.name,
    bedrooms = EXCLUDED.bedrooms,
    bathrooms = EXCLUDED.bathrooms,
    sleeps = EXCLUDED.sleeps,
    community = EXCLUDED.community,
    beds_config = EXCLUDED.beds_config,
    amenities = EXCLUDED.amenities,
    updated_at = NOW();


-- Vitamin Sea (vitamin-sea)
-- 5BR/5.5BA in Inlet Beach, Sleeps 10
INSERT INTO properties (
    property_code,
    name,
    bedrooms,
    bathrooms,
    sleeps,
    community,
    beds_config,
    amenities,
    created_at,
    updated_at
) VALUES (
    'VITSEA',
    'Vitamin Sea',
    5,
    5.5,
    10,
    'Inlet Beach',
    '{"king": 1, "queen": 0, "full": 0, "twin": 0, "bunk": 0}'::jsonb,
    '{"has_pool": false, "pool_type": null, "pool_heated": false, "has_hot_tub": false, "has_grill": true, "has_bikes": true, "bike_count": null, "has_golf_cart": false, "golf_cart_seats": null, "has_beach_gear": true, "has_washer_dryer": true, "has_wifi": true, "has_watercolor_access": false, "wristband_count": null}'::jsonb,
    NOW(),
    NOW()
) ON CONFLICT (property_code) DO UPDATE SET
    name = EXCLUDED.name,
    bedrooms = EXCLUDED.bedrooms,
    bathrooms = EXCLUDED.bathrooms,
    sleeps = EXCLUDED.sleeps,
    community = EXCLUDED.community,
    beds_config = EXCLUDED.beds_config,
    amenities = EXCLUDED.amenities,
    updated_at = NOW();


-- ============================================================================
-- VERIFICATION QUERY
-- ============================================================================
-- After running the inserts above, verify with:
-- SELECT property_code, name, bedrooms, bathrooms, sleeps, community 
-- FROM properties 
-- WHERE property_code IN ('CASAB', 'EMERBLS', 'MAINST', 'VITSEA');
