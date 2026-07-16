import logging

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .routers import (
    admin,
    admin_academic,
    admin_admissions,
    admin_audit,
    admin_cms,
    admin_people,
    admissions_public,
    auth,
    public,
    students,
    teachers,
)

logger = logging.getLogger("greenfield")

API_DESCRIPTION = """
Backend API for the Greenfield Academy school management system.

### Accounts & roles
Three account types, looked up by email at `/auth/login`:
- **student** — `user_type: student`
- **teacher** — `user_type: teacher`
- **admin** — `user_type: admin`, with sub-roles `super_admin` / `admin` / `editor` /
  `mock_admin` / `mock_editor` controlling `cms` / `academic` / `users` permissions.
  The `mock_*` roles are read-only demo accounts: they pass account-type checks and can view
  admin dashboards, but every `cms`/`academic`/`users` permission is hard-`false`, so all
  writes 403.

### Auth flow
1. `POST /auth/login` with `{email, password}` → get `access_token` + `refresh_token`.
2. Send `Authorization: Bearer <access_token>` on every protected request.
3. When a request fails with `error_code: TOKEN_EXPIRED`, call `POST /auth/refresh` with the
   `refresh_token` to get a new pair — don't make the user log in again.
4. When a request fails with `INVALID_TOKEN` or `FORBIDDEN_ACCOUNT_TYPE`, the session is bad —
   send the user back to login.

### Pagination
Endpoints whose response schema is named `Page_...` (e.g. `Page_StudentAdminOut_`) share a
common envelope:
```
{ "items": [...], "total": 87, "limit": 20, "offset": 0 }
```
- **`items`** — the rows for the current page, already filtered and sorted.
- **`total`** — the total number of matching rows across all pages, not just the current response.
- **`limit`** — the number of rows requested (each endpoint defines its own default and maximum).
- **`offset`** — the number of matching rows skipped before the current page.

Pages are addressed by `limit`/`offset` rather than a page number: `offset=0&limit=20` is the
first page, `offset=20&limit=20` is the second, and so on. Iteration continues by incrementing
`offset` by `limit` until `total` rows have been retrieved, or until `items` returns fewer rows
than `limit`, which indicates the last page has been reached.

### Error shape
Every error response is JSON, no matter the status code:
```
{ "error_code": "INVALID_CREDENTIALS", "message": "Invalid email or password" }
```
422 validation errors additionally include an `errors` array:
```
{ "error_code": "VALIDATION_ERROR", "message": "Invalid request data",
  "errors": [{"field": "email", "message": "value is not a valid email address"}] }
```
`error_code` is for programmatic handling (switch/if in the frontend); `message` is safe to show
to the user as-is.
"""

tags_metadata = [
    {"name": "auth", "description": "Login, token refresh, and current-session identity."},
    {"name": "students", "description": "Routes restricted to `user_type: student`."},
    {"name": "teachers", "description": "Routes restricted to `user_type: teacher`."},
    {
        "name": "admin",
        "description": "Routes restricted to `user_type: admin`, further gated per-route by "
        "sub-role permission (`cms` / `academic` / `users`).",
    },
    {
        "name": "admin-classes",
        "description": "CRUD for classes. Requires the `academic` permission (super_admin/admin only).",
    },
    {
        "name": "admin-subjects",
        "description": "CRUD for subjects, including activate/deactivate (soft-delete). Requires "
        "the `academic` permission (super_admin/admin only).",
    },
    {
        "name": "admin-exams",
        "description": "CRUD for exams. Requires the `academic` permission (super_admin/admin only).",
    },
    {
        "name": "admin-periods",
        "description": "CRUD for the daily period timetable. Requires the `academic` permission "
        "(super_admin/admin only).",
    },
    {
        "name": "admin-schedule",
        "description": "CRUD for the class/teacher schedule, with conflict detection. Requires "
        "the `academic` permission (super_admin/admin only).",
    },
    {
        "name": "admin-attendance",
        "description": "Mark/list attendance records for any class. Requires the `academic` "
        "permission (super_admin/admin only).",
    },
    {
        "name": "admin-results",
        "description": "Enter/list/delete exam results for any class. `grade` is computed "
        "server-side from marks/total. Requires the `academic` permission (super_admin/admin only).",
    },
    {
        "name": "admin-counts",
        "description": "Pre-aggregated attendance/results/roster numbers (present/absent/late "
        "counts, results entry counts and marks sums, student counts per class), kept in sync "
        "automatically whenever the underlying attendance/results/student rows change. Read-only "
        "- lets the UI show class-level summaries without re-fetching and re-counting full row "
        "sets. Requires the `academic` permission (super_admin/admin only).",
    },
    {
        "name": "admin-notices",
        "description": "CRUD for notices. Requires the `cms` permission (super_admin/admin/editor).",
    },
    {
        "name": "admin-events",
        "description": "CRUD for events and their images. Requires the `cms` permission "
        "(super_admin/admin/editor).",
    },
    {
        "name": "admin-testimonials",
        "description": "CRUD for testimonials. Requires the `cms` permission (super_admin/admin/editor).",
    },
    {
        "name": "admin-admission",
        "description": "Get/set the admission-open toggle. Requires the `cms` permission "
        "(super_admin/admin/editor).",
    },
    {
        "name": "admin-students",
        "description": "CRUD for student records, including password resets. Requires the "
        "`academic` permission (super_admin/admin only).",
    },
    {
        "name": "admin-teachers",
        "description": "CRUD for teacher records, including password resets. Requires the "
        "`academic` permission (super_admin/admin only). Homeroom assignment is done via "
        "`PUT /admin/classes/{id}`, not here.",
    },
    {
        "name": "admin-password-resets",
        "description": "The admin queue of student/teacher password-reset requests: list "
        "pending/accepted requests and accept one (clears the target's password so they can "
        "set a new one at login). Requires the `academic` permission (super_admin/admin only).",
    },
    {
        "name": "admin-audit",
        "description": "Shallow audit trail (who/what/when) for user/teacher/student account "
        "changes and exam/result changes. Requires the `users` permission (super_admin only).",
    },
    {
        "name": "public",
        "description": "No authentication required. Read-only, pre-filtered to published/active/"
        "non-expired content only - this is what the public website consumes.",
    },
    {
        "name": "admissions-public",
        "description": "No account-based auth. Public admission application submission, "
        "reference-number + contact-value verification (issues a short-lived admission-access "
        "token), and public-safe status lookup. IP-rate-limited and lockout-protected against "
        "abuse via Postgres-backed SubmissionAttempt/VerifyAttempt tables.",
    },
    {
        "name": "admin-admissions",
        "description": "Full admission-pipeline management: application list/detail, status "
        "transitions, exam scheduling, grading assignment, merit list, interview scheduling/"
        "outcome, bulk actions, and admission cycle CRUD. Requires the `admissions` permission "
        "(super_admin/admin only).",
    },
]

app = FastAPI(
    title="Greenfield Academy API",
    version="1.0.0",
    description=API_DESCRIPTION,
    openapi_tags=tags_metadata,
    swagger_ui_parameters={"persistAuthorization": True},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(students.router)
app.include_router(teachers.router)
app.include_router(admin.router)
app.include_router(admin_academic.router)
app.include_router(admin_cms.router)
app.include_router(admin_people.router)
app.include_router(admin_audit.router)
app.include_router(admin_admissions.router)
app.include_router(admissions_public.router)
app.include_router(public.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Flattens HTTPException details into the standard {error_code, message} shape.

    Routes raise HTTPException(detail={"error_code": ..., "message": ...}); this handler
    also tolerates plain-string details (e.g. from third-party code) by wrapping them.
    """
    detail = exc.detail
    if isinstance(detail, dict) and "error_code" in detail:
        body = detail
    else:
        body = {"error_code": "ERROR", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content=body, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Turns Pydantic's default 422 body into {error_code, message, errors: [{field, message}]}."""
    errors = [
        {"field": ".".join(str(p) for p in err["loc"][1:]) or str(err["loc"][-1]), "message": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"error_code": "VALIDATION_ERROR", "message": "Invalid request data", "errors": errors},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all so the frontend never sees a raw 500 HTML page or a stack trace.
    Logs the real exception server-side for debugging.
    """
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error_code": "INTERNAL_ERROR", "message": "Something went wrong on our end"},
    )


@app.get(
    "/health",
    tags=["health"],
    summary="Check API + database connectivity",
    description="No auth required. Runs a real query against the `students` table to confirm "
    "the database connection is live, not just that the process is up.",
)
def health(db: Session = Depends(get_db)):
    student_count = db.execute(text("SELECT count(*) FROM students")).scalar()
    return {"db": "connected", "students": student_count}