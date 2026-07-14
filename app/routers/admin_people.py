from datetime import datetime
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


def _check_email_available(db: Session, email: str, exclude_ids: Optional[dict] = None):
    """Login resolution checks students, then teachers, then users, in that order. An email
    collision across any of these tables would make one of the accounts permanently
    unreachable at login - it'd always resolve to whichever table is checked first."""
    exclude_ids = exclude_ids or {}

    q = db.query(models.Student).filter(models.Student.email == email)
    if exclude_ids.get("student"):
        q = q.filter(models.Student.id != exclude_ids["student"])
    if q.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "EMAIL_ALREADY_IN_USE", "message": f"'{email}' is already used by a student account"},
        )

    q = db.query(models.Teacher).filter(models.Teacher.email == email)
    if exclude_ids.get("teacher"):
        q = q.filter(models.Teacher.id != exclude_ids["teacher"])
    if q.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "EMAIL_ALREADY_IN_USE", "message": f"'{email}' is already used by a teacher account"},
        )

    if db.query(models.User).filter(models.User.email == email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "EMAIL_ALREADY_IN_USE", "message": f"'{email}' is already used by an admin account"},
        )


def _student_out(row: models.Student, class_name: Optional[str]) -> schemas.StudentAdminOut:
    return schemas.StudentAdminOut(
        id=row.id,
        name=row.name,
        email=row.email,
        roll=row.roll,
        class_id=row.class_id,
        class_name=class_name,
        gender=row.gender,
        dob=row.dob,
        phone=row.phone,
        guardian=row.guardian,
        guardian_phone=row.guardian_phone,
        address=row.address,
        avatar=row.avatar,
    )


def _teacher_out(row: models.Teacher, subject_name: Optional[str], class_name: Optional[str]) -> schemas.TeacherAdminOut:
    return schemas.TeacherAdminOut(
        id=row.id,
        name=row.name,
        email=row.email,
        role=row.role,
        subject_id=row.subject_id,
        subject_name=subject_name,
        class_id=row.class_id,
        class_name=class_name,
        phone=row.phone,
        join_date=row.join_date,
        avatar=row.avatar,
        message=row.message,
        bio=row.bio,
    )


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------


@router.get(
    "/students",
    response_model=schemas.Page[schemas.StudentAdminOut],
    tags=["admin-students"],
    summary="List all students",
    description="Filter by `class_id`, `roll`, and/or `name` (partial, case-insensitive search). "
    "Paginated via `limit`/`offset`. `class_name` is derived via a join, not a stored column.",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"}},
)
def list_students(
    class_id: Optional[str] = Query(None),
    roll: Optional[int] = Query(None),
    name: Optional[str] = Query(None, description="Partial, case-insensitive match on name"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    query = db.query(models.Student, models.Class.name.label("class_name")).outerjoin(
        models.Class, models.Student.class_id == models.Class.id
    )
    if class_id:
        query = query.filter(models.Student.class_id == class_id)
    if roll is not None:
        query = query.filter(models.Student.roll == roll)
    if name:
        query = query.filter(models.Student.name.ilike(f"%{name.strip()}%"))
    total = query.count()
    rows = query.order_by(models.Student.roll).offset(offset).limit(limit).all()
    items = [_student_out(row, class_name) for row, class_name in rows]
    return schemas.Page(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/students/{student_id}",
    response_model=schemas.StudentAdminOut,
    tags=["admin-students"],
    summary="Get one student",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No student with that id"},
    },
)
def get_student(student_id: str, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    row = _get_or_404(db, models.Student, student_id, "STUDENT_NOT_FOUND", "student")
    class_name = None
    if row.class_id:
        cls = db.query(models.Class).filter(models.Class.id == row.class_id).first()
        class_name = cls.name if cls else None
    return _student_out(row, class_name)


@router.post(
    "/students",
    response_model=schemas.StudentAdminOut,
    status_code=status.HTTP_201_CREATED,
    tags=["admin-students"],
    summary="Create a student",
    description="`id` is auto-generated (`std_xxxxxxxx`) if omitted. `password` is required and "
    "hashed server-side. `class_id`, if given, is validated against `classes.id`. `gender` must "
    "be one of: Male, Female. `email` is "
    "checked for uniqueness across students, teachers, and admin accounts.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "class_id given but doesn't exist"},
        409: {"model": schemas.ErrorResponse, "description": "Given id already exists, or email already in use"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def create_student(payload: schemas.StudentIn, db: Session = Depends(get_db), principal: dict = ACADEMIC):
    _check_email_available(db, payload.email)
    cls = None
    if payload.class_id:
        cls = _get_or_404(db, models.Class, payload.class_id, "CLASS_NOT_FOUND", "class")

    row_id = payload.id or utils.generate_id("std_")
    if db.query(models.Student).filter(models.Student.id == row_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ID_ALREADY_EXISTS", "message": f"Student '{row_id}' already exists"},
        )

    row = models.Student(
        id=row_id,
        name=payload.name,
        email=payload.email,
        password_hash=utils.hash_password(payload.password) if payload.password else None,
        role="student",
        roll=payload.roll,
        class_id=payload.class_id,
        gender=payload.gender,
        dob=payload.dob,
        phone=payload.phone,
        guardian=payload.guardian,
        guardian_phone=payload.guardian_phone,
        address=payload.address,
        avatar=payload.avatar,
    )
    db.add(row)
    utils.log_audit(db, principal["id"], principal["role"], "create", "student", row_id)
    if payload.class_id:
        utils.apply_student_count_delta(db, None, payload.class_id)
    db.commit()
    return _student_out(row, cls.name if cls else None)


@router.put(
    "/students/{student_id}",
    response_model=schemas.StudentAdminOut,
    tags=["admin-students"],
    summary="Update a student",
    description="Partial update — only send the fields you want to change. Password changes "
    "go through the separate /set-password endpoint. `class_id` and `email`, if sent, are "
    "validated. `gender`, if sent, must be one of: Male, Female.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No student with that id, or given class_id doesn't exist"},
        409: {"model": schemas.ErrorResponse, "description": "Email already in use elsewhere"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def update_student(
    student_id: str, payload: schemas.StudentUpdate, db: Session = Depends(get_db), principal: dict = ACADEMIC
):
    row = _get_or_404(db, models.Student, student_id, "STUDENT_NOT_FOUND", "student")
    fields = payload.model_dump(exclude_unset=True)

    if "email" in fields:
        _check_email_available(db, fields["email"], exclude_ids={"student": student_id})
    if "class_id" in fields and fields["class_id"]:
        _get_or_404(db, models.Class, fields["class_id"], "CLASS_NOT_FOUND", "class")

    old_class_id = row.class_id
    for field, value in fields.items():
        setattr(row, field, value)
    utils.log_audit(db, principal["id"], principal["role"], "update", "student", student_id)
    if "class_id" in fields:
        utils.apply_student_count_delta(db, old_class_id, row.class_id)
    db.commit()

    class_name = None
    if row.class_id:
        cls = db.query(models.Class).filter(models.Class.id == row.class_id).first()
        class_name = cls.name if cls else None
    return _student_out(row, class_name)


@router.delete(
    "/students/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["admin-students"],
    summary="Delete a student",
    description="Cascades at the database level: also deletes this student's attendance and "
    "results history. This is destructive and not reversible — confirm before calling.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No student with that id"},
    },
)
def delete_student(student_id: str, db: Session = Depends(get_db), principal: dict = ACADEMIC):
    row = _get_or_404(db, models.Student, student_id, "STUDENT_NOT_FOUND", "student")
    if row.class_id:
        utils.apply_student_count_delta(db, row.class_id, None)
    db.delete(row)
    utils.log_audit(db, principal["id"], principal["role"], "delete", "student", student_id)
    db.commit()


@router.post(
    "/students/{student_id}/clear-password",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["admin-students"],
    summary="Clear (reset) a student's password",
    description="Sets the student's password to null. Admins cannot set a password directly — "
    "clearing it lets the student set their own password at the login screen. This is the "
    "password-reset flow: a student who forgot their password asks an admin to clear it.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No student with that id"},
    },
)
def clear_student_password(
    student_id: str,
    db: Session = Depends(get_db),
    principal: dict = ACADEMIC,
):
    row = _get_or_404(db, models.Student, student_id, "STUDENT_NOT_FOUND", "student")
    row.password_hash = None
    utils.log_audit(db, principal["id"], principal["role"], "set_password", "student", student_id)
    db.commit()


# ---------------------------------------------------------------------------
# Teachers
# ---------------------------------------------------------------------------


@router.get(
    "/teachers",
    response_model=schemas.Page[schemas.TeacherAdminOut],
    tags=["admin-teachers"],
    summary="List all teachers",
    description="Filter by `subject_id` and/or `name` (partial, case-insensitive search). "
    "Paginated via `limit`/`offset`. `subject_name`/`class_name` are derived via joins, not stored columns.",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"}},
)
def list_teachers(
    subject_id: Optional[str] = Query(None),
    name: Optional[str] = Query(None, description="Partial, case-insensitive match on name"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    query = (
        db.query(
            models.Teacher,
            models.Subject.name.label("subject_name"),
            models.Class.name.label("class_name"),
        )
        .outerjoin(models.Subject, models.Teacher.subject_id == models.Subject.id)
        .outerjoin(models.Class, models.Teacher.class_id == models.Class.id)
    )
    if subject_id:
        query = query.filter(models.Teacher.subject_id == subject_id)
    if name:
        query = query.filter(models.Teacher.name.ilike(f"%{name.strip()}%"))
    total = query.count()
    rows = query.order_by(models.Teacher.name).offset(offset).limit(limit).all()
    items = [_teacher_out(row, subject_name, class_name) for row, subject_name, class_name in rows]
    return schemas.Page(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/teachers/{teacher_id}",
    response_model=schemas.TeacherAdminOut,
    tags=["admin-teachers"],
    summary="Get one teacher",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No teacher with that id"},
    },
)
def get_teacher(teacher_id: str, db: Session = Depends(get_db), _principal: dict = ACADEMIC):
    row = _get_or_404(db, models.Teacher, teacher_id, "TEACHER_NOT_FOUND", "teacher")
    subject_name = None
    if row.subject_id:
        subj = db.query(models.Subject).filter(models.Subject.id == row.subject_id).first()
        subject_name = subj.name if subj else None
    class_name = None
    if row.class_id:
        cls = db.query(models.Class).filter(models.Class.id == row.class_id).first()
        class_name = cls.name if cls else None
    return _teacher_out(row, subject_name, class_name)


@router.post(
    "/teachers",
    response_model=schemas.TeacherAdminOut,
    status_code=status.HTTP_201_CREATED,
    tags=["admin-teachers"],
    summary="Create a teacher",
    description="`id` is auto-generated (`tch_xxxxxxxx`) if omitted. `password` is required and "
    "hashed server-side. `subject_id`, if given, is validated against `subjects.id`. `email` is "
    "checked for uniqueness across students, teachers, and admin accounts. To make this teacher "
    "a homeroom teacher, use `PUT /admin/classes/{id}` with `teacher_id` afterward, not this endpoint.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "subject_id given but doesn't exist"},
        409: {"model": schemas.ErrorResponse, "description": "Given id already exists, or email already in use"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def create_teacher(payload: schemas.TeacherIn, db: Session = Depends(get_db), principal: dict = ACADEMIC):
    _check_email_available(db, payload.email)
    subj = None
    if payload.subject_id:
        subj = _get_or_404(db, models.Subject, payload.subject_id, "SUBJECT_NOT_FOUND", "subject")

    row_id = payload.id or utils.generate_id("tch_")
    if db.query(models.Teacher).filter(models.Teacher.id == row_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ID_ALREADY_EXISTS", "message": f"Teacher '{row_id}' already exists"},
        )

    row = models.Teacher(
        id=row_id,
        name=payload.name,
        email=payload.email,
        password_hash=utils.hash_password(payload.password) if payload.password else None,
        role=payload.role,
        subject_id=payload.subject_id,
        # keep the denormalized `subject` name column in sync (read by /faculty, /teachers/me)
        subject=subj.name if subj else None,
        phone=payload.phone,
        join_date=payload.join_date,
        avatar=payload.avatar,
        message=payload.message,
        bio=payload.bio,
    )
    db.add(row)
    utils.log_audit(db, principal["id"], principal["role"], "create", "teacher", row_id)
    db.commit()
    return _teacher_out(row, subj.name if subj else None, None)


@router.put(
    "/teachers/{teacher_id}",
    response_model=schemas.TeacherAdminOut,
    tags=["admin-teachers"],
    summary="Update a teacher",
    description="Partial update — only send the fields you want to change. Password changes "
    "go through the separate /set-password endpoint. `subject_id` and `email`, if sent, are "
    "validated. There's no `class_id` field here on purpose — set homeroom via "
    "`PUT /admin/classes/{id}` instead.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No teacher with that id, or given subject_id doesn't exist"},
        409: {"model": schemas.ErrorResponse, "description": "Email already in use elsewhere"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def update_teacher(
    teacher_id: str, payload: schemas.TeacherUpdate, db: Session = Depends(get_db), principal: dict = ACADEMIC
):
    row = _get_or_404(db, models.Teacher, teacher_id, "TEACHER_NOT_FOUND", "teacher")
    fields = payload.model_dump(exclude_unset=True)

    if "email" in fields:
        _check_email_available(db, fields["email"], exclude_ids={"teacher": teacher_id})
    if "subject_id" in fields and fields["subject_id"]:
        _get_or_404(db, models.Subject, fields["subject_id"], "SUBJECT_NOT_FOUND", "subject")

    for field, value in fields.items():
        setattr(row, field, value)
    # keep the denormalized `subject` name column in sync with subject_id
    if "subject_id" in fields:
        subj = (
            db.query(models.Subject).filter(models.Subject.id == fields["subject_id"]).first()
            if fields["subject_id"]
            else None
        )
        row.subject = subj.name if subj else None
    utils.log_audit(db, principal["id"], principal["role"], "update", "teacher", teacher_id)
    db.commit()

    subject_name = None
    if row.subject_id:
        subj = db.query(models.Subject).filter(models.Subject.id == row.subject_id).first()
        subject_name = subj.name if subj else None
    class_name = None
    if row.class_id:
        cls = db.query(models.Class).filter(models.Class.id == row.class_id).first()
        class_name = cls.name if cls else None
    return _teacher_out(row, subject_name, class_name)


@router.delete(
    "/teachers/{teacher_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["admin-teachers"],
    summary="Delete a teacher",
    description="Blocked if this teacher is a homeroom teacher of any class, or still has "
    "schedule entries - remove those first.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No teacher with that id"},
        409: {"model": schemas.ErrorResponse, "description": "Teacher is still referenced elsewhere"},
    },
)
def delete_teacher(teacher_id: str, db: Session = Depends(get_db), principal: dict = ACADEMIC):
    row = _get_or_404(db, models.Teacher, teacher_id, "TEACHER_NOT_FOUND", "teacher")
    _check_in_use(
        db,
        models.Class,
        models.Class.teacher_id,
        teacher_id,
        "TEACHER_IN_USE",
        "This teacher is the homeroom teacher of a class — reassign it first",
    )
    _check_in_use(
        db,
        models.Schedule,
        models.Schedule.teacher_id,
        teacher_id,
        "TEACHER_IN_USE",
        "This teacher still has schedule entries — remove those first",
    )
    db.delete(row)
    utils.log_audit(db, principal["id"], principal["role"], "delete", "teacher", teacher_id)
    db.commit()


@router.post(
    "/teachers/{teacher_id}/clear-password",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["admin-teachers"],
    summary="Clear (reset) a teacher's password",
    description="Sets the teacher's password to null. Admins cannot set a password directly — "
    "clearing it lets the teacher set their own password at the login screen. This is the "
    "password-reset flow: a teacher who forgot their password asks an admin to clear it.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No teacher with that id"},
    },
)
def clear_teacher_password(
    teacher_id: str,
    db: Session = Depends(get_db),
    principal: dict = ACADEMIC,
):
    row = _get_or_404(db, models.Teacher, teacher_id, "TEACHER_NOT_FOUND", "teacher")
    row.password_hash = None
    utils.log_audit(db, principal["id"], principal["role"], "set_password", "teacher", teacher_id)
    db.commit()


# ---------------------------------------------------------------------------
# Password reset requests (admin queue)
# ---------------------------------------------------------------------------


@router.get(
    "/password-reset-requests",
    response_model=schemas.Page[schemas.PasswordResetRequestOut],
    tags=["admin-password-resets"],
    summary="List password reset requests",
    description="The admin queue of student/teacher password-reset requests. Filter by "
    "`role`, `status`, `active` (is_active), a `created_at` date range, and/or `email` "
    "(partial, case-insensitive). Paginated via `limit`/`offset`. Ordered most-recent first.",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"}},
)
def list_password_reset_requests(
    role: Optional[schemas.ResetRole] = Query(None, description="student or teacher"),
    status_filter: Optional[schemas.ResetStatus] = Query(None, alias="status", description="pending or accepted"),
    active: Optional[bool] = Query(None, description="Filter by is_active"),
    email: Optional[str] = Query(None, description="Partial, case-insensitive match on email"),
    created_from: Optional[datetime] = Query(None, description="Inclusive lower bound on created_at"),
    created_to: Optional[datetime] = Query(None, description="Inclusive upper bound on created_at"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _principal: dict = ACADEMIC,
):
    query = db.query(models.PasswordResetRequest)
    if role:
        query = query.filter(models.PasswordResetRequest.role == role.value)
    if status_filter:
        query = query.filter(models.PasswordResetRequest.status == status_filter.value)
    if active is not None:
        query = query.filter(models.PasswordResetRequest.is_active.is_(active))
    if email:
        query = query.filter(models.PasswordResetRequest.email.ilike(f"%{email.strip()}%"))
    if created_from:
        query = query.filter(models.PasswordResetRequest.created_at >= created_from)
    if created_to:
        query = query.filter(models.PasswordResetRequest.created_at <= created_to)

    total = query.count()
    rows = (
        query.order_by(models.PasswordResetRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return schemas.Page(items=rows, total=total, limit=limit, offset=offset)


@router.post(
    "/password-reset-requests/{request_id}/accept",
    response_model=schemas.PasswordResetRequestOut,
    tags=["admin-password-resets"],
    summary="Accept a password reset request",
    description="Clears the target student/teacher's password (so they can set a new one at "
    "login), marks the request `accepted`, and sets `is_active` to false (dropping it from the "
    "active queue). Idempotent-safe: a request that's already inactive returns 409.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'academic' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No reset request with that id"},
        409: {"model": schemas.ErrorResponse, "description": "Request is already resolved (ALREADY_RESOLVED)"},
    },
)
def accept_password_reset_request(
    request_id: int,
    db: Session = Depends(get_db),
    principal: dict = ACADEMIC,
):
    req = db.query(models.PasswordResetRequest).filter(models.PasswordResetRequest.id == request_id).first()
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "RESET_REQUEST_NOT_FOUND", "message": f"No reset request with id '{request_id}'"},
        )
    if not req.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ALREADY_RESOLVED", "message": "This request has already been resolved."},
        )

    # Clear the target account's password so they can set a new one at login.
    model = models.Student if req.role == "student" else models.Teacher
    account = db.query(model).filter(model.email == req.email).first()
    if account:
        account.password_hash = None
        utils.log_audit(db, principal["id"], principal["role"], "set_password", req.role, account.id)

    req.status = "accepted"
    req.is_active = False
    db.commit()
    db.refresh(req)
    return req