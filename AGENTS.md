# AGENTS.md

Multi-modal RAG crawler for `https://sict.haui.edu.vn/vn` (crawl → PG + Qdrant + S3 → RAG API + chat UI).

**Read `CLAUDE.md` first** — it is the detailed, maintained architecture/rules doc. `plan.md` holds
owner decisions (through D33) and is the source of truth when docs and code disagree. Code comments, docs and
commit messages are mostly Vietnamese; keep that convention.

Repository GitHub hiện tại: `https://github.com/quyentech05/craw-sict`.
Plan Vercel/Sandbox đang triển khai: `/codex/PLAN_VM_SERVERLESS_NEW_RUNTIME.md`.
Owner tạm dừng đo RAGAS và benchmark retrieval mới sau khi xác nhận đối chứng parity; chỉ chạy lại khi có chỉ thị.

## Hard rules (do not violate)

- **Giới hạn tài liệu agent:** giữ mỗi tệp `AGENTS.md` / `AGENT.md` không quá 190 dòng; khi sửa,
  kiểm tra số dòng và chuyển nội dung chi tiết sang tài liệu liên kết nếu cần.
- **RAGAS golden dataset (owner, 2026-11-21):** luôn dùng bộ golden mới nhất được chủ chỉ định để đo
  RAGAS. Hiện tại là `eval/multimodal_v1.jsonl` (150 câu, gồm input ảnh + chữ; trạng thái draft).
  Truyền ảnh đầu vào thật khi collect; báo số mẫu và lý do không chấm được từng chỉ số, không gộp
  các mẫu bị loại vào điểm trung bình. Các bộ cũ chỉ chạy bổ sung để đối chiếu, không thay bộ mới
  trong kết quả RAGAS chính; nếu bộ mới thay đổi, xác nhận phiên bản và ghi rõ trong báo cáo.
- **RAGAS dưới ngưỡng phải truy vết nguyên nhân:** nếu Context Precision < 0,91, Answer Relevancy < 0,91
  hoặc chỉ số nghiệm thu khác chưa đạt, phân tích từng câu bị điểm thấp và kiểm tra lần lượt input/ảnh,
  embedding, retrieval (dense/BM25/rerank), nguồn và thứ tự context, OCR/media, prompt, câu trả lời LLM
  và lỗi/giới hạn của giám khảo. Ghi bằng chứng, nguyên nhân gốc, số câu ảnh hưởng và chỉ số trước/sau;
  chỉ kết luận cải thiện sau khi đo lại toàn bộ golden mới nhất và kiểm tra các chỉ số không bị tụt.
- **S3 / VM freeze (owner, 2026-10-14):** never upload to S3 and never run anything on the VMs
  (CD workflow, `scripts/cutover_v3.sh` VM steps, `loader --upload-media`) unless the owner explicitly
  says so. `upload-media` also requires `CONFIRM_S3_UPLOAD=yes`. Local runs use the local store (no AWS env).
- **uv only.** Never use `pip` and never add `requirements.txt`. Deps live in `pyproject.toml`
  groups `dev` (pytest), `api` (FastAPI + HTTP client), `worker` (OCR/video/CDP),
  `graph` (concept extraction), `embed` (ONNX Runtime INT8), `eval` (RAGAS).
- **Never run `playwright install`** — playwright is a CDP client for the Obscura sidecar only.
- **Graph is rules-only.** LLM entity extraction (`graph_llm.py`) was removed 2026-10-18; do not reintroduce.
- No linter/formatter/typechecker is configured. CI only runs pytest. Do not assume `ruff`/`mypy` commands exist.
- Never commit secrets (`.env`, `cookies/*.txt`, `*.pem`) or data dirs (`.pgdata*`, `_snapshot/`, `_local_store/`, `.hf-cache/`).
- **Never commit without the owner saying so.** Do not revert/stash uncommitted user changes.
  Commit/push only to the branch authorized by the owner; no production deployment without separate approval.
- Never copy review data into the repo: `/DATA/craw-sict-data/review/` (entity review CSV) is deliberately outside the
  repo because it contains student names (PII). The rules graph (catalog, review loop) was removed on 2026-11-03 (D33).

## Runtime v3-only — loại bỏ Torch (2026-11-25)

- API và worker dùng duy nhất `EMBED_BACKEND=api` và HTTP `EMBED_API_BASE` gọi Jina-CLIP v2
  ONNX Runtime INT8 (`embed_server.py`). Không dùng `torch`, `transformers`, `sentence-transformers`
  hay nhánh fallback embedding v2; giữ API chữ ký `embed_texts`/`embed_image_bytes`.
- Runtime/loader chỉ chấp nhận `sict_text_v3`, `sict_image_v3`, `sict_ocr_v3`, embedding 1024 chiều,
  manifest model/backend/dimension/prefix phù hợp. Các collection cũ được giữ nguyên tại dev để đối chiếu,
  không được dùng làm rollback bằng cấu hình. Rollback chỉ đổi API image v3 khi fingerprint index v3 khớp.
- `EMBED_API_BASE/KEY/MODEL/DIM/CACHE_PATH/WORKERS/TPM/IMAGE_BATCH` cấu hình HTTP gateway;
  vector cache bằng sqlite theo hash input. Dịch vụ embed chạy riêng trong image `Dockerfile.embed`.
- **Không chạy full compute/embedding** nếu chủ dự án chưa cho phép. Dùng `scripts/embed_pilot.py`
  để thử và ước lượng trước; không chạy VM, CD hay upload S3 theo nguyên tắc freeze ở trên.
- Router thresholds `t2i_min`/`t2c_min`/`i2i_min`/`i2t_min` (`config.py`, D21) còn cần hiệu chỉnh
  theo golden. Xem tiến độ và bằng chứng ở `docs/torch-removal-inventory.md`, kế hoạch `/codex/PLAN_REMOVE_TORCH.md`.

## Commands

```bash
uv sync --locked --group dev --group api          # worker: --group worker --group graph; embed: --group embed
docker compose up -d postgres redis qdrant        # local infra
uv run uvicorn sict_crawler.api.routes:app --port 8000   # API + chat UI at /
uv run pytest tests/ -q --ignore=tests/smoke_incremental.py   # same as CI
uv run pytest tests/test_safety.py::test_mass_delete_guard                 # single test
uv run python -m tests.test_safety   # 3 tests also run as scripts in CI (also test_captions, test_agent)
```

Pipeline CLI (`python -m sict_crawler.pipeline.main`, one mode per invocation): `--crawl-limit N`, `--full`,
`--incremental --check-edits N --crawl-limit N --annotate-ocr-n N`, `--refresh`, `--reset`.

Bulk (re)index path: `snapshot --out _snapshot/<date>` → `compute --snapshot S [--stages ...]` →
`loader --artifacts S/artifacts/v3-jina-clip-v2`. Also `reconcile [--dry-run]` and
`graphsync rebuild|sync-payloads|stats`.

## Gotchas an agent will miss

- `.venv` với group `api` không nạp model local. Live eval/smoke cần PG, Qdrant v3 và embed server
  ONNX chạy được qua HTTP; có thể dùng image `sict-api`/`sict-worker` cùng endpoint embed riêng.
- `smoke_incremental.py` excluded from CI, cần PG + Qdrant `*_v3` và **có ghi dữ liệu** — dev only.
- Config loads `config.yaml` (override with `SICT_CONFIG`); env vars override yaml on deploy.
  Backend embedding bắt buộc `api`; sai backend/model/dimension/collection phải fail rõ ràng.
- `loader.check` kiểm backend/model/dim/prefix theo artifact manifest. Only HTTP 404/410 deletes a doc,
  mass-delete guard aborts past thresholds. `--rechunk`, `--videos-backfill`, `--annotate-ocr` là v1 legacy CLI.
- Eval `eval/multimodal_v1.jsonl` 150 câu là bộ RAGAS chính; đo retrieval qua HTTP với
  `eval_api.py` (golden_v2, list_v2, person_v1), `eval_media.py`, `accept_api.py`.
  Benchmark `scripts/eval_compare.py` gọi HTTP Jina thay cho model Torch.
- Point ids are deterministic uuid5, so re-index/loader overwrite instead of duplicating.
- Schema changes go through `db.init_db()` `create_all` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
  (no Alembic yet); add new columns there.
- `test_behavior_contract.py` / `test_retrieval_response_contract.py` are spec tests derived from
  `tests/acceptance_*.md` (stdlib `unittest`); they encode policy and do not import the real code.
- Parser changes must ship with real-HTML fixtures in `tests/fixtures/` (`test_parser_theme.py`).

## Architecture map

Ingest: `frontier` (Redis BFS) → `crawler.fetch` (httpx → Obscura → crawl4ai via `CRAWLER_BACKEND`) →
`parser` → `chunker` → `embedder` → `vector_store` + `db`/`models` + `storage`.
`indexer.index_page` is the single v3 write path (idempotent via historical `hash_v2`/`hash_struct`); `incremental.py`
reuses it. Query: `api/routes.py` `/query` + `/chat` (SSE) → `agent.run` → `retriever.retrieve` (câu gốc + câu viết lại → RRF dense+BM25 → đa dạng bài
→ `sufficient` bằng luật, D27 → answer), `router.py` media intent, `filters.py` metadata, `graph.py`/`graphsync.py` entity graph
(PG is source of truth). `service/index/doc_rules.py`+`indexing.py` are the shared rule set for bulk and incremental.
Packages by responsibility (imports only point down): `core` → `model` → `repository` → `service/{crawl,index,embedding,retrieval,graph}` → `pipeline` | `api`; tests in top-level `tests/`. Full table in CLAUDE.md "Code layout".
