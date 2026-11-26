import { lookup } from 'node:dns/promises';
import { randomUUID } from 'node:crypto';
import https from 'node:https';

// Vercel giới hạn request ~4.5 MiB. Ảnh 3 MiB mã hóa base64 thành 4 MiB.
export const MAX_IMAGE_BYTES = 3 * 1024 * 1024;
const MAX_BODY_BYTES = 4 * 1024 * 1024 + 64 * 1024;
const ALLOWED_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);

export class InputError extends Error {
  constructor(message, status = 422) {
    super(message);
    this.status = status;
  }
}

export function decodeBase64(raw) {
  if (typeof raw !== 'string') throw new InputError('Thiếu ảnh base64');
  const stripped = raw.replace(/^data:image\/(png|jpeg|webp);base64,/, '');
  if (stripped.length > Math.ceil(MAX_IMAGE_BYTES * 4 / 3) + 8) {
    throw new InputError('Ảnh vượt 3 MiB', 413);
  }
  if (!stripped || stripped.length % 4 === 1 || !/^[A-Za-z0-9+/]*={0,2}$/.test(stripped)) {
    throw new InputError('Ảnh base64 không hợp lệ');
  }
  return Buffer.from(stripped, 'base64');
}

export function sniffImage(buffer) {
  const png = buffer.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  const jpg = buffer.length >= 3 && buffer[0] === 255 && buffer[1] === 216 && buffer[2] === 255;
  const webp = buffer.toString('ascii', 0, 4) === 'RIFF'
    && buffer.toString('ascii', 8, 12) === 'WEBP';
  if (!png && !jpg && !webp) throw new InputError('Chỉ hỗ trợ PNG, JPEG, WebP');
  if (buffer.length > MAX_IMAGE_BYTES) throw new InputError('Ảnh vượt 3 MiB', 413);
  return buffer;
}

function isPrivateIp(address) {
  if (address.includes(':')) {
    const ip = address.toLowerCase();
    return ip === '::1' || ip.startsWith('fc') || ip.startsWith('fd') || ip.startsWith('fe80')
      || ip.startsWith('::ffff:');
  }
  const chunks = address.split('.').map(Number);
  return chunks[0] === 0 || chunks[0] === 10 || chunks[0] === 127 || chunks[0] >= 224
    || (chunks[0] === 169 && chunks[1] === 254)
    || (chunks[0] === 172 && chunks[1] >= 16 && chunks[1] <= 31)
    || (chunks[0] === 192 && chunks[1] === 168)
    || (chunks[0] === 192 && chunks[1] === 0 && chunks[2] === 0)
    || (chunks[0] === 198 && chunks[1] >= 18 && chunks[1] <= 19)
    || (chunks[0] === 100 && chunks[1] >= 64 && chunks[1] <= 127);
}

async function fetchImageUrl(imageUrl, { resolver = lookup, requestHttps = https.request } = {}) {
  let url;
  try { url = new URL(imageUrl); } catch { throw new InputError('image_url không hợp lệ'); }
  const allowed = (process.env.OCR_IMAGE_HOSTS || '').split(',').map((x) => x.trim().toLowerCase()).filter(Boolean);
  if (url.protocol !== 'https:' || url.username || url.password || url.port || !allowed.includes(url.hostname.toLowerCase())) {
    throw new InputError('image_url phải là HTTPS thuộc OCR_IMAGE_HOSTS');
  }
  const addresses = await resolver(url.hostname, { all: true });
  if (!addresses.length || addresses.some((a) => isPrivateIp(a.address))) {
    throw new InputError('Host ảnh không có IP công khai');
  }
  // Ghim IP đã kiểm tra vào TLS connect để tránh DNS rebinding giữa lookup và GET.
  const address = addresses[0];
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    const req = requestHttps(url, {
      method: 'GET', timeout: 5000,
      lookup: (_, __, callback) => callback(null, address.address, address.family),
    }, (response) => {
      const contentType = response.headers['content-type']?.split(';')[0];
      const length = Number(response.headers['content-length'] || 0);
      if (response.statusCode !== 200 || !ALLOWED_TYPES.has(contentType)) {
        reject(new InputError('Không tải được ảnh hợp lệ', 502));
        response.destroy();
        return;
      }
      if (length > MAX_IMAGE_BYTES) {
        reject(new InputError('Ảnh vượt 3 MiB', 413));
        response.destroy();
        return;
      }
      response.on('data', (chunk) => {
        size += chunk.length;
        if (size > MAX_IMAGE_BYTES) {
          reject(new InputError('Ảnh vượt 3 MiB', 413));
          response.destroy();
        }
        else chunks.push(chunk);
      });
      response.on('end', () => resolve(Buffer.concat(chunks)));
      response.on('error', reject);
    });
    req.on('timeout', () => req.destroy(new DOMException('Timed out', 'TimeoutError')));
    req.on('error', reject);
    req.end();
  });
}

export async function parseImage(request, options) {
  if (Number(request.headers.get('content-length') || 0) > MAX_BODY_BYTES) {
    throw new InputError('Request vượt giới hạn OCR', 413);
  }
  const contentType = request.headers.get('content-type') || '';
  let buffer;
  if (contentType.startsWith('application/json')) {
    const raw = await request.text();
    if (Buffer.byteLength(raw) > MAX_BODY_BYTES) throw new InputError('Request vượt giới hạn OCR', 413);
    let body;
    try { body = JSON.parse(raw); } catch { throw new InputError('JSON không hợp lệ', 400); }
    if (!body || typeof body !== 'object' || Array.isArray(body)) {
      throw new InputError('JSON OCR phải là object');
    }
    if (body.image_url) buffer = await fetchImageUrl(body.image_url, options);
    else buffer = decodeBase64(body.image_base64 ?? body.base64);
  } else if (contentType.startsWith('multipart/form-data')) {
    const form = await request.formData();
    const image = form.get('image');
    if (!(image instanceof File)) throw new InputError('Thiếu file image');
    if (image.size > MAX_IMAGE_BYTES) throw new InputError('Ảnh vượt 3 MiB', 413);
    buffer = Buffer.from(await image.arrayBuffer());
  } else {
    throw new InputError('Content-Type phải là JSON hoặc multipart/form-data', 415);
  }
  return sniffImage(buffer);
}

export async function recognizeImage(image, { recognize, signal } = {}) {
  if (signal?.aborted) throw signal.reason;
  if (recognize) return Promise.race([
    recognize(image, { signal }),
    new Promise((_, reject) => signal?.addEventListener('abort', () => reject(signal.reason), { once: true })),
  ]);
  const { createWorker } = await import('tesseract.js');
  let worker;
  let termination;
  const terminate = () => {
    if (worker && !termination) termination = worker.terminate();
    return termination;
  };
  const abort = () => { void terminate(); };
  signal?.addEventListener('abort', abort, { once: true });
  try {
    const task = (async () => {
      worker = await createWorker(['vie', 'eng'], 1, {
        cacheMethod: 'none',
        langPath: process.env.TESSDATA_URL || 'https://tessdata.projectnaptha.com/4.0.0',
      });
      if (signal?.aborted) {
        await terminate();
        throw signal.reason;
      }
      return worker.recognize(image);
    })();
    const { data } = await Promise.race([
      task,
      new Promise((_, reject) => signal?.addEventListener('abort', () => reject(signal.reason), { once: true })),
    ]);
    return { text: data.text.trim().slice(0, 4096), language: 'vie+eng',
      confidence: Number.isFinite(data.confidence) ? data.confidence : null };
  } finally {
    signal?.removeEventListener('abort', abort);
    if (worker) await terminate();
  }
}

export function errorResponse(error) {
  const status = error instanceof InputError ? error.status
    : error?.status === 409 ? 409
    : error?.name === 'TimeoutError' || error?.name === 'AbortError' ? 504 : 502;
  return Response.json({ error: error instanceof InputError ? error.message
    : status === 409 ? 'Job/artifact xung đột, cần kiểm tra checkpoint'
    : status === 504 ? 'OCR hết thời gian chờ' : 'OCR không sẵn sàng' }, { status });
}

export function makeRequestId() { return randomUUID(); }
