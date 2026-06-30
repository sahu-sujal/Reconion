"""add soft delete columns and missing tables for ASM schema

Revision ID: 3b6c9d0e1f2a
Revises: b1f2c3d4e5f6
Create Date: 2026-06-07 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3b6c9d0e1f2a"
down_revision: Union[str, Sequence[str], None] = "b1f2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "programs",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "programs",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "scopes",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "scopes",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "assets",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "assets",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_table(
        "findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "status",
            sa.Enum(
                "NEW",
                "CONFIRMED",
                "RESOLVED",
                "FALSE_POSITIVE",
                "RISK_ACCEPTED",
                "FIXED",
                "WONT_FIX",
                "IN_TRIAGE",
                name="finding_status",
                native_enum=False,
            ),
            nullable=False,
            server_default=sa.text("'NEW'"),
        ),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_findings_asset_id", "findings", ["asset_id"])
    op.create_index("ix_findings_program_id", "findings", ["program_id"])
    op.create_index("ix_findings_scope_id", "findings", ["scope_id"])
    op.create_index("ix_findings_severity", "findings", ["severity"])
    op.create_index("ix_findings_status", "findings", ["status"])
    op.create_index("ix_findings_category", "findings", ["category"])

    op.create_table(
        "hosts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("cdn", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("waf", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hosts_asset_id", "hosts", ["asset_id"])
    op.create_index("ix_hosts_program_id", "hosts", ["program_id"])
    op.create_index("ix_hosts_scope_id", "hosts", ["scope_id"])
    op.create_index("ix_hosts_host", "hosts", ["host"])
    op.create_index("ix_hosts_ip", "hosts", ["ip"])

    op.create_table(
        "urls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_urls_asset_id", "urls", ["asset_id"])
    op.create_index("ix_urls_program_id", "urls", ["program_id"])
    op.create_index("ix_urls_scope_id", "urls", ["scope_id"])
    op.create_index("ix_urls_status", "urls", ["status"])
    op.create_index("ix_urls_url", "urls", ["url"])

    op.create_table(
        "subdomains",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subdomain", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subdomains_asset_id", "subdomains", ["asset_id"])
    op.create_index("ix_subdomains_program_id", "subdomains", ["program_id"])
    op.create_index("ix_subdomains_scope_id", "subdomains", ["scope_id"])
    op.create_index("ix_subdomains_subdomain", "subdomains", ["subdomain"])
    op.create_index("ix_subdomains_resolved", "subdomains", ["resolved"])

    op.create_table(
        "technologies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("technology", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_technologies_host_id", "technologies", ["host_id"])
    op.create_index("ix_technologies_program_id", "technologies", ["program_id"])
    op.create_index("ix_technologies_scope_id", "technologies", ["scope_id"])
    op.create_index("ix_technologies_technology", "technologies", ["technology"])
    op.create_index("ix_technologies_confidence", "technologies", ["confidence"])

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(length=128), nullable=False),
        sa.Column("sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_program_id", "notifications", ["program_id"])
    op.create_index("ix_notifications_scope_id", "notifications", ["scope_id"])
    op.create_index("ix_notifications_finding_id", "notifications", ["finding_id"])
    op.create_index("ix_notifications_channel", "notifications", ["channel"])
    op.create_index("ix_notifications_sent", "notifications", ["sent"])


def downgrade() -> None:
    op.drop_index("ix_notifications_sent", table_name="notifications")
    op.drop_index("ix_notifications_channel", table_name="notifications")
    op.drop_index("ix_notifications_finding_id", table_name="notifications")
    op.drop_index("ix_notifications_scope_id", table_name="notifications")
    op.drop_index("ix_notifications_program_id", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index("ix_technologies_confidence", table_name="technologies")
    op.drop_index("ix_technologies_technology", table_name="technologies")
    op.drop_index("ix_technologies_scope_id", table_name="technologies")
    op.drop_index("ix_technologies_program_id", table_name="technologies")
    op.drop_index("ix_technologies_host_id", table_name="technologies")
    op.drop_table("technologies")

    op.drop_index("ix_subdomains_resolved", table_name="subdomains")
    op.drop_index("ix_subdomains_subdomain", table_name="subdomains")
    op.drop_index("ix_subdomains_scope_id", table_name="subdomains")
    op.drop_index("ix_subdomains_program_id", table_name="subdomains")
    op.drop_index("ix_subdomains_asset_id", table_name="subdomains")
    op.drop_table("subdomains")

    op.drop_index("ix_urls_url", table_name="urls")
    op.drop_index("ix_urls_status", table_name="urls")
    op.drop_index("ix_urls_scope_id", table_name="urls")
    op.drop_index("ix_urls_program_id", table_name="urls")
    op.drop_index("ix_urls_asset_id", table_name="urls")
    op.drop_table("urls")

    op.drop_index("ix_hosts_ip", table_name="hosts")
    op.drop_index("ix_hosts_host", table_name="hosts")
    op.drop_index("ix_hosts_scope_id", table_name="hosts")
    op.drop_index("ix_hosts_program_id", table_name="hosts")
    op.drop_index("ix_hosts_asset_id", table_name="hosts")
    op.drop_table("hosts")

    op.drop_index("ix_findings_category", table_name="findings")
    op.drop_index("ix_findings_status", table_name="findings")
    op.drop_index("ix_findings_severity", table_name="findings")
    op.drop_index("ix_findings_scope_id", table_name="findings")
    op.drop_index("ix_findings_program_id", table_name="findings")
    op.drop_index("ix_findings_asset_id", table_name="findings")
    op.drop_table("findings")

    op.drop_column("assets", "deleted_at")
    op.drop_column("assets", "is_deleted")

    op.drop_column("scopes", "deleted_at")
    op.drop_column("scopes", "is_deleted")

    op.drop_column("programs", "deleted_at")
    op.drop_column("programs", "is_deleted")
