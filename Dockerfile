# syntax=docker/dockerfile:1
# Multi-stage build: install deps in a builder, ship a slimmer runtime image
# that runs as a non-root user.

FROM python:3.11.10-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
 && apt-get install --no-install-recommends -y build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --prefix=/install --no-cache-dir .

COPY . .

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.11.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
 && apt-get install --no-install-recommends -y libpq5 curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1001 cureforge

COPY --from=builder /install /usr/local
COPY --from=builder /app /app

RUN mkdir -p /app/.local && chown -R cureforge:cureforge /app

USER cureforge

EXPOSE 8501 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "apps/dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
