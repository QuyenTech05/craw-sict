export function authorized(request) {
  const token = process.env.MVP_JOB_TOKEN;
  return Boolean(token) && request.headers.get('authorization') === `Bearer ${token}`;
}

export async function jobApi(path, { method = 'GET', json, bytes, sha256, attempt, binary = false } = {}, http = fetch) {
  const base = process.env.SICT_API_BASE;
  const token = process.env.MVP_JOB_TOKEN;
  if (!base || !token) throw new Error('Missing job API configuration');
  const url = new URL(`/internal/jobs${path}`, base.endsWith('/') ? base : `${base}/`);
  const headers = { Authorization: `Bearer ${token}` };
  if (json !== undefined) headers['Content-Type'] = 'application/json';
  if (sha256) headers['X-Content-SHA256'] = sha256;
  if (attempt !== undefined) headers['X-Job-Attempt'] = String(attempt);
  const response = await http(url, { method, headers,
    body: json !== undefined ? JSON.stringify(json) : bytes,
    signal: AbortSignal.timeout(8000) });
  if (!response.ok) {
    const error = new Error(`Job API status ${response.status}`);
    error.status = response.status;
    throw error;
  }
  if (binary) {
    const limit = 4 * 1024 * 1024;
    if (Number(response.headers.get('content-length') || 0) > limit) {
      const error = new Error('Artifact vượt 4 MiB');
      error.status = 413;
      throw error;
    }
    const payload = Buffer.from(await response.arrayBuffer());
    if (payload.length > limit) {
      const error = new Error('Artifact vượt 4 MiB');
      error.status = 413;
      throw error;
    }
    return payload;
  }
  return response.json();
}
