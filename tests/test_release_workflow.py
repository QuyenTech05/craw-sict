"""GHCR release và CD dùng cùng prefix canonical."""
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_ghcr_prefix():
    for name, job in [('release', 'build-push'), ('cd', 'prepare')]:
        path = ROOT / '.github/workflows' / f'{name}.yml'
        content = path.read_text()
        steps = yaml.safe_load(content)['jobs'][job]['steps']
        step = next(s for s in steps if s.get('id') == 'registry')
        result = subprocess.run(['bash', '-c', step['run']], env={**os.environ,
            'GITHUB_REPOSITORY_OWNER': 'QuyenTech05', 'GITHUB_OUTPUT': '/dev/stdout'},
            check=True, capture_output=True, text=True)
        assert result.stdout.strip() == 'prefix=ghcr.io/quyentech05/sict'
        assert 'ghcr.io/${{ github.repository_owner }}' not in content
        assert '${{ steps.registry.outputs.prefix }}' in content
    assert '${{ needs.prepare.outputs.prefix }}-api:' in content
    assert '${{ needs.prepare.outputs.prefix }}-embed:' in content
