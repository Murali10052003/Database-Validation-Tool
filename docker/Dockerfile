# syntax=docker/dockerfile:1

FROM --platform=$BUILDPLATFORM node:22-slim AS frontend
ARG NPM_REGISTRY=https://packagefeedproxy.microsoft.io/npm/
WORKDIR /ui
COPY app/web/frontend/package*.json ./
RUN npm ci --registry "$NPM_REGISTRY"
COPY app/web/frontend ./
RUN npm run build -- --outDir /ui/dist

FROM python:3.12-slim AS base
ARG PIP_INDEX_URL=https://packagefeedproxy.microsoft.io/pypi/simple/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install runtime and database-driver dependencies first for better layer caching.
COPY requirements.txt requirements-drivers.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt -r requirements-drivers.txt

# Copy the application source and install the package (provides the CLI entry point).
COPY pyproject.toml README.md ./
COPY app ./app
COPY --from=frontend /ui/dist ./app/web/static
COPY config/type_mappings ./config/type_mappings
RUN pip install ".[web,entra]"

ENV MV_CATALOG_PATH=/app/data/catalog.sqlite3 \
    MV_REPORT_DIR=/app/data/reports \
    MV_RUN_LOG_DIR=/app/data/logs \
    MV_RUN_LOG_RETENTION_DAYS=0
RUN useradd --uid 10001 --create-home validator \
    && mkdir -p /app/data && chown validator:validator /app/data
USER validator
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
