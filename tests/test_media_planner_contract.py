"""Dispatch hai nhóm độc lập và provenance media không phụ thuộc text hit."""

from types import SimpleNamespace

from sict_crawler.service.retrieval import query_rewriter, retriever
from sict_crawler.service.retrieval.evidence_linking import link_evidence
from sict_crawler.service.retrieval.fusion import RankedList, fuse_media_lists, fuse_text_lists
from sict_crawler.service.retrieval.planner import make_plan
from sict_crawler.service.retrieval.query_understanding import understand


def _settings():
    return SimpleNamespace(media_first_enabled=True, parallel_multimodal_enabled=True,
                           media_coupled_optional=False, rerank_profile="baseline_rrf",
                           max_retrieval_calls=9, text_candidate_limit=50,
                           media_candidate_limit=32, rerank_timeout_ms=100)


def test_dispatch_parallel_groups_with_separate_call_budgets(monkeypatch):
    settings = _settings()
    plan = make_plan(understand("Cho xem ảnh hoạt động", has_image=True),
                     enabled=True, settings=settings)
    observed = {}

    def text_search(**kwargs):
        observed["text"] = kwargs
        return [RankedList("bm25", ({"_pid": "t1", "document_id": 1,
                                      "url": "https://example.org/1", "chunk_id": "1"},))]

    def media_search(**kwargs):
        observed["media"] = kwargs
        return [{"media_key": "m1", "url": "https://example.org/2", "caption": "Hoạt động",
                 "modality": "caption", "raw_score": .8}]

    monkeypatch.setattr(query_rewriter, "hybrid_search_text", text_search)
    monkeypatch.setattr(retriever, "_media_candidates", media_search)
    monkeypatch.setattr(retriever, "get_settings", lambda: SimpleNamespace(retrieval=settings))
    text, media, trace = retriever.retrieve_with_plan("Cho xem ảnh hoạt động", plan,
        text_kwargs={"tvec": [.1], "terms": [], "limit": 5},
        media_kwargs={"img_query_vecs": [[.1]], "terms": [], "limit": 5, "f": None})
    assert plan.mode == "parallel_multimodal"
    assert [c.candidate_id for c in text] == ["text:t1"]
    assert [c.candidate_id for c in media] == ["media:m1"]
    assert observed["text"]["allowed_legs"] == plan.text_legs
    assert observed["media"]["allowed_legs"] == plan.media_legs
    assert observed["text"]["max_legs"] + observed["media"]["max_calls"] <= 9
    assert trace["route"] == "parallel_multimodal"


def test_text_only_mode_does_not_dispatch_media(monkeypatch):
    settings = _settings()
    plan = make_plan(understand(""), enabled=True, settings=settings)
    monkeypatch.setattr(query_rewriter, "hybrid_search_text", lambda **kw: [])
    monkeypatch.setattr(retriever, "_media_candidates", lambda **kw: (_ for _ in ()).throw(
        AssertionError("media called")))
    monkeypatch.setattr(retriever, "get_settings", lambda: SimpleNamespace(retrieval=settings))
    text, media, trace = retriever.retrieve_with_plan("", plan, text_kwargs={}, media_kwargs=None)
    assert plan.mode == "text_only"
    assert text == media == []
    assert trace["leg_counts"]["media"] == 0


def test_independent_caption_provenance_and_unlinked_media():
    text = fuse_text_lists([RankedList("bm25", ({"_pid": "t", "document_id": 7,
               "url": "https://example.org/text"},))])
    caption = {"media_key": "caption", "url": "https://example.org/media",
               "caption": "Thông báo trên ảnh", "modality": "caption"}
    random = {"media_key": "random", "url": "https://example.org/other",
              "modality": "image"}
    media = fuse_media_lists([RankedList("caption", (caption, random))])
    result = link_evidence("Câu hỏi ảnh", text, media, ())
    assert len(result.links) == 1
    assert result.links[0].path == "media-caption-provenance"
    assert result.unlinked_media_ids == ("media:random",)


def test_entity_mismatch_never_links_media_from_same_document():
    from sict_crawler.service.retrieval.entity_index import EntityCandidate

    entity = EntityCandidate(entity_id="person:nghien", entity_type="person",
        canonical_name="Nguyễn Bá Nghiễn", matched_surface="Nghiễn", aliases=("Nghiễn",),
        confidence=1.0, ambiguity_count=1, source_document_ids=(7,),
        provenance=("reviewed:7",), method="alias")
    wrong = {"media_key": "wrong", "url": "https://example.org/7", "document_id": 7,
             "caption": "Một người khác", "entity_ids": ["person:someone-else"]}
    correct = {"media_key": "right", "url": "https://example.org/7", "document_id": 7,
               "caption": "Nguyễn Bá Nghiễn", "entity_ids": ["person:nghien"]}
    media = fuse_media_lists([RankedList("caption", (wrong, correct))])

    links = link_evidence("thầy Nghiễn", [], media, (entity,))

    assert [item.media_id for item in links.links] == ["media:right"]
    assert links.links[0].path == "entity-media"
    assert links.unlinked_media_ids == ("media:wrong",)


def test_verified_media_evidence_reaches_agent_context():
    from sict_crawler.service.retrieval.sources import build_context, media_sources

    media = {"video_key": "v1", "url": "https://example.org/video", "page_url": "https://example.org/p",
             "kind": "video_frame", "score": .72, "modality": "clip", "raw_score": .72,
             "caption": "Thông tin sự kiện", "ocr_text": "Bảng lịch trình", "subtitle": "Lời giới thiệu"}
    kept, count = retriever._linked_media_hits("Cho xem video sự kiện", [], [media])
    assert count == 1
    assert kept[0]["evidence_verified"] is True
    source = media_sources(kept)[0]
    assert source.evidence_verified is True
    assert all(s in source.content for s in ("Thông tin sự kiện", "Bảng lịch trình", "Lời giới thiệu"))
    assert "Lời giới thiệu" in build_context([], [source])


def test_candidate_media_rejects_unrelated_video_with_valid_provenance():
    unrelated = {"video_key": "other", "url": "https://example.org/video/other",
                 "page_url": "https://example.org/page/other", "kind": "video_frame",
                 "score": .8, "modality": "clip", "raw_score": .8,
                 "title": "Chương trình trao đổi sinh viên", "caption": "Giới thiệu trường SICT"}
    related = {"video_key": "cooking", "url": "https://example.org/video/cooking",
               "page_url": "https://example.org/page/cooking", "kind": "video_frame",
               "score": .8, "modality": "clip", "raw_score": .8,
               "title": "Hướng dẫn nấu phở truyền thống", "caption": "Các bước chuẩn bị món phở"}
    kept, count = retriever._linked_media_hits(
        "Có video hướng dẫn nấu phở không?", [], [unrelated, related], wants_video=True)
    assert [h["video_key"] for h in kept] == ["cooking"]
    assert count == 2  # provenance hợp lệ không đồng nghĩa đúng chủ đề


def test_candidate_media_uses_linked_document_or_media_title_for_relevance():
    document = {"_pid": "t1", "document_id": 7, "url": "https://example.org/page/7",
                "content": "Hoạt động tình nguyện của sinh viên tại sự kiện hè 2026"}
    video = {"video_key": "v7", "document_id": 7, "url": "https://example.org/video/7",
             "page_url": "https://example.org/page/7", "kind": "video_frame",
             "score": .8, "modality": "clip", "raw_score": .8, "caption": "Khung hình tại sân trường"}
    kept, _ = retriever._linked_media_hits("Video hoạt động tình nguyện sinh viên", [document],
                                            [video], wants_video=True)
    assert [h["video_key"] for h in kept] == ["v7"]


def test_candidate_video_request_does_not_return_unrelated_image():
    image = {"media_key": "im1", "url": "https://example.org/image/1",
             "page_url": "https://example.org/page/1", "kind": "image",
             "score": .8, "modality": "doc", "raw_score": .8,
             "caption": "Ảnh chương trình hướng nghiệp"}
    kept, _ = retriever._linked_media_hits("Cho xem video chương trình hướng nghiệp", [],
                                            [image], wants_video=True)
    assert kept == []


def test_independent_media_gate_is_candidate_required_only(monkeypatch):
    from sict_crawler.model.schemas import Source
    from sict_crawler.service.retrieval import agent, router

    media = Source(url="https://example.org/media", title="Hình hoạt động", kind="image", score=.8,
                   parent_url="https://example.org/page", via="caption", content="Chữ trên ảnh",
                   evidence_verified=True)
    random = media.model_copy(update={"url": "https://example.org/random", "content": "",
                                      "evidence_verified": False})
    settings = SimpleNamespace(retrieval=SimpleNamespace(planner_mode="candidate"),
                               router=SimpleNamespace(optional_top_docs=2))
    monkeypatch.setattr(agent, "get_settings", lambda: settings)

    route = router.Route(media="required", outputs=["image"])
    _, kept, note, _ = agent.validate("Cho xem ảnh", [], [media, random], "", {"sufficient": False}, route)
    assert [m.url for m in kept] == [media.url]
    assert note is None
    settings.retrieval.planner_mode = "baseline"
    route = router.Route(media="required", outputs=["image"])
    _, kept, note, _ = agent.validate("Cho xem ảnh", [], [media], "", {"sufficient": False}, route)
    assert kept == [] and note and "image" not in route.outputs
    settings.retrieval.planner_mode = "candidate"
    route = router.Route(media="optional", outputs=["image"])
    _, kept, _, _ = agent.validate("Ảnh hoạt động", [], [media], "", {"sufficient": False}, route)
    assert kept == []
    route = router.Route(media="required", wants_video=True, outputs=["image"])
    _, kept, _, _ = agent.validate("Cho xem video", [], [media], "", {"sufficient": False}, route)
    assert kept == []


def test_internal_provenance_flag_is_hidden_from_http():
    from sict_crawler.api.routes import RESPONSE_EXCLUDE
    from sict_crawler.model.schemas import Source

    source = Source(url="https://example.org/media", title="A", kind="image", score=.8,
                    evidence_verified=True, content="OCR private")
    response = source.model_dump(exclude=RESPONSE_EXCLUDE)
    assert "evidence_verified" not in response
    assert "content" not in response
