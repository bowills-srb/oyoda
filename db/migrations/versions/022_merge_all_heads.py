"""Merge the legacy operator-policy branch with the runtime-schema branch.

Revision ID: 022_merge_all_heads
Revises: 010_operator_policies_markets, 021_runtime_tables_to_alembic
"""

from typing import Sequence, Union


revision: str = "022_merge_all_heads"
down_revision: Union[str, Sequence[str], None] = (
    "010_operator_policies_markets",
    "021_runtime_tables_to_alembic",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
