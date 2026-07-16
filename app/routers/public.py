from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(tags=["public"])

MAX_FEATURED_EVENTS = 6

# No oauth2 import, no Depends(require_*) anywhere in this file - these routes are
# intentionally public. Each query is unconditionally filtered to the "live" subset (no
# drafts, no expired notices, no inactive testimonials) - there's no auth-conditional branch
# that could accidentally leak unpublished content, because there's no branch at all.


@router.get(
    "/notices",
    response_model=schemas.Page[schemas.NoticeOut],
    summary="List notices",
    description=" Returns all notices, including expired ones - "
    "filter by `category`, `title` (partial/case-insensitive search), and/or date range on "
    "`date` or `expires` if you only want current/relevant ones. Paginated via `limit`/`offset`.",
)
def list_public_notices(
    category: Optional[schemas.NoticeCategory] = Query(None),
    title: Optional[str] = Query(None, description="Partial, case-insensitive match on title"),
    date_from: Optional[date] = Query(None, description="Inclusive lower bound on `date`"),
    date_to: Optional[date] = Query(None, description="Inclusive upper bound on `date`"),
    expires_from: Optional[date] = Query(None, description="Inclusive lower bound on `expires`"),
    expires_to: Optional[date] = Query(None, description="Inclusive upper bound on `expires`"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(models.Notice)
    if category:
        query = query.filter(models.Notice.category == category)
    if title:
        query = query.filter(models.Notice.title.ilike(f"%{title.strip()}%"))
    if date_from:
        query = query.filter(models.Notice.date >= date_from)
    if date_to:
        query = query.filter(models.Notice.date <= date_to)
    if expires_from:
        query = query.filter(models.Notice.expires >= expires_from)
    if expires_to:
        query = query.filter(models.Notice.expires <= expires_to)
    total = query.count()
    items = query.order_by(models.Notice.date.desc()).offset(offset).limit(limit).all()
    return schemas.Page(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/events",
    response_model=schemas.Page[schemas.EventOut],
    summary="List published events",
    description=" Only returns events with `published: true`. "
    "Filter by `category`, `author_id`, `title` (partial/case-insensitive search), and/or "
    "date range via `date_from`/`date_to`. Paginated via `limit`/`offset`.",
)
def list_public_events(
    category: Optional[schemas.EventCategory] = Query(None),
    author_id: Optional[str] = Query(None),
    title: Optional[str] = Query(None, description="Partial, case-insensitive match on title"),
    date_from: Optional[date] = Query(None, description="Inclusive lower bound on `date`"),
    date_to: Optional[date] = Query(None, description="Inclusive upper bound on `date`"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(models.Event).filter(models.Event.published.is_(True))
    if category:
        query = query.filter(models.Event.category == category)
    if author_id:
        query = query.filter(models.Event.author_id == author_id)
    if title:
        query = query.filter(models.Event.title.ilike(f"%{title.strip()}%"))
    if date_from:
        query = query.filter(models.Event.date >= date_from)
    if date_to:
        query = query.filter(models.Event.date <= date_to)
    total = query.count()
    items = query.order_by(models.Event.date.desc()).offset(offset).limit(limit).all()
    return schemas.Page(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/events/featured",
    response_model=List[schemas.EventOut],
    summary="List featured published events",
    description=" Only returns events with `published: true` and "
    f"`featured: true`, capped at {MAX_FEATURED_EVENTS}."
    " Not paginated. Ordered by `date` descending.",
)
def list_featured_events(db: Session = Depends(get_db)):
    return (
        db.query(models.Event)
        .filter(models.Event.published.is_(True), models.Event.featured.is_(True))
        .order_by(models.Event.date.desc())
        .limit(MAX_FEATURED_EVENTS)
        .all()
    )


@router.get(
    "/events/{slug}",
    response_model=schemas.EventWithImagesOut,
    summary="Get one published event by slug, with its images",
    description=" Looks up by `slug`, not `id` - matches how a blog "
    "post URL normally works. An unpublished event's slug returns 404, same as a nonexistent one "
    "- doesn't reveal that a draft exists at that slug.",
    responses={404: {"model": schemas.ErrorResponse, "description": "No published event with that slug"}},
)
def get_public_event(slug: str, db: Session = Depends(get_db)):
    row = (
        db.query(models.Event)
        .filter(models.Event.slug == slug, models.Event.published.is_(True))
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "EVENT_NOT_FOUND", "message": f"No published event at '{slug}'"},
        )
    images = (
        db.query(models.EventImage)
        .filter(models.EventImage.event_id == row.id)
        .order_by(models.EventImage.sort_order)
        .all()
    )
    return schemas.EventWithImagesOut(**schemas.EventOut.model_validate(row).model_dump(), images=images)


@router.get(
    "/testimonials",
    response_model=List[schemas.TestimonialOut],
    summary="List active testimonials",
    description=" Only returns testimonials with `active: true`. "
    "Filter by `class_id` and/or `name` (partial, case-insensitive search).",
)
def list_public_testimonials(
    class_id: Optional[str] = Query(None),
    name: Optional[str] = Query(None, description="Partial, case-insensitive match on name"),
    db: Session = Depends(get_db),
):
    query = (
        db.query(models.Testimonial, models.Class.name.label("class_name"))
        .outerjoin(models.Class, models.Testimonial.class_id == models.Class.id)
        .filter(models.Testimonial.active.is_(True))
    )
    if class_id:
        query = query.filter(models.Testimonial.class_id == class_id)
    if name:
        query = query.filter(models.Testimonial.name.ilike(f"%{name.strip()}%"))
    rows = query.all()
    return [
        schemas.TestimonialOut(
            id=row.id,
            name=row.name,
            avatar=row.avatar,
            quote=row.quote,
            class_id=row.class_id,
            class_name=class_name,
            active=row.active,
        )
        for row, class_name in rows
    ]


@router.get(
    "/faculty",
    response_model=List[schemas.FacultyOut],
    summary="List faculty/staff for the public site",
    description=" Returns the school's teaching and leadership staff "
    "for the public faculty page, ordered by join date. Exposes only public-facing fields "
    "(name, role, subject, avatar, contact, bio/message) — never passwords or internal data. "
    "Optional `role` (exact match, e.g. \"Principal\") and `subject` (partial, case-insensitive) "
    "filters - used e.g. by the admission acceptance letter to look up a specific signatory "
    "without guessing at a name.",
)
def list_public_faculty(
    role: Optional[str] = Query(None, description="Exact match on Teacher.role, e.g. \"Principal\""),
    subject: Optional[str] = Query(None, description="Partial, case-insensitive match on Teacher.subject"),
    db: Session = Depends(get_db),
):
    query = db.query(models.Teacher)
    if role:
        query = query.filter(models.Teacher.role == role)
    if subject:
        query = query.filter(models.Teacher.subject.ilike(f"%{subject}%"))
    return query.order_by(models.Teacher.join_date).all()


@router.get(
    "/classes",
    response_model=List[schemas.ClassPublicOut],
    summary="List classes accepted by the active admission cycle (public, minimal fields)",
    description="Public, no auth required. Used by the admission form's \"Applying for "
    "Class\" dropdown. Scoped to whichever classes are attached to the currently active "
    "AdmissionCycle - if the active cycle has no classes attached (or no cycle is active), "
    "returns ALL classes as a fallback so the form isn't left with an empty dropdown before "
    "an admin has configured cycle scoping. Excludes room/teacher_id (internal scheduling "
    "detail) - see GET /admin/classes for the full admin view.",
)
def list_public_classes(db: Session = Depends(get_db)):
    active_cycle = db.query(models.AdmissionCycle).filter(models.AdmissionCycle.is_active.is_(True)).first()
    if active_cycle:
        scoped = (
            db.query(models.Class)
            .join(models.AdmissionCycleClass, models.AdmissionCycleClass.class_id == models.Class.id)
            .filter(models.AdmissionCycleClass.cycle_id == active_cycle.id)
            .order_by(models.Class.grade, models.Class.section)
            .all()
        )
        if scoped:
            return scoped
    return db.query(models.Class).order_by(models.Class.grade, models.Class.section).all()


@router.get(
    "/admission-status",
    response_model=schemas.AdmissionStatusOut,
    summary="Check whether admissions are currently open",
    description=" Includes the active admission cycle's name/year "
    "(if one exists) so the applicant-facing page can display it instead of a hardcoded year.",
)
def get_public_admission_status(db: Session = Depends(get_db)):
    row = db.query(models.AdmissionOpen).filter(models.AdmissionOpen.id == "admission_status").first()
    cycle = db.query(models.AdmissionCycle).filter(models.AdmissionCycle.is_active == True).first()  # noqa: E712
    cycle_name = cycle.name if cycle else None
    academic_year = cycle.academic_year if cycle else None
    if not row:
        return schemas.AdmissionStatusOut(
            id="admission_status", value=False, cycle_name=cycle_name, academic_year=academic_year,
        )
    return schemas.AdmissionStatusOut(
        id=row.id, value=row.value, cycle_name=cycle_name, academic_year=academic_year,
    )