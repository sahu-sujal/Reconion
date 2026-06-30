"""add notes column to scopes

Revision ID: 4a5b6c7d8e9f
Revises: 3b6c9d0e1f2a
Create Date: 2026-06-07 18:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "4a5b6c7d8e9f"
down_revision: Union[str, Sequence[str], None] = "3b6c9d0e1f2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scopes",
        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scopes", "notes")
