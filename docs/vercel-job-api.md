# Job API và Vercel Function batch

Job state được FastAPI giữ bền trên VM disk trong `sict_crawler/api/mvp_jobs.py`. `vercel/api/jobs.mjs` làm proxy cho create/status/manifest/artifact; `vercel/api/ocr-batch.mjs` xử lý OCR 1–3 ảnh mỗi request. Đây là endpoint **demo MVP** chỉ dùng phía server/operator.

## State machine

```text
queued → claim → running → checkpoint running → succeeded
                    │                       │
                    └── pause/crash ─→ paused → claim (attempt + 1)
```

Tạo job bằng `POST /internal/jobs` với `job_id` UUID, `kind` và `input_fingerprint` SHA256 64 ký tự hex. Cùng `job_id` và fingerprint trả lại state hiện có; khác fingerprint/kind trả 409. Một state ví dụ:

```json
{"job_id":"b2ac9670-1895-4e38-a7cf-4e15bdc2f019","kind":"ocr",
 "input_fingerprint":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
 "attempt":0,"revision":0,"status":"queued","checkpoint":{},"lease_until":0}
```

`POST /internal/jobs/{id}/claim` nhận lease 90 giây; chỉ một worker giữ lease còn hạn. Worker `POST .../heartbeat` với `expected_attempt`, rồi `PATCH /internal/jobs/{id}` kèm `expected_attempt`, `expected_revision`, `status` và `checkpoint`. Xung đột lease/revision trả 409. Chỉ kết thúc `succeeded` khi có output artifact được manifest ghi nhận và checksum tất cả artifact còn hợp lệ. Nếu có `input/items.json`, Job API còn yêu cầu `checkpoint.completed` trùng chính xác toàn bộ item ID duy nhất trong input và mỗi ID có `output/<id>.json` (hoặc `output/<id>.tar.gz` cho snapshot/compute). Thiếu item, output hoặc checksum sai trả 409 và job vẫn có thể resume.

Job types được nhận gồm `ocr`, `video`, `reconcile-dry-run`, `graph-stats`, `snapshot`, `compute`. API trả 422 cho `incremental-small`, `loader-staging`, `graph` và `reconcile-small`. Writer staging cần triển khai riêng.

Owner giữ `MVP_JOB_TOKEN` để tạo job, upload input và cấp capability qua `POST /internal/jobs/{id}/capabilities`. Capability HMAC giới hạn job_id, scope, expiry (mặc định 2700 giây, tối đa 3600 giây) và rate limit. Worker dùng `read`, `write`, `claim`; scope `report` chỉ cấp cho hai loại báo cáo. `POST /internal/jobs/{id}/report` nhận `expected_attempt`, yêu cầu lease còn hạn, chạy lệnh cố định chỉ đọc trong VM với timeout 20 giây và trả JSON tổng hợp. Không chuyển credential datastore cho Sandbox.

## OCR batch Function

`POST /api/ocr-batch` yêu cầu `MVP_JOB_TOKEN` cùng payload `{"job_id":"<uuid>","items":[{"id":"poster","base64":"<base64>"}]}`. Tối đa 3 item, body 4 MiB, thời hạn xử lý khoảng 42 giây. SHA256 fingerprint được tạo từ danh sách id và SHA256 byte ảnh, giữ nguyên thứ tự item. Function lưu bất biến `input/items.json` chứa ID và SHA256 từng ảnh **trước khi claim**. Output tên `output/<id>.json` và checkpoint `completed` cập nhật sau từng ảnh. Khi resume, Function kiểm tra từng artifact đã có bằng GET để VM xác nhận checksum và kiểm tra nội dung OCR. Nếu job chưa xong vì budget, response 202 với status `paused`; request tiếp theo dùng chính job_id và cùng input để resume. Retry một job với ảnh/input khác sẽ nhận 409.

Tương thích job cũ đã ở `paused`/`running` mà chưa có `input/items.json`: Function kiểm manifest trước khi upload, bỏ qua upload input cho job cũ và tiếp tục xác thực fingerprint, checkpoint và artifact output khi resume. Job mới ở `queued` luôn phải upload manifest trước claim; job đã có manifest phải kiểm tra nội dung bất biến khi retry.

`POST /api/jobs` (create), `GET /api/jobs?job_id=<uuid>` (status), `GET /api/jobs?job_id=<uuid>&manifest=1`, `GET/PUT /api/jobs?job_id=<uuid>&area=input&name=items.json` (artifact) là proxy có token. Upload output/work cần thêm `X-Job-Attempt`. Function proxy giữ body/response dưới **4 MiB**; artifact tới **8 MiB** dùng HTTPS VM API trực tiếp. Checksum upload qua header `X-Content-SHA256`.

Không đưa token vào frontend public. Nếu Function trả 409, đọc lại status/manifest rồi quyết định retry, tránh tạo job_id mới cho cùng batch. Bảng thử offline trong `vercel/tests/batch.test.mjs`, `vercel/tests/jobs.test.mjs` và `tests/test_mvp_jobs.py`. Chưa đo retry giữa hai invocation Vercel thật.
