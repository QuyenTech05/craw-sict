#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: bash sandbox/run_job.sh <job_id>" >&2
  exit 2
fi

# Native tools và venv phải có sẵn từ image đã prebuild.
# Không dùng sudo/apt/curl hoặc tải thư viện giữa phiên Sandbox 43 phút.
if ! command -v uv >/dev/null 2>&1; then
  echo "Sandbox image thiếu uv; cần chuẩn bị image trước runtime" >&2
  exit 1
fi
if [[ "${JOB_KIND:-}" == "video" ]] && ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Sandbox image thiếu ffmpeg" >&2
  exit 1
fi
if [[ "${JOB_KIND:-}" == "compute" ]] && ! command -v pdftotext >/dev/null 2>&1; then
  echo "Sandbox image thiếu Poppler" >&2
  exit 1
fi

if [[ ! -x /opt/sict-venv/bin/python ]] || ! cmp -s uv.lock /opt/sict-build/uv.lock || ! cmp -s pyproject.toml /opt/sict-build/pyproject.toml; then
  echo "Sandbox image và Git revision lệch dependency lock; cần build image tương ứng SHA" >&2
  exit 1
fi
export UV_OFFLINE=1 UV_NO_SYNC=1 UV_PROJECT_ENVIRONMENT=/opt/sict-venv
uv run --no-sync --offline python sandbox/job_runner.py "$1"
