"""add photo_url to applications

Revision ID: 0016_application_photo
Revises: 0015_submit_verify_attempts
Create Date: 2026-07-15

"""
from alembic import op
import sqlalchemy as sa

revision = "0016_application_photo"
down_revision = "0015_submit_verify_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("photo_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("applications", "photo_url")
