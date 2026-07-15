from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from .. import models, oauth2, schemas, utils
from ..database import get_db

router = APIRouter(prefix="/admin/admissions", tags=["admin-admissions"])

ADMISSIONS = Depends(oauth2.require_admin_permission("admissions"))

# Single source of truth for the application status state machine (see schemas.ApplicationStatus
# for the full value list). "submitted" is never a settable target - it's only ever created by
# the public apply endpoint. "graded" is a valid edge here (grading_assigned -> graded) but is
# deliberately EXCLUDED from what PUT /{id}/status will set directly - see _ADMIN_SETTABLE_EXCLUDED.
STATUS_TRANSITIONS: dict = {
    "submitted": {"under_review"},
    "under_review": {"screening_rejected", "exam_scheduled"},
    "exam_scheduled": {"exam_completed"},
    "exam_completed": {"grading_assigned"},
    "grading_assigned": {"graded"},
    "graded": {"interview_scheduled", "waitlisted", "rejected"},
    "interview_scheduled": {"interview_completed"},
    "interview_completed": {"accepted", "rejected", "waitlisted"},
    "waitlisted": {"accepted", "rejected"},
    "accepted": {"withdrawn"},
    "rejected": {"withdrawn"},
    "screening_rejected": {"withdrawn"},
}

# "graded" is only ever set via the teacher grading-result endpoint (app/routers/teachers.py),
# never via the generic admin status endpoint below - enforced in exactly one place, here.
_ADMIN_DISALLOWED_DIRECT_TARGETS = {"graded"}


def _get_application_or_404(db: Session, application_id: str) -> models.Application:
    row = db.query(models.Application).filter(models.Application.id == application_id).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "APPLICATION_NOT_FOUND", "message": f"No application with id '{application_id}'"},
        )
    return row


def _validate_transition(current: str, target: str) -> None:
    if target in _ADMIN_DISALLOWED_DIRECT_TARGETS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "INVALID_STATUS_TRANSITION",
                "message": "'graded' cannot be set directly - use the teacher grading-result submission endpoint instead.",
            },
        )
    allowed = STATUS_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "INVALID_STATUS_TRANSITION",
                "message": f"Cannot transition from '{current}' to '{target}'. Valid next states: {sorted(allowed) or 'none (terminal)'}",
            },
        )


def _build_detail_out(db: Session, application: models.Application) -> schemas.ApplicationDetailOut:
    documents = (
        db.query(models.ApplicationDocument)
        .filter(models.ApplicationDocument.application_id == application.id)
        .all()
    )
    exam_schedule = (
        db.query(models.ApplicationExamSchedule)
        .filter(models.ApplicationExamSchedule.application_id == application.id)
        .first()
    )
    grading_row = (
        db.query(models.ApplicationGradingAssignment)
        .filter(models.ApplicationGradingAssignment.application_id == application.id)
        .first()
    )
    grading_out = None
    if grading_row:
        teacher = db.query(models.Teacher).filter(models.Teacher.id == grading_row.teacher_id).first()
        grading_out = schemas.GradingAssignmentOut(
            teacher_id=grading_row.teacher_id,
            teacher_name=teacher.name if teacher else None,
            status=grading_row.status,
            assigned_at=grading_row.assigned_at,
        )
    exam_result = (
        db.query(models.ApplicationExamResult)
        .filter(models.ApplicationExamResult.application_id == application.id)
        .first()
    )
    interview = (
        db.query(models.ApplicationInterview)
        .filter(models.ApplicationInterview.application_id == application.id)
        .first()
    )

    return schemas.ApplicationDetailOut(
        id=application.id,
        reference_number=application.reference_number,
        cycle_id=application.cycle_id,
        student_name=application.student_name,
        photo_url=application.photo_url,
        dob=application.dob,
        gender=application.gender,
        applying_class=application.applying_class,
        blood_group=application.blood_group,
        previous_school=application.previous_school,
        contact_method=application.contact_method,
        contact_email=application.contact_email,
        contact_phone=application.contact_phone,
        guardian_name=application.guardian_name,
        guardian_relationship=application.guardian_relationship,
        guardian_phone=application.guardian_phone,
        guardian_email=application.guardian_email,
        guardian_occupation=application.guardian_occupation,
        address=application.address,
        medical_conditions=application.medical_conditions,
        extracurricular=application.extracurricular,
        notes=application.notes,
        status=application.status,
        entrance_score=application.entrance_score,
        interview_outcome=application.interview_outcome,
        interview_notes=application.interview_notes,
        decision_notes=application.decision_notes,
        created_at=application.created_at,
        updated_at=application.updated_at,
        documents=documents,
        exam_schedule=exam_schedule,
        grading_assignment=grading_out,
        exam_result=exam_result,
        interview=interview,
    )


# ---------------------------------------------------------------------------
# Applications: list / detail / status transition
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=schemas.Page[schemas.ApplicationAdminOut],
    summary="List admission applications",
    description="Filter by `status`, `cycle_id`, `applying_class`, and/or `q` (partial, "
    "case-insensitive search across student_name/contact_email/contact_phone/reference_number). "
    "Paginated via `limit`/`offset`. Ordered most-recent first.",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'admissions' permission"}},
)
def list_applications(
    status_filter: Optional[schemas.ApplicationStatus] = Query(None, alias="status"),
    cycle_id: Optional[str] = Query(None),
    applying_class: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Partial, case-insensitive search across student_name/contact_email/contact_phone/reference_number"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _principal: dict = ADMISSIONS,
):
    query = db.query(models.Application)
    if status_filter:
        query = query.filter(models.Application.status == status_filter.value)
    if cycle_id:
        query = query.filter(models.Application.cycle_id == cycle_id)
    if applying_class:
        query = query.filter(models.Application.applying_class == applying_class)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                models.Application.student_name.ilike(like),
                models.Application.contact_email.ilike(like),
                models.Application.contact_phone.ilike(like),
                models.Application.reference_number.ilike(like),
            )
        )
    total = query.count()
    items = query.order_by(models.Application.created_at.desc()).offset(offset).limit(limit).all()
    return schemas.Page(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/cycles",
    response_model=schemas.Page[schemas.AdmissionCycleOut],
    summary="List admission cycles",
    description="Registered before `GET /{application_id}` so the literal path `cycles` isn't "
    "swallowed by that path-parameter route.",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'admissions' permission"}},
)
def list_cycles(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _principal: dict = ADMISSIONS,
):
    query = db.query(models.AdmissionCycle)
    total = query.count()
    items = query.order_by(models.AdmissionCycle.created_at.desc()).offset(offset).limit(limit).all()
    return schemas.Page(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/{application_id}",
    response_model=schemas.ApplicationDetailOut,
    summary="Get one application, full detail",
    description="Always shows the real `status` (never the masked `visible_status` used by the "
    "public track endpoint). Includes nested documents/exam_schedule/grading_assignment/"
    "exam_result/interview.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'admissions' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No application with that id"},
    },
)
def get_application(application_id: str, db: Session = Depends(get_db), _principal: dict = ADMISSIONS):
    application = _get_application_or_404(db, application_id)
    return _build_detail_out(db, application)


@router.put(
    "/{application_id}/status",
    response_model=schemas.ApplicationDetailOut,
    summary="Transition an application's status",
    description="Validates against the status state machine. `graded` cannot be set here - use "
    "the teacher grading-result submission endpoint. `submitted` is never a valid target - only "
    "the public apply endpoint creates applications in that state.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'admissions' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No application with that id"},
        422: {"model": schemas.ErrorResponse, "description": "Invalid status transition (INVALID_STATUS_TRANSITION)"},
    },
)
def update_status(
    application_id: str,
    payload: schemas.ApplicationStatusUpdateIn,
    db: Session = Depends(get_db),
    _principal: dict = ADMISSIONS,
):
    application = _get_application_or_404(db, application_id)
    _validate_transition(application.status, payload.status.value)
    application.status = payload.status.value
    if payload.decision_notes is not None:
        application.decision_notes = payload.decision_notes
    db.commit()
    db.refresh(application)
    return _build_detail_out(db, application)


# ---------------------------------------------------------------------------
# Exam scheduling
# ---------------------------------------------------------------------------


def _upsert_exam_schedule(db: Session, application: models.Application, exam_date, exam_time, venue) -> models.ApplicationExamSchedule:
    if application.status == "submitted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "APPLICATION_NOT_READY",
                "message": "Application must be 'under_review' or later before scheduling an exam",
            },
        )
    row = (
        db.query(models.ApplicationExamSchedule)
        .filter(models.ApplicationExamSchedule.application_id == application.id)
        .first()
    )
    if row:
        row.exam_date = exam_date
        row.exam_time = exam_time
        row.venue = venue
    else:
        row = models.ApplicationExamSchedule(
            id=utils.generate_id("aexm_"),
            application_id=application.id,
            exam_date=exam_date,
            exam_time=exam_time,
            venue=venue,
            roll_number=utils.generate_roll_number(),
        )
        db.add(row)

    if application.status == "under_review":
        application.status = "exam_scheduled"
    return row


@router.post(
    "/bulk/exam-schedule",
    response_model=List[schemas.ExamScheduleOut],
    summary="Schedule the same exam date/time/venue for multiple applications",
    description="Same fields as the single endpoint, plus `application_ids`. Each application "
    "gets its own generated `roll_number`. Applications still in 'submitted' status are skipped "
    "silently is NOT the behavior - any application not ready raises 409 for the whole batch, "
    "so schedule those individually if you need per-application error handling.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'admissions' permission"},
        404: {"model": schemas.ErrorResponse, "description": "One of the application_ids doesn't exist"},
        409: {"model": schemas.ErrorResponse, "description": "One of the applications is still in 'submitted' status"},
    },
)
def bulk_schedule_exam(
    payload: schemas.BulkExamScheduleIn,
    db: Session = Depends(get_db),
    _principal: dict = ADMISSIONS,
):
    applications = [_get_application_or_404(db, aid) for aid in payload.application_ids]
    rows = [
        _upsert_exam_schedule(db, app, payload.exam_date, payload.exam_time, payload.venue)
        for app in applications
    ]
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


@router.post(
    "/{application_id}/exam-schedule",
    response_model=schemas.ExamScheduleOut,
    summary="Schedule (or reschedule) an applicant's entrance exam",
    description="Upserts the exam schedule for one application. `roll_number` is generated once "
    "on first creation and never changes on reschedule. Auto-transitions status from "
    "`under_review` to `exam_scheduled` (no-op if already past that point). Application must be "
    "`under_review` or later - not `submitted`.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'admissions' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No application with that id"},
        409: {"model": schemas.ErrorResponse, "description": "Application is still in 'submitted' status (APPLICATION_NOT_READY)"},
    },
)
def schedule_exam(
    application_id: str,
    payload: schemas.ExamScheduleIn,
    db: Session = Depends(get_db),
    _principal: dict = ADMISSIONS,
):
    application = _get_application_or_404(db, application_id)
    row = _upsert_exam_schedule(db, application, payload.exam_date, payload.exam_time, payload.venue)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Grading assignment
# ---------------------------------------------------------------------------


def _upsert_grading_assignment(db: Session, application: models.Application, teacher_id: str, assigned_by: str) -> models.ApplicationGradingAssignment:
    if application.status != "exam_completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "APPLICATION_NOT_READY",
                "message": f"Application must be 'exam_completed' to assign grading (currently '{application.status}')",
            },
        )
    teacher = db.query(models.Teacher).filter(models.Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "TEACHER_NOT_FOUND", "message": f"No teacher with id '{teacher_id}'"},
        )
    row = (
        db.query(models.ApplicationGradingAssignment)
        .filter(models.ApplicationGradingAssignment.application_id == application.id)
        .first()
    )
    if row:
        row.teacher_id = teacher_id
        row.assigned_by = assigned_by
        row.status = "assigned"
    else:
        row = models.ApplicationGradingAssignment(
            id=utils.generate_id("agra_"),
            application_id=application.id,
            teacher_id=teacher_id,
            assigned_by=assigned_by,
            status="assigned",
        )
        db.add(row)
    application.status = "grading_assigned"
    return row


@router.post(
    "/bulk/grading-assignment",
    response_model=List[schemas.GradingAssignmentOut],
    summary="Assign the same teacher to grade multiple applications",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'admissions' permission"},
        404: {"model": schemas.ErrorResponse, "description": "One of the application_ids or the teacher_id doesn't exist"},
        409: {"model": schemas.ErrorResponse, "description": "One of the applications is not currently 'exam_completed'"},
    },
)
def bulk_assign_grading(
    payload: schemas.BulkGradingAssignmentIn,
    db: Session = Depends(get_db),
    principal: dict = ADMISSIONS,
):
    applications = [_get_application_or_404(db, aid) for aid in payload.application_ids]
    rows = [_upsert_grading_assignment(db, app, payload.teacher_id, principal["id"]) for app in applications]
    db.commit()
    out = []
    for row in rows:
        db.refresh(row)
        teacher = db.query(models.Teacher).filter(models.Teacher.id == row.teacher_id).first()
        out.append(schemas.GradingAssignmentOut(
            teacher_id=row.teacher_id, teacher_name=teacher.name if teacher else None,
            status=row.status, assigned_at=row.assigned_at,
        ))
    return out


@router.post(
    "/{application_id}/grading-assignment",
    response_model=schemas.GradingAssignmentOut,
    summary="Assign a teacher to grade one applicant's entrance exam",
    description="One teacher per applicant (no multi-grader) - re-assigning replaces the "
    "existing teacher. Auto-transitions status from `exam_completed` to `grading_assigned`; "
    "409 if the application isn't currently `exam_completed`.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'admissions' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No application or teacher with that id"},
        409: {"model": schemas.ErrorResponse, "description": "Application is not currently 'exam_completed'"},
    },
)
def assign_grading(
    application_id: str,
    payload: schemas.GradingAssignmentIn,
    db: Session = Depends(get_db),
    principal: dict = ADMISSIONS,
):
    application = _get_application_or_404(db, application_id)
    row = _upsert_grading_assignment(db, application, payload.teacher_id, principal["id"])
    db.commit()
    db.refresh(row)
    teacher = db.query(models.Teacher).filter(models.Teacher.id == row.teacher_id).first()
    return schemas.GradingAssignmentOut(
        teacher_id=row.teacher_id, teacher_name=teacher.name if teacher else None,
        status=row.status, assigned_at=row.assigned_at,
    )


# ---------------------------------------------------------------------------
# Merit list
# ---------------------------------------------------------------------------


@router.get(
    "/cycles/{cycle_id}/merit-list",
    response_model=schemas.MeritListOut,
    summary="Ranked merit list for a cycle, computed on read",
    description="Ranks graded-or-later applications by `entrance_score` (descending, NULLS "
    "last is moot here since NULL scores are excluded), using SQL `RANK() OVER (...)` - never "
    "stored. Ties share the same rank. Optional `applying_class` filter. Includes the cycle's "
    "`seats_available` in the response for the admin UI to compare against.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'admissions' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No cycle with that id"},
    },
)
def get_merit_list(
    cycle_id: str,
    applying_class: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _principal: dict = ADMISSIONS,
):
    cycle = db.query(models.AdmissionCycle).filter(models.AdmissionCycle.id == cycle_id).first()
    if not cycle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "CYCLE_NOT_FOUND", "message": f"No admission cycle with id '{cycle_id}'"},
        )

    sql = """
        SELECT id, reference_number, student_name, applying_class, entrance_score, status,
               interview_outcome,
               RANK() OVER (ORDER BY entrance_score DESC NULLS LAST) AS rank
        FROM applications
        WHERE cycle_id = :cycle_id AND entrance_score IS NOT NULL
          AND status IN ('graded','interview_scheduled','interview_completed','waitlisted','accepted','rejected')
    """
    params = {"cycle_id": cycle_id}
    if applying_class:
        sql += " AND applying_class = :applying_class"
        params["applying_class"] = applying_class
    sql += " ORDER BY entrance_score DESC NULLS LAST, created_at ASC"

    rows = db.execute(text(sql), params).mappings().all()
    items = [
        schemas.MeritListEntryOut(
            application_id=row["id"],
            reference_number=row["reference_number"],
            student_name=row["student_name"],
            applying_class=row["applying_class"],
            entrance_score=row["entrance_score"],
            rank=row["rank"],
            status=row["status"],
            interview_outcome=row["interview_outcome"],
        )
        for row in rows
    ]
    return schemas.MeritListOut(items=items, seats_available=cycle.seats_available)


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------


@router.post(
    "/{application_id}/interview-schedule",
    response_model=schemas.InterviewOut,
    summary="Schedule (or reschedule) an applicant's interview",
    description="Upserts the interview for one application. Auto-transitions status to "
    "`interview_scheduled`; the application must currently be `graded`, else 409.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'admissions' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No application with that id"},
        409: {"model": schemas.ErrorResponse, "description": "Application is not currently 'graded'"},
    },
)
def schedule_interview(
    application_id: str,
    payload: schemas.InterviewScheduleIn,
    db: Session = Depends(get_db),
    _principal: dict = ADMISSIONS,
):
    application = _get_application_or_404(db, application_id)
    if application.status != "graded":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "APPLICATION_NOT_READY",
                "message": f"Application must be 'graded' to schedule an interview (currently '{application.status}')",
            },
        )
    row = (
        db.query(models.ApplicationInterview)
        .filter(models.ApplicationInterview.application_id == application_id)
        .first()
    )
    if row:
        row.interview_date = payload.interview_date
        row.interview_time = payload.interview_time
        row.mode = payload.mode.value
        row.interviewer_name = payload.interviewer_name
    else:
        row = models.ApplicationInterview(
            id=utils.generate_id("aint_"),
            application_id=application_id,
            interview_date=payload.interview_date,
            interview_time=payload.interview_time,
            mode=payload.mode.value,
            interviewer_name=payload.interviewer_name,
        )
        db.add(row)
    application.status = "interview_scheduled"
    db.commit()
    db.refresh(row)
    return row


@router.post(
    "/{application_id}/interview-outcome",
    response_model=schemas.ApplicationDetailOut,
    summary="Record an interview outcome recommendation",
    description="Sets `interview_outcome`/`interview_notes` on the application. Auto-transitions "
    "status to `interview_completed`; the application must currently be `interview_scheduled`, "
    "else 409.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'admissions' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No application with that id"},
        409: {"model": schemas.ErrorResponse, "description": "Application is not currently 'interview_scheduled'"},
    },
)
def record_interview_outcome(
    application_id: str,
    payload: schemas.InterviewOutcomeIn,
    db: Session = Depends(get_db),
    _principal: dict = ADMISSIONS,
):
    application = _get_application_or_404(db, application_id)
    if application.status != "interview_scheduled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "APPLICATION_NOT_READY",
                "message": f"Application must be 'interview_scheduled' to record an outcome (currently '{application.status}')",
            },
        )
    application.interview_outcome = payload.interview_outcome.value
    application.interview_notes = payload.interview_notes
    application.status = "interview_completed"
    db.commit()
    db.refresh(application)
    return _build_detail_out(db, application)


# ---------------------------------------------------------------------------
# Bulk status
# ---------------------------------------------------------------------------


@router.post(
    "/bulk/status",
    response_model=schemas.BulkStatusOut,
    summary="Apply the same status transition to multiple applications",
    description="Same transition-table validation as the single status endpoint, applied "
    "per-application. Individual failures are reported in `skipped` rather than failing the "
    "whole batch.",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'admissions' permission"}},
)
def bulk_update_status(
    payload: schemas.BulkStatusIn,
    db: Session = Depends(get_db),
    _principal: dict = ADMISSIONS,
):
    updated: List[str] = []
    skipped: List[schemas.BulkActionSkip] = []
    for application_id in payload.application_ids:
        application = db.query(models.Application).filter(models.Application.id == application_id).first()
        if not application:
            skipped.append(schemas.BulkActionSkip(id=application_id, reason="Application not found"))
            continue
        if payload.status.value in _ADMIN_DISALLOWED_DIRECT_TARGETS:
            skipped.append(schemas.BulkActionSkip(id=application_id, reason="'graded' cannot be set directly"))
            continue
        allowed = STATUS_TRANSITIONS.get(application.status, set())
        if payload.status.value not in allowed:
            skipped.append(
                schemas.BulkActionSkip(
                    id=application_id,
                    reason=f"Cannot transition from '{application.status}' to '{payload.status.value}'",
                )
            )
            continue
        application.status = payload.status.value
        if payload.decision_notes is not None:
            application.decision_notes = payload.decision_notes
        updated.append(application_id)
    db.commit()
    return schemas.BulkStatusOut(updated=updated, skipped=skipped)


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------


@router.post(
    "/cycles",
    response_model=schemas.AdmissionCycleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an admission cycle",
    description="`id` is auto-generated (`cyc_xxxxxxxx`) if omitted. Does NOT automatically "
    "deactivate other cycles - set `is_active` explicitly / use PUT to enforce single-active-"
    "cycle if needed.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'admissions' permission"},
        409: {"model": schemas.ErrorResponse, "description": "Given id already exists"},
    },
)
def create_cycle(payload: schemas.AdmissionCycleIn, db: Session = Depends(get_db), _principal: dict = ADMISSIONS):
    row_id = payload.id or utils.generate_id("cyc_")
    if db.query(models.AdmissionCycle).filter(models.AdmissionCycle.id == row_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ID_ALREADY_EXISTS", "message": f"Admission cycle '{row_id}' already exists"},
        )
    if payload.is_active:
        db.query(models.AdmissionCycle).update({models.AdmissionCycle.is_active: False})
    row = models.AdmissionCycle(
        id=row_id,
        name=payload.name,
        academic_year=payload.academic_year,
        is_active=payload.is_active,
        seats_available=payload.seats_available,
        results_published=payload.results_published,
    )
    db.add(row)
    db.commit()
    return row


@router.put(
    "/cycles/{cycle_id}",
    response_model=schemas.AdmissionCycleOut,
    summary="Update an admission cycle",
    description="Partial update. If setting `is_active=True`, all OTHER cycles are set to "
    "`is_active=False` in the same transaction - only one active cycle at a time.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'admissions' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No cycle with that id"},
    },
)
def update_cycle(
    cycle_id: str,
    payload: schemas.AdmissionCycleUpdate,
    db: Session = Depends(get_db),
    _principal: dict = ADMISSIONS,
):
    row = db.query(models.AdmissionCycle).filter(models.AdmissionCycle.id == cycle_id).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "CYCLE_NOT_FOUND", "message": f"No admission cycle with id '{cycle_id}'"},
        )
    fields = payload.model_dump(exclude_unset=True)
    if fields.get("is_active") is True:
        db.query(models.AdmissionCycle).filter(models.AdmissionCycle.id != cycle_id).update(
            {models.AdmissionCycle.is_active: False}
        )
    for field, value in fields.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row
