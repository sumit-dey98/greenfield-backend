from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import models, oauth2, schemas
from ..database import get_db

router = APIRouter(prefix="/admin")

# Gated to the 'users' permission (super_admin only) - the audit log itself is a security
# control, and a plain admin/editor being able to read or clear it would defeat the point.
AUDIT = Depends(oauth2.require_admin_permission("users"))

# Which model backs each resource_type, for name resolution.
_RESOURCE_MODEL = {
    "user": models.User,
    "teacher": models.Teacher,
    "student": models.Student,
    "exam": models.Exam,
    "result": models.Result,
}


def _resolve_names(db: Session, rows: List[models.AuditLog]) -> List[schemas.AuditLogOut]:
    """Attach human-readable actor/resource names to raw audit rows.

    Audit rows store only ids (and the target may have since been deleted), so names are
    resolved best-effort via batched per-type lookups. Anything that can't be resolved
    (e.g. a deleted resource) falls back to None, and the client shows the raw id.
    """
    if not rows:
        return []

    # Actors are always admin-tier users.
    actor_ids = {r.actor_id for r in rows}
    actor_names = dict(
        db.query(models.User.id, models.User.name).filter(models.User.id.in_(actor_ids)).all()
    )

    # Resource names, grouped by type so each table is queried once.
    ids_by_type: dict[str, set] = {}
    for r in rows:
        ids_by_type.setdefault(r.resource_type, set()).add(r.resource_id)

    resource_names: dict[tuple, str] = {}
    for rtype, ids in ids_by_type.items():
        model = _RESOURCE_MODEL.get(rtype)
        if model is None:
            continue
        if rtype == "result":
            # Results have no name column — describe them as "<student> · <exam>".
            q = (
                db.query(models.Result.id, models.Student.name, models.Result.exam)
                .outerjoin(models.Student, models.Result.student_id == models.Student.id)
                .filter(models.Result.id.in_(ids))
            )
            for rid, sname, exam in q.all():
                label = " · ".join(p for p in (sname, exam) if p)
                resource_names[("result", rid)] = label or None
        else:
            for rid, name in db.query(model.id, model.name).filter(model.id.in_(ids)).all():
                resource_names[(rtype, rid)] = name

    return [
        schemas.AuditLogOut(
            id=r.id,
            created_at=r.created_at,
            actor_id=r.actor_id,
            actor_role=r.actor_role,
            actor_name=actor_names.get(r.actor_id),
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            resource_name=resource_names.get((r.resource_type, r.resource_id)),
        )
        for r in rows
    ]


@router.get(
    "/audit-log",
    response_model=schemas.Page[schemas.AuditLogOut],
    tags=["admin-audit"],
    summary="List audit log entries",
    description="Shallow trail (who/what/when, no before-after values) covering user, "
    "teacher, and student account changes, plus exam and result changes. Filter by "
    "`actor_id`, `action` (create/update/delete/set_password), `resource_type` "
    "(user/teacher/student/exam/result), `resource_id`, and/or date range. Paginated "
    "via `limit`/`offset`. Restricted to `super_admin`.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'users' permission"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Invalid action or resource_type value"},
    },
)
def list_audit_log(
    actor_id: Optional[str] = Query(None),
    action: Optional[schemas.AuditAction] = Query(None, description="e.g. create, update, delete, set_password"),
    resource_type: Optional[schemas.AuditResourceType] = Query(None, description="e.g. user, teacher, student, exam, result"),
    resource_id: Optional[str] = Query(None),
    created_from: Optional[datetime] = Query(None, description="Inclusive lower bound on `created_at`"),
    created_to: Optional[datetime] = Query(None, description="Inclusive upper bound on `created_at`"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _principal: dict = AUDIT,
):
    query = db.query(models.AuditLog)
    if actor_id:
        query = query.filter(models.AuditLog.actor_id == actor_id)
    if action:
        query = query.filter(models.AuditLog.action == action)
    if resource_type:
        query = query.filter(models.AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.filter(models.AuditLog.resource_id == resource_id)
    if created_from:
        query = query.filter(models.AuditLog.created_at >= created_from)
    if created_to:
        query = query.filter(models.AuditLog.created_at <= created_to)
    total = query.count()
    rows = query.order_by(models.AuditLog.created_at.desc()).offset(offset).limit(limit).all()
    return schemas.Page(items=_resolve_names(db, rows), total=total, limit=limit, offset=offset)


@router.get(
    "/audit-log/{entry_id}",
    response_model=schemas.AuditLogOut,
    tags=["admin-audit"],
    summary="Get one audit log entry",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'users' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No audit log entry with that id"},
    },
)
def get_audit_log_entry(entry_id: str, db: Session = Depends(get_db), _principal: dict = AUDIT):
    row = db.query(models.AuditLog).filter(models.AuditLog.id == entry_id).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "AUDIT_LOG_NOT_FOUND", "message": f"No audit log entry with id '{entry_id}'"},
        )
    return _resolve_names(db, [row])[0]


@router.delete(
    "/audit-log/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["admin-audit"],
    summary="Delete one audit log entry",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'users' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No audit log entry with that id"},
    },
)
def delete_audit_log_entry(entry_id: str, db: Session = Depends(get_db), _principal: dict = AUDIT):
    row = db.query(models.AuditLog).filter(models.AuditLog.id == entry_id).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "AUDIT_LOG_NOT_FOUND", "message": f"No audit log entry with id '{entry_id}'"},
        )
    db.delete(row)
    db.commit()


@router.post(
    "/audit-log/bulk-delete",
    response_model=schemas.AuditLogBulkDeleteOut,
    tags=["admin-audit"],
    summary="Bulk-delete audit log entries",
    description="Provide either `ids` (delete those specific entries) or `before` (delete "
    "everything older than this timestamp, for retention cleanup) - at least one is required. "
    "A dedicated action endpoint rather than DELETE-with-body, since body support on DELETE "
    "is inconsistent across HTTP clients/proxies.",
    responses={
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'users' permission"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Neither ids nor before was provided"},
    },
)
def bulk_delete_audit_log(
    payload: schemas.AuditLogBulkDeleteIn, db: Session = Depends(get_db), _principal: dict = AUDIT
):
    query = db.query(models.AuditLog)
    if payload.ids:
        query = query.filter(models.AuditLog.id.in_(payload.ids))
    elif payload.before:
        query = query.filter(models.AuditLog.created_at < payload.before)
    deleted_count = query.delete(synchronize_session=False)
    db.commit()
    return schemas.AuditLogBulkDeleteOut(deleted_count=deleted_count)