# Khảo sát serverless batch trên runtime v3

Ngày 2026-11-25. Đây là đánh giá khả thi và hợp đồng job. Chưa triển khai tài nguyên cloud. PostgreSQL, Redis, Qdrant tự quản trên VM1 và API + ONNX embedding warm là các tiến trình dài hạn. Không khởi tạo embedding model mới cho từng request serverless khi chưa có đo cold start.

## Các loại job và hợp đồng thực thi

| Job | Input → output | Khoá idempotency và retry | Ngưỡng tài nguyên/thời gian cần đo | Quyền mạng và ghi |
| --- | --- | --- | --- | --- |
| OCR tài liệu/ảnh | S3/local bytes, content SHA → text OCR và trạng thái | `sha256(bytes) + ocr_version`, output theo key cố định; chỉ commit sau khi đã ghi artifact thành công | RAM/Tesseract peak, số trang, CPU-min, cold start; timeout theo số trang | đọc object store, ghi artifact staging, không sửa collection đang phục vụ |
| Video keyframe/subtitle | video URL + ETag/crawl version → manifest frame SHA và subtitle | `video_id + source_version + extractor_version`; resume theo frame id, retry lỗi tải tạm | CPU ffmpeg, disk tạm, timeout network/ffmpeg | HTTPS tới nguồn, object store staging; không tải cả video lâu dài |
| Graph rebuild | snapshot docs + graph rules version → concept artifact | `sha256(manifest + rules_version)`; staging immutable, swap chỉ sau verify | CPU, RAM underthesea, thời lượng rebuild | đọc PG/snapshot, không đổi graph đang phục vụ khi chưa pass acceptance |
| Reconcile | PG id set + Qdrant point snapshot → báo cáo mismatch | `snapshot_fingerprint + reconcile_version`; mọi retry dry-run an toàn | kích thước index, số API calls, memory của tập id | private DB và Qdrant read-only mặc định; sửa dữ liệu cần owner duyệt riêng |
| Snapshot | nguồn URL/crawl version → `state.sqlite` + HTML/media | canonical URL + content hash; resume trên cùng snapshot; artifact prefix duy nhất | bytes tải, duration, timeout từng nguồn, disk tạm | HTTPS site trường, staging object store; không viết index live |
| Compute | immutable snapshot + model/rule manifest → JSONL + `.npy` | `snapshot_sha + model + prefix + rules + dimension`; checkpoint từng stage | CPU/OCR, số lượt HTTP nhúng, RAM và giới hạn duration | embed warm gateway qua private network, ghi staging; không nạp vào Qdrant trực tiếp |
| Loader | manifest đã kiểm fingerprint → PG/Qdrant | uuid5 stable id giúp upsert lặp lại, nhưng quá trình nhiều store **không atomic**; cần staging index, preflight manifest, lock và rollback | duration DB/index, timeout, số batch lỗi | quyền ghi production chỉ sau owner approval, không dùng để spike |
| Incremental trigger | schedule event + cycle id → một lượt cron | unique `cycle_id`, distributed lease/heartbeat ở Redis; retry có backoff và bảo vệ mass-delete | startup cold start, duration và số vòng retry | private VM1 stores + VM2 embed; cron hiện tại tiếp tục ở VM2 |

Điều kiện chung cho phương án cloud gồm deadline rõ ràng, retry bounded, dead-letter hoặc checkpoint ghi bền, output theo SHA/version, chống hai worker nạp đồng thời, giới hạn batch size, chứng thực IAM tối thiểu và kiểm tra input fingerprint. Khi hết thời gian, lỗi phải được ghi vào job status trước khi retry. Không cho serverless ghi đè ba collection `*_v3` live theo mặc định.

## Spike an toàn

Candidate đầu tiên là `reconcile --dry-run`, vì triển khai hiện tại có chế độ chỉ đọc, xuất số liệu PG và Qdrant cùng cờ `dry_run=true`, không xoá point/ghi hash. Chỉ gọi trên **dev local**; tuyệt đối không chạy nếu env hiện tại trỏ VM, cloud hoặc production. Đã chạy `uv run --no-sync python -m sict_crawler.pipeline.reconcile --dry-run` ở dev, exit 0, nhận `pg_docs=2310`, `text_points=22646`, `image_points=6056`, `orphan_text=0`, `image_detach=0`, `image_orphan=0`, `docs_missing_points=0`, `dry_run=true`. Spike xác nhận code path trên corpus dev; chưa đo network, cold start, retry và chi phí Lambda/Fargate.

**Số đo bổ sung 2026-11-26:** cùng job local chạy riêng trong **14,92 giây**, MaxRSS **151.148 KiB** (~147,6 MiB), exit 0; khi ghim hai CPU `0,1` và chạy đồng thời 24 câu hỏi embed (2 request đồng thời), job hoàn tất **5,39 giây**, MaxRSS **152.552 KiB** (~149 MiB), exit 0, các mismatch vẫn bằng 0. Trong lượt chạy đồng thời, HTTP embedding p50 **427,21 ms**, p95 **697,65 ms**. Cả hai lượt chạy chế độ chỉ đọc. Khoảng chênh thời gian cần đo thêm với cache/corpus cố định; đây là runtime process local, chưa phải thời gian cold-start cloud. Xem phương pháp tại `docs/vm2-contention-report.md`.

## Mô hình chi phí

Cho mỗi job `j`, đo số lượt/tháng `N_j`, duration thực `t_j`, CPU/memory được cấp, input/output bytes, retry trung bình `k_j` và log bytes `l_j`. Với Lambda tính `C_j ≈ N_j × k_j × (t_j × GB_j × giá_GB-giây + giá_request + egress_j + object_IO_j + log_j) + NAT_j`. Với container batch tính theo vCPU-s và GiB-s, cộng phút tối thiểu và thời gian khởi tạo nếu nhà cung cấp làm tròn. Đối chiếu phí network private subnet/NAT gateway, public IPv4, inter-AZ, S3 PUT/GET, storage retention, CloudWatch/Grafana log và số retry fail. Ghi min/max theo chu kỳ 28–31 ngày và sự kiện cao điểm.

## Quyết định

Tạm giữ cron/Obscura/OCR thủ công trên VM2. OCR, snapshot và reconcile read-only là ứng viên thử sau, tuỳ duration, idempotency và chi phí đo thực. Compute/loader cần staging và guard production trước khi di chuyển. Không bật cloud batch cho các job ghi collection live trong đợt này.
