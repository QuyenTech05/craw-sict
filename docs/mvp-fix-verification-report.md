# Báo cáo kiểm chứng PLAN_FIX

Ngày 2026-11-26, môi trường local, branch `feat/retrieval-v3-ragas-20261125`.
Phạm vi: sửa và kiểm thử MVP Vercel, runtime API-only v3, release/CD. Các chức
năng đã có ở baseline được kiểm tra lại bằng regression test.

## Kết quả local

| Kiểm tra | Kết quả |
|---|---|
| `uv run --locked pytest tests/ -q --ignore=tests/smoke_incremental.py` | 687 passed, 5 skipped, 7 warnings; 309,20 s |
| Focused release/OCR/multimodal/jobs/runner tests | 50 passed, 2 warnings |
| `tests/test_embed_server.py` sau khi bổ sung kiểm tra wrong key | 14 passed, 4 skipped, 4 warnings |
| `tests/test_sandbox_image.py` | 2 passed |
| `tests/test_mvp_local_e2e.py` | 1 passed; 51,62 s |
| `npm --prefix vercel test` | 19 passed |
| Compose config, `bash -n sandbox/run_job.sh`, `git diff --check` | Pass |
| Sandbox image offline (`--network none`) | ffmpeg 7.1.5, Poppler 25.03, uv 0.12.19, Tesseract eng/osd/vie, worker/graph imports pass |
| OCR Tesseract.js thật trên poster tổng hợp PNG | HTTP 200, đúng `Hội thảo AI 2026\nSICT - HaUI`, confidence 93/100, 1487 ms; token sai HTTP 401 |

Full suite được chạy trước khi bổ sung test E2E video và test image; hai file
đó được chạy riêng. Test embedding đã sửa cũng được chạy lại riêng. Warnings
gồm FastAPI on_event deprecated, Qdrant local payload index và cảnh báo đóng
kết nối khi kết thúc suite. Test cần artifact model thật có thể skip theo điều
kiện môi trường. Số đo OCR là một lần chạy local với traineddata lấy từ máy,
không phải thống kê cold/warm cloud.

## Đối chiếu findings

| Task | Sửa/kiểm chứng | Bằng chứng test |
|---|---|---|
| 1 | Chuẩn hóa GHCR owner lowercase; release/CD dùng cùng prefix, kiểm tra manifest trước deploy | `test_canonical_ghcr_prefix` |
| 2 | OCR re-query qua agent, cache scope theo ảnh và chữ, evidence gate, giữ nguồn visual đủ mạnh nếu re-query yếu, OCR text tách khỏi citation | `test_ocr_requeries_sict_text_and_updates_citations`, `test_ocr_weak_requery_keeps_verified_visual_and_isolates_cache`, `test_ocr_bad_or_empty_response_preserves_visual`, `test_ocr_out_of_scope_skips_network`, `test_hybrid_chat_ocr_after_retrieval_before_answer` |
| 3 | Embedding fail closed khi thiếu cấu hình; thiếu/sai key bị reject trước inference; health tối giản và metrics có auth | `test_http_contract_matches_embedder_client`, `test_embed_server_fails_closed_without_key` |
| 4 | Repo allowlist, SHA 40 ký tự, xác minh HEAD, image digest, capability job thay owner token | `vercel/tests/launch-sandbox.test.mjs`, `test_capability_job_scope_expiry_and_owner_only_input` |
| 5 | Capability scope/expiry/rate limit, lease/CAS, checksum, proxy 4 MiB/direct 8 MiB | `test_capability_scopes_and_rate_limit`, `test_lease_checkpoint_resume_and_manifest`, `test_invalid_artifacts_checksum_missing_output_and_cleanup`, `vercel/tests/jobs.test.mjs` (artifact vượt budget trả 413) |
| 6 | Chặn writer chưa staging, đổi tên graph/reconcile thành báo cáo read-only | `test_job_kind_contract_rejects_unimplemented_writers`, `test_report_gateway_scope_lease_and_fixed_commands`, `test_reconcile_graph_read_only_reports` |
| 7 | Dependency image chuẩn bị trước, pin digest, offline lock check, giới hạn deadline, checkpoint/resume | `test_sandbox_image.py`, `test_sandbox_resume_from_uploaded_manifest_after_crash`, `test_sandbox_pauses_at_deadline_then_resumes`, Docker offline smoke |

## E2E local

`test_video_proxy_runner_http_resume` chạy Vercel Web handler với fetch HTTP
thật tới FastAPI/Uvicorn trên loopback, tạo job và upload video tổng hợp, cấp
capability, kiểm tra auth, runner dừng theo deadline, resume ở attempt 2, ffmpeg
trích frame thật, kiểm chứng SHA256 artifact và retry idempotent khi job đã
succeeded. Dữ liệu/state dùng thư mục tạm, không ghi datastore production.

OCR engine được smoke riêng bằng Node handler thật, ảnh PNG sinh local và
Tesseract.js với traineddata vie/eng. Luồng re-query và citation được kiểm chứng
bằng test orchestration với retrieval fixture. Chưa có E2E ảnh thật qua toàn
bộ retrieval live + LLM; evidence gate dựa trên sufficient/provenance hiện có,
chất lượng liên quan giữa OCR và nguồn SICT vẫn cần đánh giá trên golden.

## Release gate còn mở

Task 8 và phần cloud của Task 9 chưa nghiệm thu. CI/release/CD hiện tại, VCR,
Vercel cloud, hai VM và datastore thật chưa được chạy. Theo yêu cầu trước của
owner, chưa chạy lại benchmark retrieval/RAGAS; do Task 2 đổi context, các
dataset và RAGAS trong PLAN_FIX vẫn là gate chưa có kết quả mới (N/A).
Xem [mvp-cloud-verification.md](mvp-cloud-verification.md).

Kết luận: các kiểm thử local đã chạy đều pass. Chưa đạt điều kiện public release
toàn bộ theo PLAN_FIX. Không commit/push/deploy trong lần kiểm chứng này.
