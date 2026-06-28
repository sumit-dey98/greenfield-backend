import re
import secrets

import bcrypt
from fastapi import HTTPException, status


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