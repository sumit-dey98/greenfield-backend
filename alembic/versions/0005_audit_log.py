"""create audit_log table

Revision ID: 0005_audit_log
Revises: 0004_drop_child_class
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_audit_log"
down_revision = "0004_drop_child_class"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("actor_role", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
    )
    op.create_index("idx_audit_log_resource", "audit_log", ["resource_type", "resource_id"])
    op.create_index("idx_audit_log_actor", "audit_log", ["actor_id"])
    op.create_index("idx_audit_log_created_at", "audit_log", ["created_at"])


def downgrade():
    op.drop_table("audit_log")