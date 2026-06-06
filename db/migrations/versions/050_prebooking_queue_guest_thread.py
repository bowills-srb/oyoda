"""050_prebooking_queue_guest_thread

Persist guest_thread_id in the pre-booking queue read model so cached fallback
rows preserve lifecycle continuity.
"""

from alembic import op


revision = "050_prebooking_queue_guest_thread"
down_revision = "049_guest_threads_and_module_flags"
branch_labels = None
depends_on = None


UP_SQL = """
ALTER TABLE operator_prebooking_queue_read_models
    ADD COLUMN IF NOT EXISTS guest_thread_id UUID;

CREATE INDEX IF NOT EXISTS idx_prebooking_queue_guest_thread
    ON operator_prebooking_queue_read_models (tenant_id, guest_thread_id, received_at DESC);
"""


DOWN_SQL = """
DROP INDEX IF EXISTS idx_prebooking_queue_guest_thread;
ALTER TABLE operator_prebooking_queue_read_models
    DROP COLUMN IF EXISTS guest_thread_id;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
