"""create admission_cycle_classes join table

Revision ID: 0019_admission_cycle_classes
Revises: 0018_exam_interview_location
Create Date: 2026-07-16

"""
from alembic import op
import sqlalchemy as sa

revision = "0019_admission_cycle_classes"
down_revision = "0018_exam_interview_location"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admission_cycle_classes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("cycle_id", sa.String(), sa.ForeignKey("admission_cycles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_id", sa.String(), sa.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_admission_cycle_classes_cycle_id", "admission_cycle_classes", ["cycle_id"])
    op.create_index("ix_admission_cycle_classes_class_id", "admission_cycle_classes", ["class_id"])


def downgrade() -> None:
    op.drop_index("ix_admission_cycle_classes_class_id", table_name="admission_cycle_classes")
    op.drop_index("ix_admission_cycle_classes_cycle_id", table_name="admission_cycle_classes")
    op.drop_table("admission_cycle_classes")
