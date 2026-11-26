# Cost matrix VM-SERVE 2 GiB / VM-EMBED 4 GiB

Ngày lập 2026-11-26. Chưa có loại EC2, EBS thực tế và giờ sử dụng xác nhận từ AWS. Dữ liệu AWS region/instance type phải lấy từ AWS Pricing Calculator hoặc Cost Explorer tại thời điểm quyết định, nên không điền giá giả định và chưa kết luận phần trăm tiết kiệm. Tham chiếu lịch sử: `docs/vm-cost-matrix-new-runtime.md`.

| Phương án | Compute thường trực | Batch | Mức limit container tham khảo | Trạng thái |
| --- | --- | --- | --- | --- |
| Cũ 4 GiB + 8 GiB | VM1 2 vCPU/4 GiB; VM2 2 vCPU/8 GiB | cron + Obscura chung VM2 | cấu hình cũ từ baseline lịch sử | chỉ để so sánh |
| Mới 2 GiB + 4 GiB | VM-SERVE 2 vCPU/2 GiB; VM-EMBED 2 vCPU/4 GiB | không chạy | 1746 MiB + 3500 MiB | chưa live |
| Mới + batch ngoài serving | như trên | dev / thuê giờ / serverless khi nghiệm thu | như trên + batch theo thời lượng | target triển khai |
| Embed managed/cloud | VM-SERVE 2 GiB + endpoint managed | batch ngoài serving | chưa xác định | chỉ xem xét nếu owner yêu cầu benchmark riêng |

## Công thức tính theo tháng

Với máy `i`, đặt `h_i` là số giờ VM chạy, `r_i` là giá USD/giờ đúng instance type/region/OS/tenancy. `g_i` GB EBS và `s_i` giá/GB-tháng, cộng IOPS/throughput ngoài gói. Đặt `public_ip_hours`, `egress_GB`, `inter_AZ_GB`, `NAT_hours`, `NAT_GB`, `logs_ingested_GB`, `logs_retained_GB`, `snapshot_GB` theo hoá đơn.

```text
C_fixed = Σ(h_i × r_i) + Σ(EBS_GB_i × EBS_rate_i) + EBS_IOPS_extra
        + EBS_throughput_extra + public_ip_hours × ipv4_rate
        + egress_GB × egress_rate + inter_AZ_GB × inter_AZ_rate
        + NAT_hours × NAT_rate + NAT_GB × NAT_data_rate
        + logs_ingested_GB × log_ingest_rate + logs_retained_GB × log_storage_rate
        + snapshot_GB × snapshot_rate + taxes

C_batch = Σ(job_runs × retry_multiplier × billable_seconds × resource_rate)
        + batch_storage + batch_network + batch_logs + batch_requests

C_total = C_fixed + C_batch
Savings = C_old_total - C_new_total
```

Ví dụ phục vụ 24/7 dùng `h_i≈730` giờ/tháng. Serverless/Lambda/Fargate có cấu trúc giá khác nhau, cần điền minimum billable duration, vCPU-s/GiB-s và số lần khởi tạo; NAT private subnet có thể làm batch ngắn đắt hơn dự kiến. Kiểm tra region/AZ nhất quán của cổng private `8090` và lưu lượng stores.

## Biểu mẫu cần hoàn thiện từ AWS

| Đầu vào | Phương án cũ | Phương án 2/4 GiB | Nguồn |
| --- | --- | --- | --- |
| EC2 instance types + $/giờ + giờ/tháng | cần điền | cần điền | Billing / AWS Pricing Calculator đúng region |
| EBS GiB, gp3 IOPS và snapshot | cần điền | cần điền | EBS metrics / invoice |
| Public IPv4, egress, inter-AZ, NAT | cần điền | cần điền | VPC/Cost Explorer |
| CloudWatch/Grafana logs, metrics | cần điền | cần điền | usage/cost |
| Batch duration, số lượt, retry, memory | cần điền | cần đo sau tách | job metrics |
| Tổng cost/tháng | chưa đủ dữ liệu | chưa đủ dữ liệu | hóa đơn + công thức |

## Quyết định và stop gate

Chỉ chọn 2/4 GiB khi đồng thời có kết quả hai `/query` đồng thời, SSE `/chat`, query ảnh, `/readyz` 200, đủ ba Qdrant collection v3, không tăng restart/OOM, embedding error 0 trong smoke, và hóa đơn chứng minh chi phí thấp hơn. Nếu Qdrant OOM trên máy 2 GiB hoặc embed OOM trên máy 4 GiB, dừng và đề xuất cấu hình đủ lớn sau owner approval. Phục hồi chỉ dùng v3 image/index có fingerprint phù hợp.
