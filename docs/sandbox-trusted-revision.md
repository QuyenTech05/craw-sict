# Sandbox — revision và credential tin cậy

Operator cấu hình `SICT_GIT_URL=https://github.com/quyentech05/craw-sict.git`,
`SICT_GIT_SHA` là commit SHA 40 ký tự hex thường đã review và `SICT_SANDBOX_IMAGE`
là custom image trên VCR pin bằng `@sha256:<64 ký tự hex thường>`. Biến
`SICT_GIT_REF` cũ phải được đổi thành `SICT_GIT_SHA`. Launcher từ chối branch,
tag, repository khác và image dùng mutable tag trước khi gọi Job API.

Launcher dùng HTTPS để lấy job và cấp capability riêng cho đúng `job_id`, TTL
2700 giây, scope `read`, `write`, `claim`; chỉ job `graph-stats` và
`reconcile-dry-run` được bổ sung `report`. Owner token nằm ở operator.
Sandbox nhận capability của job, OCR credential chỉ được truyền cho job OCR.
Runner bị giới hạn lease, checkpoint CAS, checksum và rate limit ở Job API.
Capability không được dùng để tạo job, cấp capability khác hoặc ghi input.

SDK checkout Git source tại SHA chỉ định; launcher kiểm tra `git rev-parse HEAD`
trùng SHA trước khi chạy `sandbox/run_job.sh`. Operator chịu trách nhiệm review
commit và build image từ dependency lock tương ứng trước khi pin digest. Image
chứa sẵn uv, worker/graph dependencies, ffmpeg, Poppler và Tesseract vie/eng.
Runner đối chiếu `uv.lock` và `pyproject.toml` với image, chạy offline, deadline
40 phút, timeout Sandbox 43 phút. Retry dùng checkpoint của job đã tạo.

Kiểm thử local đã xác nhận reject revision/tag không hợp lệ, checkout lệch SHA,
scope capability và resume. Việc đưa image lên VCR, kiểm tra checkout với SDK
cloud thật và smoke Sandbox cloud còn chờ nghiệm thu/approval.
