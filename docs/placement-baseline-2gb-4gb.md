# Baseline placement thử nghiệm — VM-SERVE 2 GiB / VM-EMBED 4 GiB

Ngày lập: 2026-11-26. Cấu hình này là **target để nghiệm thu**, chưa thay instance type hay chạy trên VM production. Dữ liệu trong `docs/placement-baseline-new-runtime.md` và `docs/vm2-contention-report.md` thuộc thế hệ 4/8 GiB, chỉ dùng làm đối chứng lịch sử.

## Inventory và tài nguyên

| Máy | Cấu hình đích | Thành phần chạy thường trực | Tổng memory limit |
| --- | --- | --- | --- |
| VM-SERVE | 2 vCPU / 2 GiB | PostgreSQL 16, Redis 7, Qdrant 1.19.1 v3, FastAPI v3, nginx | 384 + 128 + 850 + 320 + 64 = **1746 MiB** |
| VM-EMBED | 2 vCPU / 4 GiB | Jina-CLIP v2 ONNX Runtime INT8, HTTP `:8090` | **3500 MiB** |
| Ngoài serving | dev / máy thuê theo giờ / batch được duyệt | incremental, OCR, video, graph rebuild, reconcile, snapshot/compute/loader | theo từng job |

VM-SERVE còn khoảng **302 MiB** ngoài giới hạn container trước khi tính kernel, Docker, filesystem cache và agent giám sát. VM-EMBED còn khoảng **596 MiB** trước phần ngoài container. Không kết luận khả thi chỉ từ phép cộng memory limit. **Nếu Qdrant hoặc embedding bị OOM trên máy thật, dừng nghiệm thu; không tiếp tục ép giảm limit.**

Defaults `.env.example` gồm `PG_SHARED_BUFFERS=64MB`, `PG_MAX_CONNECTIONS=20`, `REDIS_MAXMEMORY=64mb`. VM-EMBED dùng `EMBED_CONCURRENCY=1` chia sẻ slot giữa các loại request, `EMBED_TEXT_MAX_LEN=1536`, `EMBED_TOKEN_BUDGET=1536`, `EMBED_IMAGE_BATCH=1`, `EMBED_QUERY_IMAGE_SIZES=336`. API/worker dùng `EMBED_BACKEND=api`, `EMBED_MODEL=jina-clip-v2`, `EMBED_DIM=1024`. Ba collection đang phục vụ là `sict_text_v3`, `sict_image_v3`, `sict_ocr_v3`, vector 1024 chiều.

## Dependency và cổng

```text
VM-SERVE: PostgreSQL + Redis + Qdrant v3 ready
    ↓
VM-EMBED: HTTP :8090/healthz ready qua private network
    ↓
VM-SERVE: API /readyz = 200
    ↓
/query (1 và 2 concurrent), /chat SSE, /query có ảnh
```

VM-SERVE gọi embedding bằng `EMBED_API_BASE=http://<private-VM-EMBED>:8090/v1` với API key theo cấu hình thực tế. Cổng `8090` chỉ mở từ VM-SERVE trong private network. Store trên VM-SERVE không cần expose public, truy cập DB phục vụ batch chỉ theo quyền riêng được duyệt. Nginx là điểm vào công khai. Không ghi IP, key, password vào tài liệu hoặc commit.

Trước mỗi lần đổi image/collection, đối chiếu **fingerprint** index v3 với manifest (model, backend, dimension, prefix), xác nhận `/readyz` và kiểm tra số point; chỉ cutover khi trùng khớp.

## Cần ghi từ AWS trước khi quyết định giảm máy

| Hạng mục | VM-SERVE | VM-EMBED |
| --- | --- | --- |
| EC2 instance type / OS / region / AZ | chưa xác minh | chưa xác minh |
| Root EBS loại, dung lượng, IOPS, snapshot | chưa xác minh | chưa xác minh |
| Giờ chạy/tháng (ước tính 24/7 là 730 giờ) | cần đối chiếu hoá đơn | cần đối chiếu hoá đơn |
| Network private/inter-AZ/public, public IPv4 | chưa xác minh | chưa xác minh |
| Logs, metrics, Alloy/monitoring RSS | chưa đo | chưa đo |
| Baseline CPU/RSS peak/OOM/restart trên 2/4 GiB thật | chưa đo | chưa đo |

## Bằng chứng có sẵn và khoảng trống

- HTTP embed local cũ, 24 mẫu/lượt trên host không ghim 4 GiB: p95 **289,96 ms** khi tuần tự và **515,19 ms** khi hai request đồng thời, RSS lấy mẫu khoảng **1,921 GiB**, không thấy OOM. Số liệu chưa xác nhận giới hạn 1536 token hoặc 4 GiB trên VM đích.
- `reconcile --dry-run` trên dev trước đó hoàn tất khoảng **14,92 giây**, RSS khoảng **148 MiB**. Đây là đo batch đọc local, chưa chứng minh serverless.
- Contract test và `docker compose config` chỉ xác nhận cấu hình. Khi owner phê duyệt VM, cần ghi CPU/peak RSS/`OOMKilled`/restart, API `/readyz`, query p50/p95, SSE TTFT, lỗi và trạng thái ba collection trước/sau.

Nguồn theo dõi local là `scripts/monitor_2vm.sh infra` và `scripts/monitor_2vm.sh embed`. Tiêu chí dừng và trình tự chuyển máy xem `docs/placement-rollout-new-runtime.md`.
