# Ma trận tài nguyên và chi phí — v3 API-only

Nguồn quyết định là `/codex/PLAN_VM_SERVERLESS_NEW_RUNTIME.md` và `plan.md` D32. Các giá cloud phụ thuộc region, loại máy, tenancy, OS, thời điểm và số giờ sử dụng, cần lấy từ AWS Pricing Calculator và hoá đơn tại lúc thử. **Không có giá AWS đã xác thực hay số đo VM đích ở vòng này**, nên để ô chi phí dạng công thức và không kết luận tỷ lệ tiết kiệm.

| Phương án | VM1 (2 vCPU/4 GB) | VM2 | Mục đích | Trạng thái |
| --- | --- | --- | --- | --- |
| Baseline hiện tại | PG 600m + Redis 300m + Qdrant 1100m + API 600m + nginx 150m = 2750m | embed 6000m + cron 1024m + Obscura 150m = 7174m | tham chiếu | chỉ xác minh Compose |
| T1 API-only | PG 512m + Redis 192m + Qdrant 1000m + API 600m + nginx 100m = **2404m** | embed 5120m + cron 768m + Obscura 150m = **6038m** | giảm giới hạn container, giữ máy | chưa áp dụng/chưa đo |
| T2 VM2 nhỏ hơn | giống T1 | 2 vCPU/6 GB, chỉ sau T1 pass | giảm compute VM2 | chưa thử |
| Batch serverless | giống T1 | giữ embed warm, chuyển batch được chứng minh | biến thiên theo job | chưa thử |

**Đối chiếu local 2026-11-26:** đã đo 24 HTTP embedding request/biến thể với 1 hoặc 2 đồng thời và worker CPU tổng hợp, p95 **289,96–636,16 ms**, embed RAM cao nhất lấy mẫu ~**1.921 MiB**, worker giả lập ~**144 MiB**, không OOM/restart. Trên corpus dev, `reconcile --dry-run` hoàn tất **14,92 giây**, MaxRSS **~148 MiB**. Bảng này vẫn giữ trạng thái chưa áp dụng T1/T2 vì server đang chạy `EMBED_MEM_LIMIT=6000m`, chưa ghim RAM tổng VM 8/6 GiB hay chạy cron incremental thật. Với T2 6 GiB, tổng limit T1 là **6038 MiB** nên chỉ còn **106 MiB** ngoài tổng limit cho OS/Docker. Chi tiết tại `docs/vm2-contention-report.md`.

T1 API `600m` theo tài liệu kế hoạch mới. `/codex/PLAN.md` từng ghi `API 400m`; chọn `600m` trong thí nghiệm để giữ biên an toàn ban đầu, chưa đổi default Compose. Với VM1 4 GB, tổng giới hạn T1 còn chỗ cho OS, cache, docker và Alloy; không giảm VM1 dưới 4 GB trong gate production.

## Công thức hóa đơn hàng tháng

Đặt `h1`, `h2` là giờ chạy VM1/VM2 mỗi tháng (24/7 khoảng 730 giờ); `r1`, `r2` là USD/giờ theo đúng EC2 type/region; `g1`, `g2` là GB EBS; `s` là USD/GB-tháng; `e` là GB outbound có tính phí; `re` là USD/GB; `p` là giờ public IPv4 tính phí; `rp` là USD/IP-giờ; `l` là log/metrics GB và `rl` là giá ingestion/storage tương ứng.

`C_month = h1*r1 + h2*r2 + (g1+g2)*s + e*re + p*rp + l*rl + NAT_fixed + NAT_GB + backup/snapshot + taxes`.

Tính `min/max` theo 28–31 ngày, on-demand vs Savings Plans hợp lệ, lượng outbound và log thực đo. EBS gp3 phải cộng dung lượng và IOPS/throughput phát sinh nếu cấu hình vượt mức gộp. Tính snapshot retention và NAT gateway nếu serverless private VPC sử dụng. Cổng 8090/5432/6379/6333/6334 qua private VPC cần rà data transfer theo AZ, hạn chế giao tiếp khác AZ nếu không cần thiết. Elastic/public IPv4 tính riêng ngay cả khi Elastic IP đã gắn. VM vẫn phát sinh phí khi bật nhưng rỗi.

## Gate T1/T2

Từng phương án phải có hai truy vấn đồng thời, `/chat` SSE trả đủ event và TTFT p50/p95, `/query` p50/p95, CPU/RSS peak/`OOMKilled`/restart, heartbeat cron, `/readyz` 200 khi dependency sẵn sàng và lỗi 503 đúng hạn khi embed down. So sánh kết quả trả về của API cũ với API mới trên các bộ đối chứng **đã được chủ dự án xác nhận**; không chạy RAGAS/benchmark retrieval mới. T2 chỉ được đánh giá khi T1 qua hết gate và đã có giá tháng thực của hai loại EC2. Giảm compute VM yêu cầu owner duyệt riêng.
