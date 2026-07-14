FROM python:3.12-slim

WORKDIR /usr/src/app

# psycopg2-binary, bcrypt and cryptography ship wheels, so no build toolchain needed.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN groupadd --system app && useradd --system --gid app --no-create-home app \
    && chown -R app:app /usr/src/app
USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status == 200 else 1)"

# DATABASE_URL / SECRET_KEY / CORS_ORIGINS are supplied at runtime (docker-compose environment).
# Schema is managed by Alembic migrations, run explicitly as a deploy step — not baked into the
# image start. Run `docker compose exec api alembic upgrade head` if the DB is ever behind.
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000"]
