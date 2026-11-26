import assert from 'node:assert/strict';
import { test } from 'node:test';
import { launchSandbox } from '../launch-sandbox.mjs';

const jobId = '3f0c2a4e-7839-41e4-86f1-69c4a1434319';

async function withEnvironment(callback) {
  const variables = {
    SICT_GIT_URL: 'https://github.com/quyentech05/craw-sict.git',
    SICT_GIT_SHA: 'a'.repeat(40),
    SICT_API_BASE: 'https://demo-vm.example',
    SICT_SANDBOX_IMAGE: 'sict/sandbox@sha256:' + 'b'.repeat(64),
    MVP_JOB_TOKEN: 'test-token',
    MVP_OCR_URL: 'https://demo-ocr.vercel.app/api/ocr',
    MVP_OCR_TOKEN: 'test-ocr-token',
  };
  const previous = Object.fromEntries(Object.keys(variables).map((key) => [key, process.env[key]]));
  Object.assign(process.env, variables);
  try { await callback(); } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

test('launcher checkout đúng cwd, giới hạn thời gian, truyền env và đóng Sandbox', async () => {
  await withEnvironment(async () => {
    let created;
    let command;
    let stopped = false;
    const sdk = { create: async (options) => {
      created = options;
      return {
        cwd: '/vercel/sandbox/craw-sict',
        runCommand: async (params) => {
          if (params.cmd === 'git') return { exitCode: 0, stdout: async () => 'a'.repeat(40) + '\n' };
          command = params;
          return { exitCode: 0 };
        },
        stop: async () => { stopped = true; },
      };
    } };
    const code = await launchSandbox(jobId, { sdk,
      jobClient: async (path, options) => path.endsWith('/capabilities')
        ? { token: 'scoped-token', job_id: jobId } : { kind: 'ocr', status: 'queued' },
      output: {}, error: {},
    });
    assert.equal(code, 0);
    assert.equal(created.source.revision, 'a'.repeat(40));
    assert.equal(created.image, 'sict/sandbox@sha256:' + 'b'.repeat(64));
    assert.equal(created.persistent, false);
    assert.equal(created.resources.vcpus, 2);
    assert.equal(created.timeout, 43 * 60 * 1000);
    assert.equal(created.env.MVP_JOB_TOKEN, undefined);
    assert.equal(created.env.MVP_JOB_CAPABILITY_TOKEN, 'scoped-token');
    assert.equal(created.env.MVP_OCR_TOKEN, 'test-ocr-token');
    assert.equal(command.cwd, '/vercel/sandbox/craw-sict');
    assert.deepEqual(command.args, ['sandbox/run_job.sh', jobId]);
    assert.ok(stopped);
  });
});

test('launcher luôn stop khi lệnh thất bại', async () => {
  await withEnvironment(async () => {
    let stopped = false;
    const sdk = { create: async () => ({
      cwd: '/vercel/sandbox/craw-sict',
      runCommand: async (params) => {
        if (params.cmd === 'git') return { exitCode: 0, stdout: async () => 'a'.repeat(40) };
        throw new Error('simulated Sandbox command failure');
      },
      stop: async () => { stopped = true; },
    }) };
    await assert.rejects(launchSandbox(jobId, { sdk,
      jobClient: async (path) => path.endsWith('/capabilities')
        ? { token: 'scoped-token', job_id: jobId } : { kind: 'video', status: 'paused' },
    }), /simulated Sandbox command failure/);
    assert.ok(stopped);
  });
});

test('launcher từ chối Git branch, fork và checkout sai SHA', async () => {
  await withEnvironment(async () => {
    const original = process.env.SICT_GIT_SHA;
    process.env.SICT_GIT_SHA = 'main';
    await assert.rejects(launchSandbox(jobId), /immutable commit SHA/);
    process.env.SICT_GIT_SHA = original;
    process.env.SICT_GIT_URL = 'https://github.com/attacker/craw-sict.git';
    await assert.rejects(launchSandbox(jobId), /repository SICT tin cậy/);
    process.env.SICT_GIT_URL = 'https://github.com/quyentech05/craw-sict.git';
    let stopped = false;
    const sdk = { create: async () => ({
      cwd: '/checkout', runCommand: async () => ({ exitCode: 0, stdout: async () => 'b'.repeat(40) }),
      stop: async () => { stopped = true; },
    }) };
    await assert.rejects(launchSandbox(jobId, { sdk,
      jobClient: async (path) => path.endsWith('/capabilities')
        ? { token: 'scoped', job_id: jobId } : { kind: 'ocr', status: 'queued' },
    }), /checkout sai commit SHA/);
    assert.equal(stopped, true);
  });
});

test('launcher bỏ qua job đã xong và chặn writer live', async () => {
  await withEnvironment(async () => {
    const sdk = { create: async () => { throw new Error('Không được tạo Sandbox'); } };
    const succeeded = await launchSandbox(jobId, { sdk,
      jobClient: async () => ({ kind: 'ocr', status: 'succeeded' }),
    });
    assert.equal(succeeded, 0);
    await assert.rejects(launchSandbox(jobId, { sdk,
      jobClient: async () => ({ kind: 'loader-staging', status: 'queued' }),
    }), /chưa hỗ trợ/);
  });
});

test('report job chỉ nhận capability report, không nhận OCR token', async () => {
  await withEnvironment(async () => {
    const sdk = { create: async (options) => {
      assert.equal(options.env.MVP_OCR_TOKEN, undefined);
      assert.equal(options.env.MVP_JOB_TOKEN, undefined);
      return { cwd: '/checkout', runCommand: async () => ({ exitCode: 0,
        stdout: async () => 'a'.repeat(40) }), stop: async () => {} };
    } };
    await launchSandbox(jobId, { sdk, jobClient: async (path, options) => {
      if (path.endsWith('/capabilities')) {
        assert.deepEqual(options.json.scopes, ['read', 'write', 'claim', 'report']);
        return { token: 'scoped-token', job_id: jobId };
      }
      return { kind: 'graph-stats', status: 'queued' };
    } });
  });
});


test('launcher từ chối image mutable trước khi gọi Job API', async () => {
  await withEnvironment(async () => {
    process.env.SICT_SANDBOX_IMAGE = 'sict/sandbox:latest';
    await assert.rejects(launchSandbox(jobId, { jobClient: async () => {
      throw new Error('Không được gọi Job API');
    } }), /sha256 digest/);
  });
});
