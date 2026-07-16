"""events: add featured flag

Revision ID: 0017_events_featured
Revises: 0016_application_photo
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_events_featured"
down_revision = "0016_application_photo"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "events",
        sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("events", "featured")
