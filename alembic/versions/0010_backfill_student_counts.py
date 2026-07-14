"""backfill per-class student_count rows

Revision ID: 0010_backfill_student_counts
Revises: 0009_backfill_counts
Create Date: 2026-07-14

Same situation as 0009: utils.apply_student_count_delta (wired into student
create/update/delete) only keeps `counts` in sync for writes made after this shipped.
Every student already assigned to a class before then has no student_count contribution
backfilled yet. This computes it once from the current students table.
"""
from alembic import op

revision = "0010_backfill_student_counts"
down_revision = "0009_backfill_counts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO counts (id, scope_type, scope_id, metric, period_type, period_key, subject_id, value)
        SELECT
            'class_' || s.class_id || '_student_count_current_all_all',
            'class', s.class_id, 'student_count', 'current', 'all', NULL,
            COUNT(*)
        FROM students s
        WHERE s.class_id IS NOT NULL
        GROUP BY s.class_id
        ON CONFLICT (id) DO UPDATE SET value = counts.value + EXCLUDED.value, updated_at = now()
        """
    )


def downgrade() -> None:
    # Same reasoning as 0009 - backfilled rows are indistinguishable from organic ones
    # after this point, so downgrading is a deliberate no-op.
    pass
