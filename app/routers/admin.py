from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import models, oauth2, schemas, utils
from ..database import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_user_or_404(db: Session, user_id: str) -> models.User:
    row = db.query(models.User).filter(models.User.id == user_id).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "USER_NOT_FOUND", "message": f"No admin account with id '{user_id}'"},
        )
    return row


def _check_email_available(db: Session, email: str, exclude_user_id: Optional[str] = None):
    """Login resolution checks students, then teachers, then users, in that order. An email
    collision with a student/teacher would make this admin account permanently unreachable at
    login - it'd always resolve to the student/teacher instead. Block that case explicitly."""
    if db.query(models.Student).filter(models.Student.email == email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "EMAIL_ALREADY_IN_USE",
                "message": f"'{email}' is already used by a student account",
            },
        )
    if db.query(models.Teacher).filter(models.Teacher.email == email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "EMAIL_ALREADY_IN_USE",
                "message": f"'{email}' is already used by a teacher account",
            },
        )
    query = db.query(models.User).filter(models.User.email == email)
    if exclude_user_id:
        query = query.filter(models.User.id != exclude_user_id)
    if query.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "EMAIL_ALREADY_IN_USE",
                "message": f"'{email}' is already used by another admin account",
            },
        )


def _visible_user_roles(principal_role: str) -> Optional[List[str]]:
    """None = unrestricted (super_admin / anyone with full 'users' permission).
    A list = restricted to those roles. Raises 403 for roles with no read access at all
    (editor, mock_admin, mock_editor)."""
    if oauth2.ADMIN_PERMISSIONS.get(principal_role, {}).get("users", False):
        return None
    if principal_role == "admin":
        return ["admin", "editor"]
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error_code": "INSUFFICIENT_PERMISSION", "message": "Role has no read access to admin accounts"},
    )


def _can_manage_target_role(principal_role: str, target_role: str) -> bool:
    """super_admin (full 'users' permission) can manage any role. Plain 'admin' can manage
    only 'editor' accounts - notably this does NOT include 'mock_admin', since that's an
    exact string check against "admin", not a prefix/substring match."""
    if oauth2.ADMIN_PERMISSIONS.get(principal_role, {}).get("users", False):
        return True
    return principal_role == "admin" and target_role == "editor"


def _block_if_last_super_admin(db: Session, user: models.User, removing: bool, new_role: Optional[str] = None):
    """Raises 409 if this delete/role-change would leave zero super_admin accounts."""
    if user.role != "super_admin":
        return
    if not removing and new_role == "super_admin":
        return
    remaining = (
        db.query(models.User).filter(models.User.role == "super_admin", models.User.id != user.id).count()
    )
    if remaining == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "LAST_SUPER_ADMIN",
                "message": "Can't remove or demote the only super_admin account - promote "
                "another account to super_admin first",
            },
        )


@router.get(
    "/dashboard",
    summary="Get the logged-in admin's role + permission flags",
    description=(
        "Accessible to any admin-tier account (`user_type: admin`), regardless of sub-role. "
        "Returns which of `cms` / `academic` / `users` the current role can access, so the "
        "frontend can show/hide dashboard sections without a second lookup."
    ),
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {"model": schemas.ErrorResponse, "description": "Token is valid but not an admin-tier account"},
    },
)
def dashboard(principal: dict = Depends(oauth2.require_user_type("admin"))):
    return {"role": principal["role"], "permissions": oauth2.ADMIN_PERMISSIONS.get(principal["role"], {})}


@router.get(
    "/users",
    response_model=List[schemas.UserOut],
    summary="List all admin-tier accounts",
    description=(
        "`super_admin` sees everyone. Plain `admin` has read-only access, scoped to `admin` "
        "and `editor` accounts only — `super_admin`/`mock_admin`/`mock_editor` accounts are "
        "invisible to it, even via the `role` filter. `editor`, `mock_admin`, and `mock_editor` "
        "have no read access at all. `name`/`email` are partial, case-insensitive search."
    ),
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {
            "model": schemas.ErrorResponse,
            "description": "Not an admin-tier account, or a role with no read access "
            "(editor, mock_admin, mock_editor)",
        },
    },
)
def list_users(
    role: Optional[str] = Query(None, description="Filter to one role, e.g. admin or super_admin"),
    name: Optional[str] = Query(None, description="Partial, case-insensitive match on name"),
    email: Optional[str] = Query(None, description="Partial, case-insensitive match on email"),
    principal: dict = Depends(oauth2.require_user_type("admin")),
    db: Session = Depends(get_db),
):
    visible_roles = _visible_user_roles(principal["role"])
    query = db.query(models.User)
    if visible_roles is not None:
        query = query.filter(models.User.role.in_(visible_roles))
    if role:
        query = query.filter(models.User.role == role)
    if name:
        query = query.filter(models.User.name.ilike(f"%{name.strip()}%"))
    if email:
        query = query.filter(models.User.email.ilike(f"%{email.strip()}%"))
    return query.all()


@router.get(
    "/users/{user_id}",
    response_model=schemas.UserOut,
    summary="Get one admin-tier account",
    description=(
        "Same visibility scoping as the list endpoint: plain `admin` only sees `admin`/`editor` "
        "accounts. Requesting an out-of-scope account (e.g. a super_admin) returns 404, not 403 "
        "- it doesn't confirm whether the account exists."
    ),
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {
            "model": schemas.ErrorResponse,
            "description": "Not an admin-tier account, or a role with no read access "
            "(editor, mock_admin, mock_editor)",
        },
        404: {"model": schemas.ErrorResponse, "description": "No admin account with that id, or it's outside your visibility scope"},
    },
)
def get_user(
    user_id: str,
    principal: dict = Depends(oauth2.require_user_type("admin")),
    db: Session = Depends(get_db),
):
    visible_roles = _visible_user_roles(principal["role"])
    row = _get_user_or_404(db, user_id)
    if visible_roles is not None and row.role not in visible_roles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "USER_NOT_FOUND", "message": f"No admin account with id '{user_id}'"},
        )
    return row


@router.post(
    "/users",
    response_model=schemas.UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an admin-tier account",
    description=(
        "`id` is auto-generated (`usr_xxxxxxxx`) if omitted. `role` must be one of: "
        "super_admin, admin, editor, mock_admin, mock_editor. `super_admin` accounts can create "
        "any role; plain `admin` accounts can only create `editor` accounts, nothing higher. "
        "`email` is checked for uniqueness across students, teachers, and other admin accounts "
        "(a collision would silently lock this account out of login - see /auth/login's "
        "resolution order)."
    ),
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {
            "model": schemas.ErrorResponse,
            "description": "Not an admin-tier account, or an 'admin' role trying to create "
            "something other than 'editor'",
        },
        409: {"model": schemas.ErrorResponse, "description": "Given id already exists, or email already in use"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body, or invalid role"},
    },
)
def create_user(
    payload: schemas.UserIn,
    principal: dict = Depends(oauth2.require_user_type("admin")),
    db: Session = Depends(get_db),
):
    if not _can_manage_target_role(principal["role"], payload.role.value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "INSUFFICIENT_PERMISSION",
                "message": "Role 'admin' can only create 'editor' accounts; everything else "
                "requires the 'users' permission (super_admin)",
            },
        )

    _check_email_available(db, payload.email)

    row_id = payload.id or utils.generate_id("usr_")
    if db.query(models.User).filter(models.User.id == row_id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "ID_ALREADY_EXISTS", "message": f"User '{row_id}' already exists"},
        )

    row = models.User(
        id=row_id,
        email=payload.email,
        password_hash=utils.hash_password(payload.password),
        name=payload.name,
        phone=payload.phone,
        avatar=payload.avatar,
        role=payload.role.value,
        address=payload.address,
    )
    db.add(row)
    utils.log_audit(db, principal["id"], principal["role"], "create", "user", row_id)
    db.commit()
    return row


@router.put(
    "/users/{user_id}",
    response_model=schemas.UserOut,
    summary="Update an admin-tier account",
    description=(
        "Partial update — only send the fields you want to change. Password changes go "
        "through the separate /set-password endpoint, not this one. Blocked if changing "
        "`role` away from super_admin would leave zero super_admin accounts."
    ),
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'users' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No admin account with that id"},
        409: {
            "model": schemas.ErrorResponse,
            "description": "Email already in use elsewhere, or this would remove the last super_admin",
        },
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body, or invalid role"},
    },
)
def update_user(
    user_id: str,
    payload: schemas.UserUpdate,
    principal: dict = Depends(oauth2.require_admin_permission("users")),
    db: Session = Depends(get_db),
):
    row = _get_user_or_404(db, user_id)
    fields = payload.model_dump(exclude_unset=True)

    if "email" in fields:
        _check_email_available(db, fields["email"], exclude_user_id=user_id)

    if "role" in fields:
        fields["role"] = fields["role"].value if hasattr(fields["role"], "value") else fields["role"]
        if fields["role"] != row.role:
            _block_if_last_super_admin(db, row, removing=False, new_role=fields["role"])

    for field, value in fields.items():
        setattr(row, field, value)
    utils.log_audit(db, principal["id"], principal["role"], "update", "user", user_id)
    db.commit()
    return row


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an admin-tier account",
    description=(
        "`super_admin` can delete any account. Plain `admin` can only delete `editor` accounts. "
        "Blocked if the target is the only remaining super_admin account."
    ),
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {
            "model": schemas.ErrorResponse,
            "description": "Not an admin-tier account, or an 'admin' role trying to delete "
            "something other than an 'editor'",
        },
        404: {"model": schemas.ErrorResponse, "description": "No admin account with that id"},
        409: {"model": schemas.ErrorResponse, "description": "This is the only remaining super_admin account"},
    },
)
def delete_user(
    user_id: str,
    principal: dict = Depends(oauth2.require_user_type("admin")),
    db: Session = Depends(get_db),
):
    row = _get_user_or_404(db, user_id)
    if not _can_manage_target_role(principal["role"], row.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "INSUFFICIENT_PERMISSION",
                "message": "Role 'admin' can only delete 'editor' accounts; everything else "
                "requires the 'users' permission (super_admin)",
            },
        )
    _block_if_last_super_admin(db, row, removing=True)
    db.delete(row)
    utils.log_audit(db, principal["id"], principal["role"], "delete", "user", user_id)
    db.commit()


@router.post(
    "/users/{user_id}/set-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set or reset an admin account's password",
    description="The API equivalent of scripts/set_password.py for the users table - no shell access needed.",
    responses={
        401: {"model": schemas.ErrorResponse, "description": "Missing/invalid/expired access token"},
        403: {"model": schemas.ErrorResponse, "description": "Role lacks 'users' permission"},
        404: {"model": schemas.ErrorResponse, "description": "No admin account with that id"},
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def set_user_password(
    user_id: str,
    payload: schemas.PasswordChangeIn,
    principal: dict = Depends(oauth2.require_admin_permission("users")),
    db: Session = Depends(get_db),
):
    row = _get_user_or_404(db, user_id)
    row.password_hash = utils.hash_password(payload.new_password)
    utils.log_audit(db, principal["id"], principal["role"], "set_password", "user", user_id)
    db.commit()