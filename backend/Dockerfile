# syntax=docker/dockerfile:1.7
# Edge-server image for the API and worker. Heavy processing (OCR, embeddings, reranking, FFmpeg)
# runs here, never on the tablet.
FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Tesseract 5 + eng/hin/mar models (local OCR), FFmpeg (delivery copies), espeak-ng (offline narration
# fallback), postgresql-client (backup/restore), fonts for fixture generation.
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-mar \
      ffmpeg espeak-ng postgresql-client libglib2.0-0 libraqm0 libfribidi0 \
      fonts-dejavu-core fonts-noto-core curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# bookworm's postgresql-client is 15; pg_dump refuses a newer server and the db service is PostgreSQL 17,
# so the worker's nightly backup needs the PGDG client matching the server major (as in deploy/production/ops).
ARG PG_MAJOR=17
RUN install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
         https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
         > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-${PG_MAJOR} \
    && rm -rf /var/lib/apt/lists/*
ENV PATH="/usr/lib/postgresql/${PG_MAJOR}/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app
ARG INSTALL_DEV=1
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_DEV" = "1" ]; then uv sync --frozen --no-install-project --extra models --extra dev; \
    else uv sync --frozen --no-install-project --extra models --no-dev; fi

# Bake the local models into the image so the edge server works without internet.
ARG PREFETCH_MODELS=1
ENV ARCHIVE_MODEL_CACHE=/models
RUN if [ "$PREFETCH_MODELS" = "1" ]; then python -c "\
from fastembed import TextEmbedding; \
from fastembed.rerank.cross_encoder import TextCrossEncoder; \
TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', cache_dir='/models'); \
TextCrossEncoder('jinaai/jina-reranker-v2-base-multilingual', cache_dir='/models'); \
print('models cached')"; fi

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_DEV" = "1" ]; then uv sync --frozen --extra models --extra dev; \
    else uv sync --frozen --extra models --no-dev; fi

RUN useradd --uid 10001 --create-home archive \
    && mkdir -p /data/preservation /data/delivery /data/derivatives /data/quarantine /data/traces /backups /eval \
    && chown -R archive:archive /data /backups /eval /app \
    && (chown -R archive:archive /models 2>/dev/null || mkdir -p /models && chown archive:archive /models)
USER archive

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=10 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1
CMD ["sh", "-c", "alembic upgrade head && python -m archive.cli bootstrap && uvicorn archive.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
