# Vercel Sandbox batch

Runner `sandbox/job_runner.py` thực thi job có checkpoint trên VM-SERVE. Lệnh khởi tạo
Sandbox qua SDK là `node launch-sandbox.mjs <job_id>` trong thư mục `vercel/`
(cấu hình OIDC/token Vercel, Git URL allowlist, commit SHA, Job API HTTPS, owner token và `SICT_SANDBOX_IMAGE` trỏ custom image VCR pin @sha256 digest). Launcher chỉ truyền capability theo job; OCR token chỉ cấp cho OCR.

Trước khi chạy, tạo job qua `POST /internal/jobs`, upload `input/items.json` và
các ảnh/video/snapshot vào `input/` qua API checksum. `items.json` có dạng
`{"items":[{"id":"img01","input":"img01.png"}]}`. Mỗi `id` phải duy nhất.

Supported jobs thực thi được với artifact test gồm `ocr` (gọi Function qua
`MVP_OCR_URL`/`MVP_OCR_TOKEN`), `video`, `reconcile-dry-run`
(via Job API), `graph-stats` (via Job API), `snapshot` (`--max-pages <= 5`) và `compute`
(`--stages docs --limit-docs 5 --no-semantic`). `incremental-small` và `loader-staging` hiện bị
API và runner từ chối đến khi có writer staging độc lập, để tránh ghi collection v3 live.

Build image bằng `docker build -f sandbox/Dockerfile -t sict-sandbox:<sha> .` từ root; runtime kiểm lock, chạy offline với venv đã chuẩn bị. Publish VCR chỉ sau khi được duyệt.

Checkpoint tiến lên sau từng item thành công. Manifest trên VM giữ SHA256 của output.
Mỗi phiên có budget 40 phút, heartbeat 25 giây và dừng trước giới hạn session, lần sau chạy lại
cùng `job_id` để xử lý tiếp từ checkpoint. Trong thử nghiệm, chạy local với
fake client hoặc HTTP test server, không kết nối VM production.
