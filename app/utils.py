import re
import secrets
import uuid

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


# ---------------------------------------------------------------------------
# Admission System
# ---------------------------------------------------------------------------


def generate_reference_number() -> str:
    """The applicant's only "credential" (no passwords in this flow) - needs real entropy.
    uuid4 is cryptographically random. Format: GFA-<12 hex chars>, e.g. GFA-3f9a1c7e2b8d."""
    return f"GFA-{uuid.uuid4().hex[:12]}"


def generate_roll_number() -> str:
    """Exam roll number shown to blind-grading teachers. Must not embed or be derivable from
    any applicant PII (name/contact/reference_number) - purely random."""
    return f"AEX-{secrets.token_hex(4).upper()}"


_BD_MOBILE_RE = re.compile(r"^1\d{9}$")  # 10 digits, starts with 1 (Bangladeshi mobile prefix)


def normalize_bd_phone(raw: str) -> str:
    """Normalizes a Bangladeshi phone number to +880XXXXXXXXXX (13 chars: +880 + 10 digits).

    Accepts: 01XXXXXXXXX (11-digit local), 1XXXXXXXXX (10-digit), +8801XXXXXXXXX /
    8801XXXXXXXXX (already-prefixed). Raises ValueError for anything that doesn't resolve to
    a valid 10-digit BD mobile number (10 digits, starts with 1)."""
    digits = re.sub(r"\D", "", raw or "")

    if digits.startswith("880") and len(digits) == 13:
        digits = digits[3:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    # else: assume it's already the bare 10-digit form (or garbage, caught below)

    if not _BD_MOBILE_RE.match(digits):
        raise ValueError("Invalid Bangladesh phone number")

    return f"+880{digits}"


def upload_admission_document(file_bytes: bytes, filename: str, reference_number: str) -> dict:
    """Uploads one admission file (photo or document) to Cloudinary under a per-applicant
    folder ("greenfield/admissions/{reference_number}/"), returning the raw API response dict
    (has `secure_url`, `public_id`, etc). Configures the SDK lazily on first call so importing
    this module (and thus starting the app) never fails just because Cloudinary env vars are
    unset - only an actual upload attempt does, with a clear 500 CLOUDINARY_NOT_CONFIGURED."""
    import cloudinary
    import cloudinary.uploader

    from .config import settings

    if not (settings.cloudinary_cloud_name and settings.cloudinary_api_key and settings.cloudinary_api_secret):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "CLOUDINARY_NOT_CONFIGURED",
                "message": "File uploads are unavailable: Cloudinary credentials are not configured on the server.",
            },
        )

    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )
    return cloudinary.uploader.upload(
        file_bytes,
        folder=f"greenfield/admissions/{reference_number}",
        resource_type="auto",
        filename=filename,
        use_filename=True,
    )


def generate_admit_card_pdf(*, student_name: str, reference_number: str, roll_number: str,
                             applying_class: str | None, exam_date, exam_time: str | None,
                             venue: str | None, photo_url: str | None, cycle_name: str | None) -> bytes:
    """Renders a one-page admit card PDF in memory (no temp files) and returns the raw bytes.
    Photo is fetched from its Cloudinary URL at render time - if that fetch fails for any
    reason (network blip, deleted asset), the card still renders with a placeholder box rather
    than failing the whole download, since the exam/roll-number details are the load-bearing
    content, not the photo."""
    import io
    import urllib.request

    from reportlab.lib.pagesizes import A6
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    width, height = A6
    c = canvas.Canvas(buf, pagesize=A6)

    # Header
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(width / 2, height - 14 * mm, "Greenfield Academy")
    c.setFont("Helvetica", 9)
    c.drawCentredString(width / 2, height - 19 * mm, "Entrance Exam Admit Card")
    c.line(8 * mm, height - 22 * mm, width - 8 * mm, height - 22 * mm)

    # Photo box (top-right)
    photo_box_x, photo_box_y, photo_size = width - 8 * mm - 22 * mm, height - 50 * mm, 22 * mm
    photo_drawn = False
    if photo_url:
        try:
            with urllib.request.urlopen(photo_url, timeout=5) as resp:
                photo_bytes = resp.read()
            from reportlab.lib.utils import ImageReader
            img = ImageReader(io.BytesIO(photo_bytes))
            c.drawImage(img, photo_box_x, photo_box_y, width=photo_size, height=photo_size,
                        preserveAspectRatio=True, anchor="c")
            photo_drawn = True
        except Exception:
            photo_drawn = False
    if not photo_drawn:
        c.setStrokeColorRGB(0.7, 0.7, 0.7)
        c.rect(photo_box_x, photo_box_y, photo_size, photo_size)
        c.setFont("Helvetica", 6)
        c.drawCentredString(photo_box_x + photo_size / 2, photo_box_y + photo_size / 2, "Photo")

    # Detail rows (left column, alongside the photo). Reference number is deliberately NOT
    # listed here - it's placed as small unlabeled text in the footer corner instead (see
    # below), since it's an internal lookup key, not a detail the applicant needs to read
    # off this card at the exam venue.
    rows = [
        ("Student Name", student_name or "-"),
        ("Applying For", applying_class or "-"),
        ("Roll Number", roll_number or "-"),
        ("Exam Date", str(exam_date) if exam_date else "TBA"),
        ("Exam Time", exam_time or "TBA"),
        ("Venue", venue or "TBA"),
        ("Admission Cycle", cycle_name or "-"),
    ]
    y = height - 30 * mm
    c.setFont("Helvetica", 8)
    label_x, value_x, max_value_width = 8 * mm, 8 * mm + 26 * mm, photo_box_x - (8 * mm + 26 * mm) - 2 * mm
    for label, value in rows:
        c.setFont("Helvetica", 7.5)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawString(label_x, y, label)
        c.setFont("Helvetica-Bold", 8.5)
        c.setFillColorRGB(0, 0, 0)
        # Truncate long values rather than overflow the card - full detail is on the tracking page.
        display_value = value
        while c.stringWidth(display_value, "Helvetica-Bold", 8.5) > max_value_width and len(display_value) > 1:
            display_value = display_value[:-1]
        if display_value != value:
            display_value = display_value[:-1] + "…"
        c.drawString(value_x, y, display_value)
        y -= 6.5 * mm

    c.setFont("Helvetica-Oblique", 6.5)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(width / 2, 6 * mm, "Bring this admit card and a valid photo ID to the exam venue.")

    # Reference number, unlabeled, small, bottom-right corner - an internal lookup key rather
    # than exam-day information, so it doesn't belong in the main detail list.
    c.setFont("Helvetica", 6)
    c.setFillColorRGB(0.6, 0.6, 0.6)
    c.drawRightString(width - 6 * mm, 3 * mm, reference_number or "")

    c.showPage()
    c.save()
    return buf.getvalue()


_LUGRASIMO_PATH = "app/assets/fonts/Lugrasimo-Regular.ttf"
_lugrasimo_registered = False


def _ensure_lugrasimo_registered():
    """Registers the vendored Lugrasimo TTF with reportlab on first use. Downloaded once from
    Google Fonts' official OFL-licensed repo (google/fonts) into app/assets/fonts/ - there's
    no next/font equivalent on the backend, since this is a separate Python process rendering
    PDFs, not a browser."""
    global _lugrasimo_registered
    if _lugrasimo_registered:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    pdfmetrics.registerFont(TTFont("Lugrasimo", _LUGRASIMO_PATH))
    _lugrasimo_registered = True


def generate_acceptance_letter_pdf(*, student_name: str, applying_class: str | None,
                                    cycle_name: str | None, reference_number: str,
                                    signatory_name: str | None, signatory_role: str | None) -> bytes:
    """Renders a one-page formal acceptance letter PDF in memory and returns the raw bytes.
    Only meaningful for status == 'accepted' - callers are responsible for that gate, this
    function just renders whatever it's given."""
    import io
    from datetime import date as date_cls

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor, white
    from reportlab.pdfgen import canvas

    _ensure_lugrasimo_registered()

    buf = io.BytesIO()
    width, height = A4
    c = canvas.Canvas(buf, pagesize=A4)

    primary = HexColor("#059669")  # matches --color-primary in app/globals.css

    # Header band
    band_height = 32 * mm
    c.setFillColor(primary)
    c.rect(0, height - band_height, width, band_height, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Lugrasimo", 24)
    c.drawCentredString(width / 2, height - 16 * mm, "Greenfield Academy")
    c.setFont("Lugrasimo", 11)
    c.drawCentredString(width / 2, height - 25 * mm, "info@greenfieldacademy.edu.bd | +880-2-9876543")

    # Body - Lugrasimo throughout for a handwritten-letter feel. Script fonts read smaller and
    # need more line-height than a sans-serif at the same point size, so sizes/spacing here run
    # larger than the admit card's Helvetica-based layout.
    y = height - band_height - 20 * mm
    c.setFillColor(HexColor("#000000"))
    c.setFont("Lugrasimo", 20)
    c.drawCentredString(width / 2, y, "Admission Acceptance Letter")
    y -= 16 * mm

    c.setFont("Lugrasimo", 13)
    c.drawString(25 * mm, y, date_cls.today().strftime("%B %d, %Y"))
    y -= 12 * mm

    c.setFont("Lugrasimo", 15)
    c.drawString(25 * mm, y, student_name or "-")
    y -= 7 * mm
    if applying_class:
        c.setFont("Lugrasimo", 13)
        c.drawString(25 * mm, y, f"Admitted to: {applying_class}")
        y -= 7 * mm
    y -= 6 * mm

    c.setFont("Lugrasimo", 14)
    c.drawString(25 * mm, y, f"Dear {student_name or 'Applicant'},")
    y -= 12 * mm

    body_paragraphs = [
        f"We are pleased to inform you that your application to Greenfield Academy"
        f"{f' for {cycle_name}' if cycle_name else ''} has been accepted. Welcome to our school "
        f"community!",
        "Your dedication throughout the admissions process, from the entrance examination to "
        "the interview, truly stood out, and we are confident you will thrive as part of "
        "Greenfield Academy.",
        "Please be aware that your admission is contingent upon completing the enrollment "
        "formalities communicated by our Admissions Office. Should you have any questions or "
        "need further assistance, please do not hesitate to reach out.",
    ]
    text_width = width - 50 * mm
    body_font_size = 13
    c.setFont("Lugrasimo", body_font_size)
    for para in body_paragraphs:
        wrapped = _wrap_text(c, para, "Lugrasimo", body_font_size, text_width)
        for line in wrapped:
            c.drawString(25 * mm, y, line)
            y -= 7 * mm
        y -= 5 * mm

    y -= 6 * mm
    c.setFont("Lugrasimo", 13)
    c.drawString(25 * mm, y, "Sincerely,")
    y -= 16 * mm
    c.setFont("Lugrasimo", 20)
    c.setFillColor(primary)
    c.drawString(25 * mm, y, signatory_name or "The Admissions Office")
    y -= 8 * mm
    c.setFillColor(HexColor("#000000"))
    c.setFont("Lugrasimo", 11)
    c.drawString(25 * mm, y, signatory_role or "Greenfield Academy")

    c.setFont("Helvetica", 6.5)
    c.setFillColor(HexColor("#999999"))
    c.drawRightString(width - 10 * mm, 8 * mm, reference_number or "")

    c.showPage()
    c.save()
    return buf.getvalue()


def _wrap_text(c, text: str, font: str, size: int, max_width: float) -> list[str]:
    """Greedy word-wrap for reportlab canvas text (no built-in paragraph flow used here since
    the letter's layout is otherwise manually positioned, not a Platypus flowable)."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if c.stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


_TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify_captcha(token: str, remote_ip: str | None = None) -> bool:
    """Verifies a Cloudflare Turnstile token server-side. If CAPTCHA_SECRET_KEY is unset,
    always returns True (no-op) so local dev and environments that haven't configured
    Turnstile yet aren't blocked - callers should still call this unconditionally on every
    request so this is the only function involved in enabling/disabling the check.

    A missing/blank `token` always fails (even with no provider configured, an empty
    submission is treated as suspicious) once a secret key IS configured; with no secret key
    configured the check is fully disabled and token content doesn't matter."""
    from .config import settings

    if not settings.captcha_secret_key:
        return True
    if not token:
        return False

    import urllib.error
    import urllib.parse
    import urllib.request
    import json

    data = urllib.parse.urlencode({
        "secret": settings.captcha_secret_key,
        "response": token,
        **({"remoteip": remote_ip} if remote_ip else {}),
    }).encode("utf-8")
    try:
        with urllib.request.urlopen(_TURNSTILE_VERIFY_URL, data=data, timeout=5) as resp:
            result = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ValueError):
        # Provider unreachable/timed out - fail closed (reject) rather than silently letting
        # every submission through if Cloudflare has an outage.
        return False
    return bool(result.get("success"))


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