# Placement baseline — runtime v3 sau Torch removal

Ngày kiểm tra cục bộ 2026-11-25. Phạm vi là cấu hình, các container đang chạy trên máy dev và kiểm tra HTTP không ghi dữ liệu. Các container dev hiện tại **chưa được khởi động lại bằng code của nhánh này**, vì vậy số liệu tài nguyên dưới đây là ảnh chụp tham khảo, chưa phải nghiệm thu VM1/VM2 mới.

## Vị trí và quan hệ phụ thuộc

| Máy | Thành phần | Vai trò |
| --- | --- | --- |
| VM1, 2 vCPU/4 GB | nginx → API → PostgreSQL 16, Redis 7, Qdrant v1.19.1 | phục vụ truy vấn, lưu trạng thái và ba collection v3 |
| VM2, 2 vCPU/8 GB | embed ONNX INT8 warm, cron 12 giờ, Obscura | nhúng câu hỏi/ảnh và đồng bộ tăng dần |
| VM2, thủ công | svc-ocr | batch riêng, chỉ chạy khi cron đã dừng và embed không chịu tải query |

Luồng VM1→VM2 sử dụng TCP **8090** tới embedding gateway trên IP private VM2. VM2→VM1 dùng **5432** PostgreSQL, **6379** Redis và **6333/6334** Qdrant REST/gRPC qua mạng private, có kiểm tra xác thực. VM2 worker và embed giao tiếp bằng tên DNS `embed` trên Docker network external `sict-vm2` (`VM2_NETWORK` có thể đổi tên); pipeline kiểm tra cả bốn dependency trước lượt ghi.

## Quan sát dev (đọc tại chỗ)

| Container | CPU tức thời | RSS Docker tại thời điểm đọc | Restart | OOM |
| --- | ---: | ---: | ---: | --- |
| craw-sict-postgres-1 | 0.00% | 27.66 MiB / 600 MiB | 0 | false |
| craw-sict-redis-1 | 0.63% | 6.094 MiB / 300 MiB | 0 | false |
| craw-sict-qdrant-1 | 0.12% | 208.8 MiB / 1.074 GiB | 0 | false |
| sict-trial-embed | 0.13% | 1.844 GiB / 5.859 GiB | 0 | false |
| sict-live-api | 0.18% | 184.3 MiB / 1.465 GiB | 0 | false |

`docker stats --no-stream` và `docker inspect` chỉ phản ánh thời điểm lấy mẫu. `/healthz` ở local `127.0.0.1:8090` trả **200 trong 1.678 ms**. `/healthz` của API local cũ tại `127.0.0.1:8003` trả **404 trong 1.565 ms** vì image đang chạy chưa nhận code mới. Máy dev có 15,897 MiB RAM, `available` 1,484 MiB, swap 2,047 MiB đã sử dụng hết; không dùng dev host nhiều container này làm bằng chứng VM2 không OOM.

## Cách thu baseline nghiệm thu

1. Trên **dev đã được cấp phép**, chạy `scripts/monitor_2vm.sh infra|worker` lấy CPU/RSS/restart/OOM và HTTP health. Thu nhiều mẫu theo mốc thời gian, không lấy một snapshot làm peak.
2. Tách lượt API `/query`, SSE `/chat`, embed query và cron. Với mỗi lượt lưu thời gian, số HTTP calls tới embed từ metrics `sict_embed_items_total`/`sict_embed_request_duration_seconds`, p50/p95 theo loại input, TTFT SSE và kết quả HTTP.
3. Ghi phiên bản image, số vCPU/RAM, số request đồng thời, số lượng corpus và thời gian thử. Đối chiếu `/readyz` của API, `/healthz` của embed và heartbeat Redis.

**Quyết định tạm thời** — giữ VM1 stateful/API và VM2 warm embedding/cron như trên. Chỉ đánh giá T1/T2 khi có đo thực tế hai VM. Không thay đổi collection/model/retrieval hay bật deploy từ tài liệu này.

**Phụ lục đo local 2026-11-26:** một request nhúng chữ ngắn tuần tự có p50/p95 **236,72/289,96 ms**, 2 request đồng thời **384,35/515,19 ms** (24 mẫu mỗi lượt). Ghép worker tổng hợp giới hạn `0,7 CPU/768m` vào cùng hai CPU, p50/p95 lần lượt **283,47/341,29 ms** (tuần tự) và **551,84/636,16 ms** (2 đồng thời). `memory.current` của embed cao nhất trong các lượt ~**1.921 MiB**; container embed restart 0, OOM false. Đây là benchmark request embedding cục bộ trên host chia sẻ, không chứng minh VM2 6/8 GiB đã pass. Xem `docs/vm2-contention-report.md`.
