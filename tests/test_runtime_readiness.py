"""Hợp đồng readiness và timeout query embedding của placement hai VM, chạy offline."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
import yaml

from sict_crawler.api import metrics, routes
from sict_crawler.service.embedding import embedder


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=routes.app), base_url="http://test")


def test_health_and_readiness(monkeypatch):
    async def unavailable():
        return {"postgres": True, "redis": True, "qdrant": True, "embed": False}

    monkeypatch.setattr(routes, "_readiness_checks", unavailable)

    async def run():
        async with _client() as client:
            alive = await client.get("/healthz")
            ready = await client.get("/readyz")
        return alive, ready

    alive, ready = asyncio.run(run())
    assert alive.status_code == 200 and alive.json()["ok"] is True
    assert ready.status_code == 503
    assert ready.json() == {"ready": False, "services": {"postgres": True, "redis": True,
                                                         "qdrant": True, "embed": False}}


@pytest.mark.parametrize("endpoint", ["query", "chat"])
def test_embedding_down_returns_503_and_counts_failure(monkeypatch, endpoint):
    def failure(q):
        raise embedder.EmbedError("private endpoint down")

    monkeypatch.setattr(routes, "_run_query", failure)
    before = metrics.EMBED_FAILURES.labels(endpoint)._value.get()

    async def run():
        async with _client() as client:
            return await client.post("/" + endpoint, json={"question": "Thời khóa biểu?"})

    response = asyncio.run(run())
    assert response.status_code == 503
    assert "private endpoint" not in response.text
    assert metrics.EMBED_FAILURES.labels(endpoint)._value.get() == before + 1


def test_query_budget_limits_retries_and_timeout(monkeypatch):
    from sict_crawler.core.config import get_settings

    config = get_settings().embedding
    original_base, original_retries = config.api_base, config.api_retries
    config.api_base = "http://embed.invalid/v1"
    config.api_retries = 8
    timeouts = []

    def fail(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "post", fail)
    try:
        with pytest.raises(embedder.EmbedError):
            with embedder.query_embedding_budget(0.5):
                embedder._post([{"text": "Câu hỏi"}])
        assert len(timeouts) == 1
        assert 0 < timeouts[0] <= 0.5
    finally:
        config.api_base, config.api_retries = original_base, original_retries


def test_image_query_inherits_embedding_deadline_in_stage_pool(monkeypatch):
    from sict_crawler.service.retrieval import query_rewriter, retriever

    started = Event()
    deadlines = []
    monkeypatch.setattr(retriever.cache, "get", lambda key: None)

    def image_embedding(b64):
        deadlines.append(embedder._query_deadline.get())
        started.set()
        return None

    def stop_after_image_started(*args, **kwargs):
        assert started.wait(2)
        raise RuntimeError("dừng trước truy xuất")

    monkeypatch.setattr(retriever, "_query_image_vec", image_embedding)
    monkeypatch.setattr(query_rewriter, "rewrite", stop_after_image_started)
    with ThreadPoolExecutor(max_workers=1) as pool:
        monkeypatch.setattr(retriever, "_STAGE_POOL", pool)
        with embedder.query_embedding_budget(2):
            with pytest.raises(RuntimeError, match="dừng trước truy xuất"):
                retriever.retrieve("Câu hỏi", query_image_b64="invalid-image")
    assert len(deadlines) == 1 and deadlines[0] is not None


def test_image_query_does_not_hide_embed_gateway_failure(monkeypatch):
    from sict_crawler.service.retrieval import retriever

    def unavailable(*args):
        raise embedder.EmbedError("gateway lỗi")

    monkeypatch.setattr(embedder, "embed_query_image_base64", unavailable)
    with pytest.raises(embedder.EmbedError, match="gateway lỗi"):
        retriever._query_image_vec("invalid-image")


def test_graph_query_and_stream_propagate_embed_failure(monkeypatch):
    from sict_crawler.service.retrieval import graph

    class BrokenQueryGraph:
        def invoke(self, *args, **kwargs):
            raise embedder.EmbedError("gateway down")

    class BrokenChatGraph:
        def stream(self, *args, **kwargs):
            raise embedder.EmbedError("gateway down")
            yield  # giữ hợp đồng generator

    monkeypatch.setattr(graph, "_graph", BrokenQueryGraph())
    monkeypatch.setattr(graph, "_chat_graph", BrokenChatGraph())
    with pytest.raises(embedder.EmbedError, match="gateway down"):
        graph.run("Học phí?", 5, None, None)
    with pytest.raises(embedder.EmbedError, match="gateway down"):
        list(graph.stream_chat("Học phí?", 5, None, None))


def test_vm2_network_and_resources_are_explicit():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    worker = yaml.safe_load((root / "docker-compose.worker.yml").read_text())
    embed = yaml.safe_load((root / "docker-compose.embed.yml").read_text())
    assert worker["networks"]["vm2"] == embed["networks"]["vm2"]
    assert worker["networks"]["vm2"]["external"] is True
    assert "vm2" in worker["services"]["cron"]["networks"]
    assert "default" in worker["services"]["cron"]["networks"]
    assert worker["services"]["cron"]["environment"]["CRON_RETRY_SEC"] == "${CRON_RETRY_SEC:-300}"
    assert "sleep $$CRON_RETRY_SEC" in worker["services"]["cron"]["command"]
    assert "default" in worker["services"]["svc-ocr"]["networks"]
    assert "vm2" in embed["services"]["embed"]["networks"]
    assert embed["services"]["embed"]["environment"]["EMBED_CONCURRENCY"] == "${EMBED_CONCURRENCY:-1}"
    assert embed["services"]["embed"]["environment"]["EMBED_TEXT_MAX_LEN"] == "${EMBED_TEXT_MAX_LEN:-1536}"


def test_incremental_wait_includes_embed():
    from sict_crawler.pipeline import incremental

    assert "embed" in incremental.SERVICE_PROBES


def test_hybrid_chat_reports_embed_failure(monkeypatch):
    from sict_crawler.service.retrieval import graph

    def broken(*args, **kwargs):
        raise embedder.EmbedError("embed unreachable")
        yield  # generator body

    monkeypatch.setattr(graph, "stream_chat", broken)
    before = metrics.EMBED_FAILURES.labels("chat_hybrid")._value.get()

    async def run():
        from sict_crawler.model.schemas import QueryIn
        events = []
        async for frame in routes._hybrid_chat_stream(QueryIn(question="test")):
            events.append(frame)
        return events

    frames = asyncio.run(run())
    assert any(json.loads(frame[6:])["error"] == "Dịch vụ embedding tạm thời không sẵn sàng"
               for frame in frames if '"error"' in frame)
    assert frames[-1] == "data: [DONE]\n\n"
    assert metrics.EMBED_FAILURES.labels("chat_hybrid")._value.get() == before + 1
