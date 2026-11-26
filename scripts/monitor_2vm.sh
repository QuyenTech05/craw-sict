#!/usr/bin/env bash
# Monitor nhanh cho 2-VM compose (chạy trên từng VM, không cần Prometheus để đỡ tốn RAM).
# VM-SERVE: ./scripts/monitor_2vm.sh infra  |  VM-EMBED: ./scripts/monitor_2vm.sh embed
set -u
ROLE="${1:-infra}"
# D12: mật khẩu Redis / khoá Qdrant đọc từ .env của stack (thư mục chạy hoặc ~/craw-sict), không in ra
envv() { grep -hE "^$1=" .env ~/craw-sict/.env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"'"; }
export REDISCLI_AUTH="$(envv REDIS_PASSWORD)"; QKEY="$(envv QDRANT_API_KEY)"   # -e TÊN (không =giá trị) → không lộ qua ps
echo "=== [$(date '+%F %T')] role=$ROLE host=$(hostname) ==="
echo "--- docker ps ---"
docker ps --format 'table {{.Names}}\t{{.Status}}' 2>&1 | head -15
echo "--- resource snapshot (docker stats, no-stream) ---"
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}' 2>&1 | head -15
echo "--- restart/OOM snapshot ---"
docker ps -aq --filter label=com.docker.compose.project | xargs -r docker inspect \
  --format '{{.Name}} restarts={{.RestartCount}} oom={{.State.OOMKilled}} status={{.State.Status}}' 2>&1 | head -15
echo "--- disk / ---"
df -h / | tail -1
echo "--- mem ---"
free -h | head -2
if [ "$ROLE" = "infra" ]; then
  echo "--- postgres counts (v2/v3: bảng media, ocr_status) ---"
  docker exec "$(docker ps -q --filter name=postgres | head -1)" \
    psql -U sict -d sict_crawler -c \
    "SELECT (SELECT count(*) FROM documents) docs, (SELECT count(*) FROM media) media, (SELECT count(*) FROM media WHERE ocr_status<>'done') ocr_pending, (SELECT count(*) FROM entities) concepts;" 2>&1 | head -8
  echo "--- qdrant collections ---"
  curl -s -H @<(printf 'api-key: %s' "$QKEY") localhost:6333/collections 2>&1 | head -c 500; echo
  echo "--- api health ---"
  curl -s -m 5 -o /dev/null -w "http=%{http_code} latency=%{time_total}s " localhost:8003/healthz 2>&1; echo
  echo "--- api ready (stores + private embed) ---"
  curl -s -m 5 -o /dev/null -w "http=%{http_code} latency=%{time_total}s " localhost:8003/readyz 2>&1; echo
  echo "--- embedding failure counter ---"
  curl -fsS -m 5 localhost:8003/metrics 2>/dev/null | grep '^sict_query_embed_failures_total' | head -6 || true
  echo "--- nginx edge (8080) ---"
  curl -s -m 5 localhost:8080/nginx-health 2>&1 | head -c 100; echo
elif [ "$ROLE" = "embed" ]; then
  echo "--- embed warm readiness ---"
  EMBED_CHECK_BIND="$(envv EMBED_BIND)"
  [ -n "$EMBED_CHECK_BIND" ] || EMBED_CHECK_BIND="127.0.0.1"
  curl -s -m 5 -o /dev/null -w "http=%{http_code} latency=%{time_total}s " \
    "http://${EMBED_CHECK_BIND}:8090/healthz" 2>&1; echo
  echo "--- embed metrics (requests/errors/latency) ---"
  curl -fsS -m 5 "http://${EMBED_CHECK_BIND}:8090/metrics" 2>/dev/null | \
    grep -E '^sict_embed_(items_total|errors_total|request_duration_seconds_(count|sum))' | head -16 || true
  echo "--- batch processes must be absent on embed VM ---"
  docker ps --format '{{.Names}}' | grep -E '(^|[-_])(cron|obscura|svc-ocr)([-_]|$)|^sict-worker-24h$' || echo "none"
else
  echo "Role hợp lệ: infra | embed" >&2
  exit 2
fi
