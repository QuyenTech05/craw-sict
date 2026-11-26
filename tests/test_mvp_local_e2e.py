"""E2E localhost: Vercel handler → HTTP Job API → runner thật → artifact."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from uuid import uuid4

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from sandbox.job_runner import JobClient, run_job
from sict_crawler.api import mvp_jobs

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which('node') or not shutil.which('ffmpeg'),
                    reason='E2E local cần Node và ffmpeg')
def test_video_proxy_runner_http_resume(tmp_path, monkeypatch):
    monkeypatch.setenv('MVP_JOB_ROOT', str(tmp_path / 'jobs'))
    monkeypatch.setenv('MVP_JOB_TOKEN', 'local-e2e-only')
    app = FastAPI()
    app.include_router(mvp_jobs.router)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        base = f'http://127.0.0.1:{sock.getsockname()[1]}'
        server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.05)
            assert server.started
            job_id = str(uuid4())
            clip = tmp_path / 'clip.mp4'
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                            '-i', 'color=c=blue:s=96x64:r=2', '-t', '32', '-c:v', 'mpeg4',
                            '-threads', '1', str(clip)], check=True, timeout=30)
            env = {**os.environ, 'SICT_API_BASE': base, 'E2E_JOB_ID': job_id, 'E2E_CLIP': str(clip)}
            # Web-standard handler Vercel dùng fetch HTTP thật đến FastAPI, không mock transport.
            proxy = '''
import { handler } from './vercel/api/jobs.mjs';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
const id = process.env.E2E_JOB_ID;
const endpoint = 'http://localhost/api/jobs';
const headers = {Authorization: `Bearer ${process.env.MVP_JOB_TOKEN}`};
const clip = readFileSync(process.env.E2E_CLIP);
async function call(method, suffix, body) {
  const res = await handler(new Request(endpoint + suffix, {method, headers, body}));
  assert.equal(res.status, 200, await res.clone().text());
  return res;
}
await call('POST', '', JSON.stringify({job_id: id, kind: 'video',
  input_fingerprint: createHash('sha256').update(clip).digest('hex')}));
await call('PUT', `?job_id=${id}&area=input&name=items.json`,
  JSON.stringify({items: [{id: 'clip', input: 'clip.mp4'}]}));
await call('PUT', `?job_id=${id}&area=input&name=clip.mp4`, clip);
'''
            subprocess.run(['node', '--input-type=module', '-e', proxy], cwd=ROOT, env=env,
                           check=True, timeout=45)
            with httpx.Client(base_url=base, headers={'Authorization': 'Bearer local-e2e-only'}) as owner:
                endpoint = f'/internal/jobs/{job_id}'
                response = owner.post(endpoint + '/capabilities', json={'scopes': ['read', 'write', 'claim']})
                response.raise_for_status()
                token = response.json()['token']
                denied = owner.get(endpoint, headers={'Authorization': 'Bearer invalid'})
                assert denied.status_code == 401
                client = JobClient(base, token, job_id)
                paused = run_job(client, time.time() + 5, tmp_path / 'first')
                assert paused['status'] == 'paused' and paused['checkpoint']['completed'] == []
                result = run_job(JobClient(base, token, job_id), time.time() + 180, tmp_path / 'retry')
                assert result['status'] == 'succeeded' and result['attempt'] == 2
                assert result['checkpoint']['completed'] == ['clip']
                manifest = owner.get(endpoint + '/manifest').json()['artifacts']
                output = owner.get(endpoint + '/artifacts/output/clip.json').json()
                assert output['frames']
                for frame in output['frames']:
                    data = owner.get(endpoint + '/artifacts/output/' + frame).content
                    assert data.startswith(b'\xff\xd8')
                    assert hashlib.sha256(data).hexdigest() == manifest['output/' + frame]['sha256']
                assert run_job(JobClient(base, token, job_id), time.time() + 180, tmp_path / 'again')['attempt'] == 2
        finally:
            server.should_exit = True
            thread.join(timeout=10)
