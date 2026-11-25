# `multimodal_v1.jsonl` — golden dataset multimodal 150 câu

Ngày soạn: 2026-11-07. Bộ này đo retrieval multimodal trên `POST /query` của API dev, không chấm câu trả lời LLM trực tiếp. RAGAS chỉ chạy ở dev; không chạy trên production.

## Mục tiêu

Bộ mới bổ sung những nhánh mà 353 câu cũ chưa đo được:

- Query có ảnh thật trong `QueryIn.image`.
- Ảnh-only → text + image (U3/U4/U8).
- Text + image → text (U5), image (U6), hoặc text + image (U7).
- Ảnh crop/nén/resize để stress `i2i` và `i2t`, không dùng ảnh chụp màn hình mới theo quyết định của chủ dự án.
- Text → image/video/file và các câu none/optional để khóa regression của router.
- `expected_media_keys` chứa prefix SHA-256 của toàn bộ ảnh đúng bài khi có thể, giúp debug một phát biết media trả về có thuộc đúng corpus document hay không.

`mm-t2-01` được giữ nguyên có chủ ý: đây là bug-probe cho lỗi đã biết m001 (media leg trả ảnh từ bài khác). Nếu `media_on_target=false`, đó là tín hiệu cần điều tra, không tự sửa expected.

## Phân bổ

| Nhóm | Số câu | Input | Output / mục tiêu |
|---|---:|---|---|
| T1 | 20 | text | text-only, neo từ `golden_v2` |
| T2 | 25 | text | text → image |
| T3 | 15 | text | text → video |
| T4 | 15 | text | text → file, `wants_file=true` |
| T5 | 15 | text | none / optional / out-of-scope |
| I1 | 20 | image | image-only → image + text |
| I2 | 12 | text + image | text là output chính |
| I3 | 10 | text + image | image là output chính |
| I4 | 8 | text + image | text + image |
| S | 10 | text | style phủ chéo: no-accent, typo, chatty, English, abbrev |
| **Tổng** | **150** | 90 text-only, 20 image-only, 30 text+image, 10 style | — |

Có 50 dòng có trường `image`; 20 file ảnh test vật lý nằm ở `eval/images/` (5 sự kiện × original/crop50/q40/r60). Ảnh không bị commit vào index; chúng là file test lấy từ local corpus và đã smoke-test cosine trước khi soạn bộ.

## Schema mỗi dòng

```text
id, question, image, case, style, answerable, media_mode, wants_file,
expected_urls, expected_media_docs, expected_media_keys, min_media,
reference, expected_route, variant_of, notes, status
```

- `image`: đường dẫn tương đối tới ảnh test hoặc `null`; script gửi base64 không có tiền tố `data:`.
- `expected_urls`: URL bài/file đúng để chấm `url_hit` và text MRR.
- `expected_media_docs`: URL bài mà media trả về phải thuộc về.
- `expected_media_keys`: prefix 12 ký tự đầu SHA-256 của media đúng; chỉ dùng debug/scoring, không thay thế `expected_media_docs`.
- `expected_route`: route mong đợi `{inputs: [...], outputs: [...]}`; hiện dùng cho các dòng multimodal.
- `variant_of`: cặp text/image hoặc style dùng để đo `variant_lift`; các cặp S trỏ tới dòng trong chính file.
- `reference`: câu trả lời tóm tắt từ source, dùng cho collect/score RAGAS ở dev.
- `status`: hiện `draft` cho tới khi owner chốt baseline kết quả.

## Chấm

```bash
# scorer thuần, không LLM; chạy dev
python3 scripts/eval_media.py \
  --api http://localhost:8003 \
  --set eval/multimodal_v1.jsonl \
  --out eval/results/multimodal_v1_2026-11-07.json

# một nhóm / một câu khi debug
python3 scripts/eval_media.py --api http://localhost:8003 \
  --set eval/multimodal_v1.jsonl --only mm-i1-01,mm-t2-01
```

Scorer kế thừa các tiêu chí của `media_v1` và thêm:

| Tiêu chí | Ý nghĩa |
|---|---|
| `image_route_ok` | Dòng có ảnh phải có `"image"` trong response `inputs`. |
| `media_key_hit` | Ít nhất một `media_key` trả về khớp `expected_media_keys`; dùng để debug I1/I3/I4. |
| `variant_lift` | Với `variant_of`, kết quả của biến thể không được kém câu gốc theo `media_on_target` hoặc `url_hit`. |

Các tiêu chí cũ vẫn giữ: `media_mode_acc`, `wants_file_acc`, `url_hit`, `text_mrr@10`, `required_has_media`, `media_on_target`, `media_precision`, `none_clean`, `file_hit`, `video_hit`, `abstain_ok`, `false_abstain`.

## Gate đề xuất

- `image_route_ok = 1.0` trên tất cả dòng có ảnh.
- `media_key_hit ≥ 0.8` trên I1; đọc I3/I4 theo từng bài vì media leg có thể trả ảnh đúng bài nhưng không phải ảnh đại diện.
- `variant_lift` không âm / không giảm so với câu gốc.
- T1–T5 không thấp hơn baseline `golden_v2`/`media_v1` trên cùng index và cùng cache policy.
- `mm-t2-01` được đọc như bug-probe riêng, không dùng để che lỗi bằng cách đổi expected.

## Quy trình kiểm chứng

1. Chạy scorer trên dev; không chạy RAGAS hay bộ này trên production.
2. Xóa cách ly cache `q:v11:*` khi so sánh thay đổi retrieval hoặc text-only với image variant.
3. Với lỗi media, xem cả `parent_url`, `media_key`, `via`, `inputs`, `outputs`; không kết luận chỉ từ URL text.
4. Câu có `reference` có thể đưa vào `eval_ragas.py collect/score` ở dev, giới hạn RPM theo provider.
5. Khi thay đổi ngưỡng `i2i/i2t`, chạy lại các bộ cũ (`golden_v1`, `golden_v2`, `list_v2`, `media_v1`) theo fix-policy.

## Trạng thái smoke test ngày 2026-11-07

- 150 dòng, đúng phân bổ 20/25/15/15/15/20/12/10/8/10.
- 20/20 ảnh vật lý tồn tại và đều được dùng trong file.
- Scorer unit tests: 12 passed.
- Smoke đại diện I1: 11/11 có `image_route_ok`, `url_hit`, `media_on_target`, `required_has_media`, `media_key_hit` đạt.
- `mm-t2-01` vẫn giữ expected bug-probe theo quyết định owner.
- Full 150-row baseline và RAGAS chưa chốt trong tài liệu này; cần chạy dev theo lệnh trên rồi ghi kết quả vào `eval/RESULTS.md`.
