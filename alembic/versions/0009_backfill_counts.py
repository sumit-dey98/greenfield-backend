"""backfill counts from existing attendance/results rows

Revision ID: 0009_backfill_counts
Revises: 0008_aggregate_counts
Create Date: 2026-07-13

The `counts` table (0008) is kept in sync going forward by the write endpoints
(mark_admin_attendance / upsert_admin_result / mark_attendance / enter_results via
utils.bump_count), but that only covers writes made after 0008 shipped. Every
attendance/result row that existed before then has no corresponding counts row.
This migration computes them once, in bulk, from the current attendance/results tables -
it does not touch attendance/results/students data itself, only populates `counts`.

Row shape matches utils.bump_count's id format exactly:
  "_".join([scope_type, scope_id, metric, period_type, period_key, subject_id or "all"])
so any subsequent incremental write correctly finds and updates these backfilled rows
instead of creating duplicates.
"""
from alembic import op

revision = "0009_backfill_counts"
down_revision = "0008_aggregate_counts"
branch_labels = None
depends_on = None


def upgrade() -> None:


    # --- Attendance: one row per (class_id, year_month, status) ---------------
    op.execute(
        """
        INSERT INTO counts (id, scope_type, scope_id, metric, period_type, period_key, subject_id, value)
        SELECT
            'class_' || s.class_id || '_attendance_' || a.status || '_month_' || to_char(a.date, 'YYYY-MM') || '_all',
            'class', s.class_id, 'attendance_' || a.status, 'month', to_char(a.date, 'YYYY-MM'), NULL,
            COUNT(*)
        FROM attendance a
        JOIN students s ON s.id = a.student_id
        WHERE s.class_id IS NOT NULL
        GROUP BY s.class_id, a.status, to_char(a.date, 'YYYY-MM')
        ON CONFLICT (id) DO UPDATE SET value = counts.value + EXCLUDED.value, updated_at = now()
        """
    )

    # --- Results: class scope, per subject ------------------------------------
    op.execute(
        """
        INSERT INTO counts (id, scope_type, scope_id, metric, period_type, period_key, subject_id, value)
        SELECT
            'class_' || s.class_id || '_results_entry_count_exam_' || r.exam_id || '_' || r.subject_id,
            'class', s.class_id, 'results_entry_count', 'exam', r.exam_id, r.subject_id,
            COUNT(*)
        FROM results r
        JOIN students s ON s.id = r.student_id
        WHERE s.class_id IS NOT NULL AND r.exam_id IS NOT NULL AND r.subject_id IS NOT NULL
        GROUP BY s.class_id, r.exam_id, r.subject_id
        ON CONFLICT (id) DO UPDATE SET value = counts.value + EXCLUDED.value, updated_at = now()
        """
    )
    op.execute(
        """
        INSERT INTO counts (id, scope_type, scope_id, metric, period_type, period_key, subject_id, value)
        SELECT
            'class_' || s.class_id || '_results_marks_sum_exam_' || r.exam_id || '_' || r.subject_id,
            'class', s.class_id, 'results_marks_sum', 'exam', r.exam_id, r.subject_id,
            SUM(r.marks)
        FROM results r
        JOIN students s ON s.id = r.student_id
        WHERE s.class_id IS NOT NULL AND r.exam_id IS NOT NULL AND r.subject_id IS NOT NULL
        GROUP BY s.class_id, r.exam_id, r.subject_id
        ON CONFLICT (id) DO UPDATE SET value = counts.value + EXCLUDED.value, updated_at = now()
        """
    )

    # --- Results: class scope, all-subjects rollup (subject_id NULL) ---------
    op.execute(
        """
        INSERT INTO counts (id, scope_type, scope_id, metric, period_type, period_key, subject_id, value)
        SELECT
            'class_' || s.class_id || '_results_entry_count_exam_' || r.exam_id || '_all',
            'class', s.class_id, 'results_entry_count', 'exam', r.exam_id, NULL,
            COUNT(*)
        FROM results r
        JOIN students s ON s.id = r.student_id
        WHERE s.class_id IS NOT NULL AND r.exam_id IS NOT NULL
        GROUP BY s.class_id, r.exam_id
        ON CONFLICT (id) DO UPDATE SET value = counts.value + EXCLUDED.value, updated_at = now()
        """
    )
    op.execute(
        """
        INSERT INTO counts (id, scope_type, scope_id, metric, period_type, period_key, subject_id, value)
        SELECT
            'class_' || s.class_id || '_results_marks_sum_exam_' || r.exam_id || '_all',
            'class', s.class_id, 'results_marks_sum', 'exam', r.exam_id, NULL,
            SUM(r.marks)
        FROM results r
        JOIN students s ON s.id = r.student_id
        WHERE s.class_id IS NOT NULL AND r.exam_id IS NOT NULL
        GROUP BY s.class_id, r.exam_id
        ON CONFLICT (id) DO UPDATE SET value = counts.value + EXCLUDED.value, updated_at = now()
        """
    )

    # --- Results: student scope, per subject ----------------------------------
    op.execute(
        """
        INSERT INTO counts (id, scope_type, scope_id, metric, period_type, period_key, subject_id, value)
        SELECT
            'student_' || r.student_id || '_results_entry_count_exam_' || r.exam_id || '_' || r.subject_id,
            'student', r.student_id, 'results_entry_count', 'exam', r.exam_id, r.subject_id,
            COUNT(*)
        FROM results r
        WHERE r.exam_id IS NOT NULL AND r.subject_id IS NOT NULL AND r.student_id IS NOT NULL
        GROUP BY r.student_id, r.exam_id, r.subject_id
        ON CONFLICT (id) DO UPDATE SET value = counts.value + EXCLUDED.value, updated_at = now()
        """
    )
    op.execute(
        """
        INSERT INTO counts (id, scope_type, scope_id, metric, period_type, period_key, subject_id, value)
        SELECT
            'student_' || r.student_id || '_results_marks_sum_exam_' || r.exam_id || '_' || r.subject_id,
            'student', r.student_id, 'results_marks_sum', 'exam', r.exam_id, r.subject_id,
            SUM(r.marks)
        FROM results r
        WHERE r.exam_id IS NOT NULL AND r.subject_id IS NOT NULL AND r.student_id IS NOT NULL
        GROUP BY r.student_id, r.exam_id, r.subject_id
        ON CONFLICT (id) DO UPDATE SET value = counts.value + EXCLUDED.value, updated_at = now()
        """
    )


def downgrade() -> None:
    # Backfilled rows are indistinguishable from organically-written ones after this
    # point (same id scheme, same table) - downgrading this data migration would risk
    # deleting real counts alongside backfilled ones, so it's a deliberate no-op.
    # To undo, restore from a backup taken before this migration ran.
    pass
