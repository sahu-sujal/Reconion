"""add unique constraint to assets(program_id, scope_id, asset_value)

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-06-10

"""
from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guard: constraint may already exist if the DB was set up manually
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_assets_program_scope_value'
            ) THEN
                ALTER TABLE assets
                    ADD CONSTRAINT uq_assets_program_scope_value
                    UNIQUE (program_id, scope_id, asset_value);
            END IF;
        END;
        $$;
    """)


def downgrade() -> None:
    op.drop_constraint("uq_assets_program_scope_value", "assets", type_="unique")
