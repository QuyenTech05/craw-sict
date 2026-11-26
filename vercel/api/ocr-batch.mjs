import { createHash } from 'node:crypto';
import { authorized, jobApi } from '../lib/job-api.mjs';
import { decodeBase64, errorResponse, InputError, recognizeImage, sniffImage } from '../lib/ocr.mjs';

// Vercel Function giới hạn body 4.5 MiB; giữ thêm headroom cho JSON.
const MAX_BATCH_BODY_BYTES = 4 * 1024 * 1024;

// Mỗi Function xử lý tối đa 3 ảnh. Checkpoint lưu trên VM sau từng ảnh.
export async function handler(request, options = {}) {
  if (!authorized(request)) return Response.json({ error: 'Unauthorized' }, { status: 401 });
  if (request.method !== 'POST') return Response.json({ error: 'Method not allowed' }, { status: 405 });
  let state;
  try {
    if (Number(request.headers.get('content-length') || 0) > MAX_BATCH_BODY_BYTES) {
      throw new InputError('Batch vượt 4 MiB', 413);
    }
    const raw = await request.text();
    if (Buffer.byteLength(raw) > MAX_BATCH_BODY_BYTES) throw new InputError('Batch vượt 4 MiB', 413);
    let body;
    try { body = JSON.parse(raw); } catch { throw new InputError('JSON không hợp lệ', 400); }
    if (!body || typeof body !== 'object' || Array.isArray(body)
        || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(body.job_id || '')
        || !Array.isArray(body.items)
        || body.items.length < 1 || body.items.length > 3) {
      throw new InputError('Cần UUID job_id và 1–3 ảnh');
    }
    const items = body.items.map((item) => {
      if (!item || typeof item !== 'object' || Array.isArray(item)
          || typeof item.id !== 'string' || !/^[a-zA-Z0-9_-]{1,40}$/.test(item.id)
          || typeof item.base64 !== 'string' || item.base64.length > 5_600_000) {
        throw new InputError('Item hoặc ảnh không hợp lệ');
      }
      const image = sniffImage(decodeBase64(item.base64));
      return { id: item.id, image };
    });
    if (new Set(items.map((item) => item.id)).size !== items.length) {
      return Response.json({ error: 'Duplicate item id' }, { status: 422 });
    }
    const imageHashes = items.map(({ id, image }) =>
      [id, createHash('sha256').update(image).digest('hex')]);
    const fingerprint = createHash('sha256').update(JSON.stringify(imageHashes)).digest('hex');
    const created = await jobApi('', { method: 'POST', json: { job_id: body.job_id, kind: 'ocr',
      input_fingerprint: fingerprint } }, options.http);
    if (created.status === 'succeeded') return Response.json(created);
    // Job mới luôn có input manifest. Với job đời cũ đã claim trước khi
    // cơ chế này xuất hiện, cho phép resume qua fingerprint/checkpoint/output.
    const inputManifest = Buffer.from(JSON.stringify({ items: imageHashes.map(([id, sha256]) =>
      ({ id, sha256 })) }));
    const hasInputManifest = created.status === 'queued' || Boolean(
      (await jobApi(`/${body.job_id}/manifest`, {}, options.http)).artifacts?.['input/items.json']);
    if (hasInputManifest) {
      await jobApi(`/${body.job_id}/artifacts/input/items.json`, {
        method: 'PUT', bytes: inputManifest,
        sha256: createHash('sha256').update(inputManifest).digest('hex'),
      }, options.http);
    }
    state = await jobApi(`/${body.job_id}/claim`, { method: 'POST' }, options.http);
    if (state.status === 'succeeded') return Response.json(state);
    const checkpoint = state.checkpoint?.completed ?? [];
    if (!Array.isArray(checkpoint) || checkpoint.some((id) => !items.some((item) => item.id === id))
        || new Set(checkpoint).size !== checkpoint.length) {
      throw new InputError('Checkpoint chứa item không hợp lệ', 409);
    }
    const completed = new Set(checkpoint);
    const artifacts = (await jobApi(`/${body.job_id}/manifest`, {}, options.http)).artifacts;
    const deadline = performance.now() + 42000;
    for (const item of items) {
      const outputName = `output/${item.id}.json`;
      if (completed.has(item.id) && !artifacts[outputName]) {
        throw new InputError(`Checkpoint thiếu artifact ${item.id}`, 409);
      }
      // Manifest chỉ chứa metadata. GET sẽ kiểm tra SHA256 tại VM trước khi
      // tin output của phiên trước, kể cả item đã được checkpoint.
      if (artifacts[outputName]) {
        const saved = await jobApi(`/${body.job_id}/artifacts/${outputName}`,
          { binary: true }, options.http);
        let result;
        try { result = JSON.parse(saved.toString('utf8')); }
        catch { throw new InputError(`Artifact OCR ${item.id} có JSON hỏng`, 409); }
        if (result?.id !== item.id || typeof result.text !== 'string'
            || typeof result.language !== 'string') {
          throw new InputError(`Artifact OCR ${item.id} có nội dung không hợp lệ`, 409);
        }
      }
      if (completed.has(item.id)) continue;
      if (performance.now() >= deadline - 3000) break;
      // Worker có thể chết sau PUT, trước PATCH. Manifest bất biến sẽ xác nhận item.
      if (!artifacts[outputName]) {
        const remaining = Math.max(1000, Math.min(30000, deadline - performance.now() - 3000));
        const result = await recognizeImage(item.image, {
          ...options, signal: AbortSignal.timeout(remaining),
        });
        if (!result || typeof result.text !== 'string' || typeof result.language !== 'string') {
          throw new InputError(`OCR trả dữ liệu không hợp lệ cho ${item.id}`, 502);
        }
        const bytes = Buffer.from(JSON.stringify({ ...result, id: item.id }));
        const sha256 = createHash('sha256').update(bytes).digest('hex');
        await jobApi(`/${body.job_id}/artifacts/output/${item.id}.json`,
          { method: 'PUT', bytes, sha256, attempt: state.attempt }, options.http);
      }
      completed.add(item.id);
      state = await jobApi(`/${body.job_id}`, { method: 'PATCH', json: {
        expected_attempt: state.attempt, expected_revision: state.revision,
        status: 'running', checkpoint: { completed: [...completed] },
      } }, options.http);
    }
    state = await jobApi(`/${body.job_id}`, { method: 'PATCH', json: {
      expected_attempt: state.attempt, expected_revision: state.revision,
      status: completed.size === items.length ? 'succeeded' : 'paused',
      checkpoint: { completed: [...completed] },
    } }, options.http);
    return Response.json(state, { status: state.status === 'paused' ? 202 : 200 });
  } catch (error) {
    if (state?.status === 'running') {
      try {
        state = await jobApi(`/${state.job_id}`, { method: 'PATCH', json: {
          expected_attempt: state.attempt, expected_revision: state.revision,
          status: 'paused', checkpoint: state.checkpoint,
        } }, options.http);
      } catch { /* Lease hết hạn sẽ được claim lại ở lần gọi sau. */ }
    }
    if ((error.name === 'TimeoutError' || error.name === 'AbortError') && state?.status === 'paused') {
      return Response.json(state, { status: 202 });
    }
    return errorResponse(error);
  }
}

export default { fetch: handler };
