# Vercel Function OCR on-demand

Code nằm ở `vercel/api/ocr.mjs` và `vercel/lib/ocr.mjs`. Chọn **Root Directory `vercel/`** khi tạo Vercel project. Project Node >=22, dependency `tesseract.js`, cấu hình function trong `vercel/vercel.json`. Ba entrypoint `api/ocr.mjs`, `api/ocr-batch.mjs`, `api/jobs.mjs` dùng `export default { fetch: handler }` để Vercel truyền Web `Request` và nhận Web `Response`. Đây là demo MVP, giới hạn timeout/size phải kiểm chứng trên gói Vercel thực trước khi public.

Với Fluid compute, lựa chọn Function Standard **2 GiB / 1 vCPU** trong Project Settings. Vercel quản lý CPU/RAM theo tier nên `vercel.json` chỉ chốt `maxDuration`, không đặt cứng `memory`.

## API và xác thực

`POST /api/ocr` yêu cầu header `Authorization: Bearer <MVP_OCR_TOKEN>`. Function chỉ nhận `image/png`, `image/jpeg`, `image/webp`, tối đa **3 MiB ảnh giải mã** và khoảng **4 MiB JSON/body**. Có thể gửi multipart `image` hoặc JSON:

```json
{"image_base64":"<base64-encoded-image>"}
```

Ngoài `image_base64` còn hỗ trợ `base64` và `image_url`. Với `image_url`, host phải thuộc `OCR_IMAGE_HOSTS`, dùng HTTPS, DNS trả IP public và không cho redirect tới host khác. Không nhận URL đến localhost/private IP. Response thành công:

```json
{"text":"Hội thảo công nghệ", "language":"vie+eng", "confidence":91.2, "elapsed_ms":1250, "request_id":"<uuid>"}
```

Tesseract.js tạo worker `vie+eng` theo request, dùng `TESSDATA_URL` nếu đặt, mặc định tải traineddata từ địa chỉ được khai báo trong code. Thời hạn OCR ở handler là **45 giây** trong Function tối đa **60 giây**. Lỗi validation trả 400/413/415/422, chưa cấu hình trả 503, timeout trả 504, lỗi OCR trả 502. Dữ liệu ảnh chỉ ở memory request, response có `Cache-Control: no-store`. Không dùng `/tmp` để giữ OCR lâu dài.

## Tích hợp retrieval

VM API gọi `add_query_ocr` trong `sict_crawler/api/mvp_ocr.py` sau khi retrieval ảnh đã xong, trước khi sinh câu trả lời. Khi `MVP_OCR_POLICY=weak`, OCR chỉ kích hoạt khi `sufficient=false` hoặc câu hỏi muốn đọc chữ. Khi `always`, mọi query kèm ảnh đủ điều kiện đều thử OCR. VM dùng timeout HTTP **18 giây** và chỉ gửi ảnh tối đa 3 MiB.

Khi OCR trả text, API tìm lại SICT bằng câu hỏi kết hợp OCR (text-only) trong budget embedding. Nếu retrieval mới đủ evidence, context và citations lấy từ kết quả tìm lại. Khi không có evidence đủ, chỉ trả OCR với nhãn chưa xác minh và loại citations/context không liên quan. Trường hợp Function lỗi hoặc trả rỗng, response tiếp tục theo dữ liệu retrieval ban đầu.

## Kiểm chứng

Test offline/mock ở `vercel/tests/ocr.test.mjs` và `tests/test_mvp_ocr_fallback.py` bao gồm success, token, ảnh sai định dạng, quá size, timeout và thứ tự retrieval → OCR → text re-query → answer. Cần chạy thêm trên Vercel thật với ảnh poster tiếng Việt, ảnh banner không chữ, ảnh WebP và trường hợp thiếu traineddata để đo latency, cold start, chất lượng OCR.
