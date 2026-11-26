# Artifact và checkpoint bền trên VM-SERVE

FastAPI `mvp_jobs.py` lưu Job API vào Docker volume `mvp_jobs`, mount tại `/var/lib/sict-mvp/jobs` (có thể đổi bằng `MVP_JOB_ROOT`). Phạm vi lưu trữ này phục vụ **demo MVP** và cần dự trù disk/backup riêng nếu dữ liệu quan trọng.

```text
/var/lib/sict-mvp/jobs/<job_id>/
  state.json         # status, attempt, revision, lease, fingerprint
  checkpoint.json    # item hoàn thành
  manifest.json      # SHA256 và bytes của artifact
  input/
  work/
  output/
/var/lib/sict-mvp/jobs/.locks/<job_id>.lock
```

Mỗi artifact có tên an toàn dưới `input`, `work` hoặc `output`, không chấp nhận path traversal. Mỗi PUT yêu cầu `X-Content-SHA256` và giới hạn **8 MiB/artifact**. VM kiểm hash trước khi commit, ghi file tạm, `fsync`, đổi tên atomically rồi cập nhật `manifest.json` theo cùng quy trình atomic. Retry PUT với cùng checksum trả metadata đã lưu; cùng tên nhưng khác checksum trả 409. `GET` chỉ phục vụ artifact đã có trong manifest và kiểm checksum thực tế.

State `checkpoint.json`, `manifest.json` và `state.json` được ghi qua temp → fsync → atomic rename. Mỗi job có file lock `flock`; heartbeat giữ lease 90 giây, checkpoint dùng compare-and-swap theo revision. Worker chỉ ghi `input/` trước claim; `work/` và `output/` cần attempt đang giữ lease. Manifest không thay thế việc GET xác minh nội dung khi resume.

## Cleanup và khôi phục

`uv run python -m sict_crawler.api.mvp_jobs cleanup --ttl-hours 168` dọn **chỉ** job `succeeded` hoặc `failed` đã hết TTL và còn manifest. Job `queued`, `running`, `paused` không bị dọn. Lệnh này chưa được lên lịch tự động; operator quyết định thời điểm chạy trên máy phù hợp. Lock file tồn tại sau cleanup để tránh race với tiến trình đang chờ lock.

Nếu mất kết nối sau PUT, worker GET manifest/artifact để xác minh trước khi upload lại. Nếu manifest trỏ tới file mất hoặc checksum sai, Job API trả 409 để operator điều tra. Artifact lớn hơn 8 MiB phải chia nhỏ. Vercel proxy có giới hạn 4 MiB theo hướng truyền, vì vậy tải trực tiếp từ VM bằng URL HTTPS và token dành cho server khi cần file lớn.

Test `tests/test_mvp_jobs.py` bao phủ checksum, lease, CAS, idempotent upload, file hỏng và TTL; `tests/test_sandbox_job_contract.py` bao phủ crash/resume video. Chưa kiểm chứng mất điện thật, filesystem/disk full và quyền volume trên VM.
