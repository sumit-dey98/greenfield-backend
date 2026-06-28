from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from .. import models, oauth2, schemas, utils
from ..database import get_db
from ..utils import normalize_day

router = APIRouter(prefix="/teachers", tags=["teachers"])


def _get_homeroom_class(db: Session, teacher_id: str) -> models.Class:
    """A teacher's homeroom class is the row in `classes` where teacher_id points back to them."""
    cls = db.query(models.Class).filter(models.Class.teacher_id == teacher_id).first()
    if not cls:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "NO_HOMEROOM_CLASS",
                "message": "You are not assigned as the homeroom teacher of any class",
            },
        )
    return cls


@router.get(
    "/me",
    response_model=schemas.TeacherOut,
    summary="Get the logged-in teacher's own profile",
    description="Accessible only to access tokens with `user_type: teacher`.",
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {"model": schemas.ErrorResponse, "description": "Token is valid but not a teacher account"},
    },
)
def my_profile(
    principal: dict = Depends(oauth2.require_user_type("teacher")),
    db: Session = Depends(get_db),
):
    return db.query(models.Teacher).filter(models.Teacher.id == principal["id"]).first()


@router.get(
    "/me/class",
    response_model=schemas.ClassRosterOut,
    summary="Get the logged-in teacher's homeroom class and its student roster",
    description="A teacher is a homeroom teacher if `classes.teacher_id` points to them. "
    "Optionally filter the roster with `name` (partial, case-insensitive match). "
    "Returns 404 if they aren't assigned to any class.",
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {"model": schemas.ErrorResponse, "description": "Token is valid but not a teacher account"},
        404: {"model": schemas.ErrorResponse, "description": "Teacher has no homeroom class assigned"},
    },
)
def my_class(
    name: Optional[str] = Query(None, description="Partial, case-insensitive match on student name"),
    principal: dict = Depends(oauth2.require_user_type("teacher")),
    db: Session = Depends(get_db),
):
    cls = _get_homeroom_class(db, principal["id"])
    query = db.query(models.Student).filter(models.Student.class_id == cls.id)
    if name:
        query = query.filter(models.Student.name.ilike(f"%{name.strip()}%"))
    students = query.order_by(models.Student.roll).all()
    return schemas.ClassRosterOut(class_info=cls, students=students)


@router.get(
    "/me/schedule",
    response_model=List[schemas.TeacherScheduleEntryOut],
    summary="Get the logged-in teacher's full teaching schedule",
    description="Every period this teacher teaches, across all classes — not just their "
    "homeroom class. Optionally filter to one weekday via `day` (full name or 3-letter code, "
    "e.g. `Sunday` or `sun`). Includes joined class and subject names.",
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {"model": schemas.ErrorResponse, "description": "Token is valid but not a teacher account"},
        422: {"model": schemas.ErrorResponse, "description": "Invalid `day` value"},
    },
)
def my_schedule(
    day: Optional[str] = Query(None, description="Filter to one weekday, e.g. Sunday or sun"),
    principal: dict = Depends(oauth2.require_user_type("teacher")),
    db: Session = Depends(get_db),
):
    normalized_day = normalize_day(day) if day else None

    query = (
        db.query(
            models.Schedule,
            models.Class.name.label("class_name"),
            models.Subject.name.label("subject_name"),
        )
        .outerjoin(models.Class, models.Schedule.class_id == models.Class.id)
        .outerjoin(models.Subject, models.Schedule.subject_id == models.Subject.id)
        .filter(models.Schedule.teacher_id == principal["id"])
    )
    if normalized_day:
        query = query.filter(models.Schedule.day == normalized_day)
    rows = query.all()

    return [
        schemas.TeacherScheduleEntryOut(
            id=sch.id,
            day=sch.day,
            start_time=sch.start_time,
            end_time=sch.end_time,
            room=sch.room,
            class_id=sch.class_id,
            class_name=class_name,
            subject_id=sch.subject_id,
            subject_name=subject_name,
        )
        for sch, class_name, subject_name in rows
    ]


@router.get(
    "/me/attendance",
    response_model=schemas.Page[schemas.TeacherAttendanceOut],
    summary="Get attendance records for the teacher's homeroom class",
    description=(
        "Restricted to your homeroom roster. Optionally filter by date range and/or a single "
        "`student_id` (must be a member of your homeroom class). Ordered most-recent first. "
        "Paginated via `limit`/`offset`."
    ),
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {
            "model": schemas.ErrorResponse,
            "description": "Not a teacher account, or student_id isn't in this teacher's homeroom class",
        },
        404: {"model": schemas.ErrorResponse, "description": "Teacher has no homeroom class assigned"},
    },
)
def my_class_attendance(
    from_date: Optional[date] = Query(None, description="Inclusive lower bound, e.g. 2025-10-01"),
    to_date: Optional[date] = Query(None, description="Inclusive upper bound, e.g. 2025-10-31"),
    student_id: Optional[str] = Query(None, description="Filter to one student in your homeroom class"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: dict = Depends(oauth2.require_user_type("teacher")),
    db: Session = Depends(get_db),
):
    cls = _get_homeroom_class(db, principal["id"])
    roster_ids = {
        s.id for s in db.query(models.Student.id).filter(models.Student.class_id == cls.id).all()
    }

    if student_id and student_id not in roster_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "STUDENT_NOT_IN_CLASS",
                "message": f"Student '{student_id}' is not in your homeroom class",
            },
        )

    query = (
        db.query(models.Attendance, models.Student.name.label("student_name"))
        .join(models.Student, models.Attendance.student_id == models.Student.id)
        .filter(models.Attendance.student_id.in_(roster_ids))
    )
    if student_id:
        query = query.filter(models.Attendance.student_id == student_id)
    if from_date:
        query = query.filter(models.Attendance.date >= from_date)
    if to_date:
        query = query.filter(models.Attendance.date <= to_date)

    total = query.count()
    rows = (
        query.order_by(models.Attendance.date.desc(), models.Student.roll)
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = [
        schemas.TeacherAttendanceOut(
            id=att.id, student_id=att.student_id, student_name=student_name, date=att.date, status=att.status
        )
        for att, student_name in rows
    ]
    return schemas.Page(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/me/attendance",
    response_model=List[schemas.AttendanceOut],
    summary="Mark or update attendance for the teacher's homeroom class on a given date",
    description=(
        "Only the homeroom teacher of a class can mark attendance for its students. "
        "`status` must be one of: present, absent, late, excused. Re-submitting for the same "
        "student + date updates the existing record instead of duplicating it."
    ),
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {
            "model": schemas.ErrorResponse,
            "description": "Not a teacher account, or one of the student_ids isn't in this teacher's homeroom class",
        },
        404: {"model": schemas.ErrorResponse, "description": "Teacher has no homeroom class assigned"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def mark_attendance(
    payload: schemas.AttendanceBulkIn,
    principal: dict = Depends(oauth2.require_user_type("teacher")),
    db: Session = Depends(get_db),
):
    cls = _get_homeroom_class(db, principal["id"])
    roster_ids = {
        s.id for s in db.query(models.Student.id).filter(models.Student.class_id == cls.id).all()
    }

    saved: List[models.Attendance] = []
    for record in payload.records:
        if record.student_id not in roster_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": "STUDENT_NOT_IN_CLASS",
                    "message": f"Student '{record.student_id}' is not in your homeroom class",
                },
            )

        row_id = f"att_{record.student_id}_{payload.date.isoformat()}"
        row = db.query(models.Attendance).filter(models.Attendance.id == row_id).first()
        if row:
            row.status = record.status
        else:
            row = models.Attendance(
                id=row_id, student_id=record.student_id, date=payload.date, status=record.status
            )
            db.add(row)
        saved.append(row)

    db.commit()
    return saved


@router.get(
    "/me/results",
    response_model=schemas.Page[schemas.TeacherResultOut],
    summary="Get results for the classes/subjects the teacher teaches",
    description=(
        "Automatically scoped to whichever (class, subject) pairs appear in your teaching "
        "schedule. Passing a `class_id` or `subject_id` you don't actually teach simply "
        "returns no rows rather than an error. Filter further with `exam_id` and/or `student_id`. "
        "Paginated via `limit`/`offset`."
    ),
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {"model": schemas.ErrorResponse, "description": "Token is valid but not a teacher account"},
    },
)
def my_taught_results(
    class_id: Optional[str] = Query(None, description="Restrict to one class"),
    subject_id: Optional[str] = Query(None, description="Restrict to one subject"),
    exam_id: Optional[str] = Query(None, description="Restrict to one exam"),
    student_id: Optional[str] = Query(None, description="Restrict to one student"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: dict = Depends(oauth2.require_user_type("teacher")),
    db: Session = Depends(get_db),
):
    taught_pairs = (
        db.query(models.Schedule.class_id, models.Schedule.subject_id)
        .filter(models.Schedule.teacher_id == principal["id"])
        .distinct()
        .all()
    )
    if not taught_pairs:
        return schemas.Page(items=[], total=0, limit=limit, offset=offset)

    pair_filters = [
        and_(models.Student.class_id == c, models.Result.subject_id == s) for c, s in taught_pairs
    ]

    query = (
        db.query(
            models.Result,
            models.Student.name.label("student_name"),
            models.Subject.name.label("subject_name"),
        )
        .join(models.Student, models.Result.student_id == models.Student.id)
        .outerjoin(models.Subject, models.Result.subject_id == models.Subject.id)
        .filter(or_(*pair_filters))
    )
    if class_id:
        query = query.filter(models.Student.class_id == class_id)
    if subject_id:
        query = query.filter(models.Result.subject_id == subject_id)
    if exam_id:
        query = query.filter(models.Result.exam_id == exam_id)
    if student_id:
        query = query.filter(models.Result.student_id == student_id)

    total = query.count()
    rows = query.offset(offset).limit(limit).all()

    items = [
        schemas.TeacherResultOut(
            id=result.id,
            student_id=result.student_id,
            student_name=student_name,
            exam_id=result.exam_id,
            exam=result.exam,
            subject_id=result.subject_id,
            subject_name=subject_name,
            marks=result.marks,
            total=result.total,
            grade=result.grade,
            remarks=result.remarks,
        )
        for result, student_name, subject_name in rows
    ]
    return schemas.Page(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/me/results",
    response_model=List[schemas.ResultOut],
    summary="Enter or update exam results for a class the teacher teaches",
    description=(
        "Restricted to subject + class combinations this teacher actually teaches, per the "
        "`schedule` table. `grade` is auto-calculated server-side from `marks`/`total` - it's "
        "not a request field. Scale: A+ \u226597%, A \u226593%, A- \u226590%, B+ \u226587%, B \u226583%, "
        "B- \u226580%, C+ \u226577%, C \u226573%, C- \u226570%, D \u226560%, F below 60%. "
        "Re-submitting for the same student + subject + exam updates the "
        "existing record instead of duplicating it."
    ),
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {
            "model": schemas.ErrorResponse,
            "description": "Not a teacher account, not scheduled to teach this subject to this "
            "class, or a student_id isn't in the given class",
        },
        404: {"model": schemas.ErrorResponse, "description": "exam_id or subject_id doesn't exist"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body, or marks > total"},
    },
)
def enter_results(
    payload: schemas.ResultBulkIn,
    principal: dict = Depends(oauth2.require_user_type("teacher")),
    db: Session = Depends(get_db),
):
    exam = db.query(models.Exam).filter(models.Exam.id == payload.exam_id).first()
    if not exam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "EXAM_NOT_FOUND", "message": f"No exam with id '{payload.exam_id}'"},
        )
    subject = db.query(models.Subject).filter(models.Subject.id == payload.subject_id).first()
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "SUBJECT_NOT_FOUND", "message": f"No subject with id '{payload.subject_id}'"},
        )

    teaches_it = (
        db.query(models.Schedule)
        .filter(
            models.Schedule.teacher_id == principal["id"],
            models.Schedule.class_id == payload.class_id,
            models.Schedule.subject_id == payload.subject_id,
        )
        .first()
    )
    if not teaches_it:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "NOT_SCHEDULED_FOR_CLASS",
                "message": "You are not scheduled to teach this subject to this class",
            },
        )

    roster_ids = {
        s.id
        for s in db.query(models.Student.id).filter(models.Student.class_id == payload.class_id).all()
    }

    saved: List[models.Result] = []
    for record in payload.records:
        if record.student_id not in roster_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": "STUDENT_NOT_IN_CLASS",
                    "message": f"Student '{record.student_id}' is not in class '{payload.class_id}'",
                },
            )
        if record.marks > record.total:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_code": "INVALID_MARKS",
                    "message": f"marks ({record.marks}) cannot exceed total ({record.total}) "
                    f"for student '{record.student_id}'",
                },
            )

        row_id = f"res_{record.student_id}_{payload.exam_id}_{payload.subject_id}"
        computed_grade = utils.compute_grade(record.marks, record.total)
        row = db.query(models.Result).filter(models.Result.id == row_id).first()
        if row:
            row.marks = record.marks
            row.total = record.total
            row.grade = computed_grade
            row.remarks = record.remarks
            utils.log_audit(db, principal["id"], principal["role"], "update", "result", row_id)
        else:
            row = models.Result(
                id=row_id,
                student_id=record.student_id,
                subject_id=payload.subject_id,
                exam=exam.name,
                exam_id=payload.exam_id,
                marks=record.marks,
                total=record.total,
                grade=computed_grade,
                remarks=record.remarks,
            )
            db.add(row)
            utils.log_audit(db, principal["id"], principal["role"], "create", "result", row_id)
        saved.append(row)

    db.commit()
    return [
        schemas.ResultOut(
            id=r.id,
            exam_id=r.exam_id,
            exam=r.exam,
            subject_id=r.subject_id,
            subject_name=subject.name,
            marks=r.marks,
            total=r.total,
            grade=r.grade,
            remarks=r.remarks,
        )
        for r in saved
    ]