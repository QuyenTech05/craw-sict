# Hợp đồng runtime công khai cho demo MVP Vercel

Nguồn triển khai là `/codex/PLAN_VM_SERVERLESS_NEW_RUNTIME.md`. Phạm vi tài liệu này **chỉ dành cho demo MVP**, cần đánh giá lại trước khi dùng production. Việc expose endpoint không đồng nghĩa đã được chủ dự án duyệt triển khai VM/CD.

## Sơ đồ kết nối

```text
Người dùng → HTTPS nginx VM-SERVE → FastAPI /query, /chat
                                     ├─ PostgreSQL + Redis + Qdrant v3 (local Compose)
                                     └─ HTTP Jina-CLIP v2 → VM-EMBED :8090
FastAPI → HTTPS Vercel /api/ocr             (chỉ khi MVP_OCR_POLICY bật)
Operator → Vercel /api/jobs hoặc VM Job API (token riêng)
Operator → Vercel Sandbox SDK → HTTPS VM /internal/jobs
Sandbox → Vercel /api/ocr                  (OCR theo item)
Sandbox → VM disk API                     (artifact, checkpoint, heartbeat)
```

| Nơi chạy | Tài nguyên mục tiêu | Kết nối cần thiết |
| --- | --- | --- |
| VM-SERVE | 2 vCPU, 2 GiB; nginx, API, PG, Redis, Qdrant | Public HTTPS qua nginx. PG 5432, Redis 6379, Qdrant 6333 chỉ mở khi job thực sự cần, giới hạn nguồn và có credential. |
| VM-EMBED | 2 vCPU, 4 GiB; embed warm, concurrency 1 | HTTP 8090 từ API, public HTTPS reverse proxy nếu phải truy cập từ bên ngoài. |
| Vercel Function | 2 GiB/1 vCPU theo cấu hình dự kiến | HTTPS tới VM Job API, Tesseract.js `vie+eng`. |
| Vercel Sandbox | MicroVM tạm thời, 43 phút timeout, runner deadline 40 phút | HTTPS Job API, HTTPS OCR Function. Báo cáo datastore đi qua Job API. |

API công khai trên VM-SERVE gồm `GET /healthz`, `GET /readyz`, `POST /query`, `POST /chat` (SSE). VM-EMBED cung cấp `GET /healthz` và `POST /v1/embeddings`. VM-SERVE cung cấp `POST /internal/jobs`, `GET /internal/jobs/{job_id}`, `POST /internal/jobs/{job_id}/claim`, `POST /internal/jobs/{job_id}/heartbeat`, `PATCH /internal/jobs/{job_id}`, `GET /internal/jobs/{job_id}/manifest` và `GET/PUT /internal/jobs/{job_id}/artifacts/{area}/{name}`. VM còn có `POST /internal/jobs/{job_id}/capabilities` (owner) và `POST /internal/jobs/{job_id}/report` (scope report và lease). Job API yêu cầu owner Bearer token hoặc capability theo job và scope phù hợp; owner token chưa cấu hình trả 503. Endpoint `/v1/embeddings` và `/metrics` của VM-EMBED yêu cầu Bearer `EMBED_API_KEY`; `/healthz` và `/` chỉ trả trạng thái `ok` công khai.

## Các ràng buộc

- Embedding là `EMBED_BACKEND=api`, `EMBED_MODEL=jina-clip-v2`, `EMBED_DIM=1024` qua `EMBED_API_BASE`. Các collection chỉ gồm `sict_text_v3`, `sict_image_v3`, `sict_ocr_v3`; không đưa Torch vào API/worker.
- VM-SERVE khởi đầu với `API_MEM_LIMIT=320m`, `PG_MEM_LIMIT=384m`, `REDIS_MEM_LIMIT=128m`, `QDRANT_MEM_LIMIT=850m`, `NGINX_MEM_LIMIT=64m`. Đây là mức **chưa nghiệm thu OOM thực trên VM 2 GiB**.
- VM-EMBED khởi đầu với `EMBED_MEM_LIMIT=3500m`, `EMBED_CONCURRENCY=1`, `EMBED_THREADS=2`, `EMBED_IMAGE_BATCH=1`. Model ONNX và tokenizer phải được chuẩn bị sẵn trên máy đủ RAM.
- Các host API, embedding và Function phải đặt HTTPS khi public. Không đưa credentials DB/Qdrant, token hoặc URL có bí mật vào mã nguồn hay client browser. Operator giữ `MVP_JOB_TOKEN`; Sandbox chỉ nhận `MVP_JOB_CAPABILITY_TOKEN` ngắn hạn giới hạn job và scope, OCR token chỉ ở OCR job.
- `MVP_OCR_POLICY` mặc định `off`. Bật `weak` để OCR khi retrieval yếu/cần đọc chữ hoặc `always` khi thử demo. Lỗi Function được giới hạn timeout và API vẫn trả retrieval sẵn có.
- Các job `graph-stats` / `reconcile-dry-run` đọc datastore qua báo cáo cố định trong VM. Giữ PG/Redis/Qdrant private. Không quảng bá graph rebuild, reconcile mutation, incremental hoặc loader staging cho đến khi có write path riêng được kiểm chứng.

Chưa có xác minh VM đích, DNS/certificate public, Vercel deployment, số đo RSS/OOM và request thật. Tham khảo `docs/mvp-evaluation-report.md` trước khi đưa traffic demo.
