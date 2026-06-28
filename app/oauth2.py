from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt

from .config import settings

bearer_scheme = HTTPBearer()

# Mirrors the PERMISSIONS map in the frontend AuthProvider.
ADMIN_PERMISSIONS = {
    "super_admin": {"cms": True, "academic": True, "users": True},
    "admin": {"cms": True, "academic": True, "users": False},
    "editor": {"cms": True, "academic": False, "users": False},
    "mock_admin": {"cms": False, "academic": False, "users": False},
    "mock_editor": {"cms": False, "academic": False, "users": False},
}


def _create_token(data: dict, expires_delta: timedelta) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def create_access_token(sub: str, user_type: str, role: str) -> str:
    return _create_token(
        {"sub": sub, "user_type": user_type, "role": role, "type": "access"},
        timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(sub: str, user_type: str, role: str) -> str:
    return _create_token(
        {"sub": sub, "user_type": user_type, "role": role, "type": "refresh"},
        timedelta(days=settings.refresh_token_expire_days),
    )


def _auth_error(error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error_code": error_code, "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except ExpiredSignatureError:
        # Distinct from INVALID_TOKEN so the frontend knows to call /auth/refresh
        # instead of forcing a full re-login.
        raise _auth_error("TOKEN_EXPIRED", "Access token has expired")
    except JWTError:
        raise _auth_error("INVALID_TOKEN", "Could not validate credentials")

    if not payload.get("sub") or not payload.get("user_type"):
        raise _auth_error("INVALID_TOKEN", "Token payload is missing required fields")
    return payload


def get_current_principal(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    payload = decode_token(creds.credentials)
    if payload.get("type") != "access":
        raise _auth_error("INVALID_TOKEN", "A refresh token was used where an access token is required")
    return {"id": payload["sub"], "user_type": payload["user_type"], "role": payload["role"]}


def require_user_type(*allowed_types: str):
    def checker(principal: dict = Depends(get_current_principal)) -> dict:
        if principal["user_type"] not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": "FORBIDDEN_ACCOUNT_TYPE",
                    "message": f"This endpoint requires account type: {', '.join(allowed_types)}",
                },
            )
        return principal

    return checker


def require_admin_permission(action: str):
    def checker(principal: dict = Depends(require_user_type("admin"))) -> dict:
        if not ADMIN_PERMISSIONS.get(principal["role"], {}).get(action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": "INSUFFICIENT_PERMISSION",
                    "message": f"Role '{principal['role']}' lacks '{action}' permission",
                },
            )
        return principal

    return checker