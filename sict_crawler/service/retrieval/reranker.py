"""Rerank ứng viên với điểm tín hiệu BM25, tên riêng và provenance không bị xóa."""
from __future__ import annotations

import re
import math
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from threading import BoundedSemaphore
from typing import Callable

from sict_crawler.core.text import fold
from sict_crawler.service.retrieval.fusion import Candidate

# Adapter cross-encoder đăng ký trong eval/canary. Không tự tải mô hình khi import.
CrossEncoder = Callable[[str, list[Candidate]], list[float]]
_cross_encoder: CrossEncoder | None = None
_cross_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="retrieval-cross-encoder")
_cross_slot = BoundedSemaphore(1)


def register_cross_encoder(adapter: CrossEncoder | None) -> None:
    global _cross_encoder
    _cross_encoder = adapter


def _signals(question: str, c: Candidate) -> dict[str, float]:
    qtokens = set(re.findall(r"[a-z0-9]+", fold(question)))
    body = fold(" ".join(str(c.payload.get(k) or "") for k in ("title", "content", "caption")))
    terms = set(re.findall(r"[a-z0-9]+", body))
    lexical = len(qtokens & terms) / max(1, len(qtokens))
    leg_names = [name for name, _ in c.leg_ranks]
    return {
        "rrf": c.rrf_score,
        "agreement": max(0, len(set(leg_names)) - 1),
        "dense": min(1.0, max(0.0, c.dense_score)) if c.dense_score is not None and math.isfinite(c.dense_score) else 0.0,
        "bm25": float(any("bm25" in name or "keyword" in name for name in leg_names)),
        "lexical": lexical,
        "phrase": float(c.phrase_match),
        "entity": float(bool(c.entity_ids)),
        "metadata": float(c.metadata_match),
        "title": float(bool(qtokens & set(re.findall(r"[a-z0-9]+", fold(str(c.payload.get("title") or "")))))),
        "provenance": float(bool(c.source_url and (c.chunk_id or c.media_key or c.document_ids))),
    }


def _feature(c: Candidate, signals: dict[str, float]) -> float:
    # Trọng số candidate cần hiệu chỉnh trên golden; giữ RRF là tín hiệu chi phối.
    return (60 * signals["rrf"] + .09 * signals["agreement"] + .12 * signals["dense"] +
            .1 * signals["bm25"] + .1 * signals["lexical"] + .2 * signals["phrase"] +
            .08 * signals["entity"] + .04 * signals["metadata"] + .04 * signals["title"] +
            .02 * signals["provenance"])


def rank_candidates(question: str, candidates: list[Candidate], *, profile: str,
                    top_n: int, timeout_ms: int) -> list[Candidate]:
    pool = list(candidates)
    if top_n <= 0:
        return []
    if profile == "baseline_rrf":
        return pool[:top_n]
    if profile == "cosine_control":
        return sorted(pool, key=lambda c: c.dense_score if c.dense_score is not None and math.isfinite(c.dense_score) else float("-inf"),
                      reverse=True)[:top_n]
    if profile not in {"feature_v1", "cross_encoder"}:
        raise ValueError("Profile không được hỗ trợ")
    results = []
    for c in pool:
        signals = _signals(question, c)
        score = _feature(c, signals)
        results.append(replace(c, rank_score=score, score_breakdown=tuple(signals.items())))
    results.sort(key=lambda c: -c.rank_score)
    if profile == "cross_encoder" and _cross_encoder is not None and timeout_ms > 0 and _cross_slot.acquire(blocking=False):
        # Chỉ một inference đang chạy; timeout không tạo thêm luồng bị treo.
        adapter = _cross_encoder
        def score_bounded():
            try:
                return adapter(question, results[:top_n])
            finally:
                _cross_slot.release()

        future = _cross_pool.submit(score_bounded)
        try:
            scores = future.result(timeout=timeout_ms / 1000)
            if len(scores) == min(top_n, len(results)) and all(math.isfinite(float(s)) for s in scores):
                # tanh giới hạn trọng số cross-encoder, bảo vệ tín hiệu RRF/BM25.
                head = [replace(c, rank_score=c.rank_score + .1 * math.tanh(float(s)),
                                score_breakdown=c.score_breakdown + (("cross_encoder", float(s)),))
                        for c, s in zip(results[:top_n], scores)]
                head.sort(key=lambda c: -c.rank_score)
                return head
        except Exception:
            future.cancel()
    return results[:top_n]
