"""Merge the pre-booking and operator-auth migration branches.

Revision ID: 020_merge_branches
Revises: 018_pre_booking_pipeline, 019
"""

from typing import Sequence, Union


revision: str = "020_merge_branches"
down_revision: Union[str, Sequence[str], None] = ("018_pre_booking_pipeline", "019")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
