-- Ship S: provision dashboard_v2_primary for Beach Habitats.
--
-- This script is intentionally idempotent. The feature-flag system does not
-- have a separate flag-definition table; provisioning means inserting or
-- updating the tenant-scoped row in operator_feature_flags.
--
-- Beach Habitats tenant:
--   e07980b2-a990-4b24-91d1-c8cb71ab70e1
--
-- Result:
-- - dashboard_v2_primary exists for the tenant
-- - enabled remains FALSE until an explicit later flip

INSERT INTO operator_feature_flags (
    company_id,
    property_code,
    flag_name,
    enabled,
    enabled_at,
    enabled_by,
    notes
)
VALUES (
    'e07980b2-a990-4b24-91d1-c8cb71ab70e1'::uuid,
    NULL,
    'dashboard_v2_primary',
    FALSE,
    NULL,
    'ship_s_provision',
    'Ship S v2 route provisioned default-OFF for Beach Habitats'
)
ON CONFLICT (company_id, property_code, flag_name)
DO UPDATE SET
    enabled = FALSE,
    enabled_at = CASE
        WHEN operator_feature_flags.enabled = FALSE THEN operator_feature_flags.enabled_at
        ELSE NULL
    END,
    enabled_by = 'ship_s_provision',
    notes = 'Ship S v2 route provisioned default-OFF for Beach Habitats';

-- Verification query:
-- SELECT company_id::text, COALESCE(property_code, ''), flag_name, enabled, COALESCE(enabled_at::text, '')
-- FROM operator_feature_flags
-- WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'::uuid
--   AND flag_name = 'dashboard_v2_primary';
