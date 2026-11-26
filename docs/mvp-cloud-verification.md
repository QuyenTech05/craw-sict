# Nghiệm thu cloud/VM MVP

Ngày kiểm tra local: 2026-11-26. Các mục N/A chưa có số đo hoặc kết quả thực tế
trên cloud. Chưa có đợt deploy mới trong lần sửa PLAN_FIX này.

| Gate | Kết quả cloud/VM | Việc cần xác minh |
|---|---|---|
| GitHub CI | N/A | Workflow trên commit sửa mới |
| GHCR release | N/A | Push thành công và inspect đủ api/worker/embed manifests |
| CD prepare/deploy | N/A | Canonical tag tồn tại, deploy chỉ sau approval |
| Vercel OCR | N/A | Cold/warm vie+eng, poster/banner/WebP/no-text, timeout/error, auth |
| Vercel Job API | N/A | HTTP retry qua mạng thật, auth, lease, heartbeat, checkpoint |
| Vercel Sandbox | N/A | Custom image VCR theo digest, trusted SHA, stop/resume thật |
| VM-SERVE 2 vCPU/2 GiB | N/A | Readiness, 2 query đồng thời, chat SSE, ảnh, RSS/OOM/restart |
| VM-EMBED 2 vCPU/4 GiB | N/A | Text/image/1536 token, concurrency 1, auth, RSS/OOM/restart |
| Public embedding | N/A | Từ chối thiếu/sai key, latency khi warm và cold |
| Graph/reconcile | N/A | Báo cáo read-only trên datastore thật |
| Retrieval/answer | N/A | Golden v2, list v2, person v1, media v1 và golden multimodal RAGAS |

Theo PLAN_FIX, release-images run 45793210957 từng fail vì owner GHCR viết hoa;
CD run 45793211002 từng fail vì image không tồn tại. CI run 45793210927 là
lịch sử trước thay đổi hiện tại; không dùng làm bằng chứng CI của bản sửa.
Kết quả local xem [báo cáo kiểm chứng](mvp-fix-verification-report.md).

Chỉ nghiệm thu public khi các gate cần thiết có bằng chứng cloud/VM thực,
không có auth bypass, OOM/restart, citation sai hoặc resume thất bại.
