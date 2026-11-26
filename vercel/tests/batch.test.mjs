import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import batchEntry, { handler as batch } from '../api/ocr-batch.mjs';

const id = '2d29490d-7e05-4c8d-8845-61c21f28e7f0';
const png = Buffer.from('89504e470d0a1a0a0000000d49484452', 'hex').toString('base64');
const items = [{ id: 'poster', base64: png }, { id: 'banner', base64: png }];

test('OCR batch entrypoint dùng Web fetch handler của Vercel', () => {
  assert.equal(batchEntry.fetch, batch);
});

function createFakeGateway() {
  let state;
  const artifacts = {};
  const files = {};
  const uploads = [];
  async function http(url, init) {
    const path = url.pathname.replace('/internal/jobs', '');
    const input = init.body && init.headers['Content-Type'] === 'application/json'
      ? JSON.parse(init.body) : null;
    if (path === '' && init.method === 'POST') {
      if (state && state.input_fingerprint !== input.input_fingerprint) return Response.json({}, { status: 409 });
      state ??= { job_id: input.job_id, kind: input.kind, input_fingerprint: input.input_fingerprint,
        status: 'queued', attempt: 0, revision: 0, checkpoint: {} };
      return Response.json(state);
    }
    if (path.endsWith('/claim') && init.method === 'POST') {
      if (state.status !== 'succeeded') {
        state = { ...state, status: 'running', attempt: state.attempt + 1, revision: state.revision + 1 };
      }
      return Response.json(state);
    }
    if (path.endsWith('/manifest')) return Response.json({ artifacts });
    if (path.endsWith('/artifacts/input/items.json') && init.method === 'PUT') {
      assert.equal(state.status === 'queued' || Boolean(files['input/items.json']), true);
      const bytes = Buffer.from(init.body);
      const sha256 = createHash('sha256').update(bytes).digest('hex');
      assert.equal(init.headers['X-Content-SHA256'], sha256);
      if (files['input/items.json']) {
        assert.deepEqual(files['input/items.json'], bytes);
      } else {
        files['input/items.json'] = bytes;
        artifacts['input/items.json'] = { sha256 };
      }
      return Response.json(artifacts['input/items.json']);
    }
    if (path.includes('/artifacts/output/') && init.method === 'GET') {
      const name = path.slice(path.lastIndexOf('/') + 1);
      const key = `output/${name}`;
      if (!files[key]) return Response.json({}, { status: 404 });
      const digest = createHash('sha256').update(files[key]).digest('hex');
      if (digest !== artifacts[key]?.sha256) return Response.json({}, { status: 409 });
      return new Response(files[key]);
    }
    if (path.includes('/artifacts/output/') && init.method === 'PUT') {
      assert.equal(init.headers['X-Job-Attempt'], String(state.attempt));
      const name = path.slice(path.lastIndexOf('/') + 1);
      files[`output/${name}`] = Buffer.from(init.body);
      artifacts[`output/${name}`] = { sha256: init.headers['X-Content-SHA256'] };
      uploads.push(name);
      return Response.json(artifacts[`output/${name}`]);
    }
    if (init.method === 'PATCH') {
      if (input.expected_attempt !== state.attempt || input.expected_revision !== state.revision) {
        return Response.json({}, { status: 409 });
      }
      state = { ...state, status: input.status, checkpoint: input.checkpoint, revision: state.revision + 1 };
      return Response.json(state);
    }
    throw Error(`Unexpected fake job API call ${path} ${init.method}`);
  }
  return { http, uploads, files, artifacts, getState: () => state,
    setCheckpoint: (completed) => {
      state = { ...state, status: 'paused', checkpoint: { completed } };
    },
  };
}

test('bounded OCR batch checkpoint mỗi ảnh, resume từ manifest/checkpoint', async () => {
  const previous = { SICT_API_BASE: process.env.SICT_API_BASE, MVP_JOB_TOKEN: process.env.MVP_JOB_TOKEN };
  process.env.SICT_API_BASE = 'https://vm.example';
  process.env.MVP_JOB_TOKEN = 'job-key';
  const gateway = createFakeGateway();
  const received = [];
  const req = () => new Request('https://demo.vercel.app/api/ocr-batch', {
    method: 'POST', headers: { Authorization: 'Bearer job-key', 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: id, items }),
  });
  try {
    const first = await batch(req(), { http: gateway.http, recognize: async (_bytes, _opts) => {
      received.push(received.length === 0 ? 'poster' : 'banner');
      if (received.length === 2) throw Error('simulated OCR crash');
      return { text: 'Kết quả ảnh', language: 'vie+eng' };
    } });
    assert.equal(first.status, 502);
    assert.equal(gateway.getState().status, 'paused');
    assert.deepEqual(gateway.getState().checkpoint.completed, ['poster']);
    const second = await batch(req(), { http: gateway.http, recognize: async () => {
      received.push('resume');
      return { text: 'Đã hồi phục', language: 'vie+eng' };
    } });
    assert.equal(second.status, 200);
    assert.equal((await second.json()).status, 'succeeded');
    assert.deepEqual(gateway.uploads, ['poster.json', 'banner.json']);
    assert.deepEqual(received, ['poster', 'banner', 'resume']);
    const third = await batch(req(), { http: gateway.http, recognize: async () => {
      throw Error('Không được OCR job đã hoàn thành');
    } });
    assert.equal(third.status, 200);
    assert.equal(gateway.uploads.length, 2);
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
});

test('OCR batch kiểm tra checkpoint và nội dung artifact trước khi resume', async () => {
  const previous = { SICT_API_BASE: process.env.SICT_API_BASE, MVP_JOB_TOKEN: process.env.MVP_JOB_TOKEN };
  process.env.SICT_API_BASE = 'https://vm.example';
  process.env.MVP_JOB_TOKEN = 'job-key';
  const gateway = createFakeGateway();
  const request = () => new Request('https://demo.vercel.app/api/ocr-batch', {
    method: 'POST', headers: { Authorization: 'Bearer job-key', 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: id, items }),
  });
  let calls = 0;
  const options = { http: gateway.http, recognize: async () => {
    calls += 1;
    return { text: 'Bản OCR', language: 'vie+eng' };
  } };
  try {
    assert.equal((await batch(request(), options)).status, 200);
    assert.equal(calls, 2);

    // Crash giữa upload và checkpoint: chỉ GET artifact, không OCR lần nữa.
    gateway.setCheckpoint([]);
    assert.equal((await batch(request(), options)).status, 200);
    assert.equal(calls, 2);

    gateway.setCheckpoint(['poster']);
    delete gateway.artifacts['output/poster.json'];
    assert.equal((await batch(request(), options)).status, 409);
    assert.equal(calls, 2);

    gateway.setCheckpoint(['khong_co_trong_input']);
    assert.equal((await batch(request(), options)).status, 409);
    assert.equal(calls, 2);

    gateway.setCheckpoint([]);
    gateway.files['output/poster.json'] = Buffer.from('corrupted');
    gateway.artifacts['output/poster.json'] = { sha256: 'a'.repeat(64) };
    assert.equal((await batch(request(), options)).status, 409);

    const invalid = Buffer.from(JSON.stringify({ id: 'wrong', text: 'x', language: 'vie+eng' }));
    gateway.files['output/poster.json'] = invalid;
    gateway.artifacts['output/poster.json'] = {
      sha256: createHash('sha256').update(invalid).digest('hex'),
    };
    assert.equal((await batch(request(), options)).status, 409);
    assert.equal(calls, 2);

    // Job paused từ bản cũ không có input/items.json vẫn resume theo
    // fingerprint, checkpoint và output artifact đã xác thực checksum.
    const valid = Buffer.from(JSON.stringify({ id: 'poster', text: 'Bản OCR', language: 'vie+eng' }));
    gateway.files['output/poster.json'] = valid;
    gateway.artifacts['output/poster.json'] = {
      sha256: createHash('sha256').update(valid).digest('hex'),
    };
    delete gateway.files['input/items.json'];
    delete gateway.artifacts['input/items.json'];
    gateway.setCheckpoint([]);
    const legacyResume = await batch(request(), options);
    assert.equal(legacyResume.status, 200);
    assert.equal((await legacyResume.json()).status, 'succeeded');
    assert.equal(calls, 2);
    assert.equal(gateway.files['input/items.json'], undefined);
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
});

test('OCR batch từ chối JSON null và không checkpoint kết quả OCR sai cấu trúc', async () => {
  const previous = { SICT_API_BASE: process.env.SICT_API_BASE, MVP_JOB_TOKEN: process.env.MVP_JOB_TOKEN };
  process.env.SICT_API_BASE = 'https://vm.example';
  process.env.MVP_JOB_TOKEN = 'job-key';
  const gateway = createFakeGateway();
  const request = (payload) => new Request('https://demo.vercel.app/api/ocr-batch', {
    method: 'POST', headers: { Authorization: 'Bearer job-key', 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  try {
    assert.equal((await batch(request(null), { http: gateway.http })).status, 422);
    assert.equal((await batch(request({ job_id: id, items: [null] }),
      { http: gateway.http })).status, 422);
    assert.equal(gateway.getState(), undefined);
    const bad = await batch(request({ job_id: id, items: [items[0]] }), {
      http: gateway.http, recognize: async () => ({ text: 42, language: 'vie+eng' }),
    });
    assert.equal(bad.status, 502);
    assert.equal(gateway.getState().status, 'paused');
    assert.deepEqual(gateway.getState().checkpoint.completed ?? [], []);
    assert.equal(gateway.artifacts['output/poster.json'], undefined);

    const good = await batch(request({ job_id: id, items: [items[0]] }), {
      http: gateway.http, recognize: async () => ({ id: 'wrong', text: 'Poster', language: 'vie+eng' }),
    });
    assert.equal(good.status, 200);
    assert.equal((await good.json()).status, 'succeeded');
    assert.deepEqual(gateway.uploads, ['poster.json']);
    assert.equal(JSON.parse(gateway.files['output/poster.json']).id, 'poster');
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
});
