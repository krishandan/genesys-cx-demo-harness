FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

# Install from pyproject so the dependency list has exactly one source of truth.
RUN pip install --upgrade pip setuptools wheel && pip install .

EXPOSE 8000

# Migrate then serve, so a fresh volume comes up ready.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
