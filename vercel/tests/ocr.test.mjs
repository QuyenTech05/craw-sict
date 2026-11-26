import assert from 'node:assert/strict';
import { test } from 'node:test';
import ocrEntry, { handler as ocr } from '../api/ocr.mjs';
import { decodeBase64, MAX_IMAGE_BYTES, parseImage } from '../lib/ocr.mjs';

// PNG tối thiểu được dùng để kiểm tra contract, OCR luôn mock để tránh tải model khi test.
const image = Buffer.from('89504e470d0a1a0a0000000d49484452', 'hex');
const send = (body, headers = {}) => new Request('https://demo.vercel.app/api/ocr', {
  method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ocr-key', ...headers },
  body: JSON.stringify(body),
});

test('OCR entrypoint dùng Web fetch handler của Vercel', () => {
  assert.equal(ocrEntry.fetch, ocr);
});

test('OCR một ảnh trả text, confidence, elapsed và request_id', async (t) => {
  const previous = process.env.MVP_OCR_TOKEN;
  process.env.MVP_OCR_TOKEN = 'ocr-key';
  try {
    const result = await ocr(send({ image_base64: image.toString('base64') }), {
      recognize: async () => ({ text: 'Chào SICT', language: 'vie+eng', confidence: 93 }),
    });
    assert.equal(result.status, 200);
    const payload = await result.json();
    assert.equal(payload.text, 'Chào SICT');
    assert.equal(payload.language, 'vie+eng');
    assert.equal(payload.confidence, 93);
    assert.match(payload.request_id, /^[0-9a-f-]{36}$/);
    assert.ok(payload.elapsed_ms >= 0);
    assert.equal(result.headers.get('Cache-Control'), 'no-store');
  } finally {
    if (previous === undefined) delete process.env.MVP_OCR_TOKEN;
    else process.env.MVP_OCR_TOKEN = previous;
  }
});

test('OCR từ chối thiếu token, ảnh hỏng, ảnh quá lớn và timeout', async () => {
  const old = process.env.MVP_OCR_TOKEN;
  process.env.MVP_OCR_TOKEN = 'ocr-key';
  try {
    assert.equal((await ocr(send({ base64: image.toString('base64') },
      { Authorization: 'Bearer wrong' }))).status, 401);
    assert.equal((await ocr(send({ base64: 'SGVsbG8=' }))).status, 422);
    assert.equal((await ocr(send({ base64: image.toString('base64') }), {
      recognize: async () => { throw new DOMException('Timed out', 'TimeoutError'); },
    })).status, 504);
    assert.throws(() => decodeBase64('a'.repeat(6_000_000)), { status: 413 });
    assert.rejects(parseImage(send({ image_url: 'http://127.0.0.1/private' }), {}), { status: 422 });
  } finally {
    if (old === undefined) delete process.env.MVP_OCR_TOKEN;
    else process.env.MVP_OCR_TOKEN = old;
  }
});

test('OCR nhận được ảnh PNG chính xác 3 MiB qua JSON base64', async () => {
  const payload = Buffer.alloc(MAX_IMAGE_BYTES);
  image.copy(payload);
  const parsed = await parseImage(send({ image_base64: payload.toString('base64') }));
  assert.equal(parsed.length, MAX_IMAGE_BYTES);
  const oversized = Buffer.concat([payload, Buffer.from([0])]);
  await assert.rejects(parseImage(send({ image_base64: oversized.toString('base64') })),
    { status: 413 });
});

test('OCR nhận multipart ảnh và từ chối JSON null', async () => {
  const form = new FormData();
  form.append('image', new File([image], 'poster.png', { type: 'image/png' }));
  const multipart = new Request('https://demo.vercel.app/api/ocr', {
    method: 'POST', body: form,
  });
  assert.deepEqual(await parseImage(multipart), image);
  await assert.rejects(parseImage(new Request('https://demo.vercel.app/api/ocr', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: 'null',
  })), { status: 422 });
});
