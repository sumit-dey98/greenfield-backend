"""create application_exam_schedules and application_interviews tables

Revision ID: 0013_app_exam_interview
Revises: 0012_app_documents
Create Date: 2026-07-15

"""
from alembic import op
import sqlalchemy as sa

revision = "0013_app_exam_interview"
down_revision = "0012_app_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "application_exam_schedules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "application_id",
            sa.String(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("exam_date", sa.Date(), nullable=True),
        sa.Column("exam_time", sa.String(), nullable=True),
        sa.Column("venue", sa.String(), nullable=True),
        sa.Column("roll_number", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_application_exam_schedules_application_id",
        "application_exam_schedules",
        ["application_id"],
        unique=True,
    )
    op.create_index(
        "ix_application_exam_schedules_roll_number",
        "application_exam_schedules",
        ["roll_number"],
        unique=True,
    )

    op.create_table(
        "application_interviews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "application_id",
            sa.String(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("interview_date", sa.Date(), nullable=True),
        sa.Column("interview_time", sa.String(), nullable=True),
        sa.Column("mode", sa.String(), nullable=True),
        sa.Column("interviewer_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_application_interviews_application_id",
        "application_interviews",
        ["application_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_application_interviews_application_id", table_name="application_interviews")
    op.drop_table("application_interviews")
    op.drop_index(
        "ix_application_exam_schedules_roll_number", table_name="application_exam_schedules"
    )
    op.drop_index(
        "ix_application_exam_schedules_application_id", table_name="application_exam_schedules"
    )
    op.drop_table("application_exam_schedules")
