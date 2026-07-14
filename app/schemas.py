from datetime import date as date_type
from datetime import datetime
from enum import Enum
from typing import Annotated, Generic, List, Optional, TypeVar

from pydantic import BaseModel, EmailStr, Field, model_validator

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Generic pagination envelope. `total` is the count of all matching rows before
    limit/offset were applied - use it to render "page X of Y" without a separate count call."""

    items: List[T]
    total: int
    limit: int
    offset: int


TimeStr = Annotated[
    str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="24-hour time, HH:MM, e.g. 08:45")
]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SetInitialPasswordRequest(BaseModel):
    """Self-service first-time password set. Only works when the account currently has no
    password (an admin has cleared it, or it was never set) — it can never overwrite an
    existing password."""
    email: EmailStr
    new_password: str


class ResetRole(str, Enum):
    student = "student"
    teacher = "teacher"


class ResetStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"


class PasswordResetRequestIn(BaseModel):
    """A student/teacher asks an admin to reset their password. `role` tells the backend
    which table to look the email up in."""
    role: ResetRole
    email: EmailStr


class PasswordResetRequestOut(BaseModel):
    id: int
    email: EmailStr
    role: str
    status: str
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RefreshRequest(BaseModel):
    refresh_token: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_type: str  # "student" | "teacher" | "admin"
    role: str       # "student" | "teacher" | super_admin/admin/editor/mock_admin/mock_editor


class StudentOut(BaseModel):
    id: str
    name: Optional[str] = None
    email: EmailStr
    roll: Optional[int] = None
    class_id: Optional[str] = None
    # Extra display fields — a student sees their own, a teacher sees their roster's.
    gender: Optional[str] = None
    dob: Optional[date_type] = None
    phone: Optional[str] = None
    guardian: Optional[str] = None
    guardian_phone: Optional[str] = None
    address: Optional[str] = None
    avatar: Optional[str] = None

    class Config:
        from_attributes = True


class TeacherOut(BaseModel):
    id: str
    name: Optional[str] = None
    email: EmailStr
    role: Optional[str] = None
    subject: Optional[str] = None
    phone: Optional[str] = None
    join_date: Optional[date_type] = None
    avatar: Optional[str] = None
    message: Optional[str] = None
    bio: Optional[str] = None

    class Config:
        from_attributes = True


class TeacherSelfUpdate(BaseModel):
    """Fields a teacher may edit on their own profile (not email/subject/role — admin-managed)."""
    phone: Optional[str] = None
    avatar: Optional[str] = None
    message: Optional[str] = None
    bio: Optional[str] = None


class FacultyOut(BaseModel):
    """Public-facing faculty directory entry (the /faculty endpoint). Includes contact info
    the school publishes on its public site — no password or internal fields."""
    id: str
    name: Optional[str] = None
    role: Optional[str] = None
    subject: Optional[str] = None
    avatar: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    class_id: Optional[str] = None
    join_date: Optional[date_type] = None
    bio: Optional[str] = None
    message: Optional[str] = None

    class Config:
        from_attributes = True


# ---- Admin CRUD: students and teachers ----
# Separate from StudentOut/TeacherOut above (used by the self-service /me endpoints) since
# admin needs more fields and joined display names - this mirrors the existing pattern of
# multiple view-specific schemas per entity (e.g. ResultOut vs TeacherResultOut).


class Gender(str, Enum):
    male = "Male"
    female = "Female"


class StudentAdminOut(BaseModel):
    id: str
    name: Optional[str] = None
    email: EmailStr
    roll: Optional[int] = None
    class_id: Optional[str] = None
    class_name: Optional[str] = None  # derived via join, not a stored column
    gender: Optional[str] = None
    dob: Optional[date_type] = None
    phone: Optional[str] = None
    guardian: Optional[str] = None
    guardian_phone: Optional[str] = None
    address: Optional[str] = None
    avatar: Optional[str] = None


class StudentIn(BaseModel):
    id: Optional[str] = None  # auto-generated (std_xxxxxxxx) if omitted
    name: str
    email: EmailStr
    # Optional: when omitted the account starts with no password and the student sets it
    # themselves at first login (admins can only clear passwords, not set them).
    password: Optional[str] = None
    roll: Optional[int] = None
    class_id: Optional[str] = None  # validated against classes.id if provided
    gender: Optional[Gender] = None
    dob: Optional[date_type] = None
    phone: Optional[str] = None
    guardian: Optional[str] = None
    guardian_phone: Optional[str] = None
    address: Optional[str] = None
    avatar: Optional[str] = None


class StudentUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    roll: Optional[int] = None
    class_id: Optional[str] = None
    gender: Optional[Gender] = None
    dob: Optional[date_type] = None
    phone: Optional[str] = None
    guardian: Optional[str] = None
    guardian_phone: Optional[str] = None
    address: Optional[str] = None
    avatar: Optional[str] = None
    # Password changes go through the separate /set-password endpoint, same pattern as users.


class TeacherAdminOut(BaseModel):
    id: str
    name: Optional[str] = None
    email: EmailStr
    role: Optional[str] = None  # free-text job title, e.g. "Senior Lecturer" - not an enum
    subject_id: Optional[str] = None
    subject_name: Optional[str] = None  # derived via join on subject_id, not a stored column
    class_id: Optional[str] = None  # legacy/display only - homeroom is set via classes.teacher_id
    class_name: Optional[str] = None  # derived via join, not a stored column
    phone: Optional[str] = None
    join_date: Optional[date_type] = None
    avatar: Optional[str] = None
    message: Optional[str] = None
    bio: Optional[str] = None


class TeacherIn(BaseModel):
    id: Optional[str] = None  # auto-generated (tch_xxxxxxxx) if omitted
    name: str
    email: EmailStr
    # Optional: when omitted the account starts with no password and the teacher sets it
    # themselves at first login (admins can only clear passwords, not set them).
    password: Optional[str] = None
    role: Optional[str] = None  # free-text job title
    subject_id: Optional[str] = None  # validated against subjects.id if provided
    phone: Optional[str] = None
    join_date: Optional[date_type] = None
    avatar: Optional[str] = None
    message: Optional[str] = None
    bio: Optional[str] = None
    # No class_id here on purpose - assign homeroom via PUT /admin/classes/{id} with
    # teacher_id instead, so there's one canonical source of that relationship, not two
    # that can drift out of sync. See note on TeacherAdminOut.class_id.


class TeacherUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    subject_id: Optional[str] = None
    phone: Optional[str] = None
    join_date: Optional[date_type] = None
    avatar: Optional[str] = None
    message: Optional[str] = None
    bio: Optional[str] = None


class AuditAction(str, Enum):
    create = "create"
    update = "update"
    delete = "delete"
    set_password = "set_password"


class AuditResourceType(str, Enum):
    user = "user"
    teacher = "teacher"
    student = "student"
    exam = "exam"
    result = "result"


class AuditLogOut(BaseModel):
    id: str
    created_at: Optional[datetime] = None
    actor_id: str
    actor_role: str
    actor_name: Optional[str] = None  # resolved from users; None if the actor no longer exists
    action: str
    resource_type: str
    resource_id: str
    resource_name: Optional[str] = None  # resolved by resource_type; None if the target was deleted

    class Config:
        from_attributes = True


class AuditLogBulkDeleteIn(BaseModel):
    ids: Optional[List[str]] = None
    before: Optional[datetime] = None  # delete every entry older than this timestamp

    @model_validator(mode="after")
    def _require_one_criterion(self):
        if not self.ids and not self.before:
            raise ValueError("Provide at least one of `ids` or `before` - an empty request would wipe the whole log")
        return self


class AuditLogBulkDeleteOut(BaseModel):
    deleted_count: int


class AdminRole(str, Enum):
    super_admin = "super_admin"
    admin = "admin"
    editor = "editor"
    mock_admin = "mock_admin"
    mock_editor = "mock_editor"


class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str
    phone: Optional[str] = None
    address: Optional[str] = None
    avatar: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserIn(BaseModel):
    id: Optional[str] = None  # auto-generated (usr_xxxxxxxx) if omitted
    name: str
    email: EmailStr
    password: str  # plain text in, hashed server-side - never stored or returned as-is
    role: AdminRole
    phone: Optional[str] = None
    address: Optional[str] = None
    avatar: Optional[str] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[AdminRole] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    avatar: Optional[str] = None
    # Password changes go through a dedicated endpoint (POST /admin/users/{id}/set-password),
    # not this generic update - keeps password resets an explicit, auditable action rather
    # than something that can slip through in a routine profile edit.


class PasswordChangeIn(BaseModel):
    new_password: str


class ErrorResponse(BaseModel):
    """Shape of every non-validation error: 401/403/404/etc."""

    error_code: str
    message: str

    class Config:
        json_schema_extra = {
            "example": {"error_code": "INVALID_CREDENTIALS", "message": "Invalid email or password"}
        }


class FieldError(BaseModel):
    field: str
    message: str


class ValidationErrorResponse(BaseModel):
    """Shape of 422 errors: malformed/missing request fields."""

    error_code: str = "VALIDATION_ERROR"
    message: str = "Invalid request data"
    errors: List[FieldError]


class AttendanceOut(BaseModel):
    id: str
    date: Optional[date_type] = None
    status: Optional[str] = None

    class Config:
        from_attributes = True


class TeacherAttendanceOut(BaseModel):
    """Like AttendanceOut, but identifies which student the record belongs to -
    needed when a teacher views a whole class instead of their own record."""

    id: str
    student_id: str
    student_name: Optional[str] = None
    date: Optional[date_type] = None
    status: Optional[str] = None


class ResultOut(BaseModel):
    id: str
    exam_id: Optional[str] = None
    exam: Optional[str] = None
    subject_id: Optional[str] = None
    subject_name: Optional[str] = None
    subject_code: Optional[str] = None
    marks: Optional[int] = None
    total: Optional[int] = None
    grade: Optional[str] = None
    remarks: Optional[str] = None


class TeacherResultOut(BaseModel):
    """Like ResultOut, but identifies which student the record belongs to."""

    id: str
    student_id: str
    student_name: Optional[str] = None
    exam_id: Optional[str] = None
    exam: Optional[str] = None
    subject_id: Optional[str] = None
    subject_name: Optional[str] = None
    marks: Optional[int] = None
    total: Optional[int] = None
    grade: Optional[str] = None
    remarks: Optional[str] = None


class ScheduleEntryOut(BaseModel):
    id: str
    day: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    room: Optional[str] = None
    subject_id: Optional[str] = None
    subject_name: Optional[str] = None
    subject_code: Optional[str] = None
    teacher_id: Optional[str] = None
    teacher_name: Optional[str] = None


class StudentSelfUpdate(BaseModel):
    """Fields a student may edit on their own profile."""
    phone: Optional[str] = None
    address: Optional[str] = None
    avatar: Optional[str] = None
    guardian: Optional[str] = None
    guardian_phone: Optional[str] = None


class StudentClassOut(BaseModel):
    """A student's own class info, with the homeroom teacher's name/subject joined in."""
    id: str
    name: Optional[str] = None
    grade: Optional[int] = None
    section: Optional[str] = None
    room: Optional[str] = None
    teacher_id: Optional[str] = None
    teacher_name: Optional[str] = None
    teacher_subject: Optional[str] = None


# ---- Admin attendance / results (admin-scoped, academic permission) ----


class AttendanceAdminOut(BaseModel):
    id: str
    student_id: str
    student_name: Optional[str] = None
    class_id: Optional[str] = None
    date: Optional[date_type] = None
    status: Optional[str] = None


class ResultAdminOut(BaseModel):
    id: str
    student_id: str
    student_name: Optional[str] = None
    class_id: Optional[str] = None
    exam_id: Optional[str] = None
    exam: Optional[str] = None
    subject_id: Optional[str] = None
    subject_name: Optional[str] = None
    subject_code: Optional[str] = None
    marks: Optional[int] = None
    total: Optional[int] = None
    grade: Optional[str] = None
    remarks: Optional[str] = None


class ResultAdminIn(BaseModel):
    """Admin single-result upsert. grade is computed server-side from marks/total."""
    student_id: str
    subject_id: str
    exam_id: str
    marks: int
    total: int = 100
    remarks: Optional[str] = None


class ClassOut(BaseModel):
    id: str
    name: Optional[str] = None
    grade: Optional[int] = None
    section: Optional[str] = None
    room: Optional[str] = None
    teacher_id: Optional[str] = None

    class Config:
        from_attributes = True


class ClassRosterOut(BaseModel):
    class_info: ClassOut
    students: List[StudentOut]


class TeacherScheduleEntryOut(BaseModel):
    id: str
    day: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    room: Optional[str] = None
    class_id: Optional[str] = None
    class_name: Optional[str] = None
    subject_id: Optional[str] = None
    subject_name: Optional[str] = None


class AttendanceStatus(str, Enum):
    present = "present"
    absent = "absent"
    late = "late"
    excused = "excused"


class AttendanceMarkIn(BaseModel):
    student_id: str
    status: AttendanceStatus


class AttendanceBulkIn(BaseModel):
    date: date_type
    records: List[AttendanceMarkIn]


class ResultMarkIn(BaseModel):
    student_id: str
    marks: int = Field(ge=0, description="Grade is auto-calculated from marks/total - not provided here")
    total: int = Field(gt=0, default=100)
    remarks: Optional[str] = None


class ResultBulkIn(BaseModel):
    class_id: str
    subject_id: str
    exam_id: str
    records: List[ResultMarkIn]


# ---- Academic admin CRUD: classes, subjects, exams, periods, schedule ----
# *Update schemas are intentionally all-optional ("PATCH" semantics under PUT): only fields
# you actually send get changed. Omitting a field leaves it as-is; you can't currently clear
# a field to NULL this way, which is a fine tradeoff for admin data entry.


class ClassIn(BaseModel):
    id: Optional[str] = None  # auto-generated (cls_xxxx) if omitted
    name: str
    grade: Optional[int] = None
    section: Optional[str] = None
    room: Optional[str] = None
    teacher_id: Optional[str] = None


class ClassUpdate(BaseModel):
    name: Optional[str] = None
    grade: Optional[int] = None
    section: Optional[str] = None
    room: Optional[str] = None
    teacher_id: Optional[str] = None


class SubjectOut(BaseModel):
    id: str
    name: Optional[str] = None
    code: Optional[str] = None
    is_active: bool = True

    class Config:
        from_attributes = True


class SubjectIn(BaseModel):
    id: Optional[str] = None  # auto-generated (sub_xxxx) if omitted
    name: str
    code: Optional[str] = None


class SubjectUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None


class CountScopeType(str, Enum):
    class_ = "class"
    student = "student"


class CountMetric(str, Enum):
    attendance_present = "attendance_present"
    attendance_absent = "attendance_absent"
    attendance_late = "attendance_late"
    attendance_excused = "attendance_excused"
    results_entry_count = "results_entry_count"
    results_marks_sum = "results_marks_sum"
    student_count = "student_count"


class CountPeriodType(str, Enum):
    month = "month"
    exam = "exam"
    current = "current"  # not time-scoped, e.g. student_count (a live roster size)


class CountOut(BaseModel):
    scope_type: CountScopeType = Field(description="'class' (a class's roster/attendance/results) or 'student' (one student's results)")
    scope_id: str = Field(description="The class_id or student_id this row is about, per scope_type")
    metric: CountMetric = Field(description="Which number this row holds - see the endpoint description for the full list")
    period_type: CountPeriodType = Field(description="What period_key means: 'month', 'exam', or 'current' (not time-scoped)")
    period_key: str = Field(description="'2026-07' for period_type=month, an exam_id for period_type=exam, or 'all' for period_type=current")
    subject_id: Optional[str] = Field(None, description="A subject_id, or null for the all-subjects rollup row")
    value: int = Field(description="The count/sum itself - e.g. a day count, an entry count, or a marks total")

    class Config:
        from_attributes = True


class ExamStatus(str, Enum):
    upcoming = "upcoming"
    ongoing = "ongoing"
    grading = "grading"
    ended = "ended"


class ExamOut(BaseModel):
    id: str
    name: str
    start_date: Optional[date_type] = None
    end_date: Optional[date_type] = None
    status: str  # kept as plain str on output - legacy rows may predate the enum constraint

    class Config:
        from_attributes = True


class ExamIn(BaseModel):
    id: Optional[str] = None  # auto-generated (exam_xxxx) if omitted
    name: str
    start_date: Optional[date_type] = None
    end_date: Optional[date_type] = None
    status: ExamStatus = ExamStatus.upcoming

    @model_validator(mode="after")
    def _check_date_order(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError(f"start_date ({self.start_date}) cannot be after end_date ({self.end_date})")
        return self


class ExamUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[date_type] = None
    end_date: Optional[date_type] = None
    status: Optional[ExamStatus] = None

    @model_validator(mode="after")
    def _check_date_order(self):
        # Only catches both-fields-in-this-request conflicts. A partial update changing just
        # one date against an unchanged other date is checked separately in the route handler,
        # since this schema has no knowledge of the existing row.
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError(f"start_date ({self.start_date}) cannot be after end_date ({self.end_date})")
        return self


class PeriodOut(BaseModel):
    id: str
    sort_order: int
    start_time: str
    end_time: str
    is_break: bool
    label: Optional[str] = None

    class Config:
        from_attributes = True


class PeriodIn(BaseModel):
    id: Optional[str] = None  # auto-generated (per_xxxx) if omitted
    sort_order: int
    start_time: TimeStr
    end_time: TimeStr
    is_break: bool = False
    label: Optional[str] = None

    @model_validator(mode="after")
    def _check_time_order(self):
        if self.start_time >= self.end_time:
            raise ValueError(f"start_time ({self.start_time}) must be before end_time ({self.end_time})")
        return self


class PeriodUpdate(BaseModel):
    sort_order: Optional[int] = None
    start_time: Optional[TimeStr] = None
    end_time: Optional[TimeStr] = None
    is_break: Optional[bool] = None
    label: Optional[str] = None

    @model_validator(mode="after")
    def _check_time_order(self):
        # Only catches both-fields-in-this-request conflicts; a partial update changing just
        # one time against an unchanged other time is checked in the route handler instead.
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValueError(f"start_time ({self.start_time}) must be before end_time ({self.end_time})")
        return self


class ScheduleOut(BaseModel):
    id: str
    class_id: Optional[str] = None
    subject_id: Optional[str] = None
    teacher_id: Optional[str] = None
    day: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    room: Optional[str] = None
    period_id: Optional[str] = None

    class Config:
        from_attributes = True


class ScheduleIn(BaseModel):
    id: Optional[str] = None  # auto-generated (sch_xxxx) if omitted
    class_id: str
    subject_id: str
    teacher_id: str
    day: str
    start_time: TimeStr
    end_time: TimeStr
    room: Optional[str] = None
    period_id: Optional[str] = None

    @model_validator(mode="after")
    def _check_time_order(self):
        if self.start_time >= self.end_time:
            raise ValueError(f"start_time ({self.start_time}) must be before end_time ({self.end_time})")
        return self


class ScheduleUpdate(BaseModel):
    class_id: Optional[str] = None
    subject_id: Optional[str] = None
    teacher_id: Optional[str] = None
    day: Optional[str] = None
    start_time: Optional[TimeStr] = None
    end_time: Optional[TimeStr] = None
    room: Optional[str] = None
    period_id: Optional[str] = None

    @model_validator(mode="after")
    def _check_time_order(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValueError(f"start_time ({self.start_time}) must be before end_time ({self.end_time})")
        return self


# ---- CMS admin + public: notices, events/images, testimonials, admission status ----
# author_id is server-set from the logged-in principal on create, never accepted from the
# client - prevents spoofing authorship of notices/events.


class NoticeCategory(str, Enum):
    general = "General"
    event = "Event"
    exam = "Exam"
    academic = "Academic"
    holiday = "Holiday"
    administrative = "Administrative"


class NoticePriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class NoticeOut(BaseModel):
    id: str
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None  # kept as plain str on output - legacy rows may predate the enum
    priority: Optional[str] = None
    author_id: Optional[str] = None
    date: Optional[date_type] = None
    expires: Optional[date_type] = None

    class Config:
        from_attributes = True


class NoticeIn(BaseModel):
    id: Optional[str] = None  # auto-generated (not_xxxxxxxx) if omitted
    title: str
    content: str
    category: Optional[NoticeCategory] = None
    priority: NoticePriority = NoticePriority.medium
    date: date_type
    expires: Optional[date_type] = None

    @model_validator(mode="after")
    def _check_date_order(self):
        if self.expires and self.date > self.expires:
            raise ValueError(f"date ({self.date}) cannot be after expires ({self.expires})")
        return self


class NoticeUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[NoticeCategory] = None
    priority: Optional[NoticePriority] = None
    date: Optional[date_type] = None
    expires: Optional[date_type] = None

    @model_validator(mode="after")
    def _check_date_order(self):
        # Only catches both-in-this-request conflicts; partial updates are cross-checked
        # against the existing row in the route handler, same pattern as exams/schedule.
        if self.date and self.expires and self.date > self.expires:
            raise ValueError(f"date ({self.date}) cannot be after expires ({self.expires})")
        return self


class EventImageOut(BaseModel):
    id: str
    event_id: Optional[str] = None
    url: str
    sort_order: int = 0

    class Config:
        from_attributes = True


class EventImageIn(BaseModel):
    id: Optional[str] = None  # auto-generated (eimg_xxxxxxxx) if omitted
    url: str
    sort_order: int = 0


class EventImageUpdate(BaseModel):
    url: Optional[str] = None
    sort_order: Optional[int] = None


class EventCategory(str, Enum):
    general = "General"
    academic = "Academic"
    sports = "Sports"
    cultural = "Cultural"


class EventOut(BaseModel):
    id: str
    title: str
    slug: str
    excerpt: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None  # kept as plain str on output - legacy rows may predate the enum
    date: Optional[date_type] = None
    cover_image: Optional[str] = None
    author_id: Optional[str] = None
    author_name: Optional[str] = None
    published: Optional[bool] = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EventWithImagesOut(EventOut):
    images: List[EventImageOut] = []


class EventIn(BaseModel):
    id: Optional[str] = None  # auto-generated (evt_xxxxxxxx) if omitted
    title: str
    slug: Optional[str] = None  # auto-generated from title if omitted; de-duplicated if taken
    excerpt: Optional[str] = None
    content: Optional[str] = None
    category: Optional[EventCategory] = None
    date: Optional[date_type] = None
    cover_image: Optional[str] = None
    author_name: Optional[str] = None
    published: bool = False


class EventUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    excerpt: Optional[str] = None
    content: Optional[str] = None
    category: Optional[EventCategory] = None
    date: Optional[date_type] = None
    cover_image: Optional[str] = None
    author_name: Optional[str] = None
    published: Optional[bool] = None


class TestimonialOut(BaseModel):
    id: str
    name: Optional[str] = None
    avatar: Optional[str] = None
    quote: Optional[str] = None
    class_id: Optional[str] = None
    class_name: Optional[str] = None  # derived via join, not a stored column - see admin_cms.py
    active: Optional[bool] = True

    class Config:
        from_attributes = True


class TestimonialIn(BaseModel):
    id: Optional[str] = None  # auto-generated (tst_xxxxxxxx) if omitted
    name: str
    avatar: Optional[str] = None
    quote: str
    class_id: Optional[str] = None  # validated against classes.id if provided - not required
    active: bool = True


class TestimonialUpdate(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    quote: Optional[str] = None
    class_id: Optional[str] = None
    active: Optional[bool] = None


class AdmissionStatusOut(BaseModel):
    id: str
    value: bool

    class Config:
        from_attributes = True


class AdmissionStatusUpdate(BaseModel):
    value: bool