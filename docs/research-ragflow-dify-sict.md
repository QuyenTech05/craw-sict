# Nghiên cứu RAGFlow, Dify và SICT

> Ngày nghiên cứu: 2026-11-23. Phạm vi là các nguồn sơ cấp: repository / tài liệu chính thức của RAGFlow, Dify và mã nguồn, đặc tả, bộ đánh giá của SICT. Không dùng benchmark bên thứ ba. Các kết luận không có số đo trực tiếp được đánh dấu **Suy luận** hoặc **Chưa được chứng minh**.

## Tóm tắt điều hành

- SICT là hệ thống chuyên biệt cho một website giáo dục: crawl theo cây, parse cấu trúc HTML, xử lý bảng/file/ảnh/video, hybrid retrieval qua Qdrant, rule-based evidence gate và API/chat. Kiến trúc này được mô tả trong [`CLAUDE.md`](../CLAUDE.md), đặc biệt các phần Ingest, Query side và Evaluation.
- RAGFlow là một RAG engine tổng quát, nhấn mạnh deep document understanding, chunking theo template, knowledge compilation, agentic multi-step retrieval và citations. Đây là năng lực sản phẩm được upstream công bố, không phải kết quả benchmark trên dữ liệu SICT. ([RAGFlow README](https://github.com/infiniflow/ragflow/blob/main/README.md#what-is-ragflow), [Key Features](https://github.com/infiniflow/ragflow/blob/main/README.md#key-features))
- Dify là nền tảng phát triển ứng dụng LLM tổng quát, bao gồm workflow canvas, model providers, RAG pipeline, agents, LLMOps và API. README chính thức không công bố độ chính xác RAG, faithfulness, media precision hay latency trên bộ SICT. ([Dify README](https://github.com/langgenius/dify/blob/main/README.md#key-features))
- Vì vậy, không thể kết luận “RAGFlow/Dify chính xác hơn SICT” từ tài liệu upstream. SICT có số đo trên corpus thật; hai sản phẩm kia cần được triển khai và chấm trên cùng snapshot, cùng model, cùng câu hỏi và cùng ngân sách context trước khi so sánh.

## 1. Cách so sánh và giới hạn bằng chứng

| Khía cạnh | Bằng chứng SICT hiện có | Bằng chứng upstream RAGFlow/Dify | Kết luận hợp lệ |
|---|---|---|---|
| Retrieval accuracy | `golden_v1`, `golden_v2`, `list_v2`, `eval/RESULTS.md` | README mô tả retrieval/chunking nhưng không đưa kết quả trên SICT | Chỉ SICT có số đo định lượng trong nghiên cứu này |
| Answer faithfulness/relevancy | RAGAS trong `eval/RESULTS.md`, script [`scripts/eval_ragas.py`](../scripts/eval_ragas.py) | Không thấy benchmark tương đương trong README chính thức được dùng | Chưa có so sánh công bằng |
| List coverage | `list_v2` và `scripts/eval_api.py` | RAGFlow/Dify công bố tính năng, không công bố coverage trên cùng câu hỏi | Không suy ra bên thắng |
| Media accuracy | `media_v1`, `scripts/eval_media.py` | README RAGFlow nói hỗ trợ heterogeneous data; README Dify nói extraction common document formats, không cung cấp media precision trên SICT | SICT có gate/metric chuyên biệt; đối thủ chưa được đo |
| Latency | Các phép đo nội bộ trong `eval/RESULTS.md` và `CLAUDE.md` | RAGFlow công bố khuyến nghị tài nguyên, Dify công bố tối thiểu cài đặt; không phải latency benchmark | Không so sánh latency trực tiếp |
| Cost | SICT có cấu hình 2 VM và đo compute/embedding nội bộ; giá cloud/provider thay đổi theo thời điểm | Dify README dẫn tới pricing nhưng không có chi phí triển khai cụ thể; RAGFlow README nêu yêu cầu phần cứng | Chỉ có thể so sánh cost model, chưa có TCO chung |

**Chú ý phương pháp:** bộ SICT `golden_v2` có 88 câu, gồm câu fact/person/event/admission/document/list/image/video/latest/multi-hop và các câu ngoài phạm vi; `list_v2` có 42 câu và 214 item. Các mô tả này nằm trong [`CLAUDE.md`](../CLAUDE.md#evaluation) và [`eval/RESULTS.md`](../eval/RESULTS.md). Các số dưới đây là kết quả theo từng trạng thái index/branch ghi trong repo, không nên coi là benchmark độc lập giữa các thời điểm.

## 2. RAGFlow so với SICT

### Năng lực và cơ chế

RAGFlow README mô tả các điểm chính: deep document understanding; template-based chunking; knowledge compilation thành wiki/graph/tree/page index/mind map/timeline/skills; agentic retrieval nhiều bước có phân tích, chia nhỏ câu hỏi, retrieval và verification; citations có thể truy vết; hỗ trợ Word, PowerPoint, Excel, TXT, ảnh, PDF, scan, structured data và web pages; multiple recall và fused reranking. ([RAGFlow README](https://github.com/infiniflow/ragflow/blob/main/README.md#key-features))

SICT hiện có các cơ chế tương ứng nhưng hẹp và có điều kiện rõ hơn: parser tạo block DOM-ordered, chunk cấu trúc giữ `heading_path`/`block_range`, bảng có label năm, attachment được tách trang, video dùng subtitle-only và keyframe, ảnh/video có collection riêng; retrieval dùng dense + folded BM25 + RRF, concept graph, list neighbors, accent restoration, phrase retrieval cho tên riêng và media evidence gate. ([`CLAUDE.md`](../CLAUDE.md#bulk-index-path), [`CLAUDE.md`](../CLAUDE.md#query-side), [`CLAUDE.md`](../CLAUDE.md#multimodal--structure))

**Khác biệt thực dụng:**

1. RAGFlow upstream quảng bá agentic multi-step retrieval và verification; SICT cố ý dùng một retrieval pass và evidence rule không phụ thuộc LLM để giảm chi phí, độ dao động và false-sufficient. ([RAGFlow README](https://github.com/infiniflow/ragflow/blob/main/README.md#key-features), [`CLAUDE.md`](../CLAUDE.md#one-retrieval-pass-no-llm-judge))
2. SICT có xử lý media end-to-end theo schema và metric riêng; RAGFlow README chỉ chứng minh phạm vi định dạng được hỗ trợ, không chứng minh ảnh/video được ghép đúng bài trên corpus SICT. ([RAGFlow README](https://github.com/infiniflow/ragflow/blob/main/README.md#key-features), [`eval/media_v1.md`](../eval/media_v1.md))
3. RAGFlow khuyến nghị khởi điểm 4 CPU, 16 GB RAM, 50 GB disk cho local deployment; SICT production plan ghi VM1 2 vCPU/4 GB và VM2 2 vCPU/8 GB với embed service tách riêng. Đây là yêu cầu triển khai khác nhau, không phải cùng một workload benchmark. ([RAGFlow README](https://github.com/infiniflow/ragflow/blob/main/README.md#docker-deployment), [`CLAUDE.md`](../CLAUDE.md#hardware-d32))

### Accuracy và answer quality

SICT có các mốc sau:

- Sau context-fit (whole chunk, list neighbors, accent restoration), `list_v2` tăng từ 0,724 lên 0,878; full coverage tăng 23/42 lên 34/42; golden không đổi ở `1,0 / 0,928`; câu không dấu tăng từ `0,881 / 0,775` lên `0,985 / 0,920`. ([`eval/RESULTS.md`](../eval/RESULTS.md#L105-L131))
- Concept graph trên cùng trạng thái index đưa `golden_v1` lên `1,0 / 0,954`, `golden_v2` MRR lên 0,701 và `list_v2` lên 0,916 (37/42), nhưng một số câu giảm hạng và `sufficient_acc` là 0,96. ([`eval/RESULTS.md`](../eval/RESULTS.md#L133-L170))
- RAGAS sau các thay đổi context + graph ghi faithfulness 0,946, answer relevancy 0,739, context precision 0,758, context recall 0,887; ở nhóm list, context recall tăng 0,49 lên 0,85 nhưng context precision giảm 0,78 xuống 0,53 do thêm đoạn kề. ([`eval/RESULTS.md`](../eval/RESULTS.md#L172-L193))

RAGFlow có tuyên bố “high-fidelity”, “reduced hallucinations”, citations và verification trong README, nhưng đó là mô tả tính năng/định vị của sản phẩm; tài liệu nguồn được dùng ở đây không đưa các chỉ số faithfulness/relevancy hoặc list coverage trên `golden_v2`/`list_v2`. ([RAGFlow README](https://github.com/infiniflow/ragflow/blob/main/README.md#what-is-ragflow), [RAGFlow README](https://github.com/infiniflow/ragflow/blob/main/README.md#key-features))

**Kết luận:** SICT đang có bằng chứng đo được trên miền hẹp; RAGFlow có cơ chế tổng quát có thể đáng thử cho multi-hop/document-scale, nhưng lợi ích đó trên SICT là **chưa được chứng minh**.

## 3. Dify so với SICT

Dify README định vị sản phẩm là nền tảng LLM app: visual workflows, hàng trăm model/provider, RAG pipeline, agent sandbox, LLMOps/observability và backend APIs. Minimum self-hosting được README nêu là CPU >= 2 core, RAM >= 4 GiB. ([Dify README](https://github.com/langgenius/dify/blob/main/README.md), [Dify README](https://github.com/langgenius/dify/blob/main/README.md#quick-start), [Dify README](https://github.com/langgenius/dify/blob/main/README.md#key-features))

SICT ngược lại là một ứng dụng dọc đã tích hợp policy retrieval, schema source/citation, media route, evidence gate, incremental crawl và deploy hai VM. API contract và acceptance nằm ở [`tests/acceptance_retrieval_response.md`](../tests/acceptance_retrieval_response.md), [`tests/acceptance_criteria.md`](../tests/acceptance_criteria.md) và route/retrieval code trong [`sict_crawler/service/retrieval`](../sict_crawler/service/retrieval).

**So sánh:**

- Dify có lợi thế về orchestration, provider/model switching, workflow và observability được đóng gói. ([Dify README](https://github.com/langgenius/dify/blob/main/README.md#key-features))
- SICT có lợi thế về kiểm soát miền: metadata section/year, Vietnamese accent restoration, proper-name phrase filter, table labels, page citations, subtitle-only video và media coupling. ([`CLAUDE.md`](../CLAUDE.md#metadata-filtering), [`CLAUDE.md`](../CLAUDE.md#proper-name-phrases), [`CLAUDE.md`](../CLAUDE.md#citations-and-pages), [`CLAUDE.md`](../CLAUDE.md#media-router))
- Dify có thể là lớp workflow/API phía trên SICT, nhưng việc thay retrieval/indexing của SICT bằng mặc định Dify sẽ là thay đổi lớn. **Suy luận:** tích hợp qua API có thể giữ lại retrieval chuyên biệt và dùng Dify cho workflow, nhưng cần spike đo latency, streaming, auth, file/media payload và citation fidelity trước khi quyết định. Dify README chỉ xác nhận có APIs, không xác nhận compatibility với SICT contract. ([Dify README](https://github.com/langgenius/dify/blob/main/README.md#key-features), [`tests/acceptance_retrieval_response.md`](../tests/acceptance_retrieval_response.md))

## 4. Latency và cost

### SICT

Các số đo đã ghi:

- LLM rewrite từng tốn 2–11 giây/câu mà không có gain tổng thể; vì vậy bị tắt mặc định. ([`eval/RESULTS.md`](../eval/RESULTS.md#L112-L118), [`CLAUDE.md`](../CLAUDE.md#the-llm-rewrite-is-off-by-default))
- Parallel Qdrant tiers được thêm vì trước đó một câu gọi 9–20 lần tuần tự, 0,1–3,7 giây; media evidence gate làm `/query` p50 từ 0,118 lên 0,132 giây trong phép đo được ghi. ([`CLAUDE.md`](../CLAUDE.md#parallel-qdrant-calls), [`CLAUDE.md`](../CLAUDE.md#measured-2026-11-05))
- Embed service trên target 2 vCPU đo khoảng 0,45 giây cho một text query, khoảng 9,7 giây cho một ảnh 512; retrieval không LLM khoảng 0,4 giây. Query image 336 giảm từ 392 ở phép đo riêng, nhưng các số này không phải p95 end-to-end. ([`CLAUDE.md`](../CLAUDE.md#embedding-gateway))

### RAGFlow và Dify

RAGFlow README đưa resource starting point 4 CPU/16 GB/50 GB; Dify README đưa minimum 2 core/4 GiB. Không tài liệu nào trong các nguồn đã dùng cung cấp p50/p95 cho cùng một câu hỏi, cùng embedding/LLM, cùng corpus, hoặc chi phí inference. ([RAGFlow README](https://github.com/infiniflow/ragflow/blob/main/README.md#docker-deployment), [Dify README](https://github.com/langgenius/dify/blob/main/README.md#quick-start))

**Không được suy luận:** resource minimum không tương đương latency; số CPU/RAM cao hơn không tự chứng minh retrieval tốt hơn hay tổng chi phí thấp hơn. Pricing/provider cost cũng phụ thuộc model, token, concurrency và retention; chưa có một cấu hình thử nghiệm chung. Đây là điểm **chưa được chứng minh**.

## 5. Media accuracy

SICT `media_v1` có 101 câu, gồm image, video, file, optional, none và out-of-scope; script chấm `media_mode_acc`, `required_has_media`, `media_on_target`, `media_precision`, `none_clean`, `file_hit`, `video_hit`, `abstain_ok` và `false_abstain`. ([`CLAUDE.md`](../CLAUDE.md#evalmedia_v1jsonl), [`eval/media_v1.md`](../eval/media_v1.md), [`scripts/eval_media.py`](../scripts/eval_media.py))

Media evidence gate đã đo được: `media_precision` 0,674 → 0,798; `none_clean` 31/33 → 33/33; `video_hit` 10/15 → 12/15; `media_on_target` 57/65 → 58/67; nhưng `required_has_media` 50/51 → 47/51 và p50 `/query` 0,118 → 0,132 giây. ([`CLAUDE.md`](../CLAUDE.md#measured-2026-11-05))

RAGFlow README xác nhận hỗ trợ ảnh và scanned copies trong nhóm heterogeneous data; Dify README xác nhận out-of-box extraction cho PDF, PPT và các định dạng phổ biến. Hai nguồn không đưa media precision/target rate trên SICT, không mô tả cùng media schema `parent_url`/video-frame và không cung cấp kết quả `media_v1`. ([RAGFlow README](https://github.com/infiniflow/ragflow/blob/main/README.md#key-features), [Dify README](https://github.com/langgenius/dify/blob/main/README.md#key-features))

**Kết luận:** SICT hiện là hệ duy nhất trong so sánh có metric media-specific trên corpus này. Không nên gọi đó là ưu thế tuyệt đối của sản phẩm; chỉ có thể nói RAGFlow/Dify chưa được đo trong nghiên cứu này.

## 6. Đề xuất cải tiến tổng quát

Các đề xuất dưới đây không thay đổi code trong nghiên cứu này. Mỗi đề xuất phải được chấp thuận và đo toàn bộ suite trước khi áp dụng, theo policy trong [`CLAUDE.md`](../CLAUDE.md#fixing-quality-problems).

### P1 — Benchmark adapter chung cho RAGFlow/Dify và SICT

- **Cơ chế:** dựng adapter HTTP chuẩn hóa input/output: câu hỏi, file/ảnh, text sources, media sources, citations, route và timing; chạy cùng `golden_v2`, `list_v2`, `media_v1`, RAGAS và acceptance.
- **Bằng chứng:** SICT đã có `scripts/eval_api.py`, `scripts/eval_media.py`, `scripts/eval_ragas.py`, `scripts/accept_api.py`; upstream chỉ cung cấp mô tả feature chứ chưa có số đo cùng corpus. ([`CLAUDE.md`](../CLAUDE.md#evaluation), [RAGFlow README](https://github.com/infiniflow/ragflow/blob/main/README.md#key-features), [Dify README](https://github.com/langgenius/dify/blob/main/README.md#key-features))
- **SICT components:** [`scripts/eval_api.py`](../scripts/eval_api.py), [`scripts/eval_media.py`](../scripts/eval_media.py), [`scripts/eval_ragas.py`](../scripts/eval_ragas.py), [`scripts/accept_api.py`](../scripts/accept_api.py).
- **Effort/risk:** Trung bình; rủi ro chính là khác biệt schema/citation và model/provider làm kết quả không đồng nhất. Không thay đổi production retrieval.
- **Đo lường:** báo cáo riêng retrieval recall/MRR, list full coverage, `media_precision`/`video_hit`, RAGAS faithfulness/relevancy/precision/recall, acceptance pass rate, p50/p95 và token/cost. Không gộp thành một điểm duy nhất.

### P2 — Tách quality gate khỏi feature claims

- **Cơ chế:** mọi thay đổi retrieval, prompt, chunking, media hoặc graph phải chạy baseline/candidate trên toàn bộ suite; lưu index tag, model, prompt, cache state và timestamp cùng kết quả.
- **Bằng chứng:** `CLAUDE.md` yêu cầu kiểm tra toàn bộ eval và tránh fix theo một case; `eval/RESULTS.md` cho thấy rank flip có thể làm `list_v1` thay đổi dù code/vector gần như không đổi. ([`CLAUDE.md`](../CLAUDE.md#fixing-quality-problems), [`eval/RESULTS.md`](../eval/RESULTS.md#L77-L103))
- **SICT components:** `scripts/eval_retrieval.py`, `scripts/eval_api.py`, `scripts/eval_media.py`, `scripts/eval_ragas.py`, Redis query-cache isolation được mô tả trong [`CLAUDE.md`](../CLAUDE.md#query-results-and-media-bytes-are-cached).
- **Effort/risk:** Thấp–trung bình; chi phí compute/LLM tăng và RAGAS có judge noise. Giảm rủi ro phát hành regression.
- **Đo lường:** candidate không được giảm golden/list/media/acceptance; RAGAS phải báo paired n và model judge; latency p50/p95 và token count phải đi cùng quality.

### P3 — Thử agentic multi-step chỉ cho lớp câu hỏi cần thiết

- **Cơ chế:** giữ đường single-pass mặc định; route có điều kiện sang 2–3 bước retrieve/verify cho multi-hop hoặc list dài, với hard budget về số lần retrieval, token và thời gian. Không bật agentic mode toàn cục.
- **Bằng chứng:** RAGFlow công bố multi-step retrieval, decomposition và verification; SICT hiện dùng one retrieval pass và rule-based evidence để tránh LLM judge cost/dao động. ([RAGFlow README](https://github.com/infiniflow/ragflow/blob/main/README.md#key-features), [`CLAUDE.md`](../CLAUDE.md#one-retrieval-pass-no-llm-judge))
- **SICT components:** [`sict_crawler/service/retrieval/agent.py`](../sict_crawler/service/retrieval/agent.py), [`retriever.py`](../sict_crawler/service/retrieval/retriever.py), [`sources.py`](../sict_crawler/service/retrieval/sources.py), route/evidence trong [`router.py`](../sict_crawler/service/retrieval/router.py).
- **Effort/risk:** Cao; tăng latency, LLM cost, duplicate context và có thể làm giảm faithfulness/precision. Đây là proposal thử nghiệm, không phải khuyến nghị bật ngay.
- **Đo lường:** trên golden_v2 phân nhóm `multi_hop`/list/document; list_v2 full coverage và context recall/precision; RAGAS faithfulness/relevancy; media_v1 text MRR/media metrics; p50/p95, số retrieval calls, input/output tokens và cost per query. Acceptance phải giữ nguyên.

### P4 — Giữ media evidence gate, nhưng tối ưu precision–recall theo modality

- **Cơ chế:** giữ coupled-media-first và `sufficient` gate; tune threshold theo image/video/file và theo required/optional, không dùng một threshold chung. Chỉ chấp nhận thay đổi khi regression table được xem xét.
- **Bằng chứng:** gate cải thiện precision, none_clean và video_hit nhưng làm `required_has_media` giảm và latency tăng. ([`CLAUDE.md`](../CLAUDE.md#measured-2026-11-05))
- **SICT components:** [`retriever.py`](../sict_crawler/service/retrieval/retriever.py), [`router.py`](../sict_crawler/service/retrieval/router.py), [`agent.py`](../sict_crawler/service/retrieval/agent.py), `config.yaml`, [`scripts/eval_media.py`](../scripts/eval_media.py).
- **Effort/risk:** Trung bình; threshold tuning dễ overfit `media_v1` và có thể làm mất media đúng.
- **Đo lường:** media_v1 toàn bộ, phân theo image/video/optional/none/out-of-scope; `media_precision`, `media_on_target`, `required_has_media`, `video_hit`, `none_clean`, text MRR, p50/p95. Đồng thời chạy golden_v2/list_v2 và acceptance.

### P5 — Đánh giá Dify như orchestration layer, không thay SICT index ngay

- **Cơ chế:** spike tích hợp Dify qua API để thử workflow/model/observability, trong khi SICT vẫn là retrieval authority và trả sources/citations chuẩn.
- **Bằng chứng:** Dify công bố workflow, RAG, LLMOps và backend APIs; SICT acceptance yêu cầu contract sources/citations/streaming riêng. ([Dify README](https://github.com/langgenius/dify/blob/main/README.md#key-features), [`tests/acceptance_retrieval_response.md`](../tests/acceptance_retrieval_response.md))
- **SICT components:** [`sict_crawler/api/routes.py`](../sict_crawler/api/routes.py), [`tests/acceptance_retrieval_response.md`](../tests/acceptance_retrieval_response.md), [`scripts/accept_api.py`](../scripts/accept_api.py).
- **Effort/risk:** Trung bình; rủi ro mapping citation, streaming, auth, file upload, media bytes và thêm network hop.
- **Đo lường:** acceptance đầy đủ; golden/list/media/RAGAS so với SICT trực tiếp; p50/p95 end-to-end, error rate, token/cost và citation fidelity. Nếu có regression, không thay production path.

## 7. Kết luận

RAGFlow và Dify giải quyết bài toán rộng hơn SICT: RAGFlow nhấn mạnh document understanding, compilation và agentic retrieval; Dify nhấn mạnh workflow, model/app platform và LLMOps. ([RAGFlow README](https://github.com/infiniflow/ragflow/blob/main/README.md#key-features), [Dify README](https://github.com/langgenius/dify/blob/main/README.md#key-features))

SICT có lợi thế bằng chứng miền cụ thể: retrieval/list/answer/media được đo trên corpus SICT, với cơ chế Vietnamese-specific và media-specific. Các số đo đó không đủ để tuyên bố SICT tốt hơn hai nền tảng tổng quát, vì chưa chạy đối thủ trên cùng corpus. Quyết định hợp lý hiện tại là giữ SICT retrieval làm baseline có kiểm chứng; nếu cần, thử RAGFlow cho tài liệu phức tạp hoặc Dify cho orchestration qua adapter, rồi quyết định bằng P1/P2 thay vì feature checklist.

### Nguồn chính

- [SICT repository `CLAUDE.md`](../CLAUDE.md)
- [SICT evaluation results](../eval/RESULTS.md)
- [SICT media evaluation specification](../eval/media_v1.md)
- [SICT retrieval-response acceptance](../tests/acceptance_retrieval_response.md)
- [SICT behavior acceptance](../tests/acceptance_criteria.md)
- [RAGFlow official GitHub repository](https://github.com/infiniflow/ragflow)
- [RAGFlow official README](https://github.com/infiniflow/ragflow/blob/main/README.md)
- [Dify official GitHub repository](https://github.com/langgenius/dify)
- [Dify official README](https://github.com/langgenius/dify/blob/main/README.md)
