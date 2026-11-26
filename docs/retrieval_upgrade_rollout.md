# Retrieval upgrade — đánh giá, bật thử và rollback

Áp dụng cho phần triển khai theo `/codex/IMPLE_PLAN.md` và `/codex/IMPLE_HLD.md`.
Các thao tác dưới đây chỉ dùng môi trường dev/local. Việc chạy trên VM, CD, S3 hoặc production phải được chủ dự án cho phép riêng theo `AGENTS.md` và `docs/deploy_v3.md`.

## Trạng thái và điều kiện trước khi đo

- `retrieval.planner_mode: baseline` là mặc định. `shadow` chỉ tính plan; `candidate` mới dispatch theo plan.
- Chưa có `eval/person_alias_v1.jsonl` được review. Không tự tạo nhãn tên người hay lấy dữ liệu cá nhân từ `/DATA/craw-sict-data/review/` đưa vào repo.
- `eval/multimodal_v1.jsonl` là golden RAGAS chính hiện tại, gồm 150 câu (50 câu có ảnh), trạng thái `draft`. Ghi SHA-256 của file và đúng phiên bản trước mỗi lượt đo. `golden_v2`, `list_v2`, `person_v1`, `media_v1` là các bộ bổ sung để khóa regression.
- Bộ RAGAS cũ chỉ có giá trị đối chiếu. Kết quả RAGAS candidate cần thu thập lại từ `/chat` trên cùng golden và cùng judge.
- Chỉ so sánh hai variant cùng git SHA, Qdrant collections, embedding model/dim, dữ liệu, prompt, `top_k` và cấu hình chung. Có thể dùng cùng Qdrant index ở chế độ đọc, giữ nguyên các collection v2/v3 để rollback.

## Các feature flags

Các trường nằm dưới `retrieval` trong YAML. Có thể dùng cấu hình riêng cho dev; tránh sửa `config.yaml` dùng chung khi thử nghiệm.

| Cờ | Baseline | Candidate thăm dò | Tác dụng |
|---|---|---|---|
| `planner_mode` | `baseline` | `candidate` | Chọn pipeline truy xuất |
| `entity_index_enabled` | `false` | `true` sau khi review alias | Bổ sung name phrase/entity linking |
| `entity_alias_path` | `""` | Đường dẫn artifact đã review | Nạp alias từ corpus có provenance |
| `rerank_profile` | `baseline_rrf` | `feature_v1` | Rerank bảo toàn tín hiệu BM25/RRF |
| `media_first_enabled` | `false` | `true` | Tìm media độc lập khi câu hỏi yêu cầu |
| `parallel_multimodal_enabled` | `false` | `true` | Text và media search theo hai nhóm |
| `media_coupled_optional` | `false` | theo ablation | Media gắn bài text cho truy vấn thường |
| `graph_route_on_relation` | `true` | giữ nguyên | Graph concept candidate retrieval |
| `graph_route_on_complexity` | `true` | giữ nguyên | Graph concept candidate retrieval |

Giữ `entity_allow_ner: false`, `entity_allow_llm_fallback: false`. Graph hiện dùng rules/concept D33. Chưa có relation edges đủ provenance để suy luận quan hệ. Không bật cross-encoder cho rollout cho đến khi có model/runtime, chi phí và benchmark riêng.

## Chạy test và kiểm tra bộ dữ liệu

Chạy tại `/DATA/craw-sict`:

```bash
uv run pytest tests/ -q --ignore=tests/smoke_incremental.py
uv run python -m tests.test_safety
uv run python -m tests.test_captions
uv run python -m tests.test_agent
sha256sum eval/multimodal_v1.jsonl
```

Trước ablation, kiểm tra local Postgres/Qdrant có đúng index và kích thước embedding mong muốn. `uv run` ở host cần có backend embedding thực sự hoạt động. Nếu thiếu nhóm ML, dùng image API dev đã có dependency và mount config riêng theo `CLAUDE.md`. Không tự cài thêm dependency hoặc chuyển sang production API.

### Đo baseline/candidate trên `/query`

`scripts/eval_retrieval_variants.py` tạo hai API **tuần tự** trên `127.0.0.1`, mỗi API dùng một cấu hình YAML tạm và namespace cache riêng. Không dọn/xóa Redis cache dùng chung. Ảnh được đọc ở local và gửi base64 thật qua `/query` nhưng không ghi ảnh vào kết quả. `--dry-run` chỉ kiểm tra bộ dữ liệu/config.

```bash
uv run python scripts/eval_retrieval_variants.py run \
  --config config.yaml \
  --sets mm=eval/multimodal_v1.jsonl,old=eval/golden_v2.jsonl,list=eval/list_v2.jsonl,person=eval/person_v1.jsonl,media=eval/media_v1.jsonl \
  --out-dir /tmp/sict-retrieval-upgrade --dry-run

uv run python scripts/eval_retrieval_variants.py run \
  --config config.yaml \
  --sets mm=eval/multimodal_v1.jsonl,old=eval/golden_v2.jsonl,list=eval/list_v2.jsonl,person=eval/person_v1.jsonl,media=eval/media_v1.jsonl \
  --candidate-flags '{"rerank_profile":"feature_v1","media_first_enabled":true,"parallel_multimodal_enabled":true}' \
  --out-dir /tmp/sict-retrieval-upgrade
```

Đọc `baseline.manifest.json`, `candidate.manifest.json`, `paired.json`, `paired.md`, `*.rows.jsonl` và `*.server.log` trong thư mục output. `compare` chỉ tổng hợp lại hai bản ghi đã có:

```bash
uv run python scripts/eval_retrieval_variants.py compare --out-dir /tmp/sict-retrieval-upgrade
```

`paired` đếm câu thành công ở **cả hai** variant. Mỗi metric có `paired_scored` riêng, chỉ lấy các câu có điểm ở cả hai phía. Các mẫu không có nhãn/điểm hoặc request lỗi phải báo số lượng và nguyên nhân; không gán điểm 0 và không suy ra delta từ hai mẫu số khác nhau. `answer` và token/cost là N/A ở `/query`.

## RAGAS trên `/chat`

Thu thập riêng baseline và candidate qua **API dev đã cấu hình** tương ứng. Giữ nguyên dataset, judge/provider/model, `top_k`, RPM và độ dài generation. Đảm bảo không dùng cache câu trả lời của variant khác. Mỗi `--out` phải khác nhau; không dùng chung bộ câu trả lời đã collect từ commit trước.

```bash
uv run --group eval python scripts/eval_ragas.py collect \
  --sets mm=eval/multimodal_v1.jsonl --api http://127.0.0.1:8003 \
  --out /tmp/sict-ragas-baseline --top-k 5

uv run --group eval python scripts/eval_ragas.py score \
  --sets mm=eval/multimodal_v1.jsonl --out /tmp/sict-ragas-baseline --rpm 15
```

Lặp lại với API candidate và prefix `/tmp/sict-ragas-candidate`. Kiểm tra 150/150 câu collect, 50/50 ảnh được gửi ở cả hai lần. Báo cho từng metric `scored`, `excluded`, phân loại `missing_input`, `judge_error`, `not_applicable`, `missing_reference`, `collect_error` khi có bằng chứng. Ảnh-only có chính sách áp dụng metric đặc thù trong `scripts/eval_ragas.py`; không chia trung bình trên 150 câu khi metric chỉ chấm được ít hơn.

Nếu Context Precision < 0,91 hoặc Answer Relevancy < 0,91, làm RCA theo từng case điểm thấp. Kiểm tra ảnh/input → embedding → dense/BM25/graph/rerank → thứ tự context và citation → OCR/caption/subtitle → prompt → answer → judge. Cần kiểm tra cả các câu giảm điểm, sau đó đo lại **toàn bộ** golden mới nhất trước khi kết luận cải thiện.

## Ngưỡng đưa ra quyết định

- Chỉ nghiệm thu khi các metric bắt buộc đạt ngưỡng owner, các metric cũ không regression vượt mức đã duyệt, false-positive media và `none_clean` không xấu đi, và p50/p95/chi phí nằm trong ngân sách.
- So sánh Recall@5/10, MRR, list coverage, sufficient accuracy, URL hit, `required_has_media`, `media_precision`, `media_on_target`, `none_clean`, video/file hits, RAGAS và latency. Nếu chưa đo được, ghi `N/A` cùng lý do.
- Một câu đúng hơn không đủ để bật flag. Bản candidate phải có báo cáo từng tập và từng câu bị tụt.
- Nếu chỉ có bộ `draft` hoặc thiếu alias reviewed, ghi `HOLD`, không tuyên bố đạt production.

## Rollback và xác minh

Trên cấu hình **dev/canary** đang thử, chuyển `retrieval.planner_mode` về `baseline`. Tắt `entity_index_enabled`, `media_first_enabled`, `parallel_multimodal_enabled` và đặt `rerank_profile: baseline_rrf`; khởi động lại API dev để nạp settings. Kiểm tra `/query`, `/chat`, citation/route contract rồi chạy các bộ baseline. Rollback này dùng index và schema hiện hữu, không yêu cầu đổi collection hoặc xóa cache Redis toàn cục.

Production rollout/cutover cần quyết định riêng của chủ dự án sau khi báo cáo đầy đủ. Không thực hiện S3 upload, VM commands, CD, reindex hoặc chỉnh sửa production trong quá trình benchmark local.
