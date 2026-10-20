# One image for every Python process: web, ingestor, archiver, fan-out, and the init job.

FROM ghcr.io/astral-sh/uv:0.13.4 AS uv

FROM python:3.12.15-slim-trixie AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM python:3.12.15-slim-trixie
RUN groupadd --system app && useradd --system --gid app --home-dir /app app \
    && mkdir -p /data/archive && chown app:app /data/archive
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY manage.py ./
COPY config ./config
COPY apps ./apps
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
