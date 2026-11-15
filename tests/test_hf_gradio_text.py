"""Hợp đồng HTTP hai bước của Space: không dùng gradio_client."""
import json
from types import SimpleNamespace

import pytest
from sict_crawler.service.embedding import embedder as E


class Response:
    def __init__(self, payload=None, lines=()):
        self.payload, self.lines = payload, lines
    def raise_for_status(self):
        pass
    def json(self):
        return self.payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def iter_lines(self):
        return iter(self.lines)


def test_gradio_http_query_and_document(monkeypatch):
    import httpx
    calls = []
    config = SimpleNamespace(hf_space_url='https://example.test', hf_token='private-token', dim=3, timeout=20)
    monkeypatch.setattr(E, 'get_settings', lambda: SimpleNamespace(embedding=config))
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response({'event_id':'abc'})
    def stream(method, url, **kwargs):
        calls.append((url, kwargs))
        return Response(lines=['event: generating','data: null','', 'event: complete',
                               'data: '+json.dumps([{'status':'success','embeddings':[[1,2,3]]}]),''])
    monkeypatch.setattr(httpx, 'post', post)
    monkeypatch.setattr(httpx, 'stream', stream)
    assert E._hf_gradio_texts(['câu hỏi'], 'query') == [[1.0,2.0,3.0]]
    assert calls[0][1]['json']['data'] == [{'type':'text', 'input':'câu hỏi', 'task':'query'}, 'query', 3]
    assert calls[0][1]['headers']['Authorization'] == calls[1][1]['headers']['Authorization'] == 'Bearer private-token'
    assert calls[1][0].endswith('/gradio_api/call/embed/abc')


def test_gradio_error_does_not_produce_vector(monkeypatch):
    import httpx
    config = SimpleNamespace(hf_space_url='https://example.test', hf_token='', dim=3, timeout=20)
    monkeypatch.setattr(E, 'get_settings', lambda: SimpleNamespace(embedding=config))
    monkeypatch.setattr(httpx, 'post', lambda *a, **k: Response({'event_id':'abc'}))
    monkeypatch.setattr(httpx, 'stream', lambda *a, **k: Response(lines=['event: complete',
        'data: '+json.dumps([{'status':'error','message':'quota'}]),'']))
    with pytest.raises(E.EmbedError, match='quota'):
        E._hf_gradio_texts(['văn bản'], 'document')


def test_provider_and_task_have_separate_cache(tmp_path, monkeypatch):
    from sict_crawler.core.config import get_settings
    e = get_settings().embedding
    monkeypatch.setattr(e, 'backend', 'api')
    monkeypatch.setattr(e, 'text_provider', 'hf-space')
    monkeypatch.setattr(e, 'cache_path', str(tmp_path / 'cache.sqlite'))
    monkeypatch.setattr(E, '_cache_db', None)
    calls = []
    def fake_hf(texts, task):
        calls.append((texts, task))
        return [[1.0] * e.dim for _ in texts]
    monkeypatch.setattr(E, '_hf_gradio_texts', fake_hf)
    E.embed_texts(['cùng nội dung'], kind='query')
    E.embed_texts(['cùng nội dung'], kind='query')
    E.embed_texts(['cùng nội dung'], kind='passage')
    assert calls == [(['cùng nội dung'], 'query'), (['cùng nội dung'], 'document')]
    monkeypatch.setattr(e, 'text_provider', 'jina')
    jina_calls = []
    monkeypatch.setattr(E, '_post', lambda items: jina_calls.append(items) or [[2.0] * e.dim for _ in items])
    assert E.embed_texts(['cùng nội dung'], kind='passage')[0][0] == 2.0
    assert len(jina_calls) == 1


def test_space_rejects_wrong_dimensions(monkeypatch):
    import httpx
    config = SimpleNamespace(hf_space_url='https://example.test', hf_token='', dim=3, timeout=20)
    monkeypatch.setattr(E, 'get_settings', lambda: SimpleNamespace(embedding=config))
    monkeypatch.setattr(httpx, 'post', lambda *a, **k: Response({'event_id':'abc'}))
    monkeypatch.setattr(httpx, 'stream', lambda *a, **k: Response(lines=['event: complete',
        'data: '+json.dumps([{'status':'success','embeddings':[[1,2]]}]),'']))
    with pytest.raises(E.EmbedError, match='kích thước'):
        E._hf_gradio_texts(['văn bản'], 'document')


def test_image_uses_unified_typed_endpoint(monkeypatch):
    import httpx
    config = SimpleNamespace(hf_space_url='https://example.test', hf_token='token', dim=3, timeout=20)
    monkeypatch.setattr(E, 'get_settings', lambda: SimpleNamespace(embedding=config))
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs['json'])
        return Response({'event_id':'abc'})
    monkeypatch.setattr(httpx, 'post', post)
    monkeypatch.setattr(httpx, 'stream', lambda *a, **k: Response(lines=['event: complete',
        'data: '+json.dumps([{'status':'success','embeddings':[[1,2,3]]}]),'']))
    assert E._hf_gradio_image('ZmFrZQ==') == [1.0, 2.0, 3.0]
    assert calls[0]['data'] == [{'type':'image','input':'ZmFrZQ=='}, 'query', 3]


def test_image_provider_routes_and_caches_separately(tmp_path, monkeypatch):
    import base64
    import io
    from PIL import Image
    from sict_crawler.core.config import get_settings
    e = get_settings().embedding
    monkeypatch.setattr(e, 'backend', 'api')
    monkeypatch.setattr(e, 'image_provider', 'hf-space')
    monkeypatch.setattr(e, 'cache_path', str(tmp_path / 'image-cache.sqlite'))
    monkeypatch.setattr(E, '_cache_db', None)
    calls = []
    def fake_image(b64):
        with Image.open(io.BytesIO(base64.b64decode(b64))) as image:
            assert image.format == 'JPEG'
        calls.append(b64)
        return [1.0] * e.dim
    monkeypatch.setattr(E, '_hf_gradio_image', fake_image)
    buf = io.BytesIO()
    Image.new('RGB', (10, 10)).save(buf, format='PNG')
    raw = buf.getvalue()
    assert E.embed_image_bytes([raw, b'bad'])[1] == [0]
    assert E.embed_image_bytes([raw])[0][0][0] == 1.0
    assert len(calls) == 1
    monkeypatch.setattr(e, 'image_provider', 'jina')
    other = []
    monkeypatch.setattr(E, '_post', lambda items: other.append(items) or [[2.0] * e.dim for _ in items])
    assert E.embed_image_bytes([raw])[0][0][0] == 2.0
    assert len(other) == 1


def test_owner_embedding_environment_aliases(monkeypatch):
    from sict_crawler.core.config import EmbeddingConfig
    for name in ('HF_SPACE_URL', 'HF_SPACE_ENDPOINT', 'EMBED_DIM', 'EMBED_MODEL', 'EMBED_BACKEND', 'EMBED_TEXT_PROVIDER', 'EMBED_IMAGE_PROVIDER'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('EMBEDDING_BASE_URL', 'https://example.test')
    monkeypatch.setenv('EMBEDDING_ENDPOINT', '/gradio_api/call/embed')
    monkeypatch.setenv('EMBEDDING_DIMENSION', '1024')
    monkeypatch.setenv('EMBEDDING_MODEL', 'jinaai/jina-clip-v2')
    e = EmbeddingConfig()
    assert (e.hf_space_url, e.hf_endpoint, e.dim, e.model) == (
        'https://example.test', '/gradio_api/call/embed', 1024, 'jinaai/jina-clip-v2')
    assert (e.backend, e.text_provider, e.image_provider) == ('api', 'hf-space', 'hf-space')
