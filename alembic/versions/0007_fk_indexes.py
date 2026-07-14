"""add indexes on frequently-filtered foreign keys and date columns

Revision ID: 0007_fk_indexes
Revises: 0006_password_reset_requests
Create Date: 2026-07-13

"""
from alembic import op

revision = "0007_fk_indexes"
down_revision = "0006_password_reset_requests"
branch_labels = None
depends_on = None

# (index_name, table, column)
INDEXES = [
    ("ix_students_class_id", "students", "class_id"),
    ("ix_teachers_class_id", "teachers", "class_id"),
    ("ix_teachers_subject_id", "teachers", "subject_id"),
    ("ix_classes_teacher_id", "classes", "teacher_id"),
    ("ix_results_student_id", "results", "student_id"),
    ("ix_results_subject_id", "results", "subject_id"),
    ("ix_results_exam_id", "results", "exam_id"),
    ("ix_attendance_student_id", "attendance", "student_id"),
    ("ix_attendance_date", "attendance", "date"),
    ("ix_schedule_class_id", "schedule", "class_id"),
    ("ix_schedule_teacher_id", "schedule", "teacher_id"),
]


def upgrade() -> None:
    for name, table, column in INDEXES:
        op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, _column in reversed(INDEXES):
        op.drop_index(name, table_name=table)
