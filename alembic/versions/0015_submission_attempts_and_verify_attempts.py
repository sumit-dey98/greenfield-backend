"""create submission_attempts and verify_attempts tables

Revision ID: 0015_submit_verify_attempts
Revises: 0014_app_grading
Create Date: 2026-07-15

"""
from alembic import op
import sqlalchemy as sa

revision = "0015_submit_verify_attempts"
down_revision = "0014_app_grading"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "submission_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ip_address", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_submission_attempts_ip_address", "submission_attempts", ["ip_address"])
    op.create_index("ix_submission_attempts_created_at", "submission_attempts", ["created_at"])

    op.create_table(
        "verify_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("reference_number", sa.String(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_verify_attempts_reference_number", "verify_attempts", ["reference_number"])
    op.create_index("ix_verify_attempts_created_at", "verify_attempts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_verify_attempts_created_at", table_name="verify_attempts")
    op.drop_index("ix_verify_attempts_reference_number", table_name="verify_attempts")
    op.drop_table("verify_attempts")
    op.drop_index("ix_submission_attempts_created_at", table_name="submission_attempts")
    op.drop_index("ix_submission_attempts_ip_address", table_name="submission_attempts")
    op.drop_table("submission_attempts")
