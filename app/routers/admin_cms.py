from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import models, oauth2, schemas, utils
from ..database import get_db

router = APIRouter(prefix="/admin")

CMS = Depends(oauth2.require_admin_permission("cms"))


def _get_or_404(db: Session, model, row_id: str, error_code: str, label: str):
    row = db.query(model).filter(model.id == row_id).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": error_code, "message": f"No {label} with id '{row_id}'"},
        )
    return row


def _apply_updates(row, payload, exclude_unset_fields: set):
    for field in exclude_unset_fields:
        setattr(row, field, getattr(payload, field))


MAX_FEATURED_EVENTS = 6


def _enforce_featured_cap(db: Session, exclude_id: Optional[str] = None):
    """Keeps at most MAX_FEATURED_EVENTS featured - 1 events featured. Called right before
    featuring one more, so the oldest (by `date`) among the rest gets bumped to make room."""
    query = db.query(models.Event).filter(models.Event.featured.is_(True))
    if exclude_id:
        query = query.filter(models.Event.id != exclude_id)
    featured = query.order_by(models.Event.date.desc(), models.Event.created_at.desc()).all()
    for stale in featured[MAX_FEATURED_EVENTS - 1:]:
        stale.featured = False


def _unique_slug(db: Session, base_slug: str, exclude_id: Optional[str] = None) -> str:
    """Appends -2, -3, ... until the slug is free. events.slug has a DB unique constraint,
    so this avoids a raw IntegrityError 500 on the obvious case (two events, same title)."""
    slug = base_slug
    suffix = 2
    while True:
        query = db.query(models.Event).filter(models.Event.slug == slug)
        if exclude_id:
            query = query.filter(models.Event.id != exclude_id)
        if not query.first():
            return slug
        slug = f"{base_slug}-{suffix}"
        suffix += 1


# ---------------------------------------------------------------------------
# Notices
# ---------------------------------------------------------------------------


@router.get(
    "/notices",
    response_model=schemas.Page[schemas.NoticeOut],
    tags=["admin-notices"],
    summary="List all notices",
    description="Admin view - includes expired notices. Filter by `category`, `priority`, "
    "`title` (partial/case-insensitive search), and/or date range on `date` or `expires`. "
    "Paginated via `limit`/`offset`.",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"}},
)
def list_notices(
    category: Optional[schemas.NoticeCategory] = Query(None),
    priority: Optional[schemas.NoticePriority] = Query(None),
    title: Optional[str] = Query(None, description="Partial, case-insensitive match on title"),
    date_from: Optional[date] = Query(None, description="Inclusive lower bound on `date`"),
    date_to: Optional[date] = Query(None, description="Inclusive upper bound on `date`"),
    expires_from: Optional[date] = Query(None, description="Inclusive lower bound on `expires`"),
    expires_to: Optional[date] = Query(None, description="Inclusive upper bound on `expires`"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _principal: dict = CMS,
):
    query = db.query(models.Notice)
    if category:
        query = query.filter(models.Notice.category == category)
    if priority:
        query = query.filter(models.Notice.priority == priority)
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
    "/notices/{notice_id}",
    response_model=schemas.NoticeOut,
    tags=["admin-notices"],
    summary="Get one notice",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No notice with that id"},
    },
)
def get_notice(notice_id: str, db: Session = Depends(get_db), _principal: dict = CMS):
    return _get_or_404(db, models.Notice, notice_id, "NOTICE_NOT_FOUND", "notice")


@router.post(
    "/notices",
    response_model=schemas.NoticeOut,
    status_code=status.HTTP_201_CREATED,
    tags=["admin-notices"],
    summary="Create a notice",
    description="`id` is auto-generated (`not_xxxxxxxx`) if omitted. `author_id` is set from "
    "the logged-in account, not accepted from the request body. `category` must be one of: "
    "General, Event, Exam, Academic, Holiday, Administrative. `priority` must be one of: "
    "low, medium, high. `date` must not be after `expires`.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        409: {"model": schemas.ErrorResponse, "description": "Given id already exists"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed body, invalid priority, or date after expires"},
    },
)
def create_notice(payload: schemas.NoticeIn, db: Session = Depends(get_db), principal: dict = CMS):
    row_id = payload.id or utils.generate_id("not_")
    if db.query(models.Notice).filter(models.Notice.id == row_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ID_ALREADY_EXISTS", "message": f"Notice '{row_id}' already exists"},
        )
    row = models.Notice(
        id=row_id,
        title=payload.title,
        content=payload.content,
        category=payload.category,
        priority=payload.priority.value,
        author_id=principal["id"],
        date=payload.date,
        expires=payload.expires,
    )
    db.add(row)
    db.commit()
    return row


@router.put(
    "/notices/{notice_id}",
    response_model=schemas.NoticeOut,
    tags=["admin-notices"],
    summary="Update a notice",
    description="Partial update — only send the fields you want to change. `category` must "
    "be one of: General, Event, Exam, Academic, Holiday, Administrative. `priority` must be "
    "one of: low, medium, high. The resulting "
    "date/expires (after merging with whatever you didn't send) must not have date after expires.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No notice with that id"},
        422: {"model": schemas.ErrorResponse, "description": "Invalid priority, or resulting date after expires"},
    },
)
def update_notice(
    notice_id: str, payload: schemas.NoticeUpdate, db: Session = Depends(get_db), _principal: dict = CMS
):
    row = _get_or_404(db, models.Notice, notice_id, "NOTICE_NOT_FOUND", "notice")
    fields = payload.model_dump(exclude_unset=True)
    if "priority" in fields:
        fields["priority"] = fields["priority"].value if hasattr(fields["priority"], "value") else fields["priority"]

    merged_date = fields.get("date", row.date)
    merged_expires = fields.get("expires", row.expires)
    if merged_date and merged_expires and merged_date > merged_expires:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "INVALID_DATE_RANGE",
                "message": f"date ({merged_date}) cannot be after expires ({merged_expires})",
            },
        )

    for field, value in fields.items():
        setattr(row, field, value)
    db.commit()
    return row


@router.delete(
    "/notices/{notice_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["admin-notices"],
    summary="Delete a notice",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No notice with that id"},
    },
)
def delete_notice(notice_id: str, db: Session = Depends(get_db), _principal: dict = CMS):
    row = _get_or_404(db, models.Notice, notice_id, "NOTICE_NOT_FOUND", "notice")
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@router.get(
    "/events",
    response_model=schemas.Page[schemas.EventOut],
    tags=["admin-events"],
    summary="List all events",
    description="Admin view - includes unpublished drafts. Filter by `published`, `featured`, "
    "`category`, `author_id`, `title` (partial/case-insensitive search), and/or date range via "
    "`date_from`/`date_to`. Paginated via `limit`/`offset`.",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"}},
)
def list_events(
    published: Optional[bool] = Query(None),
    featured: Optional[bool] = Query(None),
    category: Optional[schemas.EventCategory] = Query(None),
    author_id: Optional[str] = Query(None),
    title: Optional[str] = Query(None, description="Partial, case-insensitive match on title"),
    date_from: Optional[date] = Query(None, description="Inclusive lower bound on `date`"),
    date_to: Optional[date] = Query(None, description="Inclusive upper bound on `date`"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _principal: dict = CMS,
):
    query = db.query(models.Event)
    if published is not None:
        query = query.filter(models.Event.published == published)
    if featured is not None:
        query = query.filter(models.Event.featured == featured)
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
    "/events/{event_id}",
    response_model=schemas.EventWithImagesOut,
    tags=["admin-events"],
    summary="Get one event, with its images",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No event with that id"},
    },
)
def get_event(event_id: str, db: Session = Depends(get_db), _principal: dict = CMS):
    row = _get_or_404(db, models.Event, event_id, "EVENT_NOT_FOUND", "event")
    images = (
        db.query(models.EventImage)
        .filter(models.EventImage.event_id == event_id)
        .order_by(models.EventImage.sort_order)
        .all()
    )
    return schemas.EventWithImagesOut(**schemas.EventOut.model_validate(row).model_dump(), images=images)


@router.post(
    "/events",
    response_model=schemas.EventOut,
    status_code=status.HTTP_201_CREATED,
    tags=["admin-events"],
    summary="Create an event",
    description="`id` is auto-generated (`evt_xxxxxxxx`) if omitted. `slug` is auto-generated "
    "from `title` if omitted, and de-duplicated (`-2`, `-3`, ...) if already taken. `category` "
    "must be one of: General, Academic, Sports, Cultural. `author_id` is set from the "
    "logged-in account, not accepted from the request body.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        409: {"model": schemas.ErrorResponse, "description": "Given id already exists"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def create_event(payload: schemas.EventIn, db: Session = Depends(get_db), principal: dict = CMS):
    row_id = payload.id or utils.generate_id("evt_")
    if db.query(models.Event).filter(models.Event.id == row_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ID_ALREADY_EXISTS", "message": f"Event '{row_id}' already exists"},
        )
    slug = _unique_slug(db, payload.slug or utils.slugify(payload.title))
    if payload.featured:
        _enforce_featured_cap(db)

    row = models.Event(
        id=row_id,
        title=payload.title,
        slug=slug,
        excerpt=payload.excerpt,
        content=payload.content,
        category=payload.category,
        date=payload.date,
        cover_image=payload.cover_image,
        author_id=principal["id"],
        author_name=payload.author_name,
        published=payload.published,
        featured=payload.featured,
    )
    db.add(row)
    db.commit()
    return row


@router.put(
    "/events/{event_id}",
    response_model=schemas.EventOut,
    tags=["admin-events"],
    summary="Update an event",
    description="Partial update — only send the fields you want to change. `category` must "
    "be one of: General, Academic, Sports, Cultural. If you send `slug`, "
    "it's de-duplicated the same way as on create if already taken by another event.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No event with that id"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def update_event(
    event_id: str, payload: schemas.EventUpdate, db: Session = Depends(get_db), _principal: dict = CMS
):
    row = _get_or_404(db, models.Event, event_id, "EVENT_NOT_FOUND", "event")
    fields = payload.model_dump(exclude_unset=True)
    if "slug" in fields:
        fields["slug"] = _unique_slug(db, fields["slug"], exclude_id=event_id)
    if fields.get("featured") and not row.featured:
        _enforce_featured_cap(db, exclude_id=event_id)
    for field, value in fields.items():
        setattr(row, field, value)
    db.commit()
    return row


@router.delete(
    "/events/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["admin-events"],
    summary="Delete an event",
    description="Also deletes all of its images - they have no meaning without the parent event.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No event with that id"},
    },
)
def delete_event(event_id: str, db: Session = Depends(get_db), _principal: dict = CMS):
    row = _get_or_404(db, models.Event, event_id, "EVENT_NOT_FOUND", "event")
    db.query(models.EventImage).filter(models.EventImage.event_id == event_id).delete()
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# Event images (nested under an event)
# ---------------------------------------------------------------------------


@router.get(
    "/events/{event_id}/images",
    response_model=List[schemas.EventImageOut],
    tags=["admin-events"],
    summary="List an event's images",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No event with that id"},
    },
)
def list_event_images(event_id: str, db: Session = Depends(get_db), _principal: dict = CMS):
    _get_or_404(db, models.Event, event_id, "EVENT_NOT_FOUND", "event")
    return (
        db.query(models.EventImage)
        .filter(models.EventImage.event_id == event_id)
        .order_by(models.EventImage.sort_order)
        .all()
    )


@router.post(
    "/events/{event_id}/images",
    response_model=schemas.EventImageOut,
    status_code=status.HTTP_201_CREATED,
    tags=["admin-events"],
    summary="Add an image to an event",
    description="`id` is auto-generated (`eimg_xxxxxxxx`) if omitted.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No event with that id"},
        409: {"model": schemas.ErrorResponse, "description": "Given id already exists"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def add_event_image(
    event_id: str, payload: schemas.EventImageIn, db: Session = Depends(get_db), _principal: dict = CMS
):
    _get_or_404(db, models.Event, event_id, "EVENT_NOT_FOUND", "event")
    row_id = payload.id or utils.generate_id("eimg_")
    if db.query(models.EventImage).filter(models.EventImage.id == row_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ID_ALREADY_EXISTS", "message": f"Image '{row_id}' already exists"},
        )
    row = models.EventImage(id=row_id, event_id=event_id, url=payload.url, sort_order=payload.sort_order)
    db.add(row)
    db.commit()
    return row


@router.put(
    "/events/{event_id}/images/{image_id}",
    response_model=schemas.EventImageOut,
    tags=["admin-events"],
    summary="Update one of an event's images",
    description="Partial update — only send the fields you want to change.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No event or image with that id"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def update_event_image(
    event_id: str,
    image_id: str,
    payload: schemas.EventImageUpdate,
    db: Session = Depends(get_db),
    _principal: dict = CMS,
):
    row = (
        db.query(models.EventImage)
        .filter(models.EventImage.id == image_id, models.EventImage.event_id == event_id)
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "IMAGE_NOT_FOUND", "message": f"No image '{image_id}' on event '{event_id}'"},
        )
    fields = payload.model_dump(exclude_unset=True)
    for field, value in fields.items():
        setattr(row, field, value)
    db.commit()
    return row


@router.delete(
    "/events/{event_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["admin-events"],
    summary="Remove an image from an event",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No event or image with that id"},
    },
)
def delete_event_image(event_id: str, image_id: str, db: Session = Depends(get_db), _principal: dict = CMS):
    row = (
        db.query(models.EventImage)
        .filter(models.EventImage.id == image_id, models.EventImage.event_id == event_id)
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "IMAGE_NOT_FOUND", "message": f"No image '{image_id}' on event '{event_id}'"},
        )
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# Testimonials
# ---------------------------------------------------------------------------


def _testimonial_out(row: models.Testimonial, class_name: Optional[str]) -> schemas.TestimonialOut:
    return schemas.TestimonialOut(
        id=row.id,
        name=row.name,
        avatar=row.avatar,
        quote=row.quote,
        class_id=row.class_id,
        class_name=class_name,
        active=row.active,
    )


@router.get(
    "/testimonials",
    response_model=List[schemas.TestimonialOut],
    tags=["admin-testimonials"],
    summary="List all testimonials",
    description="Admin view - includes inactive ones. Filter by `active`, `class_id`, "
    "and/or `name` (partial, case-insensitive search). `class_name` is derived via a join "
    "on `class_id`, not a stored column.",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"}},
)
def list_testimonials(
    active: Optional[bool] = Query(None),
    class_id: Optional[str] = Query(None),
    name: Optional[str] = Query(None, description="Partial, case-insensitive match on name"),
    db: Session = Depends(get_db),
    _principal: dict = CMS,
):
    query = db.query(models.Testimonial, models.Class.name.label("class_name")).outerjoin(
        models.Class, models.Testimonial.class_id == models.Class.id
    )
    if active is not None:
        query = query.filter(models.Testimonial.active == active)
    if class_id:
        query = query.filter(models.Testimonial.class_id == class_id)
    if name:
        query = query.filter(models.Testimonial.name.ilike(f"%{name.strip()}%"))
    return [_testimonial_out(row, class_name) for row, class_name in query.all()]


@router.get(
    "/testimonials/{testimonial_id}",
    response_model=schemas.TestimonialOut,
    tags=["admin-testimonials"],
    summary="Get one testimonial",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No testimonial with that id"},
    },
)
def get_testimonial(testimonial_id: str, db: Session = Depends(get_db), _principal: dict = CMS):
    row = _get_or_404(db, models.Testimonial, testimonial_id, "TESTIMONIAL_NOT_FOUND", "testimonial")
    class_name = None
    if row.class_id:
        cls = db.query(models.Class).filter(models.Class.id == row.class_id).first()
        class_name = cls.name if cls else None
    return _testimonial_out(row, class_name)


@router.post(
    "/testimonials",
    response_model=schemas.TestimonialOut,
    status_code=status.HTTP_201_CREATED,
    tags=["admin-testimonials"],
    summary="Create a testimonial",
    description="`id` is auto-generated (`tst_xxxxxxxx`) if omitted. `class_id` is optional, "
    "but validated against `classes.id` whenever it's provided - there's no free-text class "
    "label anymore, so the frontend can't submit an arbitrary, unvalidated class name.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        404: {"model": schemas.ErrorResponse, "description": "class_id given but doesn't exist"},
        409: {"model": schemas.ErrorResponse, "description": "Given id already exists"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def create_testimonial(payload: schemas.TestimonialIn, db: Session = Depends(get_db), _principal: dict = CMS):
    cls = None
    if payload.class_id:
        cls = _get_or_404(db, models.Class, payload.class_id, "CLASS_NOT_FOUND", "class")

    row_id = payload.id or utils.generate_id("tst_")
    if db.query(models.Testimonial).filter(models.Testimonial.id == row_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ID_ALREADY_EXISTS", "message": f"Testimonial '{row_id}' already exists"},
        )
    row = models.Testimonial(
        id=row_id,
        name=payload.name,
        avatar=payload.avatar,
        quote=payload.quote,
        class_id=payload.class_id,
        active=payload.active,
    )
    db.add(row)
    db.commit()
    return _testimonial_out(row, cls.name if cls else None)


@router.put(
    "/testimonials/{testimonial_id}",
    response_model=schemas.TestimonialOut,
    tags=["admin-testimonials"],
    summary="Update a testimonial",
    description="Partial update — only send the fields you want to change. Use `active` to "
    "hide/show it on the public site without deleting it. `class_id`, if sent, is validated "
    "against `classes.id`.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No testimonial with that id, or given class_id doesn't exist"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def update_testimonial(
    testimonial_id: str,
    payload: schemas.TestimonialUpdate,
    db: Session = Depends(get_db),
    _principal: dict = CMS,
):
    row = _get_or_404(db, models.Testimonial, testimonial_id, "TESTIMONIAL_NOT_FOUND", "testimonial")
    fields = payload.model_dump(exclude_unset=True)
    if "class_id" in fields and fields["class_id"]:
        _get_or_404(db, models.Class, fields["class_id"], "CLASS_NOT_FOUND", "class")
    _apply_updates(row, payload, set(fields.keys()))
    db.commit()

    class_name = None
    if row.class_id:
        cls = db.query(models.Class).filter(models.Class.id == row.class_id).first()
        class_name = cls.name if cls else None
    return _testimonial_out(row, class_name)


@router.delete(
    "/testimonials/{testimonial_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["admin-testimonials"],
    summary="Delete a testimonial",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No testimonial with that id"},
    },
)
def delete_testimonial(testimonial_id: str, db: Session = Depends(get_db), _principal: dict = CMS):
    row = _get_or_404(db, models.Testimonial, testimonial_id, "TESTIMONIAL_NOT_FOUND", "testimonial")
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# Admission status (singleton toggle)
# ---------------------------------------------------------------------------


@router.get(
    "/admission-status",
    response_model=schemas.AdmissionStatusOut,
    tags=["admin-admission"],
    summary="Get the admission-open toggle",
    responses={403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"}},
)
def get_admission_status(db: Session = Depends(get_db), _principal: dict = CMS):
    row = db.query(models.AdmissionOpen).filter(models.AdmissionOpen.id == "admission_status").first()
    if not row:
        # Seed data always has this row, but don't 500 if someone deleted it by hand.
        row = models.AdmissionOpen(id="admission_status", value=False)
        db.add(row)
        db.commit()
    return row


@router.put(
    "/admission-status",
    response_model=schemas.AdmissionStatusOut,
    tags=["admin-admission"],
    summary="Set the admission-open toggle",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'cms' permission"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def set_admission_status(
    payload: schemas.AdmissionStatusUpdate, db: Session = Depends(get_db), _principal: dict = CMS
):
    row = db.query(models.AdmissionOpen).filter(models.AdmissionOpen.id == "admission_status").first()
    if not row:
        row = models.AdmissionOpen(id="admission_status", value=payload.value)
        db.add(row)
    else:
        row.value = payload.value
    db.commit()
    return row