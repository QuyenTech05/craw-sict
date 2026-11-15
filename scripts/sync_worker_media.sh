#!/usr/bin/env bash
# Media theo SHA bất biến: chép file mới từ worker sang API, không xoá dữ liệu đích.
set -euo pipefail
: "${MEDIA_API_HOST:?thiếu MEDIA_API_HOST (IP Tailscale VM1)}"
: "${MEDIA_SYNC_KEY:?thiếu MEDIA_SYNC_KEY}"
store=${MEDIA_SOURCE:-/root/craw-sict/_local_store}
remote=${MEDIA_DESTINATION:-/root/craw-sict/_local_store}
rsync -a --timeout=60 --ignore-existing --delay-updates \
  -e "ssh -p ${MEDIA_SSH_PORT:-22} -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=yes -i $MEDIA_SYNC_KEY" \
  "$store/" "root@$MEDIA_API_HOST:$remote/"
