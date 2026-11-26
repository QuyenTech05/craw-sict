# VM2 contention — giả lập local ngày 2026-11-26

Đã đo trên dev cục bộ từ 01:32–01:34 (+07), dùng embedding Jina-CLIP v2 ONNX INT8 **đang warm**. Không đổi container đang chạy, không chạy RAGAS/retrieval benchmark, không chạy ingest ghi PG/Qdrant, không sử dụng VM/S3/CD. Đây là phép thử **CPU contention trên host chia sẻ**, chưa phải nghiệm thu VM2 8 GiB hoặc 6 GiB độc lập.

## Phương pháp

- Embed `sict-embed:latest` (digest `sha256:5f831f19f3eb5a3bb51ccc0dea5b3051f0f09aac480164274d6eccd4265fff7c`), ghim CPU `0,1`, memory limit `6000m`; cấu hình `EMBED_CONCURRENCY=1`, `EMBED_TEXT_MAX_LEN=2048`, `EMBED_TOKEN_BUDGET=2048`, `EMBED_IMAGE_BATCH=1`.
- Mỗi tình huống chạy 24 request HTTP `/v1/embeddings`, 4 câu chữ ngắn luân phiên, 1024 chiều, tuần tự hoặc tối đa 2 đồng thời. Độ trễ đo đầu-cuối ở client; p50/p95 tính nearest-rank. Lấy mẫu `memory.current`, `cpu.stat` cgroup mỗi ~120 ms.
- Worker tổng hợp chạy tách biệt trong container `sict-worker:torchless-test`, `--network none`, CPU `0,1`, quota `0.7 CPU`, RAM limit `768m` và swap cùng giới hạn; cấp phát 128 MiB rồi tính toán/nhường CPU theo chu kỳ. Container được xóa sau khi đo. Worker này **không thực hiện incremental ingest thật**.
- Host có ~15 GiB RAM, nhiều container khác dùng chung, RAM khả dụng thấp khoảng 1,1–1,3 GiB, swap 2 GiB đã đầy. Mọi số liệu chỉ đại diện cho tải cụ thể tại thời điểm thử.

## Kết quả embedding warm

| Tình huống | Thành công | p50 | p95 | Embed RAM cao nhất lấy mẫu | Worker RAM cao nhất lấy mẫu | Embed CPU trung bình |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A1 — rảnh, tuần tự | 24/24 | **236,72 ms** | **289,96 ms** | 1.921,1 MiB | — | 1,97 CPU |
| A2 — rảnh, 2 đồng thời | 24/24 | **384,35 ms** | **515,19 ms** | 1.921,3 MiB | — | 1,97 CPU |
| B — worker tổng hợp, tuần tự | 24/24 | **283,47 ms** | **341,29 ms** | 1.921,2 MiB | 143,9 MiB | 1,53 CPU |
| C — worker tổng hợp, 2 đồng thời | 24/24 | **551,84 ms** | **636,16 ms** | 1.921,2 MiB | 136,4 MiB | 1,54 CPU |

Chênh lệch p95 A2 → C khoảng **+121 ms** khi có tải nền. Có 41–57 mẫu tài nguyên/tình huống. Lượt thử trước cũng đạt 24/24 mỗi tình huống, có p95 tương ứng **290,23 / 494,15 / 427,79 / 799,52 ms**; bộ đọc CPU/RAM của lượt đó lỗi parse `cpu.stat`, nên bỏ mẫu tài nguyên và chạy lại. Chênh lệch giữa các lượt thể hiện nhiễu tải trên máy dev chia sẻ.

Sau thử, embed có `RestartCount=0`, `OOMKilled=false` và `memory.events oom=0, oom_kill=0`. Hai worker tổng hợp đều exit 0, `OOMKilled=false`, đã được dọn sạch. Số RAM là mẫu cgroup tại thời điểm đọc, không đảm bảo bắt được đỉnh rất ngắn hoặc đỉnh của 2048 token/ảnh.

## T1/T2 — mô phỏng ngân sách tài nguyên

| Phương án | Ngân sách định nghĩa trong plan | Đối chiếu phép đo | Trạng thái |
| --- | --- | --- | --- |
| **T1, VM2 8 GiB** | Embed `5120m` + cron `768m` + Obscura `150m` = **6.038 MiB**, còn **2.154 MiB** ngoài tổng container limits | Mẫu embed ~1.921 MiB, worker tổng hợp tối đa ~144 MiB, đều dưới giới hạn riêng đề xuất | **Đạt mức tải nhỏ trong mô phỏng; chưa đạt production gate** vì chưa áp limit 5120m trên embed thật hay chạy cron ingest thật. |
| **T2, VM2 6 GiB** | Giữ các limit T1, tổng **6.038/6.144 MiB**, chỉ còn **106 MiB** ngoài tổng container limits | Mẫu ngắn cùng tải C tiêu thụ thấp hơn 6 GiB, song chưa giới hạn RAM tổng toàn VM bằng cgroup | **Chưa đủ bằng chứng hạ máy**; dự phòng theo tổng limit quá nhỏ, chưa có đo workload đỉnh. |

Docker `m` dùng MiB. T1/T2 là **capacity check từ số đo tại chỗ**, không phải benchmark độc lập trên VM 8/6 GiB. Host dev chỉ còn ~1,3 GiB RAM khả dụng và swap đã đầy nên không nhân bản ONNX ~1,9 GiB để cưỡng chế RAM tổng, tránh ảnh hưởng dịch vụ đang chạy. Cần VM dev riêng và thử batch 2048 token, cron ingest thật, OCR manual theo lịch khi được phép.

## Job thật chỉ đọc và giả lập serverless batch

Đã chạy `uv run --no-sync python -m sict_crawler.pipeline.reconcile --dry-run` trên dev. Lượt đầu **14,92 giây**, MaxRSS **151.148 KiB** (~147,6 MiB), exit 0. Đã đếm **2.310 PG docs, 22.646 text points, 6.056 image points**, orphan/mismatch đều 0.

Lượt thứ hai ghim reconcile vào CPU `0,1` bằng `taskset`, đồng thời gửi **24 request embed với 2 requests đồng thời**. Reconcile hoàn tất trong **5,39 giây**, MaxRSS **152.552 KiB** (~149 MiB), exit 0; embed p50 **427,21 ms**, p95 **697,65 ms**, max **804,36 ms**. Thời lượng job dao động do cache/tải host chưa được kiểm soát. Hai lượt đều chỉ đọc. Đây là phép thử batch cục bộ, **chưa đo cold-start cloud, network private, NAT, retry và hóa đơn serverless**.

## Failure/readiness contract

- API từ code nhánh hiện tại qua ASGITransport trả `/readyz` **200 trong 1.148,32 ms** với PG/Redis/Qdrant/embed local sẵn sàng. Thay riêng URL embed bằng cổng loopback đóng trong tiến trình kiểm thử, `/readyz` trả **503 trong 24,83 ms** và `embed=false`, các store còn lại `true`.
- Client embed với budget **1,5 giây** gọi cổng bị từ chối trả `EmbedError` trong **0,181 giây**, 1 attempt. Endpoint giả nhận TCP nhưng treo trả `EmbedError(ReadTimeout)` sau **1,285 giây** với budget **1,2 giây**.
- `uv run --no-sync pytest tests/test_runtime_readiness.py -q` đạt **10 passed, 2 warnings** (FastAPI `on_event` deprecated), bao phủ `/query`, `/chat`, metric lỗi, deadline và mạng Compose. API container local cũ chưa được cập nhật image mới, nên chưa chạy live query/chat từ image nhánh này.

## Kết luận và cổng nghiệm thu còn mở

Đã xác minh độ trễ 1/2 query đồng thời, synthetic CPU contention, batch reconcile read-only, RSS lấy mẫu, OOM/restarts, và readiness/timeout trong code nhánh hiện tại. Chưa thử ingest có ghi, heartbeat cron thật, request 2048 token/ảnh, `/query` p95 và `/chat` TTFT trên image mới, limit T1/T2 thực tế, cold start cloud hay giá EC2. Theo yêu cầu chủ dự án, không chạy lại RAGAS hoặc benchmark retrieval mới.

Giữ VM1 cho API/stateful và VM2 cho embed warm + cron. Giữ `EMBED_CONCURRENCY=1`, `EMBED_TEXT_MAX_LEN=2048`, tách `svc-ocr` khỏi lịch cron/query. **Chưa chốt T1/T2 hoặc chuyển serverless** cho đến khi có phép đo trên VM dev tương đương và owner phê duyệt các hành động VM/cloud.
