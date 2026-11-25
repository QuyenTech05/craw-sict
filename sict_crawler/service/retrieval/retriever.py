"""Truy xuất lai (D17/D20/D21): viết lại câu hỏi → dense + BM25 RRF → ưu tiên metadata → media qua router;
ảnh người dùng gửi (U3–U7) → ảnh giống + chữ của bài chứa ảnh. Kết quả cache Redis theo câu hỏi."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import lru_cache

from sict_crawler.core.config import get_settings
from sict_crawler.core.text import fold
from sict_crawler.model.schemas import Source
from sict_crawler.repository import cache, vector_store
from sict_crawler.service.embedding import embedder
from sict_crawler.service.retrieval import filters as F
from sict_crawler.service.retrieval.sources import media_sources, text_sources

QUERY_TTL = 600      # kết quả retrieve theo câu hỏi (giây)
DOC_MEDIA_LIMIT = 32  # A: số ảnh / khung hình tối đa lấy từ các bài chữ đứng đầu (gate chia lượt theo hit chữ)
# Tầng GIAI ĐOẠN của truy vấn song song (2026-10-25): nhúng ảnh truy vấn, nhánh media chạy cùng nhánh chữ. Tầng dưới là
# vector_store.parallel (nhánh) → _per_collection (collection): việc ở tầng này chỉ chờ tầng dưới, không kẹt khi đầy.
_STAGE_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="retrieve-stage")
_LOG = logging.getLogger(__name__)


def index_tag() -> str:
    """Fingerprint ba collection v3 để không dùng lại cache khi đổi index."""
    q = get_settings().qdrant
    return f"{q.collection_text}|{q.collection_image}|{q.collection_ocr}"


def query_cache_key(question: str, top_k: int, filters_key: str = "", index: str | None = None) -> str:
    index = index_tag() if index is None else index
    # Eval paired chạy hai API riêng; namespace theo lần đo để tránh cache cũ làm lệch latency/quality.
    # Khi không có env này, cache key production giữ nguyên từng byte.
    namespace = os.environ.get("SICT_EVAL_CACHE_NAMESPACE", "")
    if namespace:
        index = f"{index}|eval:{namespace}"
    return "q:v13:" + hashlib.sha256(   # v13: route ảnh đầu vào và yêu cầu tệp; v12: media theo bằng chứng (ảnh của bài chữ đứng đầu, video, sufficient); v11: nhánh cụm tên riêng; v10: graph khái niệm D33 (bỏ [graph], ảnh theo người); v9: đoạn đủ dài, đoạn liền kề câu liệt kê, khôi phục dấu; v8: phạm vi mục + năm nhãn bảng + tiêu đề; v7: bảng mang nhãn; v6: D30
        f"{question}\x00{top_k}\x00{filters_key}\x00{index}".encode()).hexdigest()


def _graph_filter(keys: list[str], field: str = "entities", all_of: bool = False):
    """Lọc payload theo thực thể: bất kỳ (OR) hoặc tất cả (AND — câu hỏi nêu ≥ 2 thực thể)."""
    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue
    if not keys or (all_of and len(keys) < 2):
        return None
    if all_of:
        return Filter(must=[FieldCondition(key=field, match=MatchValue(value=k)) for k in keys])
    return Filter(must=[FieldCondition(key=field, match=MatchAny(any=keys))])


def _media_candidates(img_query_vecs: list[list[float]], terms: list[str], limit: int,
                      f: F.QueryFilters, text: str = "",
                      image_vecs: list[list[float]] | None = None, wants_video: bool = False,
                      caption_vec: list[float] | None = None,
                      max_calls: int | None = None,
                      allowed_legs: tuple[str, ...] | None = None) -> list[dict]:
    """Ứng viên media cho router.gate, giữ ĐIỂM GỐC theo loại (không RRF):
    CLIP ảnh (clip, raw_score=cosine) + caption khớp từ khoá (caption_kw, không điểm: gate chỉ nhận khi gắn bài chữ).
    image_vecs: vector của ẢNH người dùng gửi (D21, không gian jina) → modality "i2i", ngưỡng riêng; legacy CLIP thì
    ảnh gửi lên nằm chung img_query_vecs.
    wants_video (câu đòi video, D 2026-11-05): thêm 1 lượt CLIP chỉ trong khung hình video và 1 lượt dense chỉ trong
    caption video (tiêu đề + phụ đề, `caption_vec` cùng không gian collection ocr) — ảnh thường đông gấp nhiều lần nên
    trước đây chiếm hết top (v002 "xem video giới thiệu CTĐT CNTT" → 8/8 ảnh)."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    qf = F.to_qdrant(f)
    calls: list = []   # mỗi lượt Qdrant 1 hàm → vector_store.parallel
    frames = Filter(must=[FieldCondition(key="kind", match=MatchValue(value="video_frame"))])
    searches = (("image", "clip", img_query_vecs, qf),
                ("image", "i2i", image_vecs or [], qf),
                ("video", "clip", img_query_vecs if wants_video else [], vector_store._and(qf, frames)))
    if allowed_legs is not None:
        # Ảnh người dùng gửi cần giữ chỗ i2i khi budget nhỏ.
        searches = (searches[1], searches[0], searches[2])
    for leg, modality, vecs, flt in searches:
        if allowed_legs is not None and leg not in allowed_legs:
            continue
        for v in vecs:
            calls.append(lambda v=v, modality=modality, flt=flt: [
                {**h, "modality": modality, "raw_score": h.get("score")}
                for h in vector_store.search_images(v, limit=limit, query_filter=flt)])
    cap_only = vector_store._and(qf, Filter(must=[
        FieldCondition(key="kind", match=MatchValue(value="media_caption"))]))

    def captions():
        try:
            hits = vector_store.keyword_search(text or " ".join(terms), terms[:3], limit=limit,
                                               query_filter=cap_only, collection=vector_store.ocr_collection())
        except Exception:
            hits = []
        return [{**h, "modality": "caption_kw", "raw_score": None} for h in hits if h.get("kind") == "media_caption"]
    if allowed_legs is None or "caption" in allowed_legs:
        calls.append(captions)
    if wants_video and caption_vec is not None and (allowed_legs is None or "video" in allowed_legs):
        vcap = vector_store._and(cap_only, Filter(must=[FieldCondition(key="media_kind", match=MatchValue(value="video"))]))

        def video_captions():
            try:
                hits = vector_store.search_text(caption_vec, limit=limit, query_filter=vcap,
                                                collection=vector_store.ocr_collection())
            except Exception:
                hits = []
            return [{**h, "modality": "caption", "raw_score": h.get("score")} for h in hits]
        calls.append(video_captions)
    if max_calls is not None:
        calls = calls[:max(0, max_calls)]
    return [h for part in vector_store.parallel(calls) for h in part]


@lru_cache(maxsize=4)
def _alias_from_file(path: str, mtime: int, min_confidence: float):
    from sict_crawler.service.retrieval.entity_index import AliasIndex, load_alias_index
    index = load_alias_index(path)
    return AliasIndex(index.entries, min_confidence=min_confidence)


def _plan_context(question: str, has_image: bool, filters: dict | None):
    """Best-effort feature context. Thiếu artifact giữ deterministic router, không fail request."""
    from pathlib import Path
    from sict_crawler.service.retrieval import query_understanding, planner
    from sict_crawler.service.graph import graph as G

    settings = get_settings().retrieval
    alias_index = None
    if settings.entity_index_enabled and settings.entity_alias_path:
        try:
            path = Path(settings.entity_alias_path)
            alias_index = _alias_from_file(str(path.resolve()), path.stat().st_mtime_ns,
                                           settings.entity_alias_min_confidence)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            _LOG.warning("retrieval_alias_index_unavailable")
    understanding = query_understanding.understand(question, has_image=has_image,
                                                   filters=filters, alias_index=alias_index)
    # Shadow tính plan thật để quan sát, chỉ candidate mới dùng plan để truy vấn.
    # Concept graph D33 có matcher độc lập với alias entity. Dùng cùng tín hiệu
    # đang phục vụ legacy để planner không vô tình bỏ phiếu RRF của graph.
    graph_concepts = G.match_question(question, understanding.rewritten_question)
    plan = planner.make_plan(understanding, enabled=True, settings=settings,
                             has_graph_concepts=bool(graph_concepts))
    return understanding, plan


def _planner_cache_suffix(plan) -> str:
    """Fingerprint thay đổi khi mode, graph/alias/rerank/leg policy thay đổi."""
    settings = get_settings().retrieval
    config = (plan.mode, plan.text_legs, plan.media_legs, plan.rerank_profile,
              plan.max_qdrant_calls, plan.text_candidate_limit, plan.media_candidate_limit,
              settings.entity_index_enabled, settings.entity_alias_path,
              settings.entity_alias_min_confidence, settings.media_coupled_optional,
              settings.rerank_top_n, settings.rerank_timeout_ms)
    return "|planner:v1:" + hashlib.sha256(repr(config).encode()).hexdigest()[:16]


def retrieve_with_plan(question, plan, *, text_kwargs: dict,
                       media_kwargs: dict | None = None):
    """Chạy độc lập các group, fusion riêng và giữ rank provenance.

    Caller tạo embeddings/filters trước khi gọi. Cắt số leg theo budget để tránh
    số lượt Qdrant tăng không giới hạn khi câu hỏi sinh nhiều alias/phrase.
    """
    from sict_crawler.service.retrieval import query_rewriter
    from sict_crawler.service.retrieval.fusion import RankedList, fuse_text_lists, fuse_media_lists
    from sict_crawler.service.retrieval.reranker import rank_candidates

    start = time.monotonic()
    media_budget = min(4, max(1, plan.max_qdrant_calls // 3)) if media_kwargs and plan.media_legs else 0
    text_budget = max(0, plan.max_qdrant_calls - media_budget)
    tfut = _STAGE_POOL.submit(query_rewriter.hybrid_search_text,
                              return_ranked_lists=True, max_legs=text_budget,
                              allowed_legs=plan.text_legs, **text_kwargs) if text_budget else None
    mfut = _STAGE_POOL.submit(_media_candidates, max_calls=media_budget,
                              allowed_legs=plan.media_legs, **media_kwargs) if media_budget else None
    text_lists = tfut.result() if tfut else []
    text_candidates = fuse_text_lists(text_lists)
    text_candidates = rank_candidates(question, text_candidates, profile=plan.rerank_profile,
                                       top_n=min(len(text_candidates), plan.text_candidate_limit),
                                       timeout_ms=get_settings().retrieval.rerank_timeout_ms)
    try:
        media_hits = mfut.result() if mfut else []
    except Exception:
        _LOG.exception("retrieval_media_group_failed")
        media_hits = []
    groups: dict[str, list[dict]] = {}
    for hit in media_hits:
        groups.setdefault(str(hit.get("modality") or "clip"), []).append(hit)
    media_candidates = fuse_media_lists([RankedList(name, tuple(hits)) for name, hits in groups.items()])
    media_candidates = media_candidates[:plan.media_candidate_limit]
    trace = {"route": plan.mode,
             "leg_counts": {"text": len(text_lists), "media": len(groups)},
             "stage_ms": {"groups": round((time.monotonic() - start) * 1000, 2)},
             "evidence": "pending", "media_gate": "pending"}
    return text_candidates, media_candidates, trace


def _linked_media_hits(question: str, text_hits: list[dict], kept: list[dict], entities=(),
                       *, wants_video: bool = False) -> tuple[list[dict], int]:
    """Đối chiếu provenance và chủ đề sau video-dedup, giữ media-only có bằng chứng."""
    from sict_crawler.core.sparse import question_terms, tokens
    from sict_crawler.service.retrieval.evidence_linking import link_evidence
    from sict_crawler.service.retrieval.fusion import RankedList, _key, fuse_media_lists, fuse_text_lists
    from sict_crawler.service.retrieval.router import is_video

    text_group = fuse_text_lists([RankedList("text", tuple(text_hits))])
    media_group = fuse_media_lists([RankedList("media", tuple(kept))])
    links = link_evidence(question, text_group, media_group, tuple(entities))
    verified = {link.media_id for link in links.links}
    fused = {candidate.candidate_id: candidate.payload for candidate in media_group}
    # Từ về hình thức yêu cầu media không chứng minh chủ đề. Một video có
    # provenance thật vẫn có thể nói về chuyện hoàn toàn khác với câu hỏi.
    topic = set(question_terms(question)) - {
        "video", "clip", "anh", "hinh", "chup", "huong", "dan", "gioi", "thieu",
    }
    by_doc = {str(doc): [] for h in text_hits for doc in (
        h.get("document_id") if isinstance(h.get("document_id"), list)
        else [h.get("document_id")]) if doc is not None}
    for hit in text_hits:
        docs = hit.get("document_id")
        for doc in (docs if isinstance(docs, list) else [docs]):
            if doc is not None and str(doc) in by_doc:
                by_doc[str(doc)].append(str(hit.get("title") or "") + " " + str(hit.get("content") or ""))
    seen: set[str] = set()
    filtered: list[dict] = []
    for hit in kept:
        key = _key(hit, "media")
        if key in seen:
            continue
        if wants_video and not is_video(hit) and hit.get("modality") != "i2i":
            continue
        docs = hit.get("document_id")
        descriptions = [str(hit.get(field) or "") for field in
                        ("title", "caption", "ocr_text", "subtitle")]
        for doc in (docs if isinstance(docs, list) else [docs]):
            descriptions.extend(by_doc.get(str(doc), []))
        if topic and hit.get("modality") != "i2i":
            matched = topic.intersection(tokens(" ".join(descriptions)))
            # Chỉ yêu cầu một từ nội dung với câu ngắn; câu dài phải có
            # ít nhất hai tín hiệu, tránh nhận nhầm do một từ chung.
            required = 2 if len(topic) >= 4 else 1
            if len(matched) < required:
                continue
        if key in verified or hit.get("modality") == "i2i":
            merged = dict(hit)
            enriched = fused.get(key, {})
            for field_name in ("caption", "ocr_text", "subtitle"):
                if not merged.get(field_name) and enriched.get(field_name):
                    merged[field_name] = enriched[field_name]
            if key in verified:
                merged["evidence_verified"] = True
            filtered.append(merged)
            seen.add(key)
    return filtered, len(links.links)


def _doc_media(vec: list[float] | None, docs: list, limit: int, qf=None) -> list[dict]:
    """A (2026-11-05): ảnh / khung hình của chính các bài đứng đầu nhánh chữ (`document_id` của point ảnh là danh sách
    bài dùng chung) — 1 lượt Qdrant lọc theo bài, xếp theo cosine câu hỏi↔ảnh (modality `doc`, raw_score = cosine,
    cùng ngưỡng với clip). Trước đây ứng viên chỉ đến từ CLIP / caption toàn collection, nên bài đúng hạng 1–2 nhánh chữ
    vẫn có 0/8 ảnh trong kết quả (media_v1 m001 / m023 / m027) và câu không có từ khoá ảnh không có ảnh nào."""
    from qdrant_client.models import FieldCondition, Filter, MatchAny
    ids = [int(d) for d in dict.fromkeys(docs) if isinstance(d, int) or str(d).isdigit()]
    if vec is None or not ids:
        return []
    flt = vector_store._and(qf, Filter(must=[FieldCondition(key="document_id", match=MatchAny(any=ids))]))
    try:
        hits = vector_store.search_images(vec, limit=limit, query_filter=flt)
    except Exception:
        return []
    return [{**h, "modality": "doc", "raw_score": h.get("score")} for h in hits]


def _as_media(h: dict) -> dict:
    """Caption point (sict_text) → dạng media payload cho media_sources."""
    if h.get("kind") == "media_caption":
        return {**h, "kind": h.get("media_kind", "image")}
    return h


def _image_tag(b64: str | None) -> str:
    return "|img:" + hashlib.sha256(b64.encode()).hexdigest()[:20] if b64 else ""


def _query_image_vec(b64: str | None) -> list[float] | None:
    """Vector của ảnh người dùng gửi; ảnh hỏng/không giải mã được → None (truy vấn chạy tiếp bằng chữ)."""
    if not b64:
        return None
    try:
        v = embedder.embed_query_image_base64([b64])
    except Exception:
        return None
    return v[0] if v else None


def _image_block(media_key: str | None, doc_id: int) -> int | None:
    """Block chứa ảnh `media_key` trong bài `doc_id` (D23), đọc từ điểm caption của ảnh đó — điểm ảnh chung
    nhiều bài nên không mang vị trí. None = dữ liệu cũ chưa có cấu trúc."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    if not media_key:
        return None
    try:
        caps = vector_store.scroll_text(Filter(must=[
            FieldCondition(key="kind", match=MatchValue(value="media_caption")),
            FieldCondition(key="media_key", match=MatchValue(value=media_key)),
            FieldCondition(key="document_id", match=MatchValue(value=doc_id))]), limit=4,
            collection=vector_store.ocr_collection())
    except Exception:
        return None
    return next((c["block_idx"] for c in caps if c.get("block_idx") is not None), None)


def _doc_chunks(doc_id) -> list[dict]:
    """Mọi chunk chữ (không caption) của 1 bài trong collection chữ đang phục vụ."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    try:
        return [c for c in vector_store.scroll_text(Filter(must=[
            FieldCondition(key="document_id", match=MatchValue(value=doc_id))]),
            collection=get_settings().qdrant.collection_text) if c.get("kind") != "media_caption"]
    except Exception:
        return []


def list_neighbors(hits: list[dict], n_docs: int, window: int = 1) -> list[dict]:
    """Câu liệt kê (thử nghiệm 2026-11-02): đoạn liền trước / liền sau (±window theo `idx`) của các đoạn thuộc `n_docs`
    bài đứng đầu. Phần mở đầu khớp câu hỏi, còn danh sách hay nằm ở đoạn kế bên; mỗi bài chỉ lấy 1 đoạn nên mất.
    Bỏ đoạn đã có trong `hits`. Trả về theo thứ tự bài rồi `idx`, gắn via="neighbor"."""
    docs = list(dict.fromkeys(h.get("document_id") for h in hits if isinstance(h.get("document_id"), int)))[:n_docs]
    have = {(h.get("document_id"), h.get("idx")) for h in hits}
    out = []
    for d in docs:
        mine = {h.get("idx") for h in hits if h.get("document_id") == d}
        want = {i + o for i in mine if i is not None for o in range(-window, window + 1) if o}
        for c in sorted(_doc_chunks(d), key=lambda c: c.get("idx", 0)):
            if c.get("idx") in want and (d, c.get("idx")) not in have:
                out.append({**c, "via": "neighbor", "score": 0.0})
                have.add((d, c.get("idx")))
    return out


def _chunks_around(doc_id: int, block_idx: int, limit: int = 2) -> list[dict]:
    """Chunk chữ sát ảnh ở block `block_idx` (D24 — ngữ cảnh phụ cận để ánh xạ ảnh về trang): chunk có block
    nằm trong khoảng của nó trước; ảnh ở ranh giới giữa hai chunk thì lấy chunk liền trước + liền sau."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    try:
        chunks = [c for c in vector_store.scroll_text(Filter(must=[
            FieldCondition(key="document_id", match=MatchValue(value=doc_id))]),
            collection=get_settings().qdrant.collection_text)
            if c.get("block_range") and c.get("kind") != "media_caption"]
    except Exception:
        return []
    inside = [c for c in chunks if c["block_range"][0] <= block_idx <= c["block_range"][1]]
    if inside:
        return inside[:limit]
    before = max((c for c in chunks if c["block_range"][1] < block_idx), key=lambda c: c["block_range"][1], default=None)
    after = min((c for c in chunks if c["block_range"][0] > block_idx), key=lambda c: c["block_range"][0], default=None)
    return [c for c in (before, after) if c][:limit]


def _linked_doc_hits(ivec: list[float], kept: list[dict], qf) -> list[dict]:
    """U4/D24: bài chứa ảnh giống ảnh người dùng gửi → đoạn chữ gần ảnh đó (theo block) làm ngữ cảnh; ảnh chưa
    có vị trí block thì lấy đoạn giống vector ảnh nhất của bài. Điểm = độ giống của ảnh."""
    from sict_crawler.service.retrieval import router
    linked: list[dict] = []
    pairs = list(dict.fromkeys((d, h.get("media_key")) for h in kept if h.get("modality") == "i2i"
                               for d in router._docs_of(h)))[:3]
    for d, media_key in pairs:
        hits = []
        blk = _image_block(media_key, int(d))
        if blk is not None:
            hits = _chunks_around(int(d), blk)
        if not hits:
            try:
                hits = [h for h in vector_store.search_text(
                    ivec, limit=2, filter_document_id=int(d), query_filter=qf,
                    collection=get_settings().qdrant.collection_text) if h.get("kind") != "media_caption"]
            except Exception:
                hits = []
        linked += [{**h, "via": "i2i-doc"} for h in hits]
    return linked


def _doc_key(h: dict):
    d = h.get("document_id")
    return tuple(d) if isinstance(d, list) else (d if d is not None else h.get("url"))


_HEADER = re.compile(r"^\s*\[[^\]]*\]\s*")


def _title_only(h: dict) -> bool:
    """Mảnh chỉ gồm header ngữ cảnh + đúng tiêu đề (đoạn mở đầu trang có bảng): không có gì cho LLM."""
    body = _HEADER.sub("", h.get("content") or h.get("text") or "", count=1)
    return bool(body) and fold(body).strip(" .:") == fold(h.get("title") or "").strip(" .:")


def demote_title_only(hits: list[dict]) -> list[dict]:
    """Mảnh chỉ có tiêu đề xếp ngay sau mảnh nội dung cuối của cùng bài (nếu bài có mảnh nội dung trong danh sách),
    để diversify (câu liệt kê: 1 mảnh / bài) chọn mảnh nội dung. Bài chỉ có mảnh tiêu đề thì giữ nguyên chỗ."""
    out = list(hits)
    for h in [h for h in hits if _title_only(h)]:
        same = [i for i, x in enumerate(out) if _doc_key(x) == _doc_key(h) and not _title_only(x)]
        if same and same[-1] > out.index(h):
            out.remove(h)
            out.insert(same[-1], h)        # sau khi bỏ h, chỉ số mảnh cuối lùi 1 → chèn đúng sau nó
    return out


def dominant_doc(hits: list[dict], min_hits: int, window: int = 10):
    """Bài của hit đầu nếu nó chiếm ≥ `min_hits` trong `window` hit đầu (thứ tự RRF, trước diversify) → câu hỏi nhắm
    đúng bài đó; None nếu không có bài nào áp đảo hoặc min_hits ≤ 0."""
    if min_hits <= 0 or not hits:
        return None
    key = _doc_key(hits[0])
    return key if sum(_doc_key(h) == key for h in hits[:window]) >= min_hits else None


def diversify(hits: list[dict], top_k: int, per_doc: int, dominant=None, dominant_max: int = 0) -> list[dict]:
    """D27: top k không bị một bài chiếm hết — mỗi `document_id` tối đa `per_doc` đoạn trong top k, giữ thứ tự RRF;
    đoạn bị đẩy ra xếp sau (không mất: thiếu bài khác thì chúng lấp chỗ). Đoạn quanh ảnh người dùng gửi (`i2i-doc`)
    không tính giới hạn (U4 cố ý lấy nhiều đoạn của một bài). Bài áp đảo (`dominant`, xem dominant_doc) được tối đa
    `dominant_max` đoạn."""
    if per_doc <= 0:
        return hits
    head: list[dict] = []
    rest: list[dict] = []
    seen: dict = {}
    for h in hits:
        key = _doc_key(h)
        cap = max(per_doc, dominant_max) if dominant is not None and key == dominant else per_doc
        if len(head) < top_k and (h.get("via") == "i2i-doc" or seen.get(key, 0) < cap):
            head.append(h)
            seen[key] = seen.get(key, 0) + 1
        else:
            rest.append(h)
    return head + rest


def retrieve(question: str, top_k: int = 5,
             query_image_b64: str | None = None, filters: dict | None = None, *, route_override=None):
    """→ (text_sources, media_sources, route). Text: rewrite → dense + keyword RRF → rerank → ưu tiên
    mềm metadata. Media theo router D17: ý định `none` bỏ hẳn nhánh media; còn lại chặn theo bằng chứng
    (router.gate, điểm gốc theo loại, gắn với bài chữ đứng đầu).

    Đa phương thức (D21, embedding.backend=api, chữ+ảnh chung không gian): ảnh gửi lên vừa tìm ảnh giống
    (i2i), vừa tìm chunk/caption (i2t), và kéo chunk của BÀI chứa ảnh gần trùng (i2i-doc); chỉ có ảnh
    (question rỗng) → ra cả ảnh lẫn chữ qua jina-clip-v2.

    Cache Redis 10p theo (question, top_k, filters, hash ảnh).
    """
    from sict_crawler.service.retrieval import query_rewriter, router
    rc = get_settings().router
    settings = get_settings().retrieval
    candidate = settings.planner_mode == "candidate"
    understanding = plan = None
    if settings.planner_mode in {"shadow", "candidate"}:
        try:
            understanding, plan = _plan_context(question, bool(query_image_b64), filters)
        except (ValueError, TypeError):
            _LOG.exception("retrieval_planner_fallback")
            candidate = False
    if plan is not None and settings.planner_mode == "shadow":
        _LOG.info("retrieval_shadow mode=%s confidence=%.2f", plan.mode, understanding.confidence)
    has_text = bool(question.strip())
    # metadata: lọc cứng chỉ từ `filters` caller truyền; câu hỏi chỉ cho ưu tiên mềm (filters.py)
    f = F.merge(F.from_request(filters), F.infer(question))
    qf = F.to_qdrant(f)
    index = index_tag() + _planner_cache_suffix(plan) if candidate and plan is not None else None
    ck = query_cache_key(question, top_k, f.cache_key() + _image_tag(query_image_b64), index=index)
    hit = cache.get(ck) if route_override is None else None
    if hit:
        try:
            d = json.loads(hit)
            return ([Source(**s) for s in d["text"]], [Source(**s) for s in d["media"]],
                    router.Route(**d["route"]))
        except Exception:
            pass
    # ảnh truy vấn (CPU, ~4 s ở 336 px) nhúng trong lúc phần chữ chạy (luật viết tắt, graph, nhúng câu hỏi)
    ifut = _STAGE_POOL.submit(_query_image_vec, query_image_b64) if query_image_b64 else None
    if has_text:
        r = query_rewriter.rewrite(question, allow_llm=False) if route_override is not None else query_rewriter.rewrite(question)
        route = route_override or router.decide(question, r.get("route_llm"), has_image=bool(query_image_b64))
        route.list_question = router.is_list_question(question)
    else:   # chỉ ảnh (D21 U3+U4)
        r = {"rewritten": "", "terms": [], "route_llm": None}
        route = route_override or router.Route(media="required", source="image")
    # graph khái niệm (D33): khái niệm nêu trong câu hỏi → thêm danh sách dense lọc theo khái niệm vào RRF
    from sict_crawler.service.graph import graph as G
    ents = G.match_question(question, r["rewritten"]) if has_text else []
    ekeys = G.ekeys(ents)
    route.entities = [e.name for e in ents]
    if candidate and plan is not None and route_override is None:
        if plan.mode == "text_only":
            route.media = "none"
        elif plan.mode == "text_grounded" and route.media == "none" and settings.media_coupled_optional:
            route.media = "optional"
    if query_image_b64 and route.media == "none" and not route.oos:
        route.media = "optional"  # người dùng gửi ảnh → luôn xét media tương tự
    if route.wants_file:
        f.prefer_doc_types = ["attachment"]

    # D27: câu hỏi liệt kê → nhiều nguồn hơn, mỗi bài 1 đoạn; còn lại tối đa per_doc_max đoạn / bài
    gc = get_settings().retrieval
    k = max(top_k, gc.list_top_k) if route.list_question else top_k
    per_doc = 1 if route.list_question else gc.per_doc_max
    # text leg: hybrid (dense + BM25 sparse + dense của ảnh truy vấn, RRF) → ưu tiên mềm metadata.
    # D27: luôn tìm bằng CÂU GỐC; câu LLM viết lại (nếu khác sau khi bỏ dấu) chỉ thêm danh sách vào RRF → đổi/tắt LLM
    # không đổi hẳn kết quả. Nhánh media vẫn dùng vector câu viết lại (rvec) như trước.
    q0 = question.strip()
    # câu không dấu đã khôi phục dấu (retrieval.restore_accents): nhánh dense nhúng câu có dấu; BM25 vẫn dùng câu gốc
    tvec = embedder.embed_query(r.get("restored") or q0) if has_text else None
    rvec, alt = tvec, []
    if has_text and fold(r["rewritten"]).strip() != fold(q0):
        rvec = embedder.embed_query(r["rewritten"])
        alt = [(rvec, r["rewritten"])]
    terms = list(dict.fromkeys(query_rewriter._terms(q0) + r["terms"])) if has_text else []
    ivec = ifut.result() if ifut is not None else None
    if query_image_b64 and ivec is None and not has_text:
        return [], [], router.Route(media="none", source="image", inputs=["image"])   # ảnh hỏng, không có chữ
    extra = [("i2t", ivec)] if ivec is not None else []
    # nhánh media không cần kết quả chữ để TÌM (chỉ cần khi chặn bằng router.gate) → chạy song song với nhánh chữ
    mfut = None
    # số media tối đa theo ý định (router.media_cap): `none` = rc.none_max (mặc định 0 → không chạy nhánh media)
    n_media = router.media_cap(route, top_k, rc.optional_max, rc.none_max)
    img_query_vecs: list = []
    clip_min, caption_min = rc.t2i_min, rc.t2c_min
    if n_media > 0:
        img_query_vecs = [rvec] if rvec is not None else []
        image_vecs = [ivec] if ivec is not None else []
        # ý định `none` (none_max > 0): chỉ ảnh của bài chữ đứng đầu (_doc_media), không tìm toàn collection
        if route.media != "none" and (not candidate or plan.mode in {"media_first", "parallel_multimodal"}):
            if not candidate:
                mfut = _STAGE_POOL.submit(_media_candidates, img_query_vecs, r["terms"], max(top_k, 10), f,
                                          r["rewritten"], image_vecs, route.wants_video, rvec)
    # Planner path: hai nhóm chạy song song; text fusion giữ từng leg, media fusion độc lập.
    media_planned = []
    retrieval_trace = None
    search_kwargs = dict(tvec=tvec, terms=terms,
                         limit=(min(plan.text_candidate_limit, max(k * (3 if route.list_question else 2), 10))
                                if candidate else max(k * (3 if route.list_question else 2), 10)),
                         query_filter=qf, text=q0 or None,
                         graph_filter=[_graph_filter(ekeys, all_of=True), _graph_filter(ekeys)],
                         extra_vecs=extra, alt_queries=alt, scope_filter=F.scope_qdrant(f),
                         phrases=(list(understanding.name_phrases) if candidate and understanding is not None
                                  else query_rewriter.name_phrases(q0)) if has_text else None)
    if candidate and plan is not None:
        media_kwargs = None
        if n_media > 0 and route.media != "none" and set(plan.media_legs) & {"image", "caption", "video"}:
            media_kwargs = dict(img_query_vecs=img_query_vecs, terms=r["terms"],
                                limit=min(plan.media_candidate_limit, max(top_k, 10)), f=f,
                                text=r["rewritten"], image_vecs=image_vecs,
                                wants_video=route.wants_video, caption_vec=rvec)
        ranked_text, media_planned, retrieval_trace = retrieve_with_plan(
            q0, plan, text_kwargs=search_kwargs, media_kwargs=media_kwargs)
        t_hits = [cand.to_hit() for cand in ranked_text]
    else:
        t_hits = query_rewriter.hybrid_search_text(**search_kwargs)
    # cụm tên riêng (2026-11-05): "Phạm Văn Tùng" → 1 danh sách dense chỉ trong đoạn chứa nguyên cụm (xem name_phrases)
    if has_text:
        # Candidate planner đã rerank theo profile riêng; chỉ bổ sung raw_score cho gate,
        # không được để rerank cosine legacy đảo thứ tự candidate.
        reranked = query_rewriter.rerank_text(
            t_hits, r["rewritten"], top_n=len(t_hits),
            reorder=(not candidate and not vector_store.has_sparse()), qvec=tvec)
    else:   # chỉ ảnh: danh sách duy nhất là cosine ảnh↔chữ → lọc theo i2t_min, điểm gốc = cosine
        reranked = [{**h, "raw_score": h["score"]} for h in t_hits if h["score"] >= rc.i2t_min]
    boosted = F.apply_title_boost(F.apply_boost(reranked, f), q0) if has_text else F.apply_boost(reranked, f)
    if f.latest and has_text:
        # "thông báo mới nhất?": thứ tự theo nghĩa không biết ngày → bài mới nhất của mục lên đầu (năm nay và năm trước)
        latest = vector_store.latest_text(f.prefer_sections, limit=k, since_year=date.today().year - 1)
        got = {_doc_key(h) for h in latest}
        boosted = [{**h, "via": "latest"} for h in latest] + [h for h in boosted if _doc_key(h) not in got]
    chunks = demote_title_only([h for h in boosted if h.get("kind") != "media_caption"])
    text_hits = diversify(chunks, k, per_doc, dominant_doc(chunks, gc.dominant_min), gc.dominant_doc_max)

    kept: list[dict] = []
    if n_media > 0:
        top_hits = text_hits[:rc.optional_top_docs]
        # A: ảnh của chính các bài chữ đứng đầu (1 lượt Qdrant sau nhánh chữ, ~10 ms) — trong lúc chờ nhánh media
        dvec = img_query_vecs[0] if img_query_vecs and has_text else None
        cands = _doc_media(dvec, [h.get("document_id") for h in top_hits], DOC_MEDIA_LIMIT, qf)
        if mfut is not None:
            cands += mfut.result()
        if media_planned:
            cands += [c.to_hit() for c in media_planned]
        cands += [{**h, "modality": "caption" if has_text else "i2t"}
                  for h in boosted if h.get("kind") == "media_caption"]
        kept = router.gate(route, top_hits, cands, top_k, clip_min, caption_min, rc.optional_max,
                           rc.i2i_min, rc.i2t_min, rc.none_max)
        if candidate and plan is not None and plan.mode in {"media_first", "parallel_multimodal"}:
            kept, n_links = _linked_media_hits(question, text_hits[:k], kept,
                                               understanding.entities if understanding else (),
                                               wants_video=route.wants_video)
            if retrieval_trace is not None:
                retrieval_trace["evidence"] = n_links
                retrieval_trace["media_gate"] = len(kept)
    msrcs = media_sources([_as_media(h) for h in kept])

    # U4: ảnh giống ảnh người dùng gửi nằm trong bài nào → lấy đoạn gần ảnh nhất của bài đó làm ngữ cảnh
    if ivec is not None:
        linked = _linked_doc_hits(ivec, kept, qf)
        # có chữ kèm ảnh ("ảnh này là sự kiện gì?"): đoạn của bài chứa ảnh khớp NHẤT lên đầu, bài của các ảnh giống
        # kém hơn xếp sau kết quả chữ (ảnh sự kiện khác nhau cũng giống nhau ~0,9, dễ kéo nhầm bài)
        lead = [h for h in linked if linked and h.get("document_id") == linked[0].get("document_id")]
        rest = [h for h in linked if h not in lead]
        text_hits = query_rewriter.dedupe_hits(linked + text_hits if not has_text else lead + text_hits + rest)
    extra = list_neighbors(text_hits[:k], gc.list_neighbor_docs) if route.list_question and gc.list_neighbor_docs else []
    tsrcs = text_sources(text_hits[:k] + extra)
    route.inputs = [x for x, on in (("text", bool(question.strip())), ("image", bool(query_image_b64))) if on]
    route.outputs = [x for x, on in (("text", bool(tsrcs)), ("image", bool(msrcs))) if on]
    if retrieval_trace is not None:
        try:
            _LOG.info("retrieval_plan_trace %s", json.dumps(retrieval_trace))
        except (TypeError, ValueError):
            pass
    if route_override is None:
        cache.put(ck, json.dumps({
            "text": [s.model_dump() for s in tsrcs],
            "media": [s.model_dump() for s in msrcs],
            "route": route.to_dict(),
        }).encode(), QUERY_TTL)
    return tsrcs, msrcs, route
