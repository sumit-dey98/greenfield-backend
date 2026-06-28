from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, oauth2, schemas, utils
from ..database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def _find_account(db: Session, email: str):
    """Looks up an account by email across students, teachers, then admin users (in that order)."""
    if account := db.query(models.Student).filter(models.Student.email == email).first():
        return account, "student", "student"
    if account := db.query(models.Teacher).filter(models.Teacher.email == email).first():
        return account, "teacher", "teacher"
    if account := db.query(models.User).filter(models.User.email == email).first():
        return account, "admin", account.role
    return None, None, None


@router.post(
    "/login",
    response_model=schemas.Token,
    summary="Log in with email and password",
    description=(
        "Checks the students, teachers, and admin-users tables (in that order) for a matching "
        "email + password. On success, returns a short-lived access token and a longer-lived "
        "refresh token, plus the account's `user_type` (student/teacher/admin) and `role` "
        "(student/teacher/super_admin/admin/editor/mock_admin/mock_editor)."
    ),
    responses={
        401: {
            "model": schemas.ErrorResponse,
            "description": "Email not found, or password incorrect, or account has no password set yet",
        },
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    account, user_type, role = _find_account(db, payload.email)
    if (
        not account
        or not account.password_hash
        or not utils.verify_password(payload.password, account.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "INVALID_CREDENTIALS", "message": "Invalid email or password"},
        )
    # _find_account always returns user_type/role together with account, never independently -
    # this just makes that invariant explicit for the type checker, not a runtime behavior change.
    assert user_type is not None and role is not None

    return schemas.Token(
        access_token=oauth2.create_access_token(account.id, user_type, role),
        refresh_token=oauth2.create_refresh_token(account.id, user_type, role),
        user_type=user_type,
        role=role,
    )


@router.post(
    "/refresh",
    response_model=schemas.Token,
    summary="Exchange a refresh token for a new token pair",
    description=(
        "Call this when an access-token-protected request fails with `error_code: TOKEN_EXPIRED`. "
        "Returns a brand new access token + refresh token (refresh tokens are rotated, not reused)."
    ),
    responses={
        401: {
            "model": schemas.ErrorResponse,
            "description": "Refresh token is invalid, expired, or not actually a refresh token",
        },
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def refresh(payload: schemas.RefreshRequest):
    data = oauth2.decode_token(payload.refresh_token)
    if data.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "INVALID_TOKEN", "message": "Expected a refresh token"},
        )
    return schemas.Token(
        access_token=oauth2.create_access_token(data["sub"], data["user_type"], data["role"]),
        refresh_token=oauth2.create_refresh_token(data["sub"], data["user_type"], data["role"]),
        user_type=data["user_type"],
        role=data["role"],
    )


@router.get(
    "/me",
    summary="Get the current session's identity",
    description="Returns the `id`, `user_type`, and `role` encoded in the access token. Useful for "
    "the frontend to confirm who's logged in without a separate profile call.",
    responses={
        401: {
            "model": schemas.ErrorResponse,
            "description": "Missing/invalid/expired access token",
        }
    },
)
def me(principal: dict = Depends(oauth2.get_current_principal)):
    return principal