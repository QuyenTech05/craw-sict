import { authorized, jobApi } from '../lib/job-api.mjs';
import { createHash } from 'node:crypto';

const validId = (id) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id || '');
const validArtifact = (area, name) => ['input', 'work', 'output'].includes(area)
  && typeof name === 'string' && name.length < 150
  && name.split('/').every((part) => part && part !== '.' && part !== '..' && !part.includes('\\'));
const MAX_FUNCTION_BODY_BYTES = 4 * 1024 * 1024;
const MAX_FUNCTION_RESPONSE_BYTES = 4 * 1024 * 1024;

export async function handler(request, options = {}) {
  if (!authorized(request)) return Response.json({ error: 'Unauthorized' }, { status: 401 });
  try {
    const endpoint = new URL(request.url);
    const id = endpoint.searchParams.get('job_id');
    const area = endpoint.searchParams.get('area');
    const name = endpoint.searchParams.get('name');
    if (request.method !== 'POST' && !validId(id)) {
      return Response.json({ error: 'job_id invalid' }, { status: 422 });
    }
    if (request.method === 'GET') {
      if (endpoint.searchParams.has('manifest')) {
        return Response.json(await jobApi(`/${id}/manifest`, {}, options.http));
      }
      if (area !== null || name !== null) {
        if (!validArtifact(area, name)) return Response.json({ error: 'artifact invalid' }, { status: 422 });
        const data = await jobApi(`/${id}/artifacts/${area}/${name}`, { binary: true }, options.http);
        if (data.length > MAX_FUNCTION_RESPONSE_BYTES) {
          return Response.json({ error: 'Artifact lớn: tải trực tiếp từ VM Job API' }, { status: 413 });
        }
        return new Response(data, { headers: {
          'Content-Type': 'application/octet-stream', 'Cache-Control': 'no-store',
        } });
      }
      return Response.json(await jobApi(`/${id}`, {}, options.http));
    }
    if (request.method === 'POST') {
      if (Number(request.headers.get('content-length') || 0) > MAX_FUNCTION_BODY_BYTES) {
        return Response.json({ error: 'job body too large' }, { status: 413 });
      }
      const raw = await request.text();
      if (Buffer.byteLength(raw) > MAX_FUNCTION_BODY_BYTES) {
        return Response.json({ error: 'job body too large' }, { status: 413 });
      }
      let payload;
      try { payload = JSON.parse(raw); }
      catch { return Response.json({ error: 'Invalid JSON' }, { status: 400 }); }
      return Response.json(await jobApi('', { method: 'POST', json: payload }, options.http));
    }
    if (request.method === 'PUT') {
      if (!validArtifact(area, name)) return Response.json({ error: 'artifact invalid' }, { status: 422 });
      if (Number(request.headers.get('content-length') || 0) > MAX_FUNCTION_BODY_BYTES) {
        return Response.json({ error: 'artifact too large' }, { status: 413 });
      }
      const bytes = Buffer.from(await request.arrayBuffer());
      if (bytes.length > MAX_FUNCTION_BODY_BYTES) return Response.json({ error: 'artifact too large' }, { status: 413 });
      const sha256 = createHash('sha256').update(bytes).digest('hex');
      const declared = request.headers.get('x-content-sha256');
      if (declared && declared !== sha256) return Response.json({ error: 'checksum mismatch' }, { status: 422 });
      const attempt = request.headers.get('x-job-attempt');
      if (area !== 'input' && (!attempt || !/^[1-9]\d*$/.test(attempt))) {
        return Response.json({ error: 'X-Job-Attempt required' }, { status: 422 });
      }
      return Response.json(await jobApi(`/${id}/artifacts/${area}/${name}`,
        { method: 'PUT', bytes, sha256, attempt: attempt === null ? undefined : attempt }, options.http));
    }
    return Response.json({ error: 'Method not allowed' }, { status: 405 });
  } catch (error) {
    return Response.json({ error: error.status ? `Job API status ${error.status}` : 'Job API unavailable' },
      { status: error.status && error.status >= 400 && error.status < 500 ? error.status : 502 });
  }
}

export default { fetch: handler };
