"""029_password_reset_tokens

Adds self-service password reset + change-password flows.

Why we need this:
  Operators currently have no way to reset a forgotten password. The login
  page "Forgot password?" link opens a mailto:info@oyvoda.com, which means
  every password reset requires a human to manually bcrypt-hash a new value
  and UPDATE the row in the database. Not sustainable.

Security decisions:
  - `token_hash` stores SHA-256 of the raw token. The raw token is only
    emailed to the operator and never persisted. A DB dump can't be used to
    impersonate resets.
  - `used_at` is set atomically during the reset so the same token can't be
    re-spent. Enforced at the application layer with SELECT...FOR UPDATE.
  - `expires_at` is short (1 hour) to limit the window of exposure if a
    reset email is intercepted.
  - `ip_address` is captured for audit but never compared — we don't want
    to break resets for users on mobile networks where IPs shift.
  - When a new reset token is created for an operator, all other unused
    tokens for that operator are invalidated in the application layer
    (prevents stockpiling if someone repeatedly hits "forgot password").

Also: when a reset completes, the operator's existing refresh tokens are
revoked in-process (operator_app._revoke_jti). This migration only adds
the table; session invalidation logic lives in the endpoint.

Revision ID: 029_password_reset_tokens
Revises: 028_response_playbooks
"""

from alembic import op


revision = "029_password_reset_tokens"
down_revision = "028_response_playbooks"
branch_labels = None
depends_on = None


UP_SQL = """
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id     UUID NOT NULL
        REFERENCES operator_accounts(id) ON DELETE CASCADE,

    -- SHA-256 of the raw token. Never store the raw value.
    token_hash      TEXT NOT NULL,

    expires_at      TIMESTAMPTZ NOT NULL,
    used_at         TIMESTAMPTZ,

    -- Audit only, never matched against at verify time
    ip_address      TEXT,
    user_agent      TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Verify path hits this index (lookup by token_hash only among unused rows)
CREATE UNIQUE INDEX IF NOT EXISTS idx_prt_hash_active
    ON password_reset_tokens (token_hash)
    WHERE used_at IS NULL;

-- Invalidation/cleanup path queries by operator
CREATE INDEX IF NOT EXISTS idx_prt_operator_active
    ON password_reset_tokens (operator_id)
    WHERE used_at IS NULL;

-- Cleanup old tokens: idx supports periodic "DELETE WHERE expires_at < NOW()"
CREATE INDEX IF NOT EXISTS idx_prt_expires
    ON password_reset_tokens (expires_at)
    WHERE used_at IS NULL;
"""


DOWN_SQL = """
DROP TABLE IF EXISTS password_reset_tokens CASCADE;
"""


def upgrade():
    op.execute(UP_SQL)


def downgrade():
    op.execute(DOWN_SQL)
