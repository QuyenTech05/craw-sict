import { errorResponse, makeRequestId, parseImage, recognizeImage } from '../lib/ocr.mjs';

// Web-standard Vercel Function. Ảnh chỉ giữ trong RAM cho request này.
export async function handler(request, options = {}) {
  if (request.method !== 'POST') return Response.json({ error: 'Method not allowed' }, { status: 405 });
  const requiredToken = process.env.MVP_OCR_TOKEN;
  if (!requiredToken) return Response.json({ error: 'OCR chưa được cấu hình' }, { status: 503 });
  if (request.headers.get('authorization') !== `Bearer ${requiredToken}`) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const started = performance.now();
  const requestId = makeRequestId();
  try {
    const image = await parseImage(request, options);
    const result = await recognizeImage(image, { ...options, signal: AbortSignal.timeout(45000) });
    return Response.json({ ...result, elapsed_ms: Math.round(performance.now() - started), request_id: requestId },
      { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    return errorResponse(error);
  }
}

// Vercel Node.js Web Handler nhận Request và trả Response chuẩn Fetch API.
export default { fetch: handler };
