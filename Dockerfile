FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so the layer caches across source edits.
COPY pyproject.toml ./
RUN pip install --upgrade pip setuptools wheel \
    && pip install \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.30" \
        "sqlalchemy>=2.0" \
        "alembic>=1.13" \
        "pydantic>=2.7" \
        "pydantic-settings>=2.3" \
        "psycopg[binary]>=3.1" \
        "faker>=25.0"

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

EXPOSE 8000

# Migrate then serve, so a fresh volume comes up ready.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
