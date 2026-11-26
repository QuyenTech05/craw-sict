# syntax=docker/dockerfile:1
# Build từ root repository: docker build -f sandbox/Dockerfile -t sict-sandbox:<sha> .
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/sict-venv UV_NO_SYNC=1 UV_OFFLINE=1 \
    PATH=/opt/sict-venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg poppler-utils tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng \
    catdoc ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/sict-build
COPY pyproject.toml uv.lock ./
# Chuẩn bị đầy đủ wheel + môi trường trong image; runtime không tải dependency.
RUN UV_OFFLINE=0 UV_NO_SYNC=0 uv sync --locked --no-dev --no-install-project \
    --group worker --group graph --no-group embed \
    && python -c "import underthesea, pytesseract, qdrant_client"
WORKDIR /workspace
