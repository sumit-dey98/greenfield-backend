FROM python:3.12-slim

WORKDIR /usr/src/app

# psycopg2-binary, bcrypt and cryptography ship wheels, so no build toolchain needed.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# DATABASE_URL / SECRET_KEY are supplied at runtime (docker-compose environment).
# Schema + seed data already live in the host Postgres, so we do NOT run migrations
# or create tables here — just serve the API. Run `alembic upgrade head` manually
# (docker compose exec api alembic upgrade head) if the DB is ever behind.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
