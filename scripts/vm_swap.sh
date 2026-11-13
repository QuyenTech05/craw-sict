#!/usr/bin/env bash
# Swap cho máy RAM nhỏ (2026-11-13): VM1 1 GB và worker 512 MB chạy sát trần RAM; swapfile 2 GB cứu
# container khỏi OOM-kill ở các đỉnh (Qdrant 786 MiB khi eval, worker 400–969 MiB khi rebuild graph).
# Chạy 1 lần trên mỗi máy, bằng root:
#   sudo bash scripts/vm_swap.sh [size_mb]     # mặc định 2048
# Idempotent: swap đã bật đúng kích thước → không làm gì.
set -euo pipefail

SIZE_MB="${1:-2048}"
FILE=/swapfile

if [ "$(id -u)" -ne 0 ]; then
  echo "phải chạy bằng root (sudo)" >&2; exit 2
fi

cur_mb=$(swapon --show=NAME,SIZE --bytes --noheadings 2>/dev/null | awk -v f="$FILE" '$1==f {printf "%d", $2/1024/1024}')
if [ -n "$cur_mb" ]; then
  echo "swap $FILE đã bật (${cur_mb} MB) — không làm gì"
  exit 0
fi

avail_mb=$(df --output=avail -m / | tail -1 | tr -d ' ')
if [ "$avail_mb" -lt $((SIZE_MB + 1024)) ]; then
  echo "không đủ đĩa: cần $((SIZE_MB + 1024)) MB, còn ${avail_mb} MB" >&2; exit 1
fi

if [ ! -f "$FILE" ]; then
  fallocate -l "${SIZE_MB}M" "$FILE" 2>/dev/null || dd if=/dev/zero of="$FILE" bs=1M count="$SIZE_MB" status=none
  chmod 600 "$FILE"
  mkswap "$FILE" >/dev/null
fi
swapon "$FILE"
grep -q "^$FILE " /etc/fstab || echo "$FILE none swap sw 0 0" >> /etc/fstab

# swappiness thấp: ưu tiên giữ container trong RAM, chỉ tràn khi thật cần
sysctl -qw vm.swappiness=20
grep -q '^vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=20' >> /etc/sysctl.conf

echo "swap BẬT: $(swapon --show=NAME,SIZE --noheadings | head -3)"
echo "sau: $(free -m | awk '/Swap|Mem/ {printf "%s %s/%s MB  ", $1, $3, $2}')"
