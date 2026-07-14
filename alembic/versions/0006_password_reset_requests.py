"""create password_reset_requests table

Revision ID: 0006_password_reset_requests
Revises: 0005_audit_log
Create Date: 2026-07-06

"""
from alembic import op
import sqlalchemy as sa

revision = "0006_password_reset_requests"
down_revision = "0005_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "password_reset_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_password_reset_requests_email", "password_reset_requests", ["email"])
    op.create_index("ix_password_reset_requests_role", "password_reset_requests", ["role"])
    op.create_index("ix_password_reset_requests_is_active", "password_reset_requests", ["is_active"])
    op.create_index("ix_password_reset_requests_created_at", "password_reset_requests", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_password_reset_requests_created_at", table_name="password_reset_requests")
    op.drop_index("ix_password_reset_requests_is_active", table_name="password_reset_requests")
    op.drop_index("ix_password_reset_requests_role", table_name="password_reset_requests")
    op.drop_index("ix_password_reset_requests_email", table_name="password_reset_requests")
    op.drop_table("password_reset_requests")
