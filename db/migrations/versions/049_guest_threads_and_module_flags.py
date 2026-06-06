"""049_guest_threads_and_module_flags

Unified guest thread identity plus operator module feature flags.
"""

from alembic import op


revision = "049_guest_threads_and_module_flags"
down_revision = "048_operator_property_assets"
branch_labels = None
depends_on = None


UP_SQL = """
CREATE TABLE IF NOT EXISTS guest_threads (
    guest_thread_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID,
    property_code        TEXT,
    guest_name           TEXT,
    guest_name_norm      TEXT NOT NULL DEFAULT '',
    inquiry_thread_id    TEXT,
    session_token        TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_guest_threads_inquiry_thread
    ON guest_threads (tenant_id, inquiry_thread_id)
    WHERE inquiry_thread_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_guest_threads_session_token
    ON guest_threads (tenant_id, session_token)
    WHERE session_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_guest_threads_guest_lookup
    ON guest_threads (tenant_id, property_code, guest_name_norm, updated_at DESC);

ALTER TABLE concierge_guest_sessions
    ADD COLUMN IF NOT EXISTS guest_thread_id UUID;

ALTER TABLE concierge_escalations
    ADD COLUMN IF NOT EXISTS guest_thread_id UUID;

ALTER TABLE pre_booking_inquiries
    ADD COLUMN IF NOT EXISTS guest_thread_id UUID;

ALTER TABLE concierge_guest_sessions
    DROP CONSTRAINT IF EXISTS fk_concierge_sessions_guest_thread;
ALTER TABLE concierge_guest_sessions
    ADD CONSTRAINT fk_concierge_sessions_guest_thread
    FOREIGN KEY (guest_thread_id) REFERENCES guest_threads(guest_thread_id) ON DELETE SET NULL;

ALTER TABLE concierge_escalations
    DROP CONSTRAINT IF EXISTS fk_concierge_escalations_guest_thread;
ALTER TABLE concierge_escalations
    ADD CONSTRAINT fk_concierge_escalations_guest_thread
    FOREIGN KEY (guest_thread_id) REFERENCES guest_threads(guest_thread_id) ON DELETE SET NULL;

ALTER TABLE pre_booking_inquiries
    DROP CONSTRAINT IF EXISTS fk_pre_booking_inquiries_guest_thread;
ALTER TABLE pre_booking_inquiries
    ADD CONSTRAINT fk_pre_booking_inquiries_guest_thread
    FOREIGN KEY (guest_thread_id) REFERENCES guest_threads(guest_thread_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_concierge_sessions_guest_thread
    ON concierge_guest_sessions (tenant_id, guest_thread_id);
CREATE INDEX IF NOT EXISTS idx_concierge_escalations_guest_thread
    ON concierge_escalations (guest_thread_id);
CREATE INDEX IF NOT EXISTS idx_pre_booking_inquiries_guest_thread
    ON pre_booking_inquiries (guest_thread_id);

INSERT INTO guest_threads (
    guest_thread_id,
    tenant_id,
    property_code,
    guest_name,
    guest_name_norm,
    session_token,
    created_at,
    updated_at
)
SELECT
    gen_random_uuid(),
    s.tenant_id,
    s.property_code,
    s.guest_name,
    LOWER(TRIM(COALESCE(s.guest_name, ''))),
    s.token,
    COALESCE(s.created_at, NOW()),
    NOW()
FROM concierge_guest_sessions s
WHERE NOT EXISTS (
    SELECT 1
    FROM guest_threads gt
    WHERE gt.tenant_id = s.tenant_id
      AND gt.session_token = s.token
);

UPDATE concierge_guest_sessions s
SET guest_thread_id = gt.guest_thread_id
FROM guest_threads gt
WHERE s.guest_thread_id IS NULL
  AND gt.tenant_id = s.tenant_id
  AND gt.session_token = s.token;

UPDATE concierge_escalations e
SET guest_thread_id = gt.guest_thread_id
FROM concierge_guest_sessions s
JOIN guest_threads gt
  ON gt.tenant_id = s.tenant_id
 AND gt.session_token = s.token
WHERE e.guest_thread_id IS NULL
  AND e.session_token = s.token;

INSERT INTO operator_feature_flags (
    id,
    company_id,
    property_code,
    flag_name,
    enabled,
    enabled_at,
    enabled_by,
    notes,
    created_at
)
SELECT
    gen_random_uuid(),
    NULL,
    NULL,
    flag_name,
    TRUE,
    NOW(),
    'migration',
    'Backfilled default module flag',
    NOW()
FROM (
    VALUES
        ('stay_workflow_module'),
        ('work_orders_module'),
        ('property_assets_module'),
        ('vendor_intelligence_module'),
        ('handoffs_module'),
        ('safety_protocols_module')
) AS flags(flag_name)
WHERE NOT EXISTS (
    SELECT 1 FROM operator_feature_flags existing
    WHERE existing.company_id IS NULL
      AND existing.property_code IS NULL
      AND existing.flag_name = flags.flag_name
);
"""


DOWN_SQL = """
DROP INDEX IF EXISTS idx_pre_booking_inquiries_guest_thread;
DROP INDEX IF EXISTS idx_concierge_escalations_guest_thread;
DROP INDEX IF EXISTS idx_concierge_sessions_guest_thread;

ALTER TABLE pre_booking_inquiries
    DROP CONSTRAINT IF EXISTS fk_pre_booking_inquiries_guest_thread;
ALTER TABLE concierge_escalations
    DROP CONSTRAINT IF EXISTS fk_concierge_escalations_guest_thread;
ALTER TABLE concierge_guest_sessions
    DROP CONSTRAINT IF EXISTS fk_concierge_sessions_guest_thread;

ALTER TABLE pre_booking_inquiries
    DROP COLUMN IF EXISTS guest_thread_id;
ALTER TABLE concierge_escalations
    DROP COLUMN IF EXISTS guest_thread_id;
ALTER TABLE concierge_guest_sessions
    DROP COLUMN IF EXISTS guest_thread_id;

DELETE FROM operator_feature_flags
WHERE company_id IS NULL
  AND property_code IS NULL
  AND flag_name IN (
      'stay_workflow_module',
      'work_orders_module',
      'property_assets_module',
      'vendor_intelligence_module',
      'handoffs_module',
      'safety_protocols_module'
  );

DROP TABLE IF EXISTS guest_threads CASCADE;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
