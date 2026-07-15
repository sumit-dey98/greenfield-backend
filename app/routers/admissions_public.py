from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from .. import models, oauth2, schemas, utils
from ..config import settings
from ..database import get_db

router = APIRouter(prefix="/admissions", tags=["admissions-public"])

# No account-based auth anywhere in this file - these routes are for prospective-applicant
# access (reference_number + contact value, no password). Anti-spam is handled entirely via
# Postgres-backed SubmissionAttempt/VerifyAttempt rows, not per-request auth.

ALLOWED_DOCUMENT_MIME_TYPES = {"image/jpeg", "image/png", "application/pdf"}
ALLOWED_PHOTO_MIME_TYPES = {"image/jpeg", "image/png"}

# Terminal states for duplicate-collapse purposes - anything else counts as "active" and
# blocks a second submission with the same contact value in the same cycle.
_DUPLICATE_TERMINAL_STATUSES = {"screening_rejected", "rejected", "accepted", "withdrawn"}

# States masked as "decision_pending" on the public track endpoint until the cycle's
# results_published flag is flipped true - keeps applicants from finding out a real outcome
# (including a positive one) before the school is ready to announce it.
_MASKED_DECISION_STATUSES = {"accepted", "rejected", "waitlisted"}


def _check_admissions_open(db: Session) -> None:
    row = db.query(models.AdmissionOpen).filter(models.AdmissionOpen.id == "admission_status").first()
    if not row or not row.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "ADMISSIONS_CLOSED", "message": "Admissions are not currently open"},
        )


def _get_active_cycle(db: Session) -> models.AdmissionCycle:
    cycle = db.query(models.AdmissionCycle).filter(models.AdmissionCycle.is_active.is_(True)).first()
    if not cycle:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "NO_ACTIVE_CYCLE", "message": "No active admission cycle is configured"},
        )
    return cycle


def _check_rate_limit(db: Session, ip_address: str) -> None:
    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)

    hourly_count = (
        db.query(models.SubmissionAttempt)
        .filter(models.SubmissionAttempt.ip_address == ip_address, models.SubmissionAttempt.created_at >= hour_ago)
        .count()
    )
    if hourly_count >= settings.admission_rate_limit_per_hour:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "TOO_MANY_REQUESTS",
                "message": f"Too many submissions from this network - limit is {settings.admission_rate_limit_per_hour} per hour. Try again later.",
            },
        )
    daily_count = (
        db.query(models.SubmissionAttempt)
        .filter(models.SubmissionAttempt.ip_address == ip_address, models.SubmissionAttempt.created_at >= day_ago)
        .count()
    )
    if daily_count >= settings.admission_rate_limit_per_day:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "TOO_MANY_REQUESTS",
                "message": f"Too many submissions from this network - limit is {settings.admission_rate_limit_per_day} per day. Try again later.",
            },
        )


@router.post(
    "/apply",
    response_model=schemas.ApplicationSubmitOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new admission application",
    description=(
        "Public, no auth required. `multipart/form-data`: all ApplicationIn fields as form "
        "fields, a required `photo` file, plus optional `documents` file(s). Gated by the "
        "admission-open toggle and the active admission cycle. IP-rate-limited (per hour and "
        "per day) and de-duplicated: a second submission with the same contact value in the "
        "same cycle while the first is still active returns the existing reference_number "
        f"with `duplicate: true` instead of creating a new application. `photo` must be one of "
        f"{sorted(ALLOWED_PHOTO_MIME_TYPES)} and at most {settings.admission_max_photo_size_bytes} bytes. "
        f"`documents` files must be one of {sorted(ALLOWED_DOCUMENT_MIME_TYPES)} and at most "
        f"{settings.admission_max_file_size_bytes} bytes each; at most "
        f"{settings.admission_max_files} `documents` files total (in addition to the photo)."
    ),
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Admissions are currently closed (ADMISSIONS_CLOSED)"},
        409: {"model": schemas.ErrorResponse, "description": "No active admission cycle is configured (NO_ACTIVE_CYCLE)"},
        429: {"model": schemas.ErrorResponse, "description": "IP rate limit exceeded (TOO_MANY_REQUESTS)"},
        400: {"model": schemas.ErrorResponse, "description": "CAPTCHA verification failed (CAPTCHA_FAILED)"},
        422: {"model": schemas.ErrorResponse, "description": "Invalid document (INVALID_DOCUMENT) or invalid phone number"},
        500: {"model": schemas.ErrorResponse, "description": "Cloudinary not configured (CLOUDINARY_NOT_CONFIGURED)"},
    },
)
def apply(
    request: Request,
    student_name: str = Form(...),
    dob: Optional[date] = Form(None),
    gender: Optional[str] = Form(None),
    applying_class: Optional[str] = Form(None),
    blood_group: Optional[str] = Form(None),
    previous_school: Optional[str] = Form(None),
    contact_method: schemas.ContactMethod = Form(...),
    contact_email: Optional[str] = Form(None),
    contact_phone: Optional[str] = Form(None),
    guardian_name: Optional[str] = Form(None),
    guardian_relationship: Optional[str] = Form(None),
    guardian_phone: Optional[str] = Form(None),
    guardian_email: Optional[str] = Form(None),
    guardian_occupation: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    medical_conditions: Optional[str] = Form(None),
    extracurricular: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    captcha_token: str = Form(...),
    photo: UploadFile = File(...),
    documents: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    # Validate the assembled payload through the same schema/model_validator used for the
    # contact_method <-> contact_email/contact_phone invariant, so this endpoint can't drift
    # from the documented contract.
    try:
        payload = schemas.ApplicationIn(
            student_name=student_name,
            dob=dob,
            gender=gender,
            applying_class=applying_class,
            blood_group=blood_group,
            previous_school=previous_school,
            contact_method=contact_method,
            contact_email=contact_email,
            contact_phone=contact_phone,
            guardian_name=guardian_name,
            guardian_relationship=guardian_relationship,
            guardian_phone=guardian_phone,
            guardian_email=guardian_email,
            guardian_occupation=guardian_occupation,
            address=address,
            medical_conditions=medical_conditions,
            extracurricular=extracurricular,
            notes=notes,
            captcha_token=captcha_token,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "VALIDATION_ERROR", "message": str(exc)},
        )

    # 1. Admissions-open gate.
    _check_admissions_open(db)

    # 2. Active cycle.
    cycle = _get_active_cycle(db)

    # 3. IP rate limit - note request.client.host has no reverse-proxy header handling yet
    # (no X-Forwarded-For support); fine behind a single-hop deployment, revisit if a proxy
    # is added in front of this API.
    ip_address = request.client.host if request.client else "unknown"
    _check_rate_limit(db, ip_address)
    # Log this attempt regardless of what happens next - deliberate: even validation failures
    # count toward the limit, since this is an abuse-prevention measure, not a UX nicety.
    db.add(models.SubmissionAttempt(ip_address=ip_address))
    db.commit()

    # 4. CAPTCHA.
    if not utils.verify_captcha(payload.captcha_token, remote_ip=ip_address):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "CAPTCHA_FAILED", "message": "CAPTCHA verification failed"},
        )

    # 5a. Validate the required photo (its own, stricter size limit; image types only).
    if not photo.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "INVALID_DOCUMENT", "message": "A photo is required."},
        )
    photo_content = photo.file.read()
    if len(photo_content) > settings.admission_max_photo_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "INVALID_DOCUMENT",
                "message": f"Photo '{photo.filename}' is {len(photo_content)} bytes, exceeds the "
                f"{settings.admission_max_photo_size_bytes} byte limit.",
            },
        )
    if photo.content_type not in ALLOWED_PHOTO_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "INVALID_DOCUMENT",
                "message": f"Photo has type '{photo.content_type}', which is not allowed. "
                f"Allowed types: {', '.join(sorted(ALLOWED_PHOTO_MIME_TYPES))}.",
            },
        )

    # 5b. Validate documents (count, size, mime type).
    if len(documents) > settings.admission_max_files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "INVALID_DOCUMENT",
                "message": f"At most {settings.admission_max_files} files may be uploaded (got {len(documents)}).",
            },
        )
    file_payloads: List[tuple] = []  # (UploadFile, bytes)
    for f in documents:
        if not f.filename:
            continue
        content = f.file.read()
        if len(content) > settings.admission_max_file_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_code": "INVALID_DOCUMENT",
                    "message": f"File '{f.filename}' is {len(content)} bytes, exceeds the "
                    f"{settings.admission_max_file_size_bytes} byte limit.",
                },
            )
        if f.content_type not in ALLOWED_DOCUMENT_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_code": "INVALID_DOCUMENT",
                    "message": f"File '{f.filename}' has type '{f.content_type}', which is not allowed. "
                    f"Allowed types: {', '.join(sorted(ALLOWED_DOCUMENT_MIME_TYPES))}.",
                },
            )
        file_payloads.append((f, content))

    # 6. Normalize phone if that's the tracking identifier.
    normalized_phone = None
    if payload.contact_method == schemas.ContactMethod.phone:
        try:
            normalized_phone = utils.normalize_bd_phone(payload.contact_phone)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error_code": "INVALID_PHONE", "message": "contact_phone is not a valid Bangladesh phone number"},
            )

    # 7. Duplicate-collapse check (before any Cloudinary/file work).
    dup_query = db.query(models.Application).filter(
        models.Application.cycle_id == cycle.id,
        models.Application.status.notin_(_DUPLICATE_TERMINAL_STATUSES),
    )
    if payload.contact_method == schemas.ContactMethod.email:
        dup_query = dup_query.filter(models.Application.contact_email == payload.contact_email)
    else:
        dup_query = dup_query.filter(models.Application.contact_phone == normalized_phone)
    existing = dup_query.first()
    if existing:
        return schemas.ApplicationSubmitOut(
            reference_number=existing.reference_number,
            status=existing.status,
            duplicate=True,
            message="You already have an application in progress.",
        )

    # 8. Generate the reference_number first (retry on collision) - Cloudinary uploads are
    # organized per-applicant under this reference_number, so it must exist before either
    # upload call.
    reference_number = utils.generate_reference_number()
    while db.query(models.Application).filter(models.Application.reference_number == reference_number).first():
        reference_number = utils.generate_reference_number()

    # 9. Photo must upload successfully before the Application row is created - it's a
    # required field, so a Cloudinary failure here should not leave a photo-less application
    # behind (unlike optional `documents`, which are attached after the row already exists).
    photo_upload = utils.upload_admission_document(photo_content, photo.filename, reference_number)

    application = models.Application(
        id=utils.generate_id("app_"),
        reference_number=reference_number,
        cycle_id=cycle.id,
        student_name=payload.student_name,
        photo_url=photo_upload.get("secure_url"),
        dob=payload.dob,
        gender=payload.gender,
        applying_class=payload.applying_class,
        blood_group=payload.blood_group,
        previous_school=payload.previous_school,
        contact_method=payload.contact_method.value,
        contact_email=payload.contact_email if payload.contact_method == schemas.ContactMethod.email else None,
        contact_phone=normalized_phone if payload.contact_method == schemas.ContactMethod.phone else None,
        guardian_name=payload.guardian_name,
        guardian_relationship=payload.guardian_relationship,
        guardian_phone=payload.guardian_phone,
        guardian_email=payload.guardian_email,
        guardian_occupation=payload.guardian_occupation,
        address=payload.address,
        medical_conditions=payload.medical_conditions,
        extracurricular=payload.extracurricular,
        notes=payload.notes,
        status="submitted",
        submitted_ip=ip_address,
    )
    db.add(application)
    db.flush()  # get application.id available for document FK without a full commit yet

    # 10. Upload optional documents to Cloudinary (only if there's something to upload).
    for f, content in file_payloads:
        upload_result = utils.upload_admission_document(content, f.filename, reference_number)
        db.add(
            models.ApplicationDocument(
                id=utils.generate_id("adoc_"),
                application_id=application.id,
                url=upload_result.get("secure_url"),
                public_id=upload_result.get("public_id"),
                file_name=f.filename,
                mime_type=f.content_type,
                size_bytes=len(content),
            )
        )

    # 11. Commit.
    db.commit()
    return schemas.ApplicationSubmitOut(
        reference_number=reference_number,
        status="submitted",
        duplicate=False,
        message="Application submitted successfully.",
    )


@router.post(
    "/{reference_number}/verify",
    response_model=schemas.ApplicationVerifyOut,
    summary="Verify a reference number + contact value to obtain a status-lookup token",
    description=(
        "Public, no auth required. On success, returns a short-lived admission-access token "
        "(send it back as the `X-Admission-Token` header to `GET /admissions/{reference_number}/"
        "status`). Locked out after "
        f"{settings.admission_verify_max_attempts} failed attempts for a given reference_number "
        f"within {settings.admission_verify_lockout_minutes} minutes, regardless of source IP. "
        "A nonexistent reference_number returns the same generic error as a real mismatch, so "
        "this endpoint can't be used to enumerate valid reference numbers."
    ),
    responses={
        401: {"model": schemas.ErrorResponse, "description": "No application found or details do not match (VERIFICATION_FAILED)"},
        429: {"model": schemas.ErrorResponse, "description": "Too many failed attempts for this reference number (TOO_MANY_ATTEMPTS)"},
    },
)
def verify(
    reference_number: str,
    payload: schemas.ApplicationVerifyIn,
    request: Request,
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    lockout_window_start = now - timedelta(minutes=settings.admission_verify_lockout_minutes)
    failed_count = (
        db.query(models.VerifyAttempt)
        .filter(
            models.VerifyAttempt.reference_number == reference_number,
            models.VerifyAttempt.success.is_(False),
            models.VerifyAttempt.created_at >= lockout_window_start,
        )
        .count()
    )
    if failed_count >= settings.admission_verify_max_attempts:
        # Already locked - don't insert another VerifyAttempt row here, otherwise a flood of
        # requests against a locked reference_number would just keep pushing the lockout window
        # forward indefinitely instead of it naturally expiring after admission_verify_lockout_minutes.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "TOO_MANY_ATTEMPTS",
                "message": f"Too many failed attempts. Try again in up to {settings.admission_verify_lockout_minutes} minutes.",
            },
        )

    ip_address = request.client.host if request.client else "unknown"
    application = (
        db.query(models.Application).filter(models.Application.reference_number == reference_number).first()
    )

    match = False
    if application:
        try:
            if application.contact_method == "phone":
                normalized_input = utils.normalize_bd_phone(payload.contact_value)
                match = normalized_input == application.contact_phone
            else:
                match = payload.contact_value.strip().lower() == (application.contact_email or "").strip().lower()
        except ValueError:
            match = False  # bad phone input -> treated as a failed match, not a 422

    db.add(models.VerifyAttempt(reference_number=reference_number, success=match, ip_address=ip_address))
    db.commit()

    if not match:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "VERIFICATION_FAILED", "message": "No application found or details do not match."},
        )

    expires_in = 7200
    token = oauth2.create_admission_access_token(reference_number, expires_minutes=expires_in // 60)
    return schemas.ApplicationVerifyOut(access_token=token, expires_in=expires_in)


@router.get(
    "/{reference_number}/status",
    response_model=schemas.ApplicationTrackOut,
    summary="Look up an application's public-safe status",
    description=(
        "Requires a valid admission-access token from POST /verify, sent as the `X-Admission-"
        "Token` header. `visible_status` masks accepted/rejected/waitlisted as "
        "`decision_pending` until the cycle's results are published - never leaks the real "
        "decision early. No contact fields, notes, decision_notes, interview_outcome/notes, or "
        "grading/teacher identity are ever included here."
    ),
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired admission access token"},
        403: {"model": schemas.ErrorResponse, "description": "Token was not issued for this reference_number"},
        404: {"model": schemas.ErrorResponse, "description": "No application with that reference number"},
    },
)
def get_status(
    reference_number: str = Depends(oauth2.require_admission_access),
    db: Session = Depends(get_db),
):
    application = (
        db.query(models.Application).filter(models.Application.reference_number == reference_number).first()
    )
    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "APPLICATION_NOT_FOUND", "message": f"No application with reference number '{reference_number}'"},
        )

    cycle = db.query(models.AdmissionCycle).filter(models.AdmissionCycle.id == application.cycle_id).first()
    results_published = bool(cycle and cycle.results_published)

    visible_status = application.status
    if application.status in _MASKED_DECISION_STATUSES and not results_published:
        visible_status = "decision_pending"

    documents = (
        db.query(models.ApplicationDocument)
        .filter(models.ApplicationDocument.application_id == application.id)
        .all()
    )
    exam_schedule_row = (
        db.query(models.ApplicationExamSchedule)
        .filter(models.ApplicationExamSchedule.application_id == application.id)
        .first()
    )
    interview_row = (
        db.query(models.ApplicationInterview)
        .filter(models.ApplicationInterview.application_id == application.id)
        .first()
    )

    return schemas.ApplicationTrackOut(
        reference_number=application.reference_number,
        student_name=application.student_name,
        photo_url=application.photo_url,
        applying_class=application.applying_class,
        dob=application.dob,
        gender=application.gender,
        blood_group=application.blood_group,
        previous_school=application.previous_school,
        guardian_name=application.guardian_name,
        guardian_relationship=application.guardian_relationship,
        guardian_phone=application.guardian_phone,
        guardian_email=application.guardian_email,
        address=application.address,
        visible_status=visible_status,
        cycle_name=cycle.name if cycle else None,
        documents=documents,
        exam_schedule=exam_schedule_row,
        interview=interview_row,
    )


# Statuses from which an admit card is available: the exam has been scheduled (roll_number
# exists) and the application hasn't been screened out before reaching that point. Anything
# reachable from exam_scheduled onward still has a valid schedule row, so no upper bound here.
_ADMIT_CARD_ELIGIBLE_STATUSES = {
    "exam_scheduled", "exam_completed", "grading_assigned", "graded",
    "interview_scheduled", "interview_completed", "waitlisted", "accepted", "rejected",
}


@router.get(
    "/{reference_number}/admit-card",
    summary="Download the entrance-exam admit card as a PDF",
    description=(
        "Requires the same admission-access token as GET /status. Available once the "
        "application's entrance exam has been scheduled (status is `exam_scheduled` or later) "
        "- 409 before that, since the roll number/exam date/venue don't exist yet. Returns "
        "`application/pdf` bytes, not JSON."
    ),
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired admission access token"},
        403: {"model": schemas.ErrorResponse, "description": "Token was not issued for this reference_number"},
        404: {"model": schemas.ErrorResponse, "description": "No application with that reference number"},
        409: {"model": schemas.ErrorResponse, "description": "Exam has not been scheduled yet (ADMIT_CARD_NOT_AVAILABLE)"},
    },
)
def get_admit_card(
    reference_number: str = Depends(oauth2.require_admission_access),
    db: Session = Depends(get_db),
):
    application = (
        db.query(models.Application).filter(models.Application.reference_number == reference_number).first()
    )
    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "APPLICATION_NOT_FOUND", "message": f"No application with reference number '{reference_number}'"},
        )
    if application.status not in _ADMIT_CARD_ELIGIBLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "ADMIT_CARD_NOT_AVAILABLE",
                "message": "Your entrance exam has not been scheduled yet - the admit card isn't available until then.",
            },
        )

    exam_schedule = (
        db.query(models.ApplicationExamSchedule)
        .filter(models.ApplicationExamSchedule.application_id == application.id)
        .first()
    )
    if not exam_schedule:
        # Defensive: status says exam_scheduled-or-later but the schedule row is somehow
        # missing - treat the same as not-yet-available rather than crashing on None fields.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ADMIT_CARD_NOT_AVAILABLE", "message": "Exam schedule details are not available."},
        )
    cycle = db.query(models.AdmissionCycle).filter(models.AdmissionCycle.id == application.cycle_id).first()

    pdf_bytes = utils.generate_admit_card_pdf(
        student_name=application.student_name,
        reference_number=application.reference_number,
        roll_number=exam_schedule.roll_number,
        applying_class=application.applying_class,
        exam_date=exam_schedule.exam_date,
        exam_time=exam_schedule.exam_time,
        venue=exam_schedule.venue,
        photo_url=application.photo_url,
        cycle_name=cycle.name if cycle else None,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="admit-card-{application.reference_number}.pdf"'},
    )
