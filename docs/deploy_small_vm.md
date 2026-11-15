# Deploy 2 máy nhỏ (2026-11-13) — thay 2 VM EC2 khi AWS bị khóa

Phương án: 1 máy **1 GB** (stores + API + nginx) + 1 máy **512 MB** (worker crawl tăng dần),
embed qua **Jina Cloud**. Sinh ra khi EC2 bị khóa IP/secrets; giữ nguyên kiến trúc compose,
chỉ đổi giới hạn RAM và backend crawler.

## Vai trò 2 máy

| Máy | Gói | Chạy | File |
|---|---|---|---|
| VM1 (1 GB / 20 GB) | Eco Mini | postgres + redis + qdrant + api + nginx | `docker-compose.yml` |
| VM2 (512 MB) | Eco Micro | cron incremental (+ graph ngay sau lượt) | `docker-compose.worker-lite.yml` |
| Media | R2/B2/MinIO | ảnh + file, dùng chung 2 máy qua S3 API | — |

Số đo tham khảo trên dev box: toàn bộ stack rỗi khoảng **660 MiB**; worker
**< 200 MiB ở 99,7%** mẫu của trial 24 ngày; đỉnh 400–969 MiB là cửa sổ rebuild graph
→ tách sang `--graph-only` chạy ngay sau lượt (cùng vòng lặp cron), corpus không đổi thì
skip theo chữ ký `graph:corpus_sig`. Các số này chưa chứng minh graph vừa RAM 512 MB.

## Bước làm theo thứ tự

1. **Swap 2 máy** (sát RAM, bắt buộc):
   ```bash
   sudo bash scripts/vm_swap.sh 2048        # VM1
   sudo bash scripts/vm_swap.sh 1024        # VM2 (đĩa 15 GB thì dùng 1024)
   ```
2. **Docker**: `curl -fsSL https://get.docker.com | sh` trên cả 2 máy.
3. **VM1 — .env**: copy `.env.vm1-small.example` thành `.env`, điền `LLM_API_KEY`,
   `EMBED_API_KEY` (Jina), chạy `scripts/store_auth.sh init-env` để tạo
   `POSTGRES_PASSWORD`/`REDIS_PASSWORD`/`QDRANT_API_KEY` (không tự đặt tay).
4. **VM1 — firewall**: chỉ mở cho IP công khai của VM2: 5432 (pg), 6379 (redis),
   6333+6334 (qdrant); mở 8080 cho mọi người (nginx). Store KHÔNG mở cho thế giới.
   `ufw allow from <IP-VM2> to any port 5432,6379,6333,6334 proto tcp`
5. **Dữ liệu sang VM1**: trên dev box
   `scripts/cutover_v3.sh export` → chép gói sang VM1 → `restore` (xem `docs/deploy_v3.md`).
   Media: `cutover_v3.sh upload-media-store` (cần `CONFIRM_S3_UPLOAD=yes`) hoặc sync
   `_local_store/media` sang bucket dùng chung.
6. **VM2 — .env**: copy `.env.worker-small.example`, điền IP/mật khẩu của VM1 + cùng
   `EMBED_API_KEY`. Chạy `docker compose -f docker-compose.worker-lite.yml up -d`.
7. **CD**: `gh secret set VM1_HOST --body "<host-VM1>"` + `VM1_KEY` (key PEM);
   `VM2_HOST/VM2_KEY` cho máy 512 MB, **nhớ kèm port** nếu SSH đi port-forward
   (`30037`/`30075`) — `cd.yml` cần biến `VM_SSH_PORT` nếu không phải 22.
8. **Kiểm nhận quà**: `scripts/accept_api.py --api http://<IP-VM1>:8080` rồi hỏi thử
   1 câu golden qua `/chat`.

## Rủi ro đã biết (chấp nhận khi chọn máy nhỏ)

- 1 vCPU: `retrieve` p50 ~0,13 s → ước ~0,4–0,6 s; chat p50 16 s (LLM) nên người dùng khó cảm nhận.
- Đỉnh RAM ~950 MiB / 1 GB: 2–3 người hỏi đồng thời → swap, chậm vài giây.
- `httpx` thay Obscura: trang render JS thuần sẽ rỗng → bài đó bị bỏ, hẹn lượt sau.
- Media mới cần bucket dùng chung; nếu chưa có S3 → bài mới có chữ, ảnh 404.

## CD trên máy NAT port-forward

`cd.yml` hiện SSH cổng 22. Máy NAT chỉ mở `30037`/`30075` → thêm biến môi trường
`VM1_SSH_PORT`/`VM2_SSH_PORT` (mặc định 22) vào workflow, hoặc map port 22 trong
`.ssh/config` trên runner. KHÔNG mở store ra ngoài chỉ vì CD — CD chỉ cần SSH + docker.

## Triển khai qua Tailscale (2026-11-15)

- GitHub variables: `DEPLOY_RUNNER=sict-deploy`, `VM_SSH_USER=root`,
  `WORKER_COMPOSE=docker-compose.worker-lite.yml`, `VM1_SSH_PORT=2222`, `VM2_SSH_PORT=2222`.
  Secrets `VM1_HOST`/`VM2_HOST` là IP Tailscale; SSH key tách riêng cho triển khai.
- Runner `sict-dev-tailnet` chạy trên máy dev bằng user service `sict-deploy-runner`;
  chỉ job CD dùng runner này, CI/build vẫn chạy trên GitHub. Máy dev phải bật để CD chạy.
- VM1 đặt `COMPOSE_FILE=docker-compose.yml:docker-compose.small.yml`; API đọc
  `./_local_store` chỉ đọc. Store bind IP Tailscale, không mở cổng store trên IP public.
- VM2 đặt `WORKER_LOCAL_STORE=./_local_store`. Đồng bộ media sang VM1 bằng rsync qua SSH,
  không dùng AWS credentials. `sict-media-sync.timer` gọi `scripts/sync_worker_media.sh`
  mỗi 30 giây với `MEDIA_API_HOST`/`MEDIA_SYNC_KEY` trong `/etc/sict-media-sync.env`.
  Media có độ trễ tối đa một chu kỳ đồng bộ, cộng thời gian truyền file.
- `mem_limit` chỉ chặn RAM container; `memswap_limit` là tổng RAM + swap cho phép.
  Swap phải có thật và LXC phải được host cho phép. Tách tiến trình graph không tự giảm
  lượng RAM mà riêng graph cần. Kiểm OOM và lượt graph thật trước khi nhận chạy ổn.
- Jina phải trả embedding thành công; HTTP 403 `AUTHZ_INSUFFICIENT_BALANCE` là lỗi
  key/số dư, không thể khắc phục bằng tăng RAM hoặc đổi ngưỡng retrieval.

### LXC không có /dev/net/tun

Tailscale userspace nhận SSH được nhưng không tạo route 100.64.0.0/10 cho ứng dụng.
Trên VM2, bốn service `sict-tailnet-{5432,6379,6333,6334}` dùng socat +
`tailscale nc <VM1> <port>`, chỉ listen IP bridge Docker 172.17.0.1.
DSN/Redis/Qdrant của worker trỏ IP bridge đó; các service chuyển tiếp tới store VM1.
SSH từ VM2 sang VM1 dùng `ProxyCommand /usr/bin/tailscale nc %h %p` trong
/root/.ssh/config, kể cả rsync media. Không mở store trên internet công cộng.

SSH triển khai dùng service `sict-deploy-sshd` cổng 2222, chỉ cho key:
VM1 bind IP Tailscale; VM2 userspace bind 127.0.0.1 để netstack chuyển tiếp.
Tailscale SSH cổng 22 vẫn giữ check policy; automation dùng key OpenSSH qua tailnet,
không phụ thuộc phiên xác thực trình duyệt. Media timer đặt `MEDIA_SSH_PORT=2222`.

### CPU không có AVX trên VM1

Qdrant 1.19.1 chính thức biên dịch chung phần SSE với `-march=haswell`; trên Xeon X5650,
`impl_score_dot_sse` gặp SIGILL trong lúc xử lý quantization. `scripts/build_qdrant_sse.sh`
build đúng commit upstream với patch chỉ tách cờ compiler cho SSE và AVX2. Build trên máy dev,
kiểm assembly và restore/query thực tế trước khi dùng. VM1 đặt
`QDRANT_IMAGE=sict-qdrant:1.19.1-sse-compatible` sau khi image được chuyển tới VM.
