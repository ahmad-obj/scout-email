FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY browser-worker/pyproject.toml /app/browser-worker/pyproject.toml
COPY browser-worker/src /app/browser-worker/src

RUN python -m pip install --no-cache-dir /app/browser-worker \
    && python -m playwright install --with-deps chromium \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data/browser-artifacts \
    && chown -R app:app /data /app /ms-playwright

USER app
WORKDIR /app/browser-worker

EXPOSE 8010

CMD ["uvicorn", "browser_worker.app:app", "--host", "0.0.0.0", "--port", "8010"]
