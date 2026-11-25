"""Adapter cross-encoder tùy chọn có giới hạn và fallback xác định."""

import threading

from sict_crawler.service.retrieval import reranker
from sict_crawler.service.retrieval.fusion import RankedList, fuse_text_lists


def _inputs():
    hits = tuple({"_pid": str(i), "url": f"https://example.org/{i}",
                  "document_id": i, "chunk_id": str(i), "title": f"Khóa {i}",
                  "score": .95 - .02 * i} for i in range(3))
    return fuse_text_lists([RankedList("dense", hits)])


def _rank(profile="cross_encoder", timeout=500):
    return reranker.rank_candidates("Khóa 0", _inputs(), profile=profile,
                                   top_n=2, timeout_ms=timeout)


def test_cross_encoder_success_is_bounded_and_has_breakdown():
    received = []

    def adapter(question, candidates):
        received.append((question, len(candidates)))
        return [-2, 2]

    reranker.register_cross_encoder(adapter)
    try:
        ranked = _rank()
        assert received == [("Khóa 0", 2)]
        assert len(ranked) == 2
        assert all("cross_encoder" in dict(c.score_breakdown) for c in ranked)
    finally:
        reranker.register_cross_encoder(None)


def test_cross_encoder_failure_and_empty_output_fall_back_to_feature():
    expected = _rank(profile="feature_v1")
    for adapter in (lambda q, candidates: [],
                    lambda q, candidates: (_ for _ in ()).throw(ValueError("offline"))):
        reranker.register_cross_encoder(adapter)
        try:
            assert _rank() == expected
        finally:
            reranker.register_cross_encoder(None)


def test_cross_encoder_timeout_falls_back_without_launching_more_work():
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    called = []

    def adapter(question, candidates):
        called.append(len(candidates))
        started.set()
        try:
            release.wait(timeout=2)
            return [1.0] * len(candidates)
        finally:
            finished.set()

    reranker.register_cross_encoder(adapter)
    try:
        expected = _rank(profile="feature_v1")
        assert _rank(timeout=10) == expected
        assert started.wait(timeout=1)
        assert _rank(timeout=10) == expected
        assert called == [2]
    finally:
        release.set()
        assert finished.wait(timeout=2)
        reranker.register_cross_encoder(None)
