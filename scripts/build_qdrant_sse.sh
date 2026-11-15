#!/usr/bin/env bash
# Build ngoài VM: Qdrant 1.19.1, SSE không chứa AVX cho CPU cũ (Xeon X5650).
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
work=${QDRANT_BUILD_DIR:-/DATA/tmp/qdrant-sict-portable}
revision=6ab21cac18ebb6f4ae29102c7f8f5cc11affd5de
if [ ! -d "$work/.git" ]; then
  git clone --depth 1 --branch v1.19.1 https://github.com/qdrant/qdrant.git "$work"
fi
[ "$(git -C "$work" rev-parse HEAD)" = "$revision" ] || { echo "Sai Qdrant revision" >&2; exit 1; }
for patch in "$root/deploy/qdrant/1.19.1-sse.patch" "$root/deploy/qdrant/1.19.1-build-memory.patch"; do
  if git -C "$work" apply --unidiff-zero --check "$patch"; then
    git -C "$work" apply --unidiff-zero "$patch"
  elif ! git -C "$work" apply --unidiff-zero --reverse --check "$patch"; then
    echo "Patch không khớp source: $patch" >&2; exit 1
  fi
done
docker build --build-arg TARGET_CPU=x86-64-v2 --build-arg GIT_COMMIT_ID="$revision" \
  -t sict-qdrant:1.19.1-sse-compatible "$work"
