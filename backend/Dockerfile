FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/backend/.venv/bin:$PATH"

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock /app/backend/
COPY backend/src /app/backend/src
COPY backend/migrations /app/backend/migrations
COPY backend/alembic.ini /app/backend/alembic.ini
COPY config /app/config

RUN cd /app/backend \
    && uv sync --frozen --no-dev \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown -R app:app /data /app

USER app
WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "scout_email.app:app", "--host", "0.0.0.0", "--port", "8000"]
