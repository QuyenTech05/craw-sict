import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import jobsEntry, { handler as jobs } from '../api/jobs.mjs';
import { jobApi } from '../lib/job-api.mjs';

const jobId = 'd7a8b3af-40c2-4bcc-80c1-a05a86b77d10';
const api = 'https://demo.vercel.app/api/jobs';
const auth = { Authorization: 'Bearer job-key' };

test('Job proxy entrypoint dùng Web fetch handler của Vercel', () => {
  assert.equal(jobsEntry.fetch, jobs);
});

test('Job proxy GET state/manifest/download, PUT upload checksum', async () => {
  const prev = { SICT_API_BASE: process.env.SICT_API_BASE, MVP_JOB_TOKEN: process.env.MVP_JOB_TOKEN };
  process.env.SICT_API_BASE = 'https://vm.example';
  process.env.MVP_JOB_TOKEN = 'job-key';
  const seen = [];
  const http = async (url, init) => {
    seen.push([url.pathname, init]);
    if (init.method === 'PUT') return Response.json({ bytes: init.body.length, sha256: init.headers['X-Content-SHA256'] });
    if (url.pathname.includes('/artifacts/')) return new Response(Buffer.from('file bytes'));
    return Response.json(url.pathname.endsWith('/manifest') ? { artifacts: {} } : { status: 'queued' });
  };
  try {
    const state = await jobs(new Request(`${api}?job_id=${jobId}`, { headers: auth }), { http });
    assert.equal((await state.json()).status, 'queued');
    const manifest = await jobs(new Request(`${api}?job_id=${jobId}&manifest=1`, { headers: auth }), { http });
    assert.deepEqual((await manifest.json()).artifacts, {});
    const url = `${api}?job_id=${jobId}&area=input&name=items.json`;
    const content = Buffer.from('file bytes');
    const put = await jobs(new Request(url, { method: 'PUT', headers: auth, body: content }), { http });
    assert.equal(put.status, 200);
    assert.equal((await put.json()).sha256, createHash('sha256').update(content).digest('hex'));
    assert.equal(seen.at(-1)[1].headers['X-Content-SHA256'], createHash('sha256').update(content).digest('hex'));
    const get = await jobs(new Request(url, { headers: auth }), { http });
    assert.equal(Buffer.from(await get.arrayBuffer()).toString(), 'file bytes');
    assert.equal(get.headers.get('Cache-Control'), 'no-store');
    assert.equal((await jobs(new Request(`${api}?job_id=${jobId}&area=output&name=x`, {
      method: 'PUT', headers: auth, body: 'x',
    }), { http })).status, 422);
    assert.equal((await jobs(new Request(`${api}?job_id=${jobId}&area=input&name=../x`, {
      method: 'PUT', headers: auth, body: 'x',
    }), { http })).status, 422);
    assert.equal((await jobs(new Request(api, { headers: { Authorization: 'Bearer wrong' } }), { http })).status, 401);
  } finally {
    for (const [key, val] of Object.entries(prev)) {
      if (val === undefined) delete process.env[key];
      else process.env[key] = val;
    }
  }
});

test('jobApi chuyển mã lỗi upstream và đọc nhị phân', async () => {
  const old = { SICT_API_BASE: process.env.SICT_API_BASE, MVP_JOB_TOKEN: process.env.MVP_JOB_TOKEN };
  process.env.SICT_API_BASE = 'https://vm.example';
  process.env.MVP_JOB_TOKEN = 'job-key';
  try {
    await assert.rejects(jobApi(`/${jobId}`, {}, async () => Response.json({ error: 'conflict' }, { status: 409 })),
      { status: 409 });
    assert.deepEqual(await jobApi(`/${jobId}/artifacts/input/a`, { binary: true },
      async () => new Response(Uint8Array.of(1, 2, 3))), Buffer.from([1, 2, 3]));
  } finally {
    for (const [key, val] of Object.entries(old)) {
      if (val === undefined) delete process.env[key];
      else process.env[key] = val;
    }
  }
});

test('GET artifact vượt response budget của Function trả 413', async () => {
  const previous = { SICT_API_BASE: process.env.SICT_API_BASE, MVP_JOB_TOKEN: process.env.MVP_JOB_TOKEN };
  process.env.SICT_API_BASE = 'https://vm.example';
  process.env.MVP_JOB_TOKEN = 'job-key';
  try {
    const url = `${api}?job_id=${jobId}&area=output&name=large.tar.gz`;
    const result = await jobs(new Request(url, { headers: auth }), {
      http: async () => new Response(Buffer.alloc(4 * 1024 * 1024 + 1)),
    });
    assert.equal(result.status, 413);
    const bigger = await jobs(new Request(url, { headers: auth }), {
      http: async () => new Response(Buffer.alloc(8 * 1024 * 1024 + 1)),
    });
    assert.equal(bigger.status, 413);
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
});
