"""create application_grading_assignments and application_exam_results tables

Revision ID: 0014_app_grading
Revises: 0013_app_exam_interview
Create Date: 2026-07-15

"""
from alembic import op
import sqlalchemy as sa

revision = "0014_app_grading"
down_revision = "0013_app_exam_interview"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "application_grading_assignments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "application_id",
            sa.String(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("teacher_id", sa.String(), sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("assigned_by", sa.String(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("status", sa.String(), nullable=False, server_default="assigned"),
    )
    op.create_index(
        "ix_application_grading_assignments_application_id",
        "application_grading_assignments",
        ["application_id"],
        unique=True,
    )
    op.create_index(
        "ix_application_grading_assignments_teacher_id",
        "application_grading_assignments",
        ["teacher_id"],
    )

    op.create_table(
        "application_exam_results",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "application_id",
            sa.String(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("marks", sa.Integer(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=True, server_default="100"),
        sa.Column("remarks", sa.String(), nullable=True),
        sa.Column("graded_by", sa.String(), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_application_exam_results_application_id",
        "application_exam_results",
        ["application_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_application_exam_results_application_id", table_name="application_exam_results"
    )
    op.drop_table("application_exam_results")
    op.drop_index(
        "ix_application_grading_assignments_teacher_id",
        table_name="application_grading_assignments",
    )
    op.drop_index(
        "ix_application_grading_assignments_application_id",
        table_name="application_grading_assignments",
    )
    op.drop_table("application_grading_assignments")
