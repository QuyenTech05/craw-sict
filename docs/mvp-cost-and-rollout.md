# Chi phí và rollout demo Vercel

Kiến trúc mục tiêu gồm VM-SERVE 2 vCPU/2 GiB 24/7, VM-EMBED 2 vCPU/4 GiB 24/7, OCR Function theo request và Sandbox theo backlog. Đơn giá cần lấy theo region, plan và hóa đơn thực tế ở thời điểm deploy. Hiện **chưa có hóa đơn Vercel/AWS hoặc benchmark trên VM đích** để khẳng định chi phí tiết kiệm.

## Công thức ước tính

| Thành phần | Cách tính theo usage đo được |
| --- | --- |
| VM-SERVE | `giờ chạy × giá VM/giờ` cộng EBS, IPv4, outbound, snapshot, log/monitoring |
| VM-EMBED | `giờ chạy × giá VM/giờ` cộng disk model, IPv4, outbound, log |
| Vercel OCR Function | `số invocations × mức tính theo request` cộng thời gian chạy và memory/CPU theo cơ chế billing của plan, network |
| Vercel Sandbox | `số phiên × phút sử dụng × đơn giá resource của plan` cộng lưu trữ/transfer nếu có |
| Batch worker VM 24/7 | `~730 giờ/tháng × giá instance` cộng disk/network |

Lập bảng tháng theo số ảnh OCR, % fallback, cold start, tổng số phút Sandbox, số lần retry, số GB artifact, outbound và dung lượng log. Chỉ so sánh worker VM với Sandbox khi cùng workload và cùng khối lượng đầu ra đã kiểm tra. Các chỉ tiêu resource từ `docs/vm-cost-matrix-new-runtime.md` là baseline local, chưa phải kết quả chạy 2 GiB/4 GiB.

## Trình tự rollout có điều kiện

1. Sau khi chủ dự án duyệt VM/CD riêng, cấu hình volumes và datastore của VM-SERVE; xác minh readiness trước khi bật public nginx HTTPS.
2. Khởi động VM-EMBED với model ONNX INT8 đã chuẩn bị và `EMBED_CONCURRENCY=1`, kiểm tra chiều vector 1024 và endpoint health/embedding.
3. Xác minh `/query`, `/chat` và image retrieval sử dụng index `*_v3`; không bật OCR khi chưa có kết quả baseline.
4. Cấu hình Vercel Project từ thư mục `vercel/`, set `MVP_OCR_TOKEN`, `MVP_JOB_TOKEN`, `SICT_API_BASE`, `OCR_IMAGE_HOSTS` (nếu dùng image_url) và `TESSDATA_URL` (nếu dùng mirror). Thử `/api/ocr`, `/api/ocr-batch` và job proxy, sau đó mới đặt `MVP_OCR_POLICY=weak` ở VM API.
5. Với backlog thật, tạo job và upload manifest/input trước, cấu hình SDK, `SICT_GIT_URL` allowlist, `SICT_GIT_REF` SHA bất biến và `SICT_SANDBOX_IMAGE` đã chuẩn bị trên VCR, rồi khởi chạy `vercel/launch-sandbox.mjs`. Dùng snapshot/compute nhỏ, video hoặc OCR có kiểm soát; kiểm chứng resume và SHA256.
6. Ghi latency, OOM/restart, timeout, số case eligible và chi phí usage; đối chiếu `docs/mvp-evaluation-report.md` trước khi tăng traffic.

## Dừng và khôi phục demo

Khi Function/Sandbox quá hạn hoặc tốn phí vượt budget, ngừng trigger từ operator, đặt `MVP_OCR_POLICY=off`, dừng tạo job mới. API vẫn chạy với embedding/index v3 hiện có. Thu hồi hoặc rotate `MVP_OCR_TOKEN` và `MVP_JOB_TOKEN` nếu credential lộ; giữ volume job để truy vết và chỉ dọn các job đã kết thúc theo TTL. Không tự sửa collection live, chạy loader, VM command, S3 hoặc cutover nếu chưa có authorization riêng.

Hiện chưa có rollout hay deploy nào thực hiện theo tài liệu này.
