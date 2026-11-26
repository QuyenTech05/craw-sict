# Vercel Sandbox batch worker có resume

Operator khởi chạy `node launch-sandbox.mjs <job_id>` từ thư mục `vercel/` sau khi thiết lập auth Vercel SDK (OIDC hoặc token hỗ trợ), `SICT_GIT_URL` (repository `https://github.com/quyentech05/craw-sict.git`), `SICT_GIT_SHA` (SHA 40 ký tự), `SICT_API_BASE` (HTTPS), `MVP_JOB_TOKEN` và `SICT_SANDBOX_IMAGE` (custom image VCR, bắt buộc pin @sha256 digest). Launcher cấp capability theo job, xác minh checkout SHA, tạo Sandbox 2 vCPU, timeout **43 phút**, truyền deadline runner **40 phút**, chạy `bash sandbox/run_job.sh <job_id>` rồi stop instance.

Runner đọc `input/items.json` từ VM Job API, claim job, heartbeat mỗi **25 giây**, xử lý từng item và checkpoint ngay sau khi output được upload. Bắt đầu dừng khi còn **90 giây** trước deadline. Nếu chết giữa upload và checkpoint, lần tiếp theo đối chiếu manifest và SHA256 artifact trên VM. Với video, các frame đã upload được đối chiếu nội dung, frame còn thiếu được ghi bổ sung và `output/<id>.json` được ghi cuối cùng. Khi resume từ metadata video, runner xác minh toàn bộ frame đã có trước khi đánh dấu hoàn tất.

## Dữ liệu vào

Tạo job trước qua Job API và upload `input/items.json` cùng input artifact qua PUT có SHA256. Ví dụ cho một video:

```json
{"items":[{"id":"clip01","input":"clip01.mp4"}]}
```

Mỗi id là chuỗi `[A-Za-z0-9_-]` dài 1–40, không trùng. Job nhận tối đa 100 item. `ocr` cần `input` là một ảnh, `MVP_OCR_URL` HTTPS và `MVP_OCR_TOKEN`; OCR được thực thi qua Vercel Function. `video` cần MP4 và ffmpeg trong Sandbox, tạo tối đa 3 frame. `snapshot` giới hạn tối đa 5 trang, `compute` chỉ nhận snapshot test tar.gz, chạy stage docs với giới hạn 5 trang tài liệu và `--no-semantic` để không gọi embedding. Runner kiểm tra cả đường dẫn trong manifest và tạo output ở thư mục mới cho mỗi lần thử. `graph-stats` và `reconcile-dry-run` gọi báo cáo chỉ đọc qua Job API.

`incremental-small` và `loader-staging` bị API, launcher và runner từ chối cho tới khi triển khai write path vào collection staging độc lập và cơ chế verify manifest. Không chạy các job này bằng cách sửa command thành loader/indexer live.

## Dependencies và quyền kết nối

Build image từ root bằng `docker build -f sandbox/Dockerfile -t sict-sandbox:<sha> .`. Image chứa uv, môi trường Python khóa theo `uv.lock` (worker + graph), ffmpeg, Poppler, Catdoc và Tesseract vie/eng. `sandbox/run_job.sh` kiểm tra lock và dùng `uv run --no-sync --offline`; không tải dependency lúc runtime. Không cài Torch hay `requirements.txt`. File tạm thuộc Sandbox sẽ bị xóa khi phiên kết thúc, vì vậy đầu ra và checkpoint phải upload về VM.

Hai job báo cáo gọi `POST /internal/jobs/{id}/report` với scope `report` và attempt còn lease. VM chạy đúng lệnh `graphsync stats` hoặc `reconcile --dry-run` theo kind đã lưu, timeout 20 giây, tối đa một báo cáo đồng thời mỗi tiến trình API. `stats` không khởi tạo schema. Sandbox không nhận credential datastore; lỗi hoặc hết hạn trả HTTP lỗi để runner pause/resume. Cần kiểm chứng thời gian và RAM trên VM đích. Custom image cần được publish vào VCR và xác minh bằng Sandbox thật sau khi được phép triển khai.

Để mô phỏng dừng phiên mà không dùng VM, chạy `uv run pytest tests/test_sandbox_job_contract.py -q` và `cd vercel && npm test`. Sandbox SDK và network thực chưa được thử. Xem `sandbox/README.md` cho cách chuẩn bị job.
