from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .database import Base


class Subject(Base):
    __tablename__ = "subjects"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String)
    code: Mapped[Optional[str]] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String)
    subject: Mapped[Optional[str]] = mapped_column(String)
    class_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("classes.id", ondelete="SET NULL"), index=True)
    phone: Mapped[Optional[str]] = mapped_column(String)
    join_date: Mapped[Optional[date]] = mapped_column(Date)
    avatar: Mapped[Optional[str]] = mapped_column(String)
    subject_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("subjects.id"), index=True)
    message: Mapped[Optional[str]] = mapped_column(Text)
    bio: Mapped[Optional[str]] = mapped_column(Text)


class Class(Base):
    __tablename__ = "classes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String)
    grade: Mapped[Optional[int]] = mapped_column(Integer)
    section: Mapped[Optional[str]] = mapped_column(String)
    room: Mapped[Optional[str]] = mapped_column(String)
    teacher_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("teachers.id"), index=True)


class Student(Base):
    __tablename__ = "students"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String)
    roll: Mapped[Optional[int]] = mapped_column(Integer)
    class_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("classes.id", ondelete="SET NULL"), index=True)
    gender: Mapped[Optional[str]] = mapped_column(String)
    dob: Mapped[Optional[date]] = mapped_column(Date)
    phone: Mapped[Optional[str]] = mapped_column(String)
    guardian: Mapped[Optional[str]] = mapped_column(String)
    guardian_phone: Mapped[Optional[str]] = mapped_column(String)
    address: Mapped[Optional[str]] = mapped_column(Text)
    avatar: Mapped[Optional[str]] = mapped_column(String)


class Period(Base):
    __tablename__ = "periods"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[str] = mapped_column(String, nullable=False)
    end_time: Mapped[str] = mapped_column(String, nullable=False)
    is_break: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    label: Mapped[Optional[str]] = mapped_column(String)


class Exam(Base):
    __tablename__ = "exams"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, nullable=False, default="upcoming")
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    excerpt: Mapped[Optional[str]] = mapped_column(Text)
    content: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String)
    date: Mapped[Optional[date]] = mapped_column(Date)
    cover_image: Mapped[Optional[str]] = mapped_column(String)
    author_id: Mapped[Optional[str]] = mapped_column(String)
    author_name: Mapped[Optional[str]] = mapped_column(String)
    published: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    featured: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventImage(Base):
    __tablename__ = "event_images"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("events.id"))
    url: Mapped[Optional[str]] = mapped_column(String)
    sort_order: Mapped[Optional[int]] = mapped_column(Integer, default=0)


class Notice(Base):
    __tablename__ = "notices"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[Optional[str]] = mapped_column(String)
    content: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String)
    priority: Mapped[Optional[str]] = mapped_column(String)
    author_id: Mapped[Optional[str]] = mapped_column(String)
    date: Mapped[Optional[date]] = mapped_column(Date)
    expires: Mapped[Optional[date]] = mapped_column(Date)


class Result(Base):
    __tablename__ = "results"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    student_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("students.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("subjects.id"), index=True)
    exam: Mapped[Optional[str]] = mapped_column(String)
    marks: Mapped[Optional[int]] = mapped_column(Integer)
    total: Mapped[Optional[int]] = mapped_column(Integer)
    grade: Mapped[Optional[str]] = mapped_column(String)
    remarks: Mapped[Optional[str]] = mapped_column(String)
    exam_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("exams.id"), index=True)


class Attendance(Base):
    __tablename__ = "attendance"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    student_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("students.id", ondelete="CASCADE"), index=True)
    date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    status: Mapped[Optional[str]] = mapped_column(String)


class Schedule(Base):
    __tablename__ = "schedule"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    class_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("classes.id"), index=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("subjects.id"))
    teacher_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("teachers.id"), index=True)
    day: Mapped[Optional[str]] = mapped_column(String)
    start_time: Mapped[Optional[str]] = mapped_column(String)
    end_time: Mapped[Optional[str]] = mapped_column(String)
    room: Mapped[Optional[str]] = mapped_column(String)
    period_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("periods.id"))


class Testimonial(Base):
    __tablename__ = "testimonials"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String)
    avatar: Mapped[Optional[str]] = mapped_column(String)
    quote: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    class_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("classes.id", ondelete="SET NULL"))


class AdmissionOpen(Base):
    __tablename__ = "admission_open"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    actor_role: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)  # create | update | delete | set_password
    resource_type: Mapped[str] = mapped_column(String, nullable=False)  # user | teacher | student | exam | result
    resource_id: Mapped[str] = mapped_column(String, nullable=False)


class User(Base):
    """Admin-tier accounts: super_admin / admin / editor / mock_admin / mock_editor (mock_* = read-only demo)."""

    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String)
    avatar: Mapped[Optional[str]] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, nullable=False, default="admin")
    address: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PasswordResetRequest(Base):
    """A student/teacher's request for an admin to reset (clear) their password.
    `email` refers to a row in students or teachers depending on `role`."""

    __tablename__ = "password_reset_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False)  # student | teacher
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # pending | accepted
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdmissionCycle(Base):
    """A single admissions intake period (e.g. "2026-27 Intake"). Exactly one row should have
    is_active=True at a time (enforced in application code in admin_admissions.py, not a DB
    constraint - see AdmissionCycleUpdate handling)."""

    __tablename__ = "admission_cycles"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    academic_year: Mapped[Optional[str]] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    seats_available: Mapped[Optional[int]] = mapped_column(Integer)
    results_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdmissionCycleClass(Base):
    """Which classes a given admission cycle accepts applications for. Plain many-to-many
    join, no uniqueness constraint - a class may appear in more than one cycle (e.g.
    overlapping intake periods), and this table doesn't try to prevent that."""

    __tablename__ = "admission_cycle_classes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    cycle_id: Mapped[str] = mapped_column(
        String, ForeignKey("admission_cycles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    class_id: Mapped[str] = mapped_column(
        String, ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )


class Application(Base):
    """A single admissions application. No password/login - access to status is via
    reference_number + matching contact_email/contact_phone (see admissions_public.py)."""

    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    reference_number: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    cycle_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("admission_cycles.id"), index=True)
    student_name: Mapped[str] = mapped_column(String, nullable=False)
    photo_url: Mapped[Optional[str]] = mapped_column(String)  # Cloudinary secure_url, required at apply time
    dob: Mapped[Optional[date]] = mapped_column(Date)
    gender: Mapped[Optional[str]] = mapped_column(String)
    applying_class: Mapped[Optional[str]] = mapped_column(String)
    blood_group: Mapped[Optional[str]] = mapped_column(String)
    previous_school: Mapped[Optional[str]] = mapped_column(String)
    contact_method: Mapped[str] = mapped_column(String, nullable=False)  # "email" | "phone"
    contact_email: Mapped[Optional[str]] = mapped_column(String, index=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String, index=True)
    guardian_name: Mapped[Optional[str]] = mapped_column(String)
    guardian_relationship: Mapped[Optional[str]] = mapped_column(String)
    guardian_phone: Mapped[Optional[str]] = mapped_column(String)
    guardian_email: Mapped[Optional[str]] = mapped_column(String)
    guardian_occupation: Mapped[Optional[str]] = mapped_column(String)
    address: Mapped[Optional[str]] = mapped_column(Text)
    medical_conditions: Mapped[Optional[str]] = mapped_column(Text)
    extracurricular: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False, default="submitted", index=True)
    entrance_score: Mapped[Optional[int]] = mapped_column(Integer)
    interview_outcome: Mapped[Optional[str]] = mapped_column(String)
    interview_notes: Mapped[Optional[str]] = mapped_column(Text)
    decision_notes: Mapped[Optional[str]] = mapped_column(Text)
    submitted_ip: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApplicationDocument(Base):
    __tablename__ = "application_documents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String, ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    url: Mapped[str] = mapped_column(String, nullable=False)
    public_id: Mapped[Optional[str]] = mapped_column(String)
    file_name: Mapped[Optional[str]] = mapped_column(String)
    mime_type: Mapped[Optional[str]] = mapped_column(String)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    doc_type: Mapped[Optional[str]] = mapped_column(String)
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApplicationExamSchedule(Base):
    __tablename__ = "application_exam_schedules"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String, ForeignKey("applications.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    exam_date: Mapped[Optional[date]] = mapped_column(Date)
    exam_time: Mapped[Optional[str]] = mapped_column(String)
    venue: Mapped[Optional[str]] = mapped_column(String)
    room: Mapped[Optional[str]] = mapped_column(String)  # e.g. "Room 204" - within the venue
    # Generated at schedule time (utils.generate_roll_number) - deliberately NOT derived from
    # reference_number or any PII, since this is the identifier exposed to the blind grading flow.
    roll_number: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApplicationGradingAssignment(Base):
    """One teacher assigned to grade one applicant's entrance exam paper. Unique per
    application - no multi-grader. Grading is blind: see schemas.ApplicationGradingOut."""

    __tablename__ = "application_grading_assignments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String, ForeignKey("applications.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("teachers.id"), index=True, nullable=False)
    assigned_by: Mapped[Optional[str]] = mapped_column(String)  # admin user id
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String, nullable=False, default="assigned")  # assigned | graded


class ApplicationExamResult(Base):
    """Deterministic id (f"aexr_{application_id}") supports upsert-by-natural-key, same pattern
    as models.Result."""

    __tablename__ = "application_exam_results"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String, ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    marks: Mapped[Optional[int]] = mapped_column(Integer)
    total: Mapped[Optional[int]] = mapped_column(Integer, default=100)
    remarks: Mapped[Optional[str]] = mapped_column(String)
    graded_by: Mapped[Optional[str]] = mapped_column(String)  # teacher id
    graded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApplicationInterview(Base):
    __tablename__ = "application_interviews"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String, ForeignKey("applications.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    interview_date: Mapped[Optional[date]] = mapped_column(Date)
    interview_time: Mapped[Optional[str]] = mapped_column(String)
    mode: Mapped[Optional[str]] = mapped_column(String)  # in_person | phone | video
    interviewer_name: Mapped[Optional[str]] = mapped_column(String)
    # Mode-specific location detail - only the one matching `mode` is expected to be set, but
    # nothing enforces that at the DB level (mirrors the codebase's light-touch invariant style).
    room: Mapped[Optional[str]] = mapped_column(String)  # in_person
    meeting_link: Mapped[Optional[str]] = mapped_column(String)  # video
    phone_number: Mapped[Optional[str]] = mapped_column(String)  # phone
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SubmissionAttempt(Base):
    """One row per POST /admissions/apply attempt (success or rejected), inserted before the
    rest of the apply logic runs - Postgres-backed sliding-window rate limit, survives restarts
    and multi-worker deployments (unlike an in-memory limiter)."""

    __tablename__ = "submission_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip_address: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class VerifyAttempt(Base):
    """One row per POST /admissions/{ref}/verify call (success or failure) - backs the
    per-reference-number lockout."""

    __tablename__ = "verify_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reference_number: Mapped[str] = mapped_column(String, nullable=False, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Count(Base):
    """A single pre-aggregated number, kept in sync with its source rows on every write
    (see utils.bump_count). One row per (scope, metric, period[, subject]) - e.g. how many
    students in class 'cls_9a' were present in "2026-07", or the sum of marks + entry count
    for class 'cls_9a' in exam 'exam_1' subject 'sub_math' (subject_id NULL = all-subjects
    rollup for that scope+exam). `id` is a deterministic composite key so an upsert can target
    a row by primary key without a separate lookup query."""

    __tablename__ = "counts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    scope_type: Mapped[str] = mapped_column(String, nullable=False, index=True)  # class | student
    scope_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # attendance_present | attendance_absent | attendance_late | attendance_excused |
    # results_entry_count | results_marks_sum
    period_type: Mapped[str] = mapped_column(String, nullable=False)  # month | exam
    period_key: Mapped[str] = mapped_column(String, nullable=False, index=True)  # "2026-07" or an exam_id
    subject_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # NULL = all-subjects rollup
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())