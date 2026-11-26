# Kết quả kiểm chứng MVP Vercel

Ngày đối chiếu local: **2026-11-26**. Đây là báo cáo phạm vi unit/contract offline, không phải biên bản nghiệm thu Vercel production. Chủ dự án đã yêu cầu **bỏ đo RAGAS và benchmark retrieval mới** sau khi xác nhận parity giữa retrieval mới và API cũ trên các bộ đối chứng đã chạy. Báo cáo này không tự tạo số đo RAGAS hay latency cloud.

| Luồng | Bằng chứng offline | Nghiệm thu thực tế |
| --- | --- | --- |
| Query text không OCR | `tests/test_mvp_ocr_fallback.py` xác nhận policy mặc định off | Chưa đo VM-SERVE 2 GiB |
| Query ảnh visual match trước OCR | Contract yêu cầu retrieval trước fallback | Chưa thử ảnh sự kiện trên public VM |
| Poster/banner OCR | `vercel/tests/ocr.test.mjs` có token, size, timeout, mock kết quả | Chưa đo Tesseract.js tiếng Việt trên Vercel |
| OCR batch retry | `vercel/tests/batch.test.mjs` xác nhận upload input manifest, checkpoint, retry sau upload, từ chối JSON null/item null, kết quả OCR sai cấu trúc, checkpoint thiếu/trùng ID và artifact hỏng | Chưa mô phỏng kill Function thực |
| Sandbox resume | `tests/test_sandbox_job_contract.py` mô phỏng crash/manifest/lease và từ chối output OCR sai cấu trúc trước upload | Chưa tạo Sandbox thật |
| Artifact storage | `tests/test_mvp_jobs.py` kiểm hash, atomic metadata, lease/TTL và chỉ hoàn tất khi đủ output cho mọi input ID | Chưa thử gián đoạn network hoặc disk trên VM |
| `/chat` SSE | Test integration mock kiểm retrieval → OCR → answer | Chưa thử stream qua public nginx |

## Gate trước demo

Kiểm tra offline tại nhánh hiện hành gồm `npm test` với **18 passed** và `uv run pytest tests/ -q --ignore=tests/smoke_incremental.py` với **664 passed, 5 skipped, 7 warnings**. `bash -n sandbox/run_job.sh`, `docker compose config --quiet`, `docker compose -f docker-compose.embed.yml config --quiet` và `git diff --check` đều đạt. Sau khi bổ sung kiểm tra manifest snapshot và output riêng, suite Sandbox chạy **14 passed** (gồm 3 ca mới). Năm skip do môi trường dev thiếu tokenizers (1), onnx (3), underthesea (1). Các bài này dùng mock và file test cục bộ, không chứng minh latency hoặc khả năng chạy Vercel thật.

1. VM-SERVE sau khi được phép deploy phải chạy `/healthz`, `/readyz`, ít nhất 2 query đồng thời, chat SSE và query ảnh; lấy container RSS, restart count, OOM và p50/p95.
2. VM-EMBED 4 GiB cần kiểm nghiệm input dài/ảnh, concurrency=1, mức dùng RSS thực và tình huống endpoint down.
3. Vercel Function cần đo cold/warm OCR `vie+eng`, timeout, lỗi traineddata và tỷ lệ trả thành công. Ghi riêng trường hợp OCR trả rỗng hoặc fallback unavailable.
4. Job API cần thử retry sau timeout, manifest checksum và lease takeover. Sandbox cần thử session dừng trước 45 phút rồi khởi chạy cùng job_id để hoàn thành nốt.
5. `graph-stats` / `reconcile-dry-run` dùng gateway chỉ đọc theo capability và lease, chưa kiểm chứng datastore thật. `incremental-small` / `loader-staging` bị từ chối ngay tại API vì config v3 chỉ cho phép các collection đang phục vụ; cần staging writer riêng và verify manifest trước khi enable. Tất cả các mục này chưa có kết quả chạy thực trên Sandbox.

Các metric chưa đo phải ghi **N/A**, không tính như pass. Dừng rollout nếu có OOM/restart, index không khớp manifest, hoặc job không resume đúng. Bản ghi local bổ sung sau mỗi lần kiểm thử phải nêu cấu hình máy, commit, số mẫu, loại request và cỡ ảnh.
