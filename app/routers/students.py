from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models, oauth2, schemas
from ..database import get_db
from ..utils import DAY_ORDER, normalize_day

router = APIRouter(prefix="/students", tags=["students"])


@router.get(
    "/me",
    response_model=schemas.StudentOut,
    summary="Get the logged-in student's own profile",
    description="Accessible only to access tokens with `user_type: student`.",
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {"model": schemas.ErrorResponse, "description": "Token is valid but not a student account"},
    },
)
def my_profile(
    principal: dict = Depends(oauth2.require_user_type("student")),
    db: Session = Depends(get_db),
):
    return db.query(models.Student).filter(models.Student.id == principal["id"]).first()


@router.get(
    "/me/attendance",
    response_model=List[schemas.AttendanceOut],
    summary="Get the logged-in student's attendance records",
    description="Optionally filter by a date range. Ordered most-recent first.",
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {"model": schemas.ErrorResponse, "description": "Token is valid but not a student account"},
    },
)
def my_attendance(
    from_date: Optional[date] = Query(None, description="Inclusive lower bound, e.g. 2025-10-01"),
    to_date: Optional[date] = Query(None, description="Inclusive upper bound, e.g. 2025-10-31"),
    principal: dict = Depends(oauth2.require_user_type("student")),
    db: Session = Depends(get_db),
):
    query = db.query(models.Attendance).filter(models.Attendance.student_id == principal["id"])
    if from_date:
        query = query.filter(models.Attendance.date >= from_date)
    if to_date:
        query = query.filter(models.Attendance.date <= to_date)
    return query.order_by(models.Attendance.date.desc()).all()


@router.get(
    "/me/results",
    response_model=List[schemas.ResultOut],
    summary="Get the logged-in student's exam results",
    description="Filter by `exam_id` and/or `subject_id`. Includes the joined subject name.",
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {"model": schemas.ErrorResponse, "description": "Token is valid but not a student account"},
    },
)
def my_results(
    exam_id: Optional[str] = Query(None, description="Filter to one exam, e.g. exam_1775586133218"),
    subject_id: Optional[str] = Query(None, description="Filter to one subject"),
    principal: dict = Depends(oauth2.require_user_type("student")),
    db: Session = Depends(get_db),
):
    query = (
        db.query(models.Result, models.Subject.name.label("subject_name"))
        .outerjoin(models.Subject, models.Result.subject_id == models.Subject.id)
        .filter(models.Result.student_id == principal["id"])
    )
    if exam_id:
        query = query.filter(models.Result.exam_id == exam_id)
    if subject_id:
        query = query.filter(models.Result.subject_id == subject_id)

    return [
        schemas.ResultOut(
            id=result.id,
            exam_id=result.exam_id,
            exam=result.exam,
            subject_id=result.subject_id,
            subject_name=subject_name,
            marks=result.marks,
            total=result.total,
            grade=result.grade,
            remarks=result.remarks,
        )
        for result, subject_name in query.all()
    ]


@router.get(
    "/me/schedule",
    response_model=List[schemas.ScheduleEntryOut],
    summary="Get the weekly class schedule for the logged-in student",
    description=(
        "Returns every period for the student's class, ordered Saturday→Friday and by start "
        "time within each day. Optionally filter to one weekday via `day` (full name or "
        "3-letter code, e.g. `Sunday` or `sun`). Includes joined subject and teacher names. "
        "Returns an empty list if the student isn't assigned to a class."
    ),
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {"model": schemas.ErrorResponse, "description": "Token is valid but not a student account"},
        422: {"model": schemas.ErrorResponse, "description": "Invalid `day` value"},
    },
)
def my_schedule(
    day: Optional[str] = Query(None, description="Filter to one weekday, e.g. Sunday or sun"),
    principal: dict = Depends(oauth2.require_user_type("student")),
    db: Session = Depends(get_db),
):
    normalized_day = normalize_day(day) if day else None

    student = db.query(models.Student).filter(models.Student.id == principal["id"]).first()
    if not student or not student.class_id:
        return []

    query = (
        db.query(
            models.Schedule,
            models.Subject.name.label("subject_name"),
            models.Teacher.name.label("teacher_name"),
        )
        .outerjoin(models.Subject, models.Schedule.subject_id == models.Subject.id)
        .outerjoin(models.Teacher, models.Schedule.teacher_id == models.Teacher.id)
        .filter(models.Schedule.class_id == student.class_id)
    )
    if normalized_day:
        query = query.filter(models.Schedule.day == normalized_day)
    rows = query.all()

    entries = [
        schemas.ScheduleEntryOut(
            id=sch.id,
            day=sch.day,
            start_time=sch.start_time,
            end_time=sch.end_time,
            room=sch.room,
            subject_id=sch.subject_id,
            subject_name=subject_name,
            teacher_id=sch.teacher_id,
            teacher_name=teacher_name,
        )
        for sch, subject_name, teacher_name in rows
    ]

    def sort_key(entry: schemas.ScheduleEntryOut):
        day_index = DAY_ORDER.index(entry.day) if entry.day in DAY_ORDER else len(DAY_ORDER)
        return (day_index, entry.start_time or "")

    return sorted(entries, key=sort_key)