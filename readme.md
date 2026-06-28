# Greenfield Academy - Backend API

FastAPI + PostgreSQL backend for a school management system: students, teachers, and
tiered admin accounts, each with their own dashboard, plus a public read API for the
school's website. Originally migrated off a Supabase/RLS-based backend - auth, permissions,
and data integrity are now enforced entirely in this API, not at the database layer.

## Tech stack

- **FastAPI** + **SQLAlchemy 2.0** (typed `Mapped[]` models) + **PostgreSQL**
- **JWT** auth (access + refresh tokens), **bcrypt** password hashing
- **Alembic** for schema migrations
- **Pydantic v2** for request/response validation

## Setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create `.env` in the project root:

```env
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/greenfield_db
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
```

Apply migrations, then start the server:

```powershell
alembic upgrade head
uvicorn app.main:app --reload
```

Full interactive API reference: **http://127.0.0.1:8000/docs**

## Project structure

```
app/
  main.py            FastAPI app, global error handlers, OpenAPI metadata
  config.py          Settings (reads .env)
  database.py        SQLAlchemy engine/session
  models.py          ORM models (typed Mapped[] style)
  schemas.py         Pydantic request/response schemas + enums
  oauth2.py          JWT creation/validation, permission dependencies
  utils.py           Password hashing, ID generation, audit logging, grading, misc helpers
  routers/
    auth.py          Login, refresh, /me
    students.py      Student self-service (/students/me/...)
    teachers.py      Teacher self-service (class roster, attendance, results)
    admin.py         Admin-tier account management (users)
    admin_academic.py  Classes, subjects, exams, periods, schedule
    admin_cms.py     Notices, events (+images), testimonials, admission toggle
    admin_people.py  Student/teacher record CRUD
    admin_audit.py   Audit log (read/delete)
    public.py        Unauthenticated public reads (notices, events, testimonials)
alembic/             Migrations - source of truth for schema changes
scripts/
  set_password.py    CLI fallback for setting a password without going through the API
```

## Auth model

Three `user_type`s, resolved by email in this order at `/auth/login`: **student** →
**teacher** → **admin**. Admin accounts have a `role` sub-tier controlling permissions:

| role | cms | academic | users |
|---|---|---|---|
| `super_admin` | ✅ | ✅ | ✅ |
| `admin` | ✅ | ✅ | ❌ |
| `editor` | ✅ | ❌ | ❌ |
| `mock_admin` / `mock_editor` | ❌ | ❌ | ❌ (read-only demo accounts) |

`admin` additionally has narrow exceptions to create/delete/list `editor` accounts only -
see `admin.py` for the exact rules.

Access tokens are short-lived; on `401 TOKEN_EXPIRED`, call `POST /auth/refresh` with the
refresh token rather than forcing a re-login.

## API conventions

- **Errors** are always `{"error_code": "...", "message": "..."}` (422s add an `errors`
  array of `{field, message}`). See `main.py`'s exception handlers.
- **Pagination**: list endpoints that can grow large accept `limit`/`offset` and return
  `{"items": [...], "total": N, "limit": ..., "offset": ...}` (see `schemas.Page`).
- **Categorical fields are real enums**, not free text (`category`, `priority`, `status`,
  `gender`, `action`, etc.) - invalid values get a clean `422`, not silent mismatches.
- **Soft vs. hard delete**: `subjects` use activate/deactivate (no destructive delete);
  most other resources hard-delete, some guarded by `409` if still referenced elsewhere
  (e.g. deleting a teacher who's a homeroom teacher).
- **Audit log**: user/teacher/student account changes and exam/result changes are logged
  (who/what/when, no before-after values) - `GET /admin/audit-log`, `super_admin` only.

## Useful scripts

```powershell
# Set/reset a password directly, bypassing the API (e.g. for initial bootstrap)
python -m scripts.set_password students std_01 somepassword
python -m scripts.set_password teachers tch_07 somepassword
python -m scripts.set_password users usr_admin_003 somepassword
```

Equivalent API endpoints also exist (`POST /admin/{students|teachers|users}/{id}/set-password`)
for everything after initial setup.

## Known limitations

- No self-service "forgot password" flow (email-based reset) - resets are admin-driven only.
- No rate limiting on `/auth/login`.