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
    class_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("classes.id", ondelete="SET NULL"))
    phone: Mapped[Optional[str]] = mapped_column(String)
    join_date: Mapped[Optional[date]] = mapped_column(Date)
    avatar: Mapped[Optional[str]] = mapped_column(String)
    subject_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("subjects.id"))
    message: Mapped[Optional[str]] = mapped_column(Text)
    bio: Mapped[Optional[str]] = mapped_column(Text)


class Class(Base):
    __tablename__ = "classes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String)
    grade: Mapped[Optional[int]] = mapped_column(Integer)
    section: Mapped[Optional[str]] = mapped_column(String)
    room: Mapped[Optional[str]] = mapped_column(String)
    teacher_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("teachers.id"))


class Student(Base):
    __tablename__ = "students"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String)
    roll: Mapped[Optional[int]] = mapped_column(Integer)
    class_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("classes.id", ondelete="SET NULL"))
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
    student_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("students.id", ondelete="CASCADE"))
    subject_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("subjects.id"))
    exam: Mapped[Optional[str]] = mapped_column(String)
    marks: Mapped[Optional[int]] = mapped_column(Integer)
    total: Mapped[Optional[int]] = mapped_column(Integer)
    grade: Mapped[Optional[str]] = mapped_column(String)
    remarks: Mapped[Optional[str]] = mapped_column(String)
    exam_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("exams.id"))


class Attendance(Base):
    __tablename__ = "attendance"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    student_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("students.id", ondelete="CASCADE"))
    date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[Optional[str]] = mapped_column(String)


class Schedule(Base):
    __tablename__ = "schedule"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    class_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("classes.id"))
    subject_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("subjects.id"))
    teacher_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("teachers.id"))
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