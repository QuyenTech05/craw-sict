"""Hợp đồng embedding v3 dùng HTTP API, không phụ thuộc device hay CUDA."""

import pytest

from sict_crawler.core.config import EmbeddingConfig
from sict_crawler.service.embedding import embedder


def test_api_backend_is_the_only_supported_backend():
    assert EmbeddingConfig().backend == "api"
    assert embedder.backend() == "api"


@pytest.mark.parametrize("legacy", ["torch", "onnx", "cuda"])
def test_legacy_backends_are_refused(monkeypatch, legacy):
    monkeypatch.setenv("EMBED_BACKEND", legacy)
    with pytest.raises(ValueError, match="EMBED_BACKEND phải là api"):
        EmbeddingConfig()


def test_embedding_has_no_device_configuration():
    assert not hasattr(EmbeddingConfig(), "device")
    assert not hasattr(embedder, "get_device")
