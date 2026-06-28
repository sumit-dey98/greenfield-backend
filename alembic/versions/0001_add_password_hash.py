"""add password_hash columns

Revision ID: 0001_add_password_hash
Revises:
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

# NOTE: set down_revision to your current alembic head before running.
revision = "0001_add_password_hash"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("students", sa.Column("password_hash", sa.String(), nullable=True))
    op.add_column("teachers", sa.Column("password_hash", sa.String(), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(), nullable=True))


def downgrade():
    op.drop_column("students", "password_hash")
    op.drop_column("teachers", "password_hash")
    op.drop_column("users", "password_hash")