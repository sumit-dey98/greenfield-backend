from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import models, oauth2, schemas, utils
from ..database import get_db

router = APIRouter(prefix="/admin")

ACADEMIC = Depends(oauth2.require_admin_permission("academic"))


def _get_or_404(db: Session, model, row_id: str, error_code: str, label: str):
    row = db.query(model).filter(model.id == row_id).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": error_code, "message": f"No {label} with id '{row_id}'"},
        )
    return row


def _check_in_use(db: Session, model, column, value: str, error_code: str, message: str):
    if db.query(model).filter(column == value).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"error_code": error_code, "message": message}
        )


def _check_class_uniqueness(db: Session, grade, section, exclude_id: Optional[str] = None):
    """Only meaningful when both grade and section are set - skip if either is missing."""
    if grade is None or section is None:
        return
    query = db.query(models.Class).filter(models.Class.grade == grade, models.Class.section == section)
    if exclude_id:
        query = query.filter(models.Class.id != exclude_id)
    existing = query.first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "CLASS_ALREADY_EXISTS",
                "message": f"Grade {grade} Section {section} already exists as class '{existing.id}'",
            },
        )


def _apply_updates(row, payload, exclude_unset_fields: set):
    for field in exclude_unset_fields:
        setattr(row, field, getattr(payload, field))


def _times_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    """String comparison works because times are stored zero-padded 24h ("HH:MM"),
    which sorts identically to numeric comparison. Back-to-back periods (one ending
    exactly when the other starts) don't count as overlapping."""
    return start_a < end_b and start_b < end_a


def _check_period_conflicts(
    db: Session, sort_order: int, start_time: str, end_time: str, exclude_id: Optional[str] = None
):
    """Raises 409 if another period shares this sort_order, or its time range overlaps."""
    query = db.query(models.Period)
    if exclude_id:
        query = query.filter(models.Period.id != exclude_id)

    for other in query.all():
        if other.sort_order == sort_order:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "PERIOD_SORT_ORDER_CONFLICT",
                    "message": f"sort_order {sort_order} is already used by period '{other.id}'",
                },
            )
        if _times_overlap(start_time, end_time, other.start_time, other.end_time):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "PERIOD_TIME_CONFLICT",
                    "message": f"{start_time}-{end_time} overlaps period '{other.id}' "
                    f"({other.start_time}-{other.end_time})",
                },
            )


def _check_schedule_conflicts(
    db: Session,
    day: str,
    start_time: str,
    end_time: str,
    teacher_id: str,
    class_id: str,
    room: Optional[str],
    exclude_id: Optional[str] = None,
):
    """Raises 409 if this slot overlaps an existing entry for the same teacher, class, or room."""
    query = db.query(models.Schedule).filter(models.Schedule.day == day)
    if exclude_id:
        query = query.filter(models.Schedule.id != exclude_id)

    for other in query.all():
        if not _times_overlap(start_time, end_time, other.start_time, other.end_time):
            continue
        if other.teacher_id == teacher_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "TEACHER_SCHEDULE_CONFLICT",
                    "message": f"Teacher '{teacher_id}' is already booked {day} "
                    f"{other.start_time}-{other.end_time} (entry '{other.id}')",
                },
            )
        if other.class_id == class_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "CLASS_SCHEDULE_CONFLICT",
                    "message": f"Class '{class_id}' already has a period {day} "
                    f"{other.start_time}-{other.end_time} (entry '{other.id}')",
                },
            )
        if room and other.room == room:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "ROOM_SCHEDULE_CONFLICT",
                    "message": f"Room '{room}' is already booked {day} "
                    f"{other.start_time}-{other.end_time} (entry '{other.id}')",
                },
            )


# ---------------------------------------------------------------------------
# Counts (pre-aggregated attendance/results numbers)
# ---------------------------------------------------------------------------


@router.get(
    "/counts",
    response_model=schemas.Page[schemas.CountOut],
    tags=["admin-counts"],
    summary="List pre-aggregated counts (attendance/results numbers)",
    description=(
        "Returns matching rows from the `counts` table - e.g. every class's "
        "present/absent/late/excused for a given month, or every class's results entry_count/"
        "marks_sum for a given exam. Kept in sync automatically whenever attendance is marked "
        "or a result is entered/updated/deleted (admin or teacher endpoints), so this is always "
        "current without re-fetching the underlying rows. `metric` values: `attendance_present`, "
        "`attendance_absent`, `attendance_late`, `attendance_excused`, `results_entry_count`, "
        "`results_marks_sum`, `student_count`. For results, `results_marks_sum / "
        "results_entry_count` gives the average - it's not stored directly so it's never stale "
        "relative to its inputs. `subject_id=null` rows are an all-subjects rollup for that "
        "scope+exam. Paginated via `limit`/`offset` - always filter by at least `period_key` "
        "or `scope_id` in practice, since an unfiltered call can span the whole table."
    ),
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"}},
)
def list_counts(
    scope_type: Optional[schemas.CountScopeType] = Query(
        None, description="What the count is about: 'class' (a class's roster/attendance/results) or 'student' (one student's results)"
    ),
    scope_id: Optional[str] = Query(
        None, description="The id of the class or student named by scope_type, e.g. a class_id like 'cls_01' or a student_id like 'std_01'"
    ),
    metric: Optional[schemas.CountMetric] = Query(None, description="Which number to fetch - see the metric list above"),
    period_type: Optional[schemas.CountPeriodType] = Query(
        None, description="What period_key means: 'month' (attendance), 'exam' (results), or 'current' (student_count, not time-scoped)"
    ),
    period_key: Optional[str] = Query(None, description="e.g. '2026-07' for period_type=month, an exam_id for period_type=exam, or 'all' for period_type=current"),
    subject_id: Optional[str] = Query(
        None, description="Restrict results metrics to one subject; omit for the all-subjects rollup row (subject_id=null in the response)"
    ),
    limit: int = Query(200, ge=1, le=2000, description="Max rows to return, 1-2000"),
    offset: int = Query(0, ge=0, description="How many matching rows to skip, for paging past the first `limit`"),
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    query = db.query(models.Count)
    if scope_type:
        query = query.filter(models.Count.scope_type == scope_type.value)
    if scope_id:
        query = query.filter(models.Count.scope_id == scope_id)
    if metric:
        query = query.filter(models.Count.metric == metric.value)
    if period_type:
        query = query.filter(models.Count.period_type == period_type.value)
    if period_key:
        query = query.filter(models.Count.period_key == period_key)
    if subject_id:
        query = query.filter(models.Count.subject_id == subject_id)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return schemas.Page(items=items, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------


@router.get(
    "/classes",
    tags=["admin-classes"],
    response_model=List[schemas.ClassOut],
    summary="List all classes",
    description="Filter by `grade`, `section` (exact match), `teacher_id`, and/or `name` "
    "(partial, case-insensitive search). Requires the `academic` permission (super_admin/admin only).",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"}},
)
def list_classes(
    grade: Optional[int] = Query(None),
    section: Optional[str] = Query(None),
    teacher_id: Optional[str] = Query(None),
    name: Optional[str] = Query(None, description="Partial, case-insensitive match on name"),
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    query = db.query(models.Class)
    if grade is not None:
        query = query.filter(models.Class.grade == grade)
    if section:
        query = query.filter(models.Class.section == section)
    if teacher_id:
        query = query.filter(models.Class.teacher_id == teacher_id)
    if name:
        query = query.filter(models.Class.name.ilike(f"%{name.strip()}%"))
    return query.order_by(models.Class.grade, models.Class.section).all()


@router.get(
    "/classes/{class_id}",
    tags=["admin-classes"],
    response_model=schemas.ClassOut,
    summary="Get one class",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No class with that id"},
    },
)
def get_class(class_id: str, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    return _get_or_404(db, models.Class, class_id, "CLASS_NOT_FOUND", "class")


@router.post(
    "/classes",
    tags=["admin-classes"],
    response_model=schemas.ClassOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a class",
    description="`id` is auto-generated (`cls_xxxxxxxx`) if omitted.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "teacher_id given but doesn't exist"},
        409: {
            "model": schemas.ErrorResponse,
            "description": "Given id already exists, or a class with this grade+section already exists",
        },
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def create_class(payload: schemas.ClassIn, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    if payload.teacher_id:
        _get_or_404(db, models.Teacher, payload.teacher_id, "TEACHER_NOT_FOUND", "teacher")
    _check_class_uniqueness(db, payload.grade, payload.section)

    row_id = payload.id or utils.generate_id("cls_")
    if db.query(models.Class).filter(models.Class.id == row_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ID_ALREADY_EXISTS", "message": f"Class '{row_id}' already exists"},
        )

    row = models.Class(
        id=row_id,
        name=payload.name,
        grade=payload.grade,
        section=payload.section,
        room=payload.room,
        teacher_id=payload.teacher_id,
    )
    db.add(row)
    db.commit()
    return row


@router.put(
    "/classes/{class_id}",
    tags=["admin-classes"],
    response_model=schemas.ClassOut,
    summary="Update a class",
    description="Partial update — only send the fields you want to change.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "Class or given teacher_id doesn't exist"},
        409: {"model": schemas.ErrorResponse, "description": "Resulting grade+section already exists on another class"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def update_class(
    class_id: str,
    payload: schemas.ClassUpdate,
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    row = _get_or_404(db, models.Class, class_id, "CLASS_NOT_FOUND", "class")
    fields = payload.model_dump(exclude_unset=True)
    if "teacher_id" in fields and fields["teacher_id"]:
        _get_or_404(db, models.Teacher, fields["teacher_id"], "TEACHER_NOT_FOUND", "teacher")

    merged_grade = fields.get("grade", row.grade)
    merged_section = fields.get("section", row.section)
    _check_class_uniqueness(db, merged_grade, merged_section, exclude_id=class_id)

    _apply_updates(row, payload, set(fields.keys()))
    db.commit()
    return row


@router.delete(
    "/classes/{class_id}",
    tags=["admin-classes"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a class",
    description="Blocked if any schedule entries still reference this class.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No class with that id"},
        409: {"model": schemas.ErrorResponse, "description": "Class is still referenced by schedule entries"},
    },
)
def delete_class(class_id: str, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    row = _get_or_404(db, models.Class, class_id, "CLASS_NOT_FOUND", "class")
    _check_in_use(
        db,
        models.Schedule,
        models.Schedule.class_id,
        class_id,
        "CLASS_IN_USE",
        "This class still has schedule entries — remove those first",
    )
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


@router.get(
    "/subjects",
    tags=["admin-subjects"],
    response_model=List[schemas.SubjectOut],
    summary="List all subjects",
    description="Filter by `is_active` (true/false, omit for both), `name`, and/or `code` "
    "(both partial, case-insensitive search).",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"}},
)
def list_subjects(
    is_active: Optional[bool] = Query(None),
    name: Optional[str] = Query(None, description="Partial, case-insensitive match on name"),
    code: Optional[str] = Query(None, description="Partial, case-insensitive match on code"),
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    query = db.query(models.Subject)
    if is_active is not None:
        query = query.filter(models.Subject.is_active == is_active)
    if name:
        query = query.filter(models.Subject.name.ilike(f"%{name.strip()}%"))
    if code:
        query = query.filter(models.Subject.code.ilike(f"%{code.strip()}%"))
    return query.order_by(models.Subject.name).all()


@router.get(
    "/subjects/{subject_id}",
    tags=["admin-subjects"],
    response_model=schemas.SubjectOut,
    summary="Get one subject",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No subject with that id"},
    },
)
def get_subject(subject_id: str, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    return _get_or_404(db, models.Subject, subject_id, "SUBJECT_NOT_FOUND", "subject")


@router.post(
    "/subjects",
    tags=["admin-subjects"],
    response_model=schemas.SubjectOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a subject",
    description="`id` is auto-generated (`sub_xxxxxxxx`) if omitted.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        409: {"model": schemas.ErrorResponse, "description": "Given id already exists"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def create_subject(payload: schemas.SubjectIn, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    row_id = payload.id or utils.generate_id("sub_")
    if db.query(models.Subject).filter(models.Subject.id == row_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ID_ALREADY_EXISTS", "message": f"Subject '{row_id}' already exists"},
        )
    row = models.Subject(id=row_id, name=payload.name, code=payload.code, is_active=True)
    db.add(row)
    db.commit()
    return row


@router.put(
    "/subjects/{subject_id}",
    tags=["admin-subjects"],
    response_model=schemas.SubjectOut,
    summary="Update a subject",
    description="Partial update — only send the fields you want to change.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No subject with that id"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def update_subject(
    subject_id: str,
    payload: schemas.SubjectUpdate,
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    row = _get_or_404(db, models.Subject, subject_id, "SUBJECT_NOT_FOUND", "subject")
    fields = payload.model_dump(exclude_unset=True)
    _apply_updates(row, payload, set(fields.keys()))
    db.commit()
    return row


@router.post(
    "/subjects/{subject_id}/deactivate",
    tags=["admin-subjects"],
    response_model=schemas.SubjectOut,
    summary="Mark a subject inactive",
    description=(
        "Soft-delete: hides the subject from active use (new schedule entries can't reference "
        "it) without touching any existing data. Past schedule entries and results stay fully "
        "intact and readable. Reversible via /activate."
    ),
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No subject with that id"},
    },
)
def deactivate_subject(subject_id: str, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    row = _get_or_404(db, models.Subject, subject_id, "SUBJECT_NOT_FOUND", "subject")
    row.is_active = False
    db.commit()
    return row


@router.post(
    "/subjects/{subject_id}/activate",
    tags=["admin-subjects"],
    response_model=schemas.SubjectOut,
    summary="Mark a subject active again",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No subject with that id"},
    },
)
def activate_subject(subject_id: str, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    row = _get_or_404(db, models.Subject, subject_id, "SUBJECT_NOT_FOUND", "subject")
    row.is_active = True
    db.commit()
    return row


# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------


@router.get(
    "/exams",
    tags=["admin-exams"],
    response_model=List[schemas.ExamOut],
    summary="List all exams",
    description="Filter by `status` (upcoming/ongoing/grading/ended), `name` (partial, "
    "case-insensitive search), and/or date range on `start_date` or `end_date`.",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"}},
)
def list_exams(
    status_filter: Optional[schemas.ExamStatus] = Query(None, alias="status"),
    name: Optional[str] = Query(None, description="Partial, case-insensitive match on name"),
    start_date_from: Optional[date] = Query(None, description="Inclusive lower bound on `start_date`"),
    start_date_to: Optional[date] = Query(None, description="Inclusive upper bound on `start_date`"),
    end_date_from: Optional[date] = Query(None, description="Inclusive lower bound on `end_date`"),
    end_date_to: Optional[date] = Query(None, description="Inclusive upper bound on `end_date`"),
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    query = db.query(models.Exam)
    if status_filter:
        query = query.filter(models.Exam.status == status_filter)
    if name:
        query = query.filter(models.Exam.name.ilike(f"%{name.strip()}%"))
    if start_date_from:
        query = query.filter(models.Exam.start_date >= start_date_from)
    if start_date_to:
        query = query.filter(models.Exam.start_date <= start_date_to)
    if end_date_from:
        query = query.filter(models.Exam.end_date >= end_date_from)
    if end_date_to:
        query = query.filter(models.Exam.end_date <= end_date_to)
    return query.order_by(models.Exam.start_date.desc()).all()


@router.get(
    "/exams/{exam_id}",
    tags=["admin-exams"],
    response_model=schemas.ExamOut,
    summary="Get one exam",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No exam with that id"},
    },
)
def get_exam(exam_id: str, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    return _get_or_404(db, models.Exam, exam_id, "EXAM_NOT_FOUND", "exam")


@router.post(
    "/exams",
    tags=["admin-exams"],
    response_model=schemas.ExamOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an exam",
    description=(
        "`id` is auto-generated (`exam_xxxxxxxx`) if omitted. `status` must be one of: "
        "upcoming, ongoing, grading, ended. `start_date` must not be after `end_date`."
    ),
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        409: {"model": schemas.ErrorResponse, "description": "Given id already exists"},
        422: {
            "model": schemas.ValidationErrorResponse,
            "description": "Malformed body, invalid status value, or start_date after end_date",
        },
    },
)
def create_exam(payload: schemas.ExamIn, db: Session = Depends(get_db), principal: dict = ACADEMIC):
    row_id = payload.id or utils.generate_id("exam_")
    if db.query(models.Exam).filter(models.Exam.id == row_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ID_ALREADY_EXISTS", "message": f"Exam '{row_id}' already exists"},
        )
    row = models.Exam(
        id=row_id,
        name=payload.name,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status=payload.status,
    )
    db.add(row)
    utils.log_audit(db, principal["id"], principal["role"], "create", "exam", row_id)
    db.commit()
    return row


@router.put(
    "/exams/{exam_id}",
    tags=["admin-exams"],
    response_model=schemas.ExamOut,
    summary="Update an exam",
    description=(
        "Partial update — only send the fields you want to change. `status` must be one of: "
        "upcoming, ongoing, grading, ended. The resulting start_date/end_date (after merging "
        "with whichever you didn't send) must not have start after end."
    ),
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No exam with that id"},
        422: {
            "model": schemas.ErrorResponse,
            "description": "Invalid status value, or resulting start_date after end_date (INVALID_DATE_RANGE)",
        },
    },
)
def update_exam(
    exam_id: str, payload: schemas.ExamUpdate, db: Session = Depends(get_db), principal: dict = ACADEMIC
):
    row = _get_or_404(db, models.Exam, exam_id, "EXAM_NOT_FOUND", "exam")
    fields = payload.model_dump(exclude_unset=True)

    merged_start = fields.get("start_date", row.start_date)
    merged_end = fields.get("end_date", row.end_date)
    if merged_start and merged_end and merged_start > merged_end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "INVALID_DATE_RANGE",
                "message": f"start_date ({merged_start}) cannot be after end_date ({merged_end})",
            },
        )

    _apply_updates(row, payload, set(fields.keys()))
    utils.log_audit(db, principal["id"], principal["role"], "update", "exam", exam_id)
    db.commit()
    return row


@router.delete(
    "/exams/{exam_id}",
    tags=["admin-exams"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an exam",
    description="Blocked if any results still reference this exam.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No exam with that id"},
        409: {"model": schemas.ErrorResponse, "description": "Exam is still referenced by results"},
    },
)
def delete_exam(exam_id: str, db: Session = Depends(get_db), principal: dict = ACADEMIC):
    row = _get_or_404(db, models.Exam, exam_id, "EXAM_NOT_FOUND", "exam")
    _check_in_use(
        db,
        models.Result,
        models.Result.exam_id,
        exam_id,
        "EXAM_IN_USE",
        "This exam still has result entries — remove those first",
    )
    db.delete(row)
    utils.log_audit(db, principal["id"], principal["role"], "delete", "exam", exam_id)
    db.commit()


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------


@router.get(
    "/periods",
    tags=["admin-periods"],
    response_model=List[schemas.PeriodOut],
    summary="List all periods",
    description="Ordered by `sort_order` (the daily sequence: per_1, per_2, break, ...).",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"}},
)
def list_periods(db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    return db.query(models.Period).order_by(models.Period.sort_order).all()


@router.get(
    "/periods/{period_id}",
    tags=["admin-periods"],
    response_model=schemas.PeriodOut,
    summary="Get one period",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No period with that id"},
    },
)
def get_period(period_id: str, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    return _get_or_404(db, models.Period, period_id, "PERIOD_NOT_FOUND", "period")


@router.post(
    "/periods",
    tags=["admin-periods"],
    response_model=schemas.PeriodOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a period",
    description="`id` is auto-generated (`per_xxxxxxxx`) if omitted. `start_time`/`end_time` must "
    "be 24-hour `HH:MM` with start before end. `sort_order` and time range must not collide "
    "with an existing period.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        409: {
            "model": schemas.ErrorResponse,
            "description": "Given id already exists, sort_order is taken, or time range overlaps another period",
        },
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed body, bad time format, or start after end"},
    },
)
def create_period(payload: schemas.PeriodIn, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    _check_period_conflicts(db, payload.sort_order, payload.start_time, payload.end_time)

    row_id = payload.id or utils.generate_id("per_")
    if db.query(models.Period).filter(models.Period.id == row_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ID_ALREADY_EXISTS", "message": f"Period '{row_id}' already exists"},
        )
    row = models.Period(
        id=row_id,
        sort_order=payload.sort_order,
        start_time=payload.start_time,
        end_time=payload.end_time,
        is_break=payload.is_break,
        label=payload.label,
    )
    db.add(row)
    db.commit()
    return row


@router.put(
    "/periods/{period_id}",
    tags=["admin-periods"],
    response_model=schemas.PeriodOut,
    summary="Update a period",
    description="Partial update — only send the fields you want to change. The resulting "
    "sort_order and time range (after merging with whatever you didn't send) are checked "
    "against every other period.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No period with that id"},
        409: {"model": schemas.ErrorResponse, "description": "Resulting sort_order or time range conflicts with another period"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed body, bad time format, or start after end"},
    },
)
def update_period(
    period_id: str,
    payload: schemas.PeriodUpdate,
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    row = _get_or_404(db, models.Period, period_id, "PERIOD_NOT_FOUND", "period")
    fields = payload.model_dump(exclude_unset=True)

    merged_sort_order = fields.get("sort_order", row.sort_order)
    merged_start = fields.get("start_time", row.start_time)
    merged_end = fields.get("end_time", row.end_time)
    if merged_start >= merged_end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "INVALID_TIME_RANGE",
                "message": f"start_time ({merged_start}) must be before end_time ({merged_end})",
            },
        )
    _check_period_conflicts(db, merged_sort_order, merged_start, merged_end, exclude_id=period_id)

    _apply_updates(row, payload, set(fields.keys()))
    db.commit()
    return row


@router.delete(
    "/periods/{period_id}",
    tags=["admin-periods"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a period",
    description="Blocked if any schedule entries still reference this period.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No period with that id"},
        409: {"model": schemas.ErrorResponse, "description": "Period is still referenced by schedule entries"},
    },
)
def delete_period(period_id: str, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    row = _get_or_404(db, models.Period, period_id, "PERIOD_NOT_FOUND", "period")
    _check_in_use(
        db,
        models.Schedule,
        models.Schedule.period_id,
        period_id,
        "PERIOD_IN_USE",
        "This period still has schedule entries — remove those first",
    )
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------


@router.get(
    "/schedule",
    tags=["admin-schedule"],
    response_model=schemas.Page[schemas.ScheduleOut],
    summary="List schedule entries",
    description="Filter by `class_id`, `teacher_id`, and/or `day`. Paginated via `limit`/`offset`.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        422: {"model": schemas.ErrorResponse, "description": "Invalid `day` value"},
    },
)
def list_schedule(
    class_id: Optional[str] = Query(None),
    teacher_id: Optional[str] = Query(None),
    day: Optional[str] = Query(None, description="e.g. Sunday or sun"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    query = db.query(models.Schedule)
    if class_id:
        query = query.filter(models.Schedule.class_id == class_id)
    if teacher_id:
        query = query.filter(models.Schedule.teacher_id == teacher_id)
    if day:
        query = query.filter(models.Schedule.day == utils.normalize_day(day))
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return schemas.Page(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/schedule/{schedule_id}",
    tags=["admin-schedule"],
    response_model=schemas.ScheduleOut,
    summary="Get one schedule entry",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No schedule entry with that id"},
    },
)
def get_schedule_entry(schedule_id: str, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    return _get_or_404(db, models.Schedule, schedule_id, "SCHEDULE_NOT_FOUND", "schedule entry")


@router.post(
    "/schedule",
    tags=["admin-schedule"],
    response_model=schemas.ScheduleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a schedule entry",
    description="`id` is auto-generated (`sch_xxxxxxxx`) if omitted. `day` accepts full names "
    "or 3-letter codes. `class_id`, `subject_id`, and `teacher_id` are validated to exist. "
    "Also checks for time-overlap conflicts on the same day against the same teacher, class, "
    "or room.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "class_id/subject_id/teacher_id/period_id doesn't exist"},
        409: {
            "model": schemas.ErrorResponse,
            "description": "Given id already exists, subject is inactive, or this slot conflicts "
            "with an existing entry for the same teacher/class/room "
            "(TEACHER_SCHEDULE_CONFLICT / CLASS_SCHEDULE_CONFLICT / ROOM_SCHEDULE_CONFLICT)",
        },
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body, or invalid day"},
    },
)
def create_schedule_entry(
    payload: schemas.ScheduleIn, db: Session = Depends(get_db), _principal: dict = ACADEMIC
):
    _get_or_404(db, models.Class, payload.class_id, "CLASS_NOT_FOUND", "class")
    subject = _get_or_404(db, models.Subject, payload.subject_id, "SUBJECT_NOT_FOUND", "subject")
    if not subject.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "SUBJECT_INACTIVE",
                "message": f"Subject '{payload.subject_id}' is inactive and can't be scheduled",
            },
        )
    _get_or_404(db, models.Teacher, payload.teacher_id, "TEACHER_NOT_FOUND", "teacher")
    if payload.period_id:
        _get_or_404(db, models.Period, payload.period_id, "PERIOD_NOT_FOUND", "period")
    normalized_day = utils.normalize_day(payload.day)

    _check_schedule_conflicts(
        db,
        normalized_day,
        payload.start_time,
        payload.end_time,
        payload.teacher_id,
        payload.class_id,
        payload.room,
    )

    row_id = payload.id or utils.generate_id("sch_")
    if db.query(models.Schedule).filter(models.Schedule.id == row_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ID_ALREADY_EXISTS", "message": f"Schedule entry '{row_id}' already exists"},
        )

    row = models.Schedule(
        id=row_id,
        class_id=payload.class_id,
        subject_id=payload.subject_id,
        teacher_id=payload.teacher_id,
        day=normalized_day,
        start_time=payload.start_time,
        end_time=payload.end_time,
        room=payload.room,
        period_id=payload.period_id,
    )
    db.add(row)
    db.commit()
    return row


@router.put(
    "/schedule/{schedule_id}",
    tags=["admin-schedule"],
    response_model=schemas.ScheduleOut,
    summary="Update a schedule entry",
    description="Partial update — only send the fields you want to change. The resulting "
    "slot (after merging with whatever you didn't send) is checked for time-overlap "
    "conflicts against the same teacher, class, or room.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "Entry or a referenced id doesn't exist"},
        409: {
            "model": schemas.ErrorResponse,
            "description": "Subject is inactive, or the resulting slot conflicts with an existing "
            "entry for the same teacher/class/room",
        },
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body, or invalid day"},
    },
)
def update_schedule_entry(
    schedule_id: str,
    payload: schemas.ScheduleUpdate,
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    row = _get_or_404(db, models.Schedule, schedule_id, "SCHEDULE_NOT_FOUND", "schedule entry")
    fields = payload.model_dump(exclude_unset=True)

    if "class_id" in fields:
        _get_or_404(db, models.Class, fields["class_id"], "CLASS_NOT_FOUND", "class")
    if "subject_id" in fields:
        subject = _get_or_404(db, models.Subject, fields["subject_id"], "SUBJECT_NOT_FOUND", "subject")
        if not subject.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "SUBJECT_INACTIVE",
                    "message": f"Subject '{fields['subject_id']}' is inactive and can't be scheduled",
                },
            )
    if "teacher_id" in fields:
        _get_or_404(db, models.Teacher, fields["teacher_id"], "TEACHER_NOT_FOUND", "teacher")
    if "period_id" in fields and fields["period_id"]:
        _get_or_404(db, models.Period, fields["period_id"], "PERIOD_NOT_FOUND", "period")
    if "day" in fields:
        fields["day"] = utils.normalize_day(fields["day"])

    merged_day = fields.get("day", row.day)
    merged_start = fields.get("start_time", row.start_time)
    merged_end = fields.get("end_time", row.end_time)
    if merged_start >= merged_end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "INVALID_TIME_RANGE",
                "message": f"start_time ({merged_start}) must be before end_time ({merged_end})",
            },
        )
    merged_teacher = fields.get("teacher_id", row.teacher_id)
    merged_class = fields.get("class_id", row.class_id)
    merged_room = fields.get("room", row.room)
    _check_schedule_conflicts(
        db, merged_day, merged_start, merged_end, merged_teacher, merged_class, merged_room,
        exclude_id=schedule_id,
    )

    for field, value in fields.items():
        setattr(row, field, value)
    db.commit()
    return row


@router.delete(
    "/schedule/{schedule_id}",
    tags=["admin-schedule"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a schedule entry",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No schedule entry with that id"},
    },
)
def delete_schedule_entry(schedule_id: str, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    row = _get_or_404(db, models.Schedule, schedule_id, "SCHEDULE_NOT_FOUND", "schedule entry")
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# Attendance (admin, academic)
# ---------------------------------------------------------------------------


@router.get(
    "/attendance",
    response_model=schemas.Page[schemas.AttendanceAdminOut],
    tags=["admin-attendance"],
    summary="List attendance records (admin)",
    description="Filter by `class_id`, `student_id`, and/or a `date` range. Paginated via "
    "`limit`/`offset` (limit up to 2000 for month-wide class views). Ordered most-recent first.",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"}},
)
def list_admin_attendance(
    class_id: Optional[str] = Query(None),
    student_id: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None, description="Inclusive lower bound on date"),
    to_date: Optional[date] = Query(None, description="Inclusive upper bound on date"),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    query = (
        db.query(
            models.Attendance,
            models.Student.name.label("student_name"),
            models.Student.class_id.label("class_id"),
        )
        .join(models.Student, models.Attendance.student_id == models.Student.id)
    )
    if class_id:
        query = query.filter(models.Student.class_id == class_id)
    if student_id:
        query = query.filter(models.Attendance.student_id == student_id)
    if from_date:
        query = query.filter(models.Attendance.date >= from_date)
    if to_date:
        query = query.filter(models.Attendance.date <= to_date)

    total = query.count()
    rows = query.order_by(models.Attendance.date.desc()).offset(offset).limit(limit).all()
    items = [
        schemas.AttendanceAdminOut(
            id=att.id, student_id=att.student_id, student_name=name, class_id=cid, date=att.date, status=att.status
        )
        for att, name, cid in rows
    ]
    return schemas.Page(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/attendance",
    response_model=List[schemas.AttendanceOut],
    tags=["admin-attendance"],
    summary="Mark/update attendance for a set of students on a date (admin)",
    description="Bulk insert-or-update: `{date, records:[{student_id, status}]}`. Re-submitting "
    "for the same student + date updates the existing record. `status` must be one of: present, "
    "absent, late, excused.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def mark_admin_attendance(
    payload: schemas.AttendanceBulkIn,
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    year_month = payload.date.isoformat()[:7]
    saved: List[models.Attendance] = []
    for record in payload.records:
        student = db.query(models.Student).filter(models.Student.id == record.student_id).first()

        row_id = f"att_{record.student_id}_{payload.date.isoformat()}"
        row = db.query(models.Attendance).filter(models.Attendance.id == row_id).first()
        old_status = row.status if row else None
        if row:
            row.status = record.status
        else:
            row = models.Attendance(
                id=row_id, student_id=record.student_id, date=payload.date, status=record.status
            )
            db.add(row)
        # Skip the count update (not the save) if the student has no class to attribute it to.
        if student and student.class_id:
            utils.apply_attendance_count_delta(db, student.class_id, year_month, old_status, record.status)
        saved.append(row)
    db.commit()
    return saved


# ---------------------------------------------------------------------------
# Results (admin, academic)
# ---------------------------------------------------------------------------


@router.get(
    "/results",
    response_model=schemas.Page[schemas.ResultAdminOut],
    tags=["admin-results"],
    summary="List results (admin)",
    description="Filter by `class_id`, `student_id`, `subject_id`, and/or `exam_id`. Includes "
    "joined subject and student names. Paginated via `limit`/`offset` (up to 2000).",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"}},
)
def list_admin_results(
    class_id: Optional[str] = Query(None),
    student_id: Optional[str] = Query(None),
    subject_id: Optional[str] = Query(None),
    exam_id: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    query = (
        db.query(
            models.Result,
            models.Student.name.label("student_name"),
            models.Student.class_id.label("class_id"),
            models.Subject.name.label("subject_name"),
            models.Subject.code.label("subject_code"),
        )
        .join(models.Student, models.Result.student_id == models.Student.id)
        .outerjoin(models.Subject, models.Result.subject_id == models.Subject.id)
    )
    if class_id:
        query = query.filter(models.Student.class_id == class_id)
    if student_id:
        query = query.filter(models.Result.student_id == student_id)
    if subject_id:
        query = query.filter(models.Result.subject_id == subject_id)
    if exam_id:
        query = query.filter(models.Result.exam_id == exam_id)

    total = query.count()
    rows = query.order_by(models.Result.student_id).offset(offset).limit(limit).all()
    items = [
        schemas.ResultAdminOut(
            id=r.id, student_id=r.student_id, student_name=sname, class_id=cid,
            exam_id=r.exam_id, exam=r.exam, subject_id=r.subject_id,
            subject_name=subj_name, subject_code=subj_code,
            marks=r.marks, total=r.total, grade=r.grade, remarks=r.remarks,
        )
        for r, sname, cid, subj_name, subj_code in rows
    ]
    return schemas.Page(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/results",
    response_model=schemas.ResultOut,
    tags=["admin-results"],
    summary="Create or update one result (admin)",
    description="Upsert by (student, subject, exam). `grade` is computed server-side from "
    "marks/total. Re-submitting for the same student+subject+exam updates the existing record.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "exam_id or subject_id doesn't exist"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed body, or marks > total"},
    },
)
def upsert_admin_result(
    payload: schemas.ResultAdminIn,
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    exam = _get_or_404(db, models.Exam, payload.exam_id, "EXAM_NOT_FOUND", "exam")
    subject = _get_or_404(db, models.Subject, payload.subject_id, "SUBJECT_NOT_FOUND", "subject")
    student = _get_or_404(db, models.Student, payload.student_id, "STUDENT_NOT_FOUND", "student")
    if payload.marks > payload.total:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "INVALID_MARKS", "message": "marks cannot exceed total"},
        )
    computed_grade = utils.compute_grade(payload.marks, payload.total)
    row_id = f"res_{payload.student_id}_{payload.exam_id}_{payload.subject_id}"
    row = db.query(models.Result).filter(models.Result.id == row_id).first()
    old_marks = row.marks if row else None
    if row:
        row.marks = payload.marks
        row.total = payload.total
        row.grade = computed_grade
        row.remarks = payload.remarks
    else:
        row = models.Result(
            id=row_id, student_id=payload.student_id, subject_id=payload.subject_id,
            exam=exam.name, exam_id=payload.exam_id, marks=payload.marks, total=payload.total,
            grade=computed_grade, remarks=payload.remarks,
        )
        db.add(row)
    if student.class_id:
        utils.apply_result_count_delta(
            db, student.class_id, payload.student_id, payload.subject_id, payload.exam_id,
            old_marks, payload.marks,
        )
    db.commit()
    return schemas.ResultOut(
        id=row.id, exam_id=row.exam_id, exam=row.exam, subject_id=row.subject_id,
        subject_name=subject.name, subject_code=subject.code, marks=row.marks,
        total=row.total, grade=row.grade, remarks=row.remarks,
    )


@router.delete(
    "/results/{result_id}",
    tags=["admin-results"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a result (admin)",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No result with that id"},
    },
)
def delete_admin_result(result_id: str, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    row = _get_or_404(db, models.Result, result_id, "RESULT_NOT_FOUND", "result")
    student = db.query(models.Student).filter(models.Student.id == row.student_id).first()
    if student and student.class_id:
        utils.apply_result_count_delta(
            db, student.class_id, row.student_id, row.subject_id, row.exam_id, row.marks, None,
        )
    db.delete(row)
    db.commit()