"""Hợp đồng runtime v3 chỉ dùng HTTP embedding client và ONNX service."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sict_crawler.core.config import EmbeddingConfig, QdrantConfig


ROOT = Path(__file__).resolve().parents[1]


def test_import_runtime_without_torch_family():
    code = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'torch', 'sentence_transformers', 'transformers'}:
        raise AssertionError('runtime imported forbidden dependency: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from sict_crawler.service.embedding import embedder
from sict_crawler.service.retrieval import retriever
from sict_crawler.service.index import indexer
from sict_crawler.api import routes
assert embedder.backend() == 'api'
"""
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    # Import các module lớn có thể chậm khi máy CI đang chạy nhiều bài kiểm tra.
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr


def test_embedding_configuration_refuses_legacy_and_missing_endpoint(monkeypatch):
    monkeypatch.setenv("EMBED_BACKEND", "torch")
    with pytest.raises(ValueError, match="api"):
        EmbeddingConfig(api_base="http://embed:8090/v1")
    monkeypatch.delenv("EMBED_BACKEND")
    monkeypatch.delenv("EMBED_API_BASE", raising=False)
    monkeypatch.delenv("BASEURL_EMBEDDING", raising=False)
    with pytest.raises(ValueError, match="EMBED_API_BASE"):
        EmbeddingConfig(api_base="")


def test_v3_config_defaults():
    qdrant = QdrantConfig()
    assert (qdrant.collection_text, qdrant.collection_image, qdrant.collection_ocr) == (
        "sict_text_v3", "sict_image_v3", "sict_ocr_v3")
    assert (qdrant.text_dim, qdrant.image_dim) == (1024, 1024)


def test_no_runtime_torch_dependencies_or_gpu_build():
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert '"torch"' not in pyproject
    assert '"sentence-transformers' not in pyproject
    assert '"transformers' not in pyproject
    for name in ("Dockerfile.api", "Dockerfile.worker", "Dockerfile.embed"):
        dockerfile = (ROOT / name).read_text()
        assert "--group ml" not in dockerfile
        assert "uv pip install" not in dockerfile


def test_compose_defaults_use_only_v3():
    for name in ("docker-compose.worker.yml", "docker-compose.worker-lite.yml"):
        services = yaml.safe_load((ROOT / name).read_text())["services"]
        for service in services.values():
            env = service.get("environment", {})
            if "EMBED_BACKEND" not in env:
                continue
            assert env["EMBED_BACKEND"].endswith(":-api}")
            for key, expected in (("QDRANT_COLLECTION_TEXT", "sict_text_v3"),
                                  ("QDRANT_COLLECTION_IMAGE", "sict_image_v3"),
                                  ("QDRANT_COLLECTION_OCR", "sict_ocr_v3")):
                assert env[key].endswith(f":-{expected}}}")
