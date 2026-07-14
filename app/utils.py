import re
import secrets

import bcrypt
from fastapi import HTTPException, status
from sqlalchemy.sql import func


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


# Bangladeshi school week: Saturday-Wednesday classes, Thursday half/varies, Friday off.
DAY_ORDER = ["Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
DAY_CODES = {day[:3].lower(): day for day in DAY_ORDER}  # "sun" -> "Sunday", etc.


def normalize_day(day: str) -> str:
    """Accepts full names or 3-letter codes, case-insensitively. Raises 422 on a bad value."""
    key = day.strip().lower()
    for full_day in DAY_ORDER:
        if full_day.lower() == key:
            return full_day
    if key[:3] in DAY_CODES:
        return DAY_CODES[key[:3]]
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "error_code": "INVALID_DAY",
            "message": f"day must be one of: {', '.join(DAY_ORDER)} (or their 3-letter codes)",
        },
    )


def generate_id(prefix: str) -> str:
    """Short, collision-unlikely id for admin-created rows, e.g. generate_id('cls_') -> 'cls_a1b2c3d4'."""
    return f"{prefix}{secrets.token_hex(4)}"


def log_audit(db, actor_id: str, actor_role: str, action: str, resource_type: str, resource_id: str) -> None:
    """Shallow audit trail: who did what to which resource, when. Call before db.commit() in
    the same transaction, so the log entry and the actual change succeed or fail together."""
    from . import models  # local import - avoids a module-load-order dependency on models.py

    db.add(
        models.AuditLog(
            id=generate_id("aud_"),
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
        )
    )


def slugify(text: str) -> str:
    """'Annual Sports Day 2024' -> 'annual-sports-day-2024'. Falls back to 'untitled' for
    titles with no alphanumeric characters at all (e.g. pure emoji or punctuation)."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "untitled"


# Percentage cutoffs for the 11-tier scale (A+ through F). This wasn't given to us as the
# school's actual grading policy - it's a common standard convention. Adjust the thresholds
# here if Greenfield Academy uses different cutoffs; this is the single place that matters.
GRADE_THRESHOLDS = [
    (97, "A+"),
    (93, "A"),
    (90, "A-"),
    (87, "B+"),
    (83, "B"),
    (80, "B-"),
    (77, "C+"),
    (73, "C"),
    (70, "C-"),
    (60, "D"),
    (0, "F"),
]


def bump_count(
    db,
    scope_type: str,
    scope_id: str,
    metric: str,
    period_type: str,
    period_key: str,
    delta: int,
    subject_id=None,
) -> None:
    """Atomically adjusts one row of the `counts` table by `delta` (can be negative), creating
    it at 0 first if it doesn't exist yet. Call before db.commit() in the same transaction as
    the source-row write, so the count and the underlying data change together or not at all -
    this is the single place that keeps `counts` in sync; every attendance/result write path
    must route its count changes through here rather than writing to `counts` directly."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from . import models  # local import - avoids a module-load-order dependency on models.py

    row_id = "_".join([scope_type, scope_id, metric, period_type, period_key, subject_id or "all"])
    stmt = pg_insert(models.Count).values(
        id=row_id,
        scope_type=scope_type,
        scope_id=scope_id,
        metric=metric,
        period_type=period_type,
        period_key=period_key,
        subject_id=subject_id,
        value=delta,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={"value": models.Count.value + delta, "updated_at": func.now()},
    )
    db.execute(stmt)


def apply_attendance_count_delta(db, class_id: str, year_month: str, old_status, new_status) -> None:
    """Moves one attendance record's contribution from `old_status` to `new_status` (either may
    be None: None -> status is a fresh mark, status -> None would be a delete, which the
    attendance endpoints don't currently support). Status is one of: present, absent, late,
    excused."""
    # Normalize enum members to their plain string value - `f"{enum_member}"` is not reliably
    # the bare value across Pydantic/Python versions (can render as "ClassName.member").
    old_value = old_status.value if hasattr(old_status, "value") else old_status
    new_value = new_status.value if hasattr(new_status, "value") else new_status
    if old_value == new_value:
        return
    if old_value:
        bump_count(db, "class", class_id, f"attendance_{old_value}", "month", year_month, -1)
    if new_value:
        bump_count(db, "class", class_id, f"attendance_{new_value}", "month", year_month, +1)


def apply_student_count_delta(db, old_class_id, new_class_id) -> None:
    """Moves one student's contribution to their class's roster count from `old_class_id` to
    `new_class_id` (either may be None: no class assigned). Call on create (old=None),
    delete (new=None), and class transfer (both set, different). Roster size isn't time-scoped
    like attendance/results, so period_type/period_key are the fixed sentinel "current"/"all"."""
    if old_class_id == new_class_id:
        return
    if old_class_id:
        bump_count(db, "class", old_class_id, "student_count", "current", "all", -1)
    if new_class_id:
        bump_count(db, "class", new_class_id, "student_count", "current", "all", +1)


def apply_result_count_delta(
    db,
    class_id: str,
    student_id: str,
    subject_id: str,
    exam_id: str,
    old_marks,
    new_marks,
) -> None:
    """Adjusts entry_count/marks_sum for a result upsert or delete, at both the class scope
    (per-subject row + an all-subjects rollup row) and the student scope. Pass new_marks=None
    for a delete; old_marks=None for a brand-new result."""
    count_delta = (0 if old_marks is None else -1) + (0 if new_marks is None else 1)
    marks_delta = (0 if old_marks is None else -old_marks) + (0 if new_marks is None else new_marks)
    if count_delta == 0 and marks_delta == 0:
        return

    for scope_type, scope_id, subj in (
        ("class", class_id, subject_id),
        ("class", class_id, None),  # all-subjects rollup for this class+exam
        ("student", student_id, subject_id),
    ):
        bump_count(db, scope_type, scope_id, "results_entry_count", "exam", exam_id, count_delta, subject_id=subj)
        bump_count(db, scope_type, scope_id, "results_marks_sum", "exam", exam_id, marks_delta, subject_id=subj)


def compute_grade(marks: int, total: int) -> str:
    """Auto-calculates a letter grade from marks/total using GRADE_THRESHOLDS. `total` must
    be > 0 - callers should validate this before calling (ResultMarkIn.total already enforces
    `gt=0` at the schema level, so this should never actually be hit via the API)."""
    if total <= 0:
        raise ValueError("total must be greater than 0 to compute a grade")
    percentage = (marks / total) * 100
    for cutoff, grade in GRADE_THRESHOLDS:
        if percentage >= cutoff:
            return grade
    return "F"  # unreachable given the 0 cutoff above, but keeps the function total