"""Hợp đồng cấu hình media local giữa hai VM."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sync_uses_configured_ssh_user(tmp_path):
    rsync = tmp_path / 'rsync'
    rsync.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$OUT"\n')
    rsync.chmod(0o755)
    out = tmp_path / 'args'
    env = dict(os.environ, PATH=f'{tmp_path}:{os.environ["PATH"]}', OUT=str(out),
               MEDIA_API_HOST='vm1', MEDIA_SYNC_KEY='/tmp/key', MEDIA_SSH_USER='ubuntu')
    subprocess.run(['bash', str(ROOT / 'scripts/sync_worker_media.sh')], env=env, check=True)
    assert 'ubuntu@vm1:' in out.read_text()


def test_full_worker_and_api_allow_local_store_mounts():
    worker = (ROOT / 'docker-compose.worker.yml').read_text()
    api = (ROOT / 'docker-compose.yml').read_text()
    assert worker.count('${WORKER_LOCAL_STORE:-localstore}:/app/_local_store') == 2
    assert '${API_LOCAL_STORE:-api_localstore}:/app/_local_store:ro' in api


def test_empty_aws_profile_selects_local_store(tmp_path):
    import json
    envfile = tmp_path / 'env'
    envfile.write_text('AWS_PROFILE=\n')
    for compose, service, profiles in [('docker-compose.yml', 'api', []),
                                       ('docker-compose.worker.yml', 'cron', ['--profile', 'batch'])]:
        result = subprocess.run(['docker', 'compose', '--env-file', str(envfile), '-f', str(ROOT / compose),
                                 *profiles, 'config', '--format', 'json'], capture_output=True, text=True, check=True,
                                env={**os.environ, 'AWS_PROFILE': ''})
        assert json.loads(result.stdout)['services'][service]['environment']['AWS_PROFILE'] == ''
