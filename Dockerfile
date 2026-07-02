# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
# git is required for the pinned ddb-single git dependency (SPEC forbids vendoring it).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY apps/web/pyproject.toml apps/web/
COPY packages/domain/pyproject.toml packages/domain/
COPY packages/data/pyproject.toml packages/data/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages --no-install-workspace
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages --no-editable

FROM python:3.12-slim-bookworm
RUN useradd --system --uid 10001 --create-home app \
    && mkdir -p /app/media \
    && chown -R app:app /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    MEDIA_ROOT=/app/media \
    WEB_CONCURRENCY=2
USER app
WORKDIR /app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=5 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()"]
CMD ["sh", "-c", "exec uvicorn algodoo_web.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*' --workers ${WEB_CONCURRENCY:-2}"]
