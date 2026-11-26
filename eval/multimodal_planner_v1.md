# Multimodal planner v1 — protocol và expected policy

Nguồn yêu cầu `/codex/IMPLE_HLD.md`, `/codex/IMPLE_PLAN.md` và `eval/multimodal_v1.md`. Đây là protocol để đánh giá **candidate planner**. Nhãn của `eval/multimodal_v1.jsonl` vẫn là `draft`, cần review trước khi xem như số liệu nghiệm thu.

## Đơn vị đo

Mỗi mẫu gồm `id`, `question`, `image` (nếu có), `filters` do caller truyền và các nhãn trong golden. Ảnh được đọc từ file và truyền nguyên bytes base64, không chấm một text-only replacement cho câu có ảnh. Ghi SHA-256 dataset, git SHA, collection names và dimension, embedding model, cấu hình router, planner/reranker, prompt/judge, top-k, cache namespace, thời gian chạy.

Bộ hiện tại có 150 câu với 50 input chứa ảnh. Các nhóm T1–T5, I1–I4 và S được mô tả trong `eval/multimodal_v1.md`. Chạy song song bộ `golden_v2`, `list_v2`, `person_v1`, `media_v1` để phát hiện regression, chỉ dùng `person_alias_v1` khi đã có nhãn alias và expected URLs được review.

## Expected mode và media policy

| Kiểu câu hỏi | Expected mode (khi flag tương ứng được bật) | Nhánh tìm kiếm | Media gate |
|---|---|---|---|
| Câu fact/tra cứu text | `text_grounded` | Dense + BM25 + name/scope/graph theo signal | `none` hoặc coupled optional có evidence |
| Liệt kê, so sánh nội dung text | `text_grounded` | Text + multi-leg RRF, diversify theo bài | Không để media làm mất text top-k |
| Yêu cầu trực tiếp ảnh/video | `media_first` | Media image/caption/video độc lập và text bổ trợ | `required`, kiểm provenance/source, video-level dedup |
| Text + ảnh đầu vào | `parallel_multimodal` | Text và media thành hai nhóm riêng, image-to-text nếu backend hỗ trợ | Media evidence gắn nguồn, đúng `inputs`/`outputs` |
| Text yêu cầu cả nội dung và ảnh/video | `parallel_multimodal` | Hai nhóm RRF độc lập | Chặn media không có provenance |
| Không yêu cầu media, ngoài phạm vi | `text_grounded` hoặc `text_only` theo rule | Text truy xuất hoặc abstain | `none_clean` và refusal accuracy |
| Ảnh-only | `parallel_multimodal` | Image-to-image và image-to-text | Trả text/media khi có evidence đủ mạnh |
| Tên viết tắt/tên người trùng | `text_grounded` với additive name legs | Không hard-filter entity ambiguous | Cần citation, không suy diễn identity |
| Event/time/relation/multi-hop | `text_grounded` + graph concept candidate khi phù hợp | Graph chỉ là một retrieval leg | Không khẳng định quan hệ thiếu source edge |

`text_only` trong API planner là mode có thể không chạy leg text hoặc media với input rỗng. Xem đây là trường hợp an toàn để kiểm tra, không tự gán đúng/sai cho câu ảnh-only có `image` hợp lệ. `media_first` và `parallel_multimodal` phụ thuộc `media_first_enabled` và `parallel_multimodal_enabled`; khi flag tắt, ghi rõ mode fallback và chỉ chấm với policy tương ứng.

## Điểm cần kiểm thử kỹ

- Person alias gồm full name, dấu/không dấu, tên rút gọn, unknown và ambiguous. Không thêm hard filter cho alias trùng. Source/entity phải có provenance corpus.
- `mm-t2-01` giữ nguyên như case phát hiện media sai bài. Chấm `media_on_target` và `media_key_hit` theo nhãn, không sửa expected để nâng điểm.
- Video trả nhiều keyframe cùng video chỉ chiếm một slot sau fusion, không cộng trùng RRF vote trong một leg.
- `media_first` phải giữ media caption/OCR/subtitle có URL, media ID và provenance ngay cả khi text search không có tài liệu liên kết. Media cosine-only không đủ thành evidence.
- Graph chỉ dùng concept/entity candidate theo rules D33. Relation graph chưa có edge đủ provenance; không dùng kết quả graph để khẳng định quan hệ người/sự kiện.
- Baseline `planner_mode=baseline` phải giữ route, thứ tự `Source`, `media_mode`, citation và `sufficient` hiện hữu.

## Chỉ số và mẫu số

| Nhóm | Chỉ số | Điều kiện chấm |
|---|---|---|
| Text | Recall@5/10, MRR@10, URL hit | Chỉ câu có expected URL tương ứng |
| Text | List coverage, full coverage | Chỉ câu có nhãn `expected_items` |
| Text | Sufficient/abstain accuracy | Câu có nhãn answerable/out_of_scope |
| Media | `media_mode_acc`, `required_has_media`, `media_on_target`, `none_clean` | Theo loại `media_mode` và nhãn của golden |
| Media | `media_precision`, `media_key_hit`, video/file hit | Chỉ mẫu có media/label áp dụng |
| RAGAS | Faithfulness, Answer Relevancy, Context Precision, Context Recall | Collect `/query` + `/chat`, chấm theo chính sách của từng metric |
| Operation | p50/p95, API errors, latency stage, call/cost | Đo riêng ở mỗi variant, ghi N/A nếu thiếu instrumentation |

So sánh delta **trên cùng ID hợp lệ cho từng metric**. Ghi `paired_scored`, số bị loại và lý do. Với RAGAS, ảnh-only có thể không áp dụng Answer Relevancy/Context Precision/Context Recall theo evaluator hiện tại; chỉ báo denominator thực tế. Không ghép điểm từ run khác index, dataset, model hay judge. Nếu Context Precision hoặc Answer Relevancy dưới 0,91 phải RCA từng case điểm thấp và chạy lại đủ 150 câu sau sửa lỗi.

## Lệnh thực hiện

```bash
uv run python scripts/eval_retrieval_variants.py run \
  --config config.yaml --sets mm=eval/multimodal_v1.jsonl \
  --out-dir /tmp/sict-mm-planner --dry-run

uv run pytest tests/test_retrieval_planner.py tests/test_media_planner_contract.py \
  tests/test_retrieval_regression_contract.py -q
```

Đánh giá toàn bộ dùng runner ở `docs/retrieval_upgrade_rollout.md`. Cần API dev và embedding/index sẵn sàng, collection v2/v3 chọn đúng cấu hình. Full RAGAS dùng `scripts/eval_ragas.py` với cùng LLM judge và 150 input, trong đó gửi ảnh thật. Bản báo cáo phải ghi các câu bị giảm, evidence/retrieval stage và quyết định `HOLD` hoặc `PROMOTE` có căn cứ. Chưa có báo cáo so sánh candidate được xác nhận ở tài liệu này.
