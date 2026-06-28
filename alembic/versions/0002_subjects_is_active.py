"""subjects: add is_active for soft-delete

Revision ID: 0002_subjects_is_active
Revises: 0001_add_password_hash
Create Date: 2026-06-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_subjects_is_active"
down_revision = "0001_add_password_hash"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "subjects",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade():
    op.drop_column("subjects", "is_active")