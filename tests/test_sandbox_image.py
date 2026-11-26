"""Contract dependency image và bootstrap offline của Sandbox."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sandbox_image_has_locked_native_and_python_dependencies():
    dockerfile = (ROOT / 'sandbox/Dockerfile').read_text()
    for dependency in ('ffmpeg', 'poppler-utils', 'tesseract-ocr-vie',
                       'tesseract-ocr-eng', 'underthesea', 'pytesseract', 'qdrant_client'):
        assert dependency in dockerfile
    assert 'uv sync --locked' in dockerfile
    assert '--group worker --group graph --no-group embed' in dockerfile
    assert 'COPY pyproject.toml uv.lock' in dockerfile


def test_sandbox_runtime_uses_prebuilt_dependencies_without_install():
    script = (ROOT / 'sandbox/run_job.sh').read_text()
    commands = '\n'.join(line for line in script.splitlines() if not line.lstrip().startswith('#'))
    for command in ('apt-get', 'uv sync', 'pip install', 'curl ', 'sudo '):
        assert command not in commands
    assert 'cmp -s uv.lock /opt/sict-build/uv.lock' in commands
    assert 'cmp -s pyproject.toml /opt/sict-build/pyproject.toml' in commands
    assert 'uv run --no-sync --offline' in commands
