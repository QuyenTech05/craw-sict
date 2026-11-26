# Báo cáo acceptance VM-SERVE 2 GiB / VM-EMBED 4 GiB

Ngày 2026-11-26. **Chưa nghiệm thu trên phần cứng đích** vì chưa có owner approval để tác động VM, CD, S3 hoặc cutover. Không coi kết quả pytest và snapshot dev là pass production.

## Ma trận đo

| Phép thử | Kết quả trên VM 2/4 GiB | Tiêu chí |
| --- | --- | --- |
| PostgreSQL / Redis auth / Qdrant 3 collection v3 | Chưa chạy | mỗi store ready và đúng fingerprint |
| `GET /readyz` sau khi embed warm | Chưa chạy | HTTP 200, latency ghi thực tế |
| `/query` text đơn và hai request đồng thời | Chưa chạy | hai request hoàn tất; ghi p50/p95/errors |
| `/chat` SSE | Chưa chạy | sự kiện hợp lệ, `[DONE]`, TTFT và lỗi được ghi |
| `/query` với ảnh, image tower 336 | Chưa chạy | hoàn tất, không OOM, nguồn ảnh hợp lệ |
| Embed input 1024/1536/2048 token | Chưa chạy | ghi truncation, RSS peak, không lỗi |
| Ngắt/tạo timeout endpoint embedding trên môi trường dev | Chưa chạy trong vòng này | `/readyz` chuyển 503, lỗi query có thời hạn, phục hồi được |
| Cgroup memory / RSS peak / OOM / restart cả 2 VM | Chưa chạy | OOM 0, restart không tăng |
| Qdrant latency trong giờ query | Chưa chạy | ghi p50/p95, không optimizer/rebuild đồng thời |
| Chi phí tháng compute/EBS/network/IPv4/log | Chưa có đơn giá thực | chi phí giảm và có số liệu kiểm chứng |

## Nghiệm thu offline

Chạy `uv run pytest tests/test_placement_2gb_4gb.py tests/test_compose_2gb_4gb.py tests/test_embed_4gb_contract.py tests/test_runtime_readiness.py -q`, `uv run pytest tests/test_embed_server.py -q`, `docker compose config`, `docker compose -f docker-compose.embed.yml config`, và full pytest. Kết quả lệnh thực tế cần ghi theo lần chạy. Kiểm tra `git diff --check` trước chuyển giao.

## Các gate chưa được chấp nhận

Không thực hiện trên VM cho đến khi được duyệt riêng. Khi được duyệt, cố định image SHA, manifest/fingerprint v3, cgroup RAM thực tế, và đo ít nhất 24 yêu cầu embedding theo baseline A1 một user và A2 hai user, tách chữ/ảnh. Theo dõi memory peak cgroup, OS page cache, Qdrant restart và LLM SSE. Ghi số mẫu thành công/thất bại cùng lý do, không suy ra p95 từ snapshot ngắn.

Giới hạn `EMBED_TEXT_MAX_LEN` giảm từ 2048 xuống 1536 có thể cắt ngắn chunk dài. Phép đối chứng retrieval/API cũ đã được chủ dự án xác nhận trước đó, nhưng **chưa xác nhận quality parity của cấu hình 1536 mới**. Theo yêu cầu gần nhất, vòng này không chạy thêm RAGAS hay retrieval benchmark. Gate chất lượng cần được owner quyết định trước production cutover.
