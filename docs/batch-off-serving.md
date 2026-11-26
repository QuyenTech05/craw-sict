# Batch tách khỏi hai VM serving

Quyết định 2026-11-26. VM-SERVE (2 GiB) chỉ chạy stores/API/nginx. VM-EMBED (4 GiB) chỉ giữ Jina-CLIP v2 ONNX INT8 HTTP warm. Không chạy `cron`, `svc-ocr`, Obscura, graph rebuild, video hoặc loader trên hai máy này. Các dịch vụ worker trong `docker-compose.worker.yml` và `docker-compose.worker-lite.yml` nằm sau profile `batch` hoặc `manual`, chỉ dành cho một host batch độc lập.

## Job contract

Mỗi job có `job_id` hoặc idempotency key dựa trên SHA256 input, phiên bản crawler/parser/OCR/model/rules và collection schema. Input bắt đầu từ snapshot hoặc artifact đã cố định, output nằm trong staging riêng theo job_id và manifest. Manifest ghi `source_fingerprint`, `model_revision`, `model_backend=api`, `embedding_dim=1024`, prefix và schema, số record, checksum và trạng thái hoàn tất. Job ghi checkpoint sau mỗi stage, timeout và retry hữu hạn với backoff. Resume phải đọc checkpoint và không tạo duplicate point; uuid5 hiện tại giúp upsert lặp được ở bước loader nhưng không bảo đảm giao dịch atomic qua PG + Qdrant.

| Nhóm job | Nơi chạy phù hợp | Input / output / lưu ý |
| --- | --- | --- |
| `incremental` và fetch | dev hoặc batch VM theo giờ có kết nối private được duyệt | Frontier/crawl version → snapshot diff; code hiện tại ghi live, cần staging rồi duyệt promotion trước khi bật schedule |
| OCR/backfill | dev, batch container, serverless khi đo đủ | ảnh/tài liệu + OCR version → text, confidence, artifact theo hash |
| Video, subtitle, keyframe | batch container/VM | video+ETag → manifest frame/subtitle theo source hash; chặn kích thước download/timeout |
| `graphsync` rebuild | batch VM có đủ RAM | snapshot + rule version → artifact graph kiểm tra trước promotion; rules-only |
| `reconcile --dry-run` | dev hoặc serverless thử read-only | PG/Qdrant snapshot → mismatch report, không sửa index |
| `snapshot` / `compute` | dev hoặc batch VM có embedding riêng | immutable snapshot → `.npy`/JSONL + manifest embedding v3 |
| `loader` | job kiểm soát riêng sau duyệt | chỉ ghi vào collection staging v3 có fingerprint hợp lệ, không ghi collection đang phục vụ |

## Isolation và retry

- Serving Qdrant chỉ phục vụ `sict_text_v3`, `sict_image_v3`, `sict_ocr_v3`. Batch không được viết trực tiếp các collection này trước approval, không tự xoá dữ liệu hoặc di chuyển collection alias.
- Batch compute dùng embedding riêng trên batch host, không gửi batch dài vào VM-EMBED đang phục vụ user. Không chia sẻ volume ONNX/cache hoặc CPU với VM-EMBED.
- Chỉ cấp kết nối PG/Redis/Qdrant cho job cần thiết, qua private network và credentials riêng. Batch đọc được thực hiện dry-run mặc định. Mọi bước promotion/sync dữ liệu live phải có lock chống ghi đồng thời, backup, checksum và lệnh rollback đã duyệt.
- Khi timeout, lưu trạng thái lỗi theo job_id, bảo toàn artifact staging để retry cùng idempotency key. Chặn ghi nếu manifest model/backend/dimension/collection prefix không khớp v3.

## Kiểm thử offline hiện có

`reconcile --dry-run` dev từng hoàn tất ~14,92 giây, RSS ~148 MiB, mismatch 0 với corpus dev. Đây là một phép đo local, chưa có cloud cold-start, egress, S3 request, tần suất batch hoặc kiểm tra rollback thực tế. Không chạy thử lại vào production trong đợt implementation này.

## Điều kiện bật job bên ngoài serving

Trước khi chạy cloud hoặc máy thuê giờ, thu `duration`, peak RAM/CPU, cold start, bytes in/out, tỷ lệ retry, log bytes và đơn giá region thực. Staging phải được đối chiếu đủ số documents/media/points và fingerprint. Từng tác vụ có thao tác S3, VM, loader/cutover hoặc thay đổi live cần owner phê duyệt riêng. Chi phí và lựa chọn runtime ghi tại `docs/vm-cost-matrix-2gb-4gb.md`.
