# Audit coverage bộ eval hiện tại và đề xuất bộ golden mới ~150 câu cho multimodal retrieval

Ngày: 2026-11-06. Phạm vi: read-only (không sửa code, không chạy test nặng).
Người đọc: chủ dự án. Ngôn ngữ: tiếng Việt (theo convention repo).

## 1. Hiện trạng: 353 câu trên 5 bộ

| Bộ | câu | media_mode | case / kind | style | đầu vào ảnh | output ảnh | RAGAS-able |
|---|---|---|---|---|---|---|---|
| golden_v1 | 70 | none 52, opt 11, req 7 | không có case | không có style | 0 | 7 req | không (không có reference) |
| golden_v2 | 88 | none 80, req 8 | 14 case (fact/person/event/admission/document/list/image/video/latest/multi_hop/no_text/ambiguous/oos/no_answer) | 7 style + 6 cặp variant_of | 0 | 8 req (5 image, 3 video) | có (reference + answerable) |
| media_v1 | 101 | req 53, none 31, opt 17 | image 36, video 15, file 15, opt 16, none 15, oos 4; 11 cặp variant_of | 7 style | 0 | 53 req | có (reference, 1–2 câu) |
| list_v2 | 50 | none (kind=list) | liệt kê, không có case | không có style | 0 | 0 | một phần (expected_items) |
| person_v1 | 44 | none 36, opt 7, req 1 | intent=person, group=lecturer… | không có style | 0 | 1 req | không (không có reference) |
| **Tổng** | **353** | req ~69, opt ~35, none ~249 | — | — | **0** | **~69** | — |

Schema hiện dùng: `id, question, case, style, answerable, media_mode, wants_file, expected_urls,
expected_media_docs, min_media, reference, notes, status, variant_of` (media_v1); golden_v2 thêm
`expected_items`, `reference`; list_v2 dùng `kind, expected_items, source`; person_v1 dùng
`persona, intent, group, expect_any, filters`.

Tiêu chí chấm hiện có (`eval_media.py`, thuần, không phụ thuộc LLM):
`media_mode_acc, wants_file_acc, url_hit, text_mrr@10, required_has_media, media_on_target,
media_precision, none_clean, file_hit, video_hit, abstain_ok, false_abstain` + bảng theo case/style
và danh sách failures. golden chấm bằng `eval_api.py` (recall@5, MRR@10, url_hit);
list chấm coverage `expected_items`; RAGAS chấm `collect→score` (faithfulness, answer_relevancy,
context_precision, context_recall) trên `reference`.

## 2. Ma trận input × output (AC-U1..U11) và khoảng trống

Code quyết định (đã đọc): `retriever.retrieve` (route.inputs/outputs, `extra=[("i2t", ivec)]`,
`ivec` → `_linked_doc_hits` via `i2i-doc`, `via=i2i` miễn coupled, `via` khác: text/clip/caption/
caption_kw/graph/i2t/i2i-doc/neighbor/latest), `router.classify_rules/decide/gate/passes`
(req/opt/none + wants_file + ngưỡng cặp `t2i/t2c/i2i/i2t_min`), `sources.text_sources/media_sources`
(via, media_key, parent_url, page, cite, heading_path), `citations` (D24).

| Output ↓ / Input → | text only (đã có) | image only, question rỗng (U3/U4/U8) | text + image (U5/U6/U7) |
|---|---|---|---|
| text only (U1) | ✅ đủ (golden_v1/v2, list_v2, person_v1) | ❌ **trống**: ảnh chụp sự kiện / bảng thông báo / ảnh người → hỏi "đây là gì / ở đâu / khi nào" | ❌ **trống**: "ảnh này là sự kiện gì + xác nhận bằng chữ" |
| image only (U2/U3) | ✅ có 53 câu req (media_v1 image/video) nhưng **toàn là chữ → ảnh cùng không gian** | ❌ **trống hoàn toàn**: `image` trong QueryIn chưa có câu eval nào dùng tới | ❌ **trống**: ảnh upload + "cho xem thêm ảnh cùng sự kiện" |
| text + image (U6/U7) | ⚠️ mỏng: chỉ đo qua `media_on_target` trên nguồn `/query`, không chấm "ảnh minh họa đúng chỗ trong câu trả lời" | ❌ trống | ❌ trống |
| file (wants_file) | ✅ có 15 câu (media_v1) + 17 câu golden; file_hit 15/15 | ❌ trống: chụp ảnh văn bản/bảng → xin file gốc | ❌ trống |
| video | ✅ có 15 câu nhưng yếu nhất (video_hit 0,667, precision 0,333; xem RESULTS 2026-11-05) | ❌ trống | ❌ trống |
| none_clean (không trả media) | ✅ 31 câu none | ❌ trống: gửi ảnh + hỏi fact (VD ảnh khuôn viên + "học phí bao nhiêu") → phải ra chữ, không ảnh | ❌ trống |

## 3. 10 khoảng trống lớn nhất (xếp theo giá trị debug / rủi ro regression)

1. **0 câu dùng `QueryIn.image`.** Cả 353 câu đều text-only; các nhánh `i2i / i2t / i2i-doc`,
   `route.inputs=["image"]`, U8 (question rỗng → required), ảnh hỏng → rỗng — chỉ có test fake
   (`test_multimodal_query.py`), chưa từng đo trên index thật. Đây là lỗ hổng lớn nhất của bộ eval
   so với mục tiêu "input ảnh".
2. **Không có câu "output only image" theo nghĩa debug.** Muốn debug "retrieval ảnh có đúng không"
   cần câu mà đáp án đúng/sai nhìn một phát ra ngay (ảnh đúng bài vs ảnh bài khác). media_v1 đo
   `media_on_target` trên JSON `/query` — tốt cho máy, nhưng người debug vẫn phải mở từng `media_key`.
   Thiếu câu dạng "trong N ảnh trả về, ảnh nào đúng" với `expected_media_keys` (sha256 cụ thể).
3. **Ngưỡng cặp chưa từng bị stress bởi ảnh upload.** `i2i_min / i2t_min` mới chỉ đo bằng test fake;
   ảnh thật (chụp lại màn hình, crop, nén, ảnh chụp bảng tin) có cosine phân bố khác ảnh gốc trong index.
4. **Video là nhóm yếu nhất mà không có câu bổ sung.** video_hit 0,667, precision 0,333; lỗi đã biết:
   bài đúng ngoài top 10 (v002), bài tin không video chen trên bài có video (v003/v004), mất slot video
   vào ảnh (v015), tiếng Anh mất sufficiency (v008/v013). Chưa có câu video + ảnh upload, video + file.
5. **Ngoài phạm vi đòi ảnh vẫn trả 8 ảnh ngẫu nhiên** (x002, x004 — đã ghi nhận 2026-11-05, trái AC-R9).
   Chỉ 2 câu oos+ảnh; cần thêm để khóa regression khi chỉnh `clip_min/caption_min`.
6. **Câu hỏi bằng ảnh + chữ (U5/U6/U7) trống.** VD: gửi ảnh hội trường + hỏi "sự kiện này khi nào,
   cho xem thêm ảnh" — nhánh `extra=[("i2t", ivec)]` + RRF text+image chưa từng được đo.
7. **File qua ảnh (chụp quyết định/bảng điểm → xin file gốc)** trống; router `wants_file` qua ảnh chưa đo.
8. **Câu `none` + ảnh upload** trống: gửi ảnh nhưng hỏi fact thuần chữ → media phải rỗng (`none_clean`
   cho input ảnh). Quan trọng vì `retrieve` tự nâng `none → optional` khi có ảnh (retriever.py).
9. **Thiếu cặp before/after cho ảnh.** `variant_of` hiện chỉ có cho text (11 cặp media_v1, 6 cặp golden_v2,
   toàn biến thể gõ). Cần cặp "cùng nhu cầu, một câu chữ-only vs một câu có ảnh" để đo ảnh giúp hay hại.
10. **Chồng lấn giữa các bộ, tốn quota đo.** golden_v2 đã có 5 image + 3 video; media_v1 lặp lại dạng đó
    ở quy mô lớn; list_v2/person_v1 không có `media_mode` đầy đủ ở mọi dòng. Bộ 150 câu mới nên là
    **một file duy nhất, schema thống nhất**, thay vì bộ thứ 6 chồng lên 5 bộ cũ.

## 4. Đề xuất bộ golden mới ~150 câu: `eval/multimodal_v1.jsonl`

Nguyên tắc: một file, một schema (superset của media_v1 + `image` + `expected_media_keys` +
`expected_route`), chấm bằng `eval_media.py` mở rộng (không viết scorer mới).
Kế thừa tiêu chí hiện có; chỉ thêm 3 tiêu chí mới (mục 5).

Schema mỗi dòng: `id, question, image (đường dẫn file ảnh test, null = text-only),
case, style, answerable, media_mode, wants_file, expected_urls, expected_media_docs,
expected_media_keys (sha256, cho câu image-only debug), min_media, reference,
expected_route {inputs, outputs} (đo route.inputs/outputs của U7/U9), variant_of, notes, status`.

| Nhóm | câu | input | output kỳ vọng | ghi chú |
|---|---|---|---|---|
| T1 text→text giữ nguyên (neo chống regression) | 20 | text | text, mode none | lấy từ golden_v2 case fact/person/document (giữ `reference` để RAGAS chạy tiếp) |
| T2 text→image (mở rộng media_v1.image) | 25 | text | image, mode required | sự kiện/người/cơ sở vật chất; ghi `expected_media_keys` cho ≥ 10 câu để debug only-image |
| T3 text→video | 15 | text | video, mode required | khoét sâu 5 lỗi đã biết (v002–v004, v008, v013, v015) + 10 câu mới (FIT News, tuyển sinh theo ngành) |
| T4 text→file | 15 | text | file, wants_file=true | giữ file_hit; thêm 5 câu "chỉ nêu tên văn bản" (dạng f007/f010/f013 đã biết router trượt) |
| T5 optional / none (khóa gate) | 15 | text | text (+ảnh cho phép) / text only | giữ `media_on_target`, `none_clean`; thêm 4 câu oos đòi ảnh (khóa lỗi x002/x004) |
| I1 image-only → image+text (U3/U4/U8) | 20 | image, question rỗng hoặc "đây là gì/ở đâu" | image + text | ảnh lấy từ chính index (gốc + bản crop/nén/chụp lại); đo `via=i2i`, `i2i-doc`, `i2i_min/i2t_min` thật |
| I2 image + text → text (U5) | 12 | image + câu hỏi chữ | text (ảnh là gợi ý) | VD gửi ảnh hội trường + "sự kiện này trao giải gì"; đo RRF có ảnh có hơn text-only không (cặp variant_of với T1) |
| I3 image + text → image (U6) | 10 | image + "cho xem thêm ảnh" | image | ảnh giống không cần thuộc top bài chữ — đo đúng nhánh miễn coupled |
| I4 image + text → cả hai (U7) | 8 | image + câu hỏi mở | text + image | đo `expected_route {inputs:[text,image], outputs:[text,image]}` |
| S style biến thể (không dấu/typo/chatty/english) | 10 | text | như T2–T4 | phủ lên các nhóm trên, giữ tỉ lệ ~30% như media_v1 (đã chứng minh typo/english là nhóm yếu: text_mrr 0,611/0,131) |
| **Tổng** | **150** | text 90 / image-only 20 / text+image 30 / style phủ chéo 10 | — | — |

Phân bổ input: text-only 90 (60%), image-only 20 (13%), text+image 30 (20%), style phủ chéo 10 (7%).
Phân bổ output: text 47, image 55, video 15, file 15, text+image 8, none/oos 10.

## 5. Tiêu chí chấm: dùng lại + thêm 3 cái

Dùng lại nguyên `eval_media.py` (12 số đo ở mục 1) — chỉ cần scorer đọc thêm trường `image`
(gửi kèm base64 trong `POST /query`) và `expected_route` (so `route.inputs/outputs`).
Thêm 3 tiêu chí mới (viết vào `score_row`, test trong `test_eval_media.py`):

- `image_route_ok`: `route.inputs` chứa "image" khi câu có ảnh (U9).
- `media_key_hit`: ≥ 1 `media_key` trả về nằm trong `expected_media_keys` (debug only-image:
  nhìn một phát biết ảnh nào đúng, không cần mở từng ảnh).
- `variant_lift`: với cặp `variant_of` (câu có ảnh vs câu text-only cùng nhu cầu),
  `url_hit`/`media_on_target` của bản có ảnh không thua bản text (ảnh không được làm hại retrieval chữ).

Ảnh test cho I1–I3: lấy từ `_local_store`/S3 của chính index (đã biết sha256 → ghi sẵn
`expected_media_keys`), gồm: ảnh gốc, bản crop 50%, bản nén mạnh, ảnh chụp màn hình —
4 biến thể × 5 sự kiện = 20 câu I1. Không commit ảnh lớn vào git: để trong `eval/images/`
kèm `.gitignore` ngoại lệ hoặc tải từ store lúc chạy (ghi rõ trong md của bộ).

## 6. Rủi ro và cách kiểm chứng

- **Rủi ro 1: ảnh test rò rỉ vào index** (ảnh upload trùng ảnh corpus làm `i2i` cosine ~1,0 giả).
  Kiểm: cosine bản crop/nén phải < 0,99; ghi `notes` nguồn ảnh; chạy `--only` từng câu mới trước khi chốt.
- **Rủi ro 2: tốn quota LLM khi RAGAS 150 câu.** Kiểm: scorer chính vẫn trên `/query` (không LLM);
  RAGAS chỉ chạy trên ~60 câu có `reference` (T1 + một nửa T2/T3), reuse `collect` đã có.
- **Rủi ro 3: cache Redis làm bẩn so sánh text vs image** (key đã gồm hash ảnh — đã có `_image_tag`,
  nhưng vẫn phải xóa `q:v11:*` giữa các lượt, như convention eval-cache-isolation).
- **Rủi ro 4: bộ mới chồng lấn bộ cũ, gấp đôi công duy trì.** Kiểm: bộ mới là file duy nhất cho
  multimodal; media_v1 giữ nguyên làm baseline, không sửa; sau 2 lượt đo ổn định thì bàn với owner
  có gộp media_v1 vào không (quyết định của owner, không tự gộp).
- **Tiêu chí đạt (gate đề xuất):** `image_route_ok` = 1,0; `media_key_hit` ≥ 0,8 ở I1;
  `variant_lift` không âm; các số đo cũ trên T1–T5 không thấp hơn baseline media_v1/golden_v2
  (so trên cùng index, cache xóa). Theo fix-policy: đo cả 5 bộ cũ khi chỉnh ngưỡng `i2i/i2t_min`.

## 7. Việc tiếp theo (không làm trong task này)

1. Thu thập 20 ảnh test (5 sự kiện × 4 biến thể) + sha256 → `eval/images/` + manifest.
2. Soạn 150 dòng jsonl theo schema mục 4 (owner duyệt mẫu 10 câu trước khi soạn hết).
3. Mở rộng `eval_media.py` (+3 tiêu chí) + test scorer + md mô tả bộ (`eval/multimodal_v1.md`
   theo mẫu `media_v1.md`).
4. Chạy baseline trên API dev, ghi `eval/results/multimodal_v1_<ngày>.json` + mục RESULTS.md.
