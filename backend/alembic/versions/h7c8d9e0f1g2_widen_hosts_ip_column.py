"""Widen hosts.ip from VARCHAR(64) to VARCHAR(255).

httpx returns CDN/CNAME hostnames in the ip field which exceed 64 chars.

Revision ID: h7c8d9e0f1g2
Revises: g6b7c8d9e0f1
Branch Labels: None
Depends On: None
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "h7c8d9e0f1g2"
down_revision = "g6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("hosts", "ip", type_=sa.String(255), existing_nullable=True)


def downgrade() -> None:
    op.alter_column("hosts", "ip", type_=sa.String(64), existing_nullable=True)
