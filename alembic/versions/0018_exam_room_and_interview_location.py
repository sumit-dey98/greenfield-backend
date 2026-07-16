"""add room to application_exam_schedules; add room/meeting_link/phone_number to application_interviews

Revision ID: 0018_exam_interview_location
Revises: 0017_events_featured
Create Date: 2026-07-16

"""
from alembic import op
import sqlalchemy as sa

revision = "0018_exam_interview_location"
down_revision = "0017_events_featured"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("application_exam_schedules", sa.Column("room", sa.String(), nullable=True))
    op.add_column("application_interviews", sa.Column("room", sa.String(), nullable=True))
    op.add_column("application_interviews", sa.Column("meeting_link", sa.String(), nullable=True))
    op.add_column("application_interviews", sa.Column("phone_number", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("application_interviews", "phone_number")
    op.drop_column("application_interviews", "meeting_link")
    op.drop_column("application_interviews", "room")
    op.drop_column("application_exam_schedules", "room")
