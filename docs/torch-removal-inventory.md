# Kiểm kê loại bỏ PyTorch — runtime v3

Ngày rà soát 2026-11-25. Phạm vi là API, worker, embedding server, CLI production, cấu hình và Docker images. Căn cứ triển khai là `/codex/PLAN_REMOVE_TORCH.md` phương án B. Các ghi chép benchmark v1/v2 và tên trường dữ liệu lịch sử (`hash_v2`) được giữ để truy vết.

## Các điểm chuyển đổi

| Vị trí | Symbol / caller cần kiểm | Xử lý | Trạng thái |
| --- | --- | --- | --- |
| `sict_crawler/service/embedding/embedder.py` | `embed_texts`, `embed_image_bytes`, `embed_text_clip`, `embed_query_image_base64`; API, indexer, retriever, compute gọi | Chuyển embedding sang HTTP gateway, bỏ local model, `_torch_*`, `get_device` | Đã smoke HTTP với embed ONNX dev |
| `sict_crawler/core/config.py`, `config.yaml`, `.env.example` | `EmbeddingConfig`, `QdrantConfig`; API, worker, loader | Chỉ `backend=api`, jina-clip-v2, 1024 chiều, ba collection v3; sai cấu hình fail rõ ràng | Đã sửa, có unit contract |
| `sict_crawler/repository/vector_store.py` | search, upsert, delete; retriever/indexer/loader | Chỉ `sict_text_v3`, `sict_image_v3`, `sict_ocr_v3` | Đã smoke `/query` trên Qdrant dev thật, cần đủ eval |
| `sict_crawler/pipeline/compute.py`, `loader.py`, `reconcile.py` | compute artifact, manifest check, nạp điểm, đối soát | Artifact backend API, fingerprint/model/dimension kiểm trước write; bỏ nhánh v2 | Đã sửa, cần thử artifact v3 |
| `sict_crawler/service/index/indexer.py`, `service/retrieval/query_rewriter.py`, `retriever.py` | `embedder` callers | Giữ chữ ký embedding public, gỡ xử lý v2/Torch | Đã smoke retrieval live, cần đủ eval |
| `scripts/eval_compare.py`, `scripts/eval_retrieval.py`, `scripts/serve_jina_clip.py` | embedding benchmark, client, server entrypoint | Thay gọi model Torch bằng HTTP hoặc ủy quyền cho ONNX embed server | Đã sửa, import test pass; benchmark retrieval còn mở |
| `sict_crawler/service/embedding/embed_server.py`, `Dockerfile.embed` | ONNX model/tower load | Chỉ model Jina-CLIP v2 ONNX INT8 | Build/smoke pass, parity text/image mẫu pass |
| `pyproject.toml`, `uv.lock` | các nhóm dependency api, worker, graph, embed, eval | Xóa torch, sentence-transformers, transformers và nhóm `ml` | `uv lock --check` và build pass |
| `Dockerfile.api`, `Dockerfile.worker`, `docker-compose*.yml` | build/run API và worker | Cài nhóm uv cần thiết và gắn cấu hình gateway/v3 | Build/smoke pass, compose config pass |
| `scripts/cutover_v3.sh`, `docs/deploy_v3.md` | `rollback`, env-check, verify | Chỉ rollback image/index fingerprint v3 tương thích | Đã sửa, unit test mock pass; chưa thử rollback thực |
| `tests/test_device.py`, `tests/test_embedder_api.py`, `tests/test_no_torch_runtime.py`, `tests/test_compose_v3.py` | import guard, config negative, HTTP client, compose | Hợp đồng v3 và kiểm thử phủ định legacy | Full pytest pass |
| `README.md`, `CLAUDE.md`, `docs/deploy_v3.md` | hướng dẫn runtime, deploy, đánh giá | Ghi rõ đường chạy v3, giữ số liệu v2 có ghi nhãn lịch sử | Đã cập nhật runtime v3, cần review khi chốt báo cáo |

## Tham chiếu lịch sử được giữ

- `hash_v2` trong ORM, indexer và incremental là tên cột/hash hiện có. Đổi tên ảnh hưởng tương thích schema.
- `golden_v2`, `list_v2`, `sict_*_v2` trong tài liệu số đo cũ và báo cáo là dữ liệu lịch sử để đối chiếu. Runtime phải từ chối dùng collection v2.
- `torch` trong negative test, ghi chú benchmark và tài liệu lịch sử để kiểm chứng việc loại bỏ dependency.
- `scripts/embed_parity.py` so ONNX v3 với artifact cũ và không yêu cầu cài Torch, nhưng cần endpoint và artifact thật.

## Tiêu chuẩn nghiệm thu

1. `uv lock --check`, full pytest, import khi chặn `torch`/`transformers`, `docker compose config` và shell syntax.
2. Build ba image API, worker, embed trên máy dev; smoke khởi động khi không có Torch.
3. Parity ONNX với artifact/index v3; HTTP acceptance trên PG + Qdrant + embed endpoint dev.
4. Đo golden_v2, list_v2, person_v1, media_v1 và 150 câu `eval/multimodal_v1.jsonl`, truyền ảnh thật, đếm mẫu hợp lệ theo metric và điều tra câu dưới ngưỡng.

Ghi kết quả thực tế vào `_torch_removal_verify/<timestamp>/` tại local. Không chạy VM, CD, cutover production hoặc upload S3 theo nhiệm vụ này.

## Kết quả xác minh local ngày 2026-11-25

- Full unit suite: `602 passed, 5 skipped, 5 warnings`; `uv lock --check`, `uv sync --locked --group dev --group api`, `git diff --check`, `bash -n scripts/cutover_v3.sh`, `docker compose config` (base/worker/GPU) đều pass.
- Đã build ba image `sict-api:torchless-test`, `sict-worker:torchless-test`, `sict-embed:torchless-test`. Import/smoke API, worker, embed server thành công; trong cả ba image, `find_spec` đều không tìm thấy `torch`, `transformers`, `sentence_transformers`.
- Endpoint ONNX dev `127.0.0.1:8090/healthz` trả `ok=true`, model `jina-clip-v2`, quant `w8`. Container API xác minh riêng trên `127.0.0.1:8093` trả `/docs` HTTP 200; `/query` trực tiếp truy vấn PG/Qdrant v3 thu được 12 nguồn text và `sufficient=true` cho câu thử về chương trình đào tạo.
- Parity mẫu ở `_torch_removal_verify/20261125/embed_parity.json`: 5 text, cosine trung bình 0,999, tối thiểu 0,9958; 2 ảnh, cosine 1,0. Chưa có vector câu hỏi tham chiếu để đo top-10 overlap (`n=0`), vì vậy chưa kết luận parity toàn bộ.
- HTTP golden_v2 (78 câu): API mới/cũ đều `Recall@5=0,897`, `Recall@10=0,910`, `MRR@10=0,721`, `media_mode_acc=0,920`, `required_media_on_target=8/8`. Hai kết quả bằng nhau trên cùng dữ liệu local.
- HTTP list_v2 (42 câu liệt kê): API mới/cũ đều `coverage=0,892`, `full_coverage=36`, `sufficient_acc=0,900`.
- HTTP person_v1 (40 câu): API mới có `Recall@5=0,975`, `Recall@10=0,975`, `MRR@10=0,921`, `media_mode_acc=0,795`, `required_media_on_target=1/1`. Không có đối chứng API cũ trong lượt này.
- HTTP media_v1 (101 câu): API mới/cũ bằng nhau: `media_mode_acc=0,970`, `wants_file_acc=0,980`, `url_hit=0,990` (96/97), `text_mrr@10=0,835`, `required_has_media=0,902` (46/51), `media_on_target=0,851` (57/67), `media_precision=0,803`, `video_hit=0,733` (11/15), `false_abstain=0,093`.
- RAGAS đối chứng trước thay đổi (`eval/results/ragas/mm-2026-11-23.summary.json`): 150 câu, `faithfulness=0,787` (145 câu chấm), `answer_relevancy=0,612` (133), `context_precision=0,686` (131), `context_recall=0,585` (111), `url_hit=0,904`. Đây là baseline lịch sử.
- Theo chỉ đạo trực tiếp ngày 2026-11-25, dừng RAGAS mới sau 109/150 câu collect, bỏ chấm RAGAS, `accept_api` và benchmark retrieval bổ sung. Dữ liệu thu thập dở được giữ cục bộ trong `_torch_removal_verify/20261125/`, không đưa vào điểm trung bình hay commit. Kết luận nghiệm thu của đợt gỡ Torch dựa trên unit suite, import/container smoke, parity mẫu và các bộ HTTP retrieval đối chứng đã chạy. Không có số RAGAS sau thay đổi, nên chưa kết luận chất lượng câu trả lời tăng/giảm.
