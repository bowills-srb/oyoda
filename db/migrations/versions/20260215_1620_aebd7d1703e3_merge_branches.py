"""merge_branches

Revision ID: aebd7d1703e3
Revises: 003_create_properties, 007_concierge_maintenance_events
Create Date: 2026-02-15 16:20:03.405327+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aebd7d1703e3'
down_revision: Union[str, None] = ('003_create_properties', '007_concierge_maintenance_events')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
