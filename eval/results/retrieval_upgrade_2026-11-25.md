# Đánh giá retrieval upgrade và RAGAS — 25/11/2026

**Quyết định HOLD.** Golden còn ở trạng thái draft và các ngưỡng chất lượng chưa được chứng minh.

Golden `eval/multimodal_v1.jsonl` có 150 ID duy nhất, 50 ảnh đầu vào có file thực (50/50 hiện diện) và 14 câu chỉ có ảnh. SHA-256 `88420ea48c9caa46b82876d6aebd3ce30258e5f238ff5c2daff2ea6d02bc66f6`.

Git HEAD `e2b99ff8991dadeb2937f7c468d64e7e59fc8be9`, working tree có sửa đổi chưa commit. API đánh giá dùng index v3, `jina-clip-v2 1024d`. Answer Kira `gpt-oss-120b-sale`, judge Kira `deepseek-v4-flash-sale`. RAGAS top-k=5, retrieval paired top-k=8.

## Benchmark truy xuất ghép cặp

433/433 câu có kết quả ở cả baseline và candidate. Mẫu thiếu nhãn được loại riêng theo metric, không xem như điểm 0.

| Chỉ số | Baseline | Candidate | Delta | n |
|---|---:|---:|---:|---:|
| recall@5 | 0.9263 | 0.9263 | +0.0000 | 380 |
| recall@10 | 0.9368 | 0.9368 | +0.0000 | 380 |
| mrr@10 | 0.8057 | 0.8057 | +0.0000 | 380 |
| list_coverage | 0.8919 | 0.8885 | -0.0034 | 48 |
| full_coverage | 0.8333 | 0.8333 | +0.0000 | 48 |
| sufficient_acc | 0.8012 | 0.8012 | +0.0000 | 347 |
| url_hit | 0.9514 | 0.9514 | +0.0000 | 350 |
| media_mode_acc | 0.9112 | 0.9112 | +0.0000 | 383 |
| required_has_media | 0.9343 | 0.9635 | +0.0292 | 137 |
| media_on_target | 0.8553 | 0.8816 | +0.0263 | 152 |
| media_precision | 0.6915 | 0.7151 | +0.0236 | 143 |
| none_clean | 0.9350 | 0.9350 | +0.0000 | 200 |
| video_hit | 0.6857 | 0.8000 | +0.1143 | 35 |
| wants_file_acc | 0.9817 | 0.9817 | +0.0000 | 383 |
| media_key_hit | 0.9483 | 0.9483 | +0.0000 | 58 |
| latency_ms | 120.1044 | 109.3882 | -10.7162 | 433 |

P50 / P95 baseline 111.03 / 229.75 ms, candidate 101.93 / 204.45 ms.

## Biến động dữ liệu đầu vào / trả lời khi ghép cặp

Trên 150 câu, ngữ cảnh truy xuất giống hệt ở 122 câu, danh sách URL chữ giống ở 135 câu, URL media giống ở 124 câu. Câu trả lời giống hệt ở 3 câu. Trong đó 119 câu có cùng context nhưng câu trả lời khác, và 28 câu thay đổi cả context và answer. Đây là dấu hiệu biến động generation độc lập với thay đổi retrieval ở một phần lớn mẫu. So điểm RAGAS trên cặp answer/context giống hệt mới tách được phần biến động của judge.

## RAGAS — golden 150 câu

Collect baseline 150/150, candidate 150/150. Ảnh gửi trong candidate 50/50. Score rows baseline 150/150, candidate 150/150.

| Metric | Baseline mean | Scored/eligible | Candidate mean | Scored/eligible | Paired Δ (n) | Baseline <0.91 | Candidate <0.91 |
|---|---:|---:|---:|---:|---:|---:|---:|
| faithfulness | 0.8407 | 147/147 | 0.8205 | 147/147 | -0.0202 (147) | 74 | 72 |
| answer_relevancy | 0.6252 | 133/133 | 0.6269 | 133/133 | +0.0017 (133) | 118 | 114 |
| context_precision | 0.7533 | 133/133 | 0.7913 | 133/133 | +0.0380 (133) | 77 | 71 |
| context_recall | 0.6019 | 112/112 | 0.5841 | 112/112 | -0.0179 (112) | 49 | 54 |

Các mẫu không áp dụng, không chấm được và lỗi giám khảo được tách riêng khỏi mẫu số. RAGAS collections dùng text cho câu hỏi và context. Các câu chỉ có ảnh dùng câu hỏi mặc định khi chấm faithfulness, đồng thời không chấm answer_relevancy, context_precision và context_recall.

**Coverage Baseline**
- faithfulness: eligible=147, scored=147, excluded={"out_of_scope": 3}, missing={}
- answer_relevancy: eligible=133, scored=133, excluded={"image_only_without_text": 14, "out_of_scope": 3}, missing={}
- context_precision: eligible=133, scored=133, excluded={"image_only_without_text": 14, "out_of_scope": 3}, missing={}
- context_recall: eligible=112, scored=112, excluded={"image_only_without_text": 14, "missing_reference": 21, "out_of_scope": 3}, missing={}

**Coverage Candidate**
- faithfulness: eligible=147, scored=147, excluded={"out_of_scope": 3}, missing={}
- answer_relevancy: eligible=133, scored=133, excluded={"image_only_without_text": 14, "out_of_scope": 3}, missing={}
- context_precision: eligible=133, scored=133, excluded={"image_only_without_text": 14, "out_of_scope": 3}, missing={}
- context_recall: eligible=112, scored=112, excluded={"image_only_without_text": 14, "missing_reference": 21, "out_of_scope": 3}, missing={}

## Phân bố điểm thấp theo nhóm câu hỏi

| Case | Số mẫu | AR baseline | AR candidate | CP baseline | CP candidate | CR baseline | CR candidate |
|---|---:|---:|---:|---:|---:|---:|---:|
| document | 4 | 0.6106 (4) | 0.6363 (4) | 0.9042 (4) | 0.8417 (4) | 0.5 (4) | 0.375 (4) |
| fact | 21 | 0.7179 (21) | 0.7145 (21) | 0.7253 (21) | 0.777 (21) | 0.9167 (13) | 0.9167 (13) |
| file | 17 | 0.6997 (17) | 0.6322 (17) | 0.8065 (17) | 0.9045 (17) | 0.1309 (14) | 0.2262 (14) |
| image | 80 | 0.5423 (66) | 0.5736 (66) | 0.7669 (66) | 0.7949 (66) | 0.6066 (61) | 0.5765 (61) |
| none | 2 | 0.6004 (2) | 0.5702 (2) | 1.0 (2) | 1.0 (2) | None (0) | None (0) |
| optional | 2 | 0.9036 (2) | 0.8266 (2) | 0.4048 (2) | 0.4325 (2) | 0.5 (2) | 0.5 (2) |
| out_of_scope | 3 | None (0) | None (0) | None (0) | None (0) | None (0) | None (0) |
| person | 4 | 0.8745 (4) | 0.8688 (4) | 0.8208 (4) | 0.925 (4) | 0.8889 (3) | 0.8889 (3) |
| video | 17 | 0.6734 (17) | 0.6443 (17) | 0.6426 (17) | 0.6556 (17) | 0.7333 (15) | 0.6667 (15) |

Triage tự động baseline, 140 câu có ít nhất một metric dưới 0.91. Số cờ theo nhóm là {"duplicate_text_source_urls": 115, "image_only_judge_text_only": 11, "expected_source_missing": 12, "possible_false_abstain": 27, "media_not_returned": 6, "reviewed_source_vs_media_conflict": 3}. Một câu có thể có nhiều cờ và chưa đủ bằng chứng để kết luận nguyên nhân gốc.

Triage tự động candidate, 138 câu có ít nhất một metric dưới 0.91. Số cờ theo nhóm là {"duplicate_text_source_urls": 113, "image_only_judge_text_only": 10, "possible_false_abstain": 23, "expected_source_missing": 12, "media_not_returned": 6, "reviewed_source_vs_media_conflict": 3}. Một câu có thể có nhiều cờ và chưa đủ bằng chứng để kết luận nguyên nhân gốc.

## Kiểm tra tính ổn định của giám khảo khi context không đổi

Trong 99 cặp có cùng danh sách context và đủ nhãn Context Recall, điểm giám khảo thay đổi ở 16 cặp, gồm 8 lần giảm và 8 lần tăng trên 0,05. Context Recall chỉ nhận câu hỏi, reference và retrieved contexts, vì vậy đây là bằng chứng biến động của judge trên cùng đầu vào. Ví dụ mm:mm-i1-06, mm:mm-t3-10 và mm:mm-i2-01 đều từ 1,0 xuống 0,0 dù context giống hệt. Không thể quy toàn bộ thay đổi Context Recall cho retrieval.

| Metric | Số cặp context giống | Cặp đổi điểm | Giảm >0,05 | Tăng >0,05 |
|---|---:|---:|---:|---:|
| faithfulness | 119 | 80 | 35 | 35 |
| answer_relevancy | 118 | 108 | 34 | 27 |
| context_precision | 118 | 42 | 15 | 25 |
| context_recall | 99 | 16 | 8 | 8 |

Với Faithfulness và Context Precision, câu trả lời ở hai lần collect có thể khác nhau dù context giữ nguyên, nên chênh lệch gồm cả biến động sinh câu trả lời. Context Recall không sử dụng câu trả lời để chấm.

## Kiểm tra biến động so với giám khảo lịch sử

Lần chấm 23/11 so với baseline chấm lại 24–25/11 là biến động theo lần chạy giám khảo cùng variant. Các số sau ghép trên ID có điểm ở cả hai phía.

| Metric | Paired n | 23/11 | Baseline mới | Δ |
|---|---:|---:|---:|---:|
| faithfulness | 145 | 0.7865 | 0.8431 | 0.0566 |
| answer_relevancy | 133 | 0.612 | 0.6252 | 0.0132 |
| context_precision | 131 | 0.686 | 0.7508 | 0.0648 |
| context_recall | 111 | 0.5848 | 0.6074 | 0.0225 |

## Truy vết các câu điểm thấp

Đã trực tiếp đối chiếu input, ảnh và ngữ cảnh cho các ID dưới đây. Danh sách tất cả ID dưới 0.91 kèm điểm, nhãn và cờ triage nằm trong tệp JSON. Các cờ tự động là dấu hiệu cần kiểm chứng, chưa phải root cause đã xác minh.

### `mm:mm-i2-02`

- Bằng chứng: Ảnh đầu vào có bảng địa điểm sân thể thao. /query trả đúng bài SICT Tournament 2026 ở [1],[2]. LLM lại dựa vào OCR [6] của ảnh địa điểm để từ chối trả lời giải thưởng. F=0.75, AR=0, CP=0.1667, CR=0 trong baseline.
- Nhận định: Ưu tiên OCR ảnh phụ hơn nội dung bài liên quan khi lập câu trả lời. Nguồn chính phù hợp đã nằm trong context.
- Hướng kiểm chứng: Đánh giá vai trò OCR trong context và cách LLM tổng hợp bằng các câu kiểm tra khác. Chỉ đổi sau khi đo hồi quy.

### `mm:mm-i2-07`

- Bằng chứng: Đã kiểm tra ảnh crop50 thật: hai sinh viên, một người cầm điện thoại; không có chữ chỉ số cơ hội việc làm. Nguồn text [1],[2] ghi gần 1.000 cơ hội, nhưng OCR của ảnh liên quan [6] ghi hơn 200; answer chọn hơn 200, F=1, AR=0.6068, CP=0.1667, CR=1.
- Nhận định: Xung đột bằng chứng text/OCR từ ảnh truy xuất. OCR [6] mô tả ảnh liên quan, không phải chữ trên ảnh truy vấn. Faithfulness/Recall cao không chứng minh answer đúng golden.
- Hướng kiểm chứng: Kiểm provenance OCR theo nguồn và ưu tiên chứng cứ bài viết khi câu hỏi cần tổng số sự kiện.

### `mm:mm-i2-08`

- Bằng chứng: Ảnh hội thao thật cho thấy bảng cơ sở cho thuê sân, có địa chỉ Bắc Từ Liêm. Answer dựa vào bảng này; golden chỉ ghi ảnh chụp hội thao tại Trường CNTT&TT, thông tin có thể là đơn vị tổ chức.
- Nhận định: Golden reference có nguy cơ gộp đơn vị tổ chức với vị trí vật lý của ảnh. Cần owner rà soát trước khi quy lỗi cho retrieval.
- Hướng kiểm chứng: Rà soát reference với ảnh gốc và bài đăng, giữ minh bạch cả câu bị thay nhãn.

### `mm:mm-s-05`

- Bằng chứng: Truy xuất đúng bài SICT Tournament 2026 ở top text nhưng media_urls rỗng. Answer từ chối cung cấp ảnh. AR=0, CP=1 ở baseline.
- Nhận định: Ảnh liên quan không được trả trong kết quả /query dù text đúng. Điểm CP cao không phản ánh việc thiếu media.
- Hướng kiểm chứng: Kiểm router media intent, threshold, lọc media và media-on-target trên toàn golden.

### `mm:mm-t3-07`

- Bằng chứng: Truy vấn video giới thiệu chương trình Khoa học máy tính; top text có trang chương trình, media_urls rỗng, answer từ chối. AR=0, CR=0 ở baseline.
- Nhận định: Không có video liên quan trong candidate context, cần đối chiếu index video/subtitle và rule router.
- Hướng kiểm chứng: Đối chiếu video keys có trong index v3 và kiểm media selector.

### `mm:mm-t4-04`

- Bằng chứng: Truy xuất 4 chunk file quyết định ở trang 53–55, gồm trùng URL, text tiêu đề quyết định nằm [5]. Faithfulness=0.2222, CP=1, CR=0.5.
- Nhận định: Độ phân tán chứng cứ ở trang cuối của PDF và trùng cùng một URL; chưa xác minh độ đúng từng mệnh đề với toàn văn PDF.
- Hướng kiểm chứng: Kiểm chunk/page phù hợp và căn cứ cho từng ý answer, đồng thời đối chiếu lỗi judge.

### `mm:mm-i1-09`

- Bằng chứng: Ảnh hội thao đã gửi, có bài SICT Tournament đúng top context, nhưng answer nói không có thông tin. Faithfulness=0 trong baseline.
- Nhận định: False abstain ở câu chỉ có ảnh. RAGAS dạng chữ chỉ giả lập user_input cho câu ảnh-only nên score hạn chế.
- Hướng kiểm chứng: Đánh giá VLM câu trả lời trên ảnh thật và bổ sung giám khảo đa phương thức khi có thể.

### `mm:mm-t4-01`

- Bằng chứng: Golden gắn answerable=true nhưng reference rỗng và expected_urls=[] cho yêu cầu tải kế hoạch hè 2026. Trong candidate, 5 nguồn truy xuất gồm tài liệu học kỳ phụ 2021-2022, thông báo liên thông 2026 và thời khóa biểu năm khác; answer từ chối vì không thấy kế hoạch hè 2026. Judge AR=0, CP=1, không có reference để chấm CR.
- Nhận định: Thiếu nhãn đáp án/reference và nguồn đích kiểm chứng trong golden draft. Các nguồn file đang lệch năm và loại tài liệu; cần xác minh tài liệu đích có tồn tại.
- Hướng kiểm chứng: Chủ bộ golden xác minh đáp án và URL của kế hoạch hè 2026. Nếu có, kiểm tra dense/BM25, metadata lọc năm, index file; nếu không, rà soát answerable.

### `mm:mm-t1-05`

- Bằng chứng: Candidate top-1 và top-5 là thông báo 2026-2027 đúng yêu cầu. Answer trả đúng mốc chính 12/8–26/8/2026. Nguồn [2] là 2025-2026, [3][4] trùng URL thời khóa biểu 2024-2025; CP của lần chấm candidate=0.2, F=1, CR=1.
- Nhận định: Context vẫn chứa các nguồn cũ và URL trùng làm loãng thứ tự chứng cứ mặc dù đáp án chính có căn cứ. Kiểm thêm lý do judge chấm CP=0.2 trước khi đổi reranker.
- Hướng kiểm chứng: Đối chiếu từng verdict của Context Precision với 5 nguồn, kiểm cơ chế đa dạng bài và gộp URL.

## Ca giảm điểm giữa baseline và candidate

- faithfulness ghép cặp n=147, delta=-0.0202, giảm >0.05 ở 44 câu.
  - mm:mm-i1-02, 1.0000 → 0.0000 (-1.0000)
  - mm:mm-t3-15, 1.0000 → 0.0000 (-1.0000)
  - mm:mm-i1-01, 0.7143 → 0.0000 (-0.7143)
  - mm:mm-t2-24, 1.0000 → 0.3333 (-0.6667)
  - mm:mm-t2-25, 0.9167 → 0.3333 (-0.5834)
  - mm:mm-i1-17, 0.5714 → 0.0000 (-0.5714)
  - mm:mm-i1-15, 1.0000 → 0.5000 (-0.5000)
  - mm:mm-i4-02, 1.0000 → 0.5000 (-0.5000)
  - mm:mm-t2-06, 1.0000 → 0.5000 (-0.5000)
  - mm:mm-t3-02, 1.0000 → 0.5000 (-0.5000)
  - mm:mm-t3-11, 1.0000 → 0.5000 (-0.5000)
  - mm:mm-t5-06, 0.5000 → 0.0000 (-0.5000)
- answer_relevancy ghép cặp n=133, delta=0.0017, giảm >0.05 ở 38 câu.
  - mm:mm-t4-01, 0.9371 → 0.0000 (-0.9371)
  - mm:mm-t3-09, 0.7995 → 0.0000 (-0.7995)
  - mm:mm-s-10, 0.5978 → 0.1566 (-0.4412)
  - mm:mm-t2-02, 0.7233 → 0.3495 (-0.3738)
  - mm:mm-t4-03, 0.7001 → 0.4387 (-0.2614)
  - mm:mm-t2-13, 0.7365 → 0.4788 (-0.2577)
  - mm:mm-t2-10, 0.8808 → 0.6567 (-0.2241)
  - mm:mm-i2-06, 0.7175 → 0.4991 (-0.2184)
  - mm:mm-t2-04, 0.4696 → 0.2817 (-0.1879)
  - mm:mm-t4-13, 0.8332 → 0.6526 (-0.1806)
  - mm:mm-i4-04, 0.5765 → 0.3972 (-0.1793)
  - mm:mm-t1-03, 0.9153 → 0.7396 (-0.1757)
- context_precision ghép cặp n=133, delta=0.038, giảm >0.05 ở 19 câu.
  - mm:mm-i2-10, 0.8333 → 0.1250 (-0.7083)
  - mm:mm-i2-05, 1.0000 → 0.4762 (-0.5238)
  - mm:mm-t3-07, 1.0000 → 0.5000 (-0.5000)
  - mm:mm-t2-05, 1.0000 → 0.6667 (-0.3333)
  - mm:mm-t4-08, 1.0000 → 0.7000 (-0.3000)
  - mm:mm-t1-17, 1.0000 → 0.7500 (-0.2500)
  - mm:mm-t2-06, 1.0000 → 0.7500 (-0.2500)
  - mm:mm-t1-12, 1.0000 → 0.8056 (-0.1944)
  - mm:mm-i2-01, 0.5193 → 0.3333 (-0.1860)
  - mm:mm-t2-13, 1.0000 → 0.8333 (-0.1667)
  - mm:mm-t2-21, 1.0000 → 0.8333 (-0.1667)
  - mm:mm-t3-04, 1.0000 → 0.8333 (-0.1667)
- context_recall ghép cặp n=112, delta=-0.0179, giảm >0.05 ở 8 câu.
  - mm:mm-i1-06, 1.0000 → 0.0000 (-1.0000)
  - mm:mm-i1-16, 1.0000 → 0.0000 (-1.0000)
  - mm:mm-i2-01, 1.0000 → 0.0000 (-1.0000)
  - mm:mm-t3-10, 1.0000 → 0.0000 (-1.0000)
  - mm:mm-t1-18, 1.0000 → 0.5000 (-0.5000)
  - mm:mm-t2-12, 1.0000 → 0.5000 (-0.5000)
  - mm:mm-t4-02, 0.3333 → 0.0000 (-0.3333)
  - mm:mm-t1-03, 0.7500 → 0.5000 (-0.2500)

## Quyết định và phạm vi

- HOLD — candidate context_precision 0.7913 below 0.91.
- HOLD — candidate answer_relevancy 0.6269 below 0.91.
- HOLD — owner golden is draft, unresolved reviewed alias artifact and rollout gate.

Chỉ đánh giá local, không deploy, không chạm v2 production, không upload S3, không thao tác VM, không commit.
