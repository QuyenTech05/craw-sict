"""OCR Vercel chỉ chạy sau retrieval và khi opt-in, degrade gracefully."""
import asyncio
import base64
import io

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from sict_crawler.api import mvp_ocr
from sict_crawler.model.schemas import QueryIn, Source


with io.BytesIO() as buffer:
    Image.new("RGB", (2, 2)).save(buffer, format="PNG")
    IMAGE = base64.b64encode(buffer.getvalue()).decode()


def _result(sufficient=True):
    return {"context": "[1] Trang tuyển sinh SICT", "sufficient": sufficient,
            "text": [], "media": []}


def test_ocr_default_off_does_not_call_network(monkeypatch):
    monkeypatch.delenv("MVP_OCR_POLICY", raising=False)
    monkeypatch.setenv("MVP_OCR_URL", "https://demo.vercel.app/api/ocr")
    monkeypatch.setenv("MVP_OCR_TOKEN", "key")
    result = _result(sufficient=False)
    assert asyncio.run(mvp_ocr.add_query_ocr(QueryIn(question="Đọc chữ", image=IMAGE), result)) is result


def test_ocr_requeries_sict_text_and_updates_citations(monkeypatch):
    monkeypatch.setenv("MVP_OCR_POLICY", "weak")
    monkeypatch.setenv("MVP_OCR_URL", "https://demo.vercel.app/api/ocr")
    monkeypatch.setenv("MVP_OCR_TOKEN", "key")
    calls = []

    def serve(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer key"
        return httpx.Response(200, json={"text": "Hội thảo AI", "language": "vie+eng"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(serve))
    monkeypatch.setattr(mvp_ocr.httpx, "AsyncClient", lambda **kwargs: client)
    from sict_crawler.service.retrieval import agent
    retrievals = []

    def search(question, top_k, image, filters):
        retrievals.append((question, top_k, image, filters))
        return {**_result(), "context": "[1] Hội thảo AI — sict.haui.edu.vn",
                "text": [Source(url="https://sict.haui.edu.vn/vn/hoi-thao-ai", title="Hội thảo AI",
                                kind="text", score=0.9)]}

    monkeypatch.setattr(agent, "run", search)
    q = QueryIn(question="Đây là sự kiện nào?", image=IMAGE)
    initial = _result(sufficient=False)
    outcome = asyncio.run(mvp_ocr.add_query_ocr(q, initial))
    assert len(calls) == 1
    assert retrievals == [("Đây là sự kiện nào?\nHội thảo AI", 8, None, None)]
    assert outcome["ocr"] == {"status": "ok", "text": "Hội thảo AI", "language": "vie+eng",
                              "source_verified": True}
    assert outcome["text"][0].url.endswith("hoi-thao-ai")
    assert "Trang tuyển sinh" not in outcome["context"]
    assert outcome["sufficient"] is True
    assert initial["context"] == "[1] Trang tuyển sinh SICT"


def test_ocr_without_verified_source_removes_visual_citations(monkeypatch):
    from sict_crawler.service.retrieval import agent
    monkeypatch.setenv("MVP_OCR_POLICY", "always")
    monkeypatch.setenv("MVP_OCR_URL", "https://demo.vercel.app/api/ocr")
    monkeypatch.setenv("MVP_OCR_TOKEN", "key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"text": "Hội thảo AI", "language": "vie"})))
    monkeypatch.setattr(mvp_ocr.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(agent, "run", lambda *args: {**_result(sufficient=False), "text": []})
    original = {**_result(sufficient=False), "text": [Source(
        url="https://sict.haui.edu.vn/vn/khac", title="Không liên quan", kind="text", score=0.5)]}
    output = asyncio.run(mvp_ocr.add_query_ocr(QueryIn(question="Sự kiện?", image=IMAGE), original))
    assert output["text"] == [] and output["media"] == []
    assert output["sufficient"] is False
    assert output["ocr"]["source_verified"] is False
    assert "chưa được xác minh" in output["context"]


def test_ocr_requery_failure_does_not_reuse_unrelated_visual_sources(monkeypatch):
    from sict_crawler.service.retrieval import agent
    monkeypatch.setenv("MVP_OCR_POLICY", "always")
    monkeypatch.setenv("MVP_OCR_URL", "https://demo.vercel.app/api/ocr")
    monkeypatch.setenv("MVP_OCR_TOKEN", "key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"text": "Hội thảo AI", "language": "vie"})))
    monkeypatch.setattr(mvp_ocr.httpx, "AsyncClient", lambda **kwargs: client)

    def unavailable(*args):
        raise RuntimeError("index offline")

    monkeypatch.setattr(agent, "run", unavailable)
    original = {**_result(sufficient=False), "text": [Source(
        url="https://sict.haui.edu.vn/vn/khac", title="Không liên quan", kind="text", score=0.5)]}
    output = asyncio.run(mvp_ocr.add_query_ocr(QueryIn(question="Đọc chữ poster", image=IMAGE), original))
    assert output["ocr"]["status"] == "unverified"
    assert output["ocr"]["reason"] == "retrieval_unavailable"
    assert output["ocr"]["source_verified"] is False
    assert output["text"] == [] and output["media"] == []
    assert output["sufficient"] is False
    assert "chưa được xác minh" in output["context"]


def test_ocr_explicit_read_text_and_failed_upstream(monkeypatch):
    monkeypatch.setenv("MVP_OCR_POLICY", "weak")
    monkeypatch.setenv("MVP_OCR_URL", "https://demo.vercel.app/api/ocr")
    monkeypatch.setenv("MVP_OCR_TOKEN", "key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(504)))
    monkeypatch.setattr(mvp_ocr.httpx, "AsyncClient", lambda **kwargs: client)
    q = QueryIn(question="Trong ảnh ghi gì?", image=IMAGE)
    outcome = asyncio.run(mvp_ocr.add_query_ocr(q, _result(sufficient=True)))
    assert outcome["ocr"]["status"] == "unavailable"
    assert outcome["context"] == _result()["context"]


def test_ocr_skips_unneeded_or_invalid_inputs(monkeypatch):
    monkeypatch.setenv("MVP_OCR_POLICY", "weak")
    monkeypatch.setenv("MVP_OCR_URL", "https://demo.vercel.app/api/ocr")
    monkeypatch.setenv("MVP_OCR_TOKEN", "key")
    enough = _result()
    assert asyncio.run(mvp_ocr.add_query_ocr(QueryIn(question="Ai trong ảnh?", image=IMAGE), enough)) is enough
    invalid = asyncio.run(mvp_ocr.add_query_ocr(QueryIn.model_construct(question="Đọc chữ", image="??"), enough))
    assert invalid["ocr"] == {"status": "skipped", "reason": "invalid_image"}


def test_hybrid_chat_ocr_after_retrieval_before_answer(monkeypatch):
    from sict_crawler.api.routes import app
    from sict_crawler.core.config import get_settings
    from sict_crawler.service.retrieval import graph, prompt_cache

    monkeypatch.setattr(get_settings().llm, "router_mode", "hybrid")
    monkeypatch.setenv("MVP_OCR_POLICY", "weak")
    monkeypatch.setenv("MVP_OCR_URL", "https://demo.vercel.app/api/ocr")
    monkeypatch.setenv("MVP_OCR_TOKEN", "key")
    stages = []

    class FakeGraph:
        def stream(self, state, **kwargs):
            stages.append("retrieval")
            result = _result(sufficient=False)
            yield from graph._answer_events(state["question"], state["image"],
                                             state["postprocess_result"](result))

    def recognize(request):
        stages.append("ocr")
        return httpx.Response(200, json={"text": "Hội thảo AI", "language": "vie+eng"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(recognize))
    monkeypatch.setattr(mvp_ocr.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(graph, "_chat_graph", FakeGraph())
    from sict_crawler.service.retrieval import agent
    monkeypatch.setattr(agent, "run", lambda *args: {
        **_result(), "context": "[1] Hội thảo AI", "text": [Source(
            url="https://sict.haui.edu.vn/vn/hoi-thao-ai", title="Hội thảo AI",
            kind="text", score=0.95, cite="Hội thảo AI")],
    })

    def stream_answer(question, context, image, *, state=None):
        stages.append("answer")
        assert "Hội thảo AI" in context
        yield "Hội thảo AI"
        if state is not None:
            state["finish"] = "done"

    monkeypatch.setattr(prompt_cache, "stream_answer_cached", stream_answer)
    with TestClient(app) as api_client:
        response = api_client.post("/chat", json={"question": "Đây là sự kiện nào?", "image": IMAGE})
    events = [__import__("json").loads(frame[6:]) for frame in response.text.splitlines()
              if frame.startswith("data: ") and frame != "data: [DONE]"]
    assert response.status_code == 200
    assert stages == ["retrieval", "ocr", "answer"]
    assert events[0]["status"]["ocr"]["status"] == "ok"
    assert events[-1]["citations"][0]["url"].endswith("hoi-thao-ai")
    assert response.text.endswith("data: [DONE]\n\n")


@pytest.mark.parametrize("body,status", [([], "unavailable"), ({"text": "  "}, "empty")])
def test_ocr_bad_or_empty_response_preserves_visual(monkeypatch, body, status):
    monkeypatch.setenv("MVP_OCR_POLICY", "always")
    monkeypatch.setenv("MVP_OCR_URL", "https://demo.vercel.app/api/ocr")
    monkeypatch.setenv("MVP_OCR_TOKEN", "key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)))
    monkeypatch.setattr(mvp_ocr.httpx, "AsyncClient", lambda **kwargs: client)
    original = _result()
    outcome = asyncio.run(mvp_ocr.add_query_ocr(QueryIn(question="Đọc chữ", image=IMAGE), original))
    assert outcome == {**original, "ocr": {"status": status}}


def test_ocr_out_of_scope_skips_network(monkeypatch):
    monkeypatch.setenv("MVP_OCR_POLICY", "always")
    original = {**_result(False), "oos": True}
    outcome = asyncio.run(mvp_ocr.add_query_ocr(QueryIn(question="Đọc chữ", image=IMAGE), original))
    assert outcome is original


def test_ocr_weak_requery_keeps_verified_visual_and_isolates_cache(monkeypatch):
    from sict_crawler.service.retrieval import agent, retriever
    monkeypatch.setenv("MVP_OCR_POLICY", "always")
    monkeypatch.setenv("MVP_OCR_URL", "https://demo.vercel.app/api/ocr")
    monkeypatch.setenv("MVP_OCR_TOKEN", "key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"text": "Hội thảo AI"})))
    monkeypatch.setattr(mvp_ocr.httpx, "AsyncClient", lambda **kwargs: client)
    keys = []
    def search(question, top_k, image, filters):
        keys.append(retriever.query_cache_key(question, top_k))
        assert retriever.OCR_CACHE_SCOPE.get()
        return {**_result(), "text": [Source(url="https://example.com/fake", title="Fake", kind="text", score=1)]}
    monkeypatch.setattr(agent, "run", search)
    original = {**_result(), "text": [Source(url="https://sict.haui.edu.vn/vn/verified", title="Verified", kind="text", score=0.9)]}
    outcome = asyncio.run(mvp_ocr.add_query_ocr(QueryIn(question="Đọc chữ", image=IMAGE), original))
    assert outcome["text"] == original["text"]
    assert outcome["sufficient"] is True
    assert outcome["context"].startswith(original["context"])
    assert "Hội thảo AI" in outcome["context"]
    assert outcome["ocr"]["source_verified"] is False
    assert keys != [retriever.query_cache_key("Đọc chữ\nHội thảo AI", 8)]
    assert not retriever.OCR_CACHE_SCOPE.get()
