"""Rerank dựa nhiều tín hiệu và giữ nguồn gốc điểm hybrid."""

from sict_crawler.service.retrieval.fusion import RankedList, fuse_text_lists
from sict_crawler.service.retrieval.reranker import rank_candidates


def _candidates():
    exact = {"_pid": "exact", "url": "https://example.org/exact", "document_id": 7,
             "chunk_id": "7:1", "title": "Nguyễn Bá Nghiễn", "content": "Giảng viên Nguyễn Bá Nghiễn",
             "score": 0.40}
    approximate = {"_pid": "similar", "url": "https://example.org/similar", "document_id": 8,
                   "chunk_id": "8:1", "title": "Tin học", "content": "Đại học kỹ thuật", "score": 0.99}
    return fuse_text_lists([RankedList("dense", (approximate, exact)),
                            RankedList("bm25", (exact,)), RankedList("name_bm25", (exact,))])


def test_feature_rerank_keeps_bm25_exact_phrase_signal():
    candidates = _candidates()
    question = "Nguyễn Bá Nghiễn"
    result = rank_candidates(question, candidates, profile="feature_v1", top_n=2, timeout_ms=500)
    assert result[0].candidate_id == "text:exact"
    assert result[0].phrase_match
    assert dict(result[0].score_breakdown)["bm25"] == 1.0
    assert dict(result[0].score_breakdown)["lexical"] > 0
    assert result[0].dense_score == 0.40


def test_baseline_retains_rrf_order_and_cosine_is_explicit_control():
    candidates = _candidates()
    baseline = rank_candidates("Nguyễn Bá Nghiễn", candidates,
                               profile="baseline_rrf", top_n=2, timeout_ms=50)
    cosine = rank_candidates("Nguyễn Bá Nghiễn", candidates,
                             profile="cosine_control", top_n=2, timeout_ms=50)
    assert baseline == candidates
    assert cosine[0].candidate_id == "text:similar"


def test_top_n_zero_is_safe():
    assert rank_candidates("abc", _candidates(), profile="feature_v1",
                           top_n=0, timeout_ms=100) == []
