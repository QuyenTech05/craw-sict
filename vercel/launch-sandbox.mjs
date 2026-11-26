import { Sandbox } from '@vercel/sandbox';
import { fileURLToPath } from 'node:url';
import { jobApi } from './lib/job-api.mjs';

const TRUSTED_REPOSITORY = 'https://github.com/quyentech05/craw-sict.git';
const JOB_KINDS = ['ocr', 'video', 'reconcile-dry-run', 'graph-stats', 'snapshot', 'compute'];

// Chạy CLI từ operator máy dev/CI có Vercel OIDC, không tự chạy trong Function.
export async function launchSandbox(jobId, {
  sdk = Sandbox, jobClient = jobApi, output = process.stdout, error = process.stderr,
} = {}) {
  const source = process.env.SICT_GIT_URL;
  const revision = process.env.SICT_GIT_REF;
  const api = process.env.SICT_API_BASE;
  const token = process.env.MVP_JOB_TOKEN;
  const image = process.env.SICT_SANDBOX_IMAGE;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(jobId || '')
      || !source || !revision || !api || !token || !image) {
    throw new Error('Cần job_id, SICT_GIT_URL, SICT_GIT_REF (SHA), SICT_API_BASE, MVP_JOB_TOKEN, SICT_SANDBOX_IMAGE');
  }
  if (source !== TRUSTED_REPOSITORY || !/^[0-9a-f]{40}$/.test(revision)) {
    throw new Error('Chỉ cho phép repository SICT tin cậy và immutable commit SHA 40 ký tự');
  }
  if (!api.startsWith('https://')) {
    throw new Error('Job API URL phải dùng HTTPS');
  }
  const state = await jobClient(`/${jobId}`);
  if (state.status === 'succeeded') return 0;
  if (!JOB_KINDS.includes(state.kind)) {
    throw new Error(`Sandbox chưa hỗ trợ job kind=${state.kind}`);
  }
  // Credential owner chỉ nằm ở operator. Code checkout nhận capability của job này.
  const scopes = ['read', 'write', 'claim'];
  if (['graph-stats', 'reconcile-dry-run'].includes(state.kind)) scopes.push('report');
  const capability = await jobClient(`/${jobId}/capabilities`, {
    method: 'POST', json: { scopes, ttl_seconds: 2700 },
  });
  if (!capability.token || capability.job_id !== jobId) {
    throw new Error('Job API không cấp capability token hợp lệ');
  }
  const sandbox = await sdk.create({
    source: { type: 'git', url: source, revision, depth: 1 },
    image,
    persistent: false,
    resources: { vcpus: 2 },
    timeout: 43 * 60 * 1000,
    env: {
      SICT_API_BASE: api, MVP_JOB_CAPABILITY_TOKEN: capability.token, JOB_KIND: state.kind,
      ...(state.kind === 'ocr' ? {
        MVP_OCR_URL: process.env.MVP_OCR_URL || '',
        MVP_OCR_TOKEN: process.env.MVP_OCR_TOKEN || '',
      } : {}),
      JOB_DEADLINE: String(Math.floor(Date.now() / 1000) + 40 * 60),
    },
  });
  try {
    const check = await sandbox.runCommand({
      cmd: 'git', args: ['rev-parse', 'HEAD'], cwd: sandbox.cwd,
    });
    const head = typeof check.stdout === 'function' ? await check.stdout() : check.stdout;
    if (check.exitCode !== 0 || String(head || '').trim() !== revision) {
      throw new Error('Sandbox checkout sai commit SHA của repository tin cậy');
    }
    // Sandbox SDK trả cwd chính xác cho checkout từ Git source.
    const result = await sandbox.runCommand({
      cmd: 'bash', args: ['sandbox/run_job.sh', jobId],
      cwd: sandbox.cwd,
      stdout: output, stderr: error,
    });
    return result.exitCode;
  } finally {
    await sandbox.stop();
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  try {
    process.exitCode = await launchSandbox(process.argv[2]);
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}
