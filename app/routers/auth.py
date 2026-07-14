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
            "description": "Email not found, or password incorrect",
        },
        403: {
            "model": schemas.ErrorResponse,
            "description": "Account exists but has no password set yet (PASSWORD_NOT_SET) — "
            "the user should set one via POST /auth/set-password",
        },
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    account, user_type, role = _find_account(db, payload.email)
    # Account exists but has no password yet -> tell the frontend to show the "set password" form.
    if account and not account.password_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "PASSWORD_NOT_SET",
                "message": "This account has no password yet. Please set one to continue.",
            },
        )
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
    "/set-password",
    response_model=schemas.Token,
    summary="Set the password for an account that has none yet (self-service first-time setup)",
    description=(
        "For students/teachers (and any account) whose password is null — either never set, or "
        "cleared by an admin as a reset. Sets the password and logs the user in (returns a token "
        "pair). Fails with 409 if the account already has a password (use the admin clear-password "
        "reset flow instead) or 404 if no account matches the email."
    ),
    responses={
        404: {"model": schemas.ErrorResponse, "description": "No account with that email"},
        409: {
            "model": schemas.ErrorResponse,
            "description": "Account already has a password (PASSWORD_ALREADY_SET)",
        },
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def set_password(payload: schemas.SetInitialPasswordRequest, db: Session = Depends(get_db)):
    account, user_type, role = _find_account(db, payload.email)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "USER_NOT_FOUND", "message": "No account with that email"},
        )
    if account.password_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "PASSWORD_ALREADY_SET",
                "message": "This account already has a password. Ask an admin to reset it first.",
            },
        )
    account.password_hash = utils.hash_password(payload.new_password)
    db.commit()
    assert user_type is not None and role is not None

    return schemas.Token(
        access_token=oauth2.create_access_token(account.id, user_type, role),
        refresh_token=oauth2.create_refresh_token(account.id, user_type, role),
        user_type=user_type,
        role=role,
    )


@router.post(
    "/request-password-reset",
    response_model=schemas.PasswordResetRequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Request an admin-driven password reset (public)",
    description=(
        "A student or teacher who forgot their password submits `{role, email}`. `role` "
        "(student|teacher) tells the backend which table to verify the email against. The "
        "request lands in an admin queue; an admin then accepts it, which clears the password "
        "so the user can set a new one at login.\n\n"
        "Anti-spam: the email must exist in the matching table (404 otherwise), and only one "
        "**active** request may exist per email+role at a time (409 if one is already open)."
    ),
    responses={
        201: {"description": "Request recorded"},
        404: {"model": schemas.ErrorResponse, "description": "No student/teacher with that email for the given role"},
        409: {
            "model": schemas.ErrorResponse,
            "description": "An active reset request already exists for this email+role (RESET_REQUEST_EXISTS)",
        },
        422: {"model": schemas.ValidationErrorResponse, "description": "Malformed request body"},
    },
)
def request_password_reset(payload: schemas.PasswordResetRequestIn, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    role = payload.role.value

    model = models.Student if role == "student" else models.Teacher
    account = db.query(model).filter(model.email == email).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": f"{role.upper()}_NOT_FOUND",
                "message": f"No {role} account with that email",
            },
        )

    # Anti-spam: block duplicate open requests for the same person.
    existing = (
        db.query(models.PasswordResetRequest)
        .filter(
            models.PasswordResetRequest.email == email,
            models.PasswordResetRequest.role == role,
            models.PasswordResetRequest.is_active.is_(True),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "RESET_REQUEST_EXISTS",
                "message": "A password reset request is already pending for this account.",
            },
        )

    row = models.PasswordResetRequest(email=email, role=role, status="pending", is_active=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


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