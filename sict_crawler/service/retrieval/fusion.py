"""RRF theo nhóm độc lập. Giữ provenance leg và cosine chưa quan sát dưới dạng None."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, Mapping


@dataclass(frozen=True)
class RankedList:
    leg: str
    hits: tuple[dict, ...]


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    group: Literal["text", "media"]
    via: str
    modality: str | None
    document_ids: tuple[int, ...]
    entity_ids: tuple[str, ...]
    rrf_score: float
    dense_score: float | None
    raw_score: float | None
    leg_ranks: tuple[tuple[str, int], ...]
    source_url: str | None
    chunk_id: str | None
    media_key: str | None
    video_key: str | None
    phrase_match: bool
    metadata_match: bool
    payload: Mapping[str, object] = field(compare=False, repr=False)
    rank_score: float | None = None
    score_breakdown: tuple[tuple[str, float], ...] = ()

    def to_hit(self) -> dict:
        h = dict(self.payload)
        h["score"] = self.rank_score if self.rank_score is not None else self.rrf_score
        if self.dense_score is not None:
            h["dense_score"] = self.dense_score
        if self.raw_score is not None:
            h["raw_score"] = self.raw_score
        h["via"] = self.via
        return h


def _ids(value) -> tuple[int, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (list, tuple)) else [value]
    return tuple(int(v) for v in values if str(v).isdigit())


def _video_id(h: dict) -> str | None:
    # Video frames cùng video_url chỉ là một nguồn media; timestamp giữ trong payload.
    if h.get("video_id"):
        return str(h["video_id"])
    if h.get("video_url"):
        return str(h["video_url"])
    if h.get("kind") == "video_frame" or h.get("media_kind") == "video":
        return str(h.get("parent_media_key") or h.get("video_key") or h.get("media_key") or "") or None
    return None


def _key(h: dict, group: str) -> str:
    if group == "media":
        vid = _video_id(h)
        if vid:
            return "video:" + vid
        return "media:" + str(h.get("media_key") or h.get("media_id") or h.get("_pid") or h.get("url"))
    return "text:" + str(h.get("_pid") or (h.get("url"), h.get("chunk_id", h.get("idx"))))


def _merge_media_evidence(first: Mapping[str, object], later: dict) -> dict:
    """Bổ sung mô tả của cùng video/cùng nguồn, giữ định danh và tín hiệu hạng đầu."""
    first_url = first.get("page_url") or first.get("url")
    later_url = later.get("page_url") or later.get("url")
    if not first_url or not later_url or first_url != later_url:
        return dict(first)
    merged = dict(first)
    for field_name in ("caption", "ocr_text", "subtitle"):
        if not merged.get(field_name) and later.get(field_name):
            merged[field_name] = later[field_name]
    return merged


def _fuse(lists: list[RankedList], group: Literal["text", "media"], rrf_k: int) -> list[Candidate]:
    if rrf_k <= 0:
        raise ValueError("rrf_k phải dương")
    items: dict[str, Candidate] = {}
    for ranked in lists:
        # Một candidate chỉ được một phiếu RRF mỗi leg. Video có nhiều keyframe
        # không thể tự cộng điểm bằng cách xuất hiện nhiều lần trong cùng leg.
        seen_leg: set[str] = set()
        for rank, hit in enumerate(ranked.hits, 1):
            key = _key(hit, group)
            if key in seen_leg:
                if group == "media" and key in items:
                    previous = items[key]
                    items[key] = replace(previous, payload=_merge_media_evidence(previous.payload, hit))
                continue
            seen_leg.add(key)
            previous = items.get(key)
            incr = 1 / (rrf_k + rank)
            dense = hit.get("dense_score")
            if dense is None and ranked.leg.startswith(("dense", "image", "i2i")):
                dense = hit.get("score")
            base = {
                "candidate_id": key, "group": group, "via": str(hit.get("via") or ranked.leg),
                "modality": hit.get("modality"), "document_ids": _ids(hit.get("document_id")),
                "entity_ids": tuple(hit.get("entity_ids") or ()),
                "rrf_score": incr, "dense_score": dense, "raw_score": hit.get("raw_score"),
                "leg_ranks": ((ranked.leg, rank),), "source_url": hit.get("url"),
                "chunk_id": str(hit["chunk_id"]) if hit.get("chunk_id") is not None else None,
                "media_key": hit.get("media_key"), "video_key": _video_id(hit),
                "phrase_match": ranked.leg.startswith("name") or hit.get("via") == "name",
                "metadata_match": bool(hit.get("metadata_match")), "payload": dict(hit),
            }
            if previous is None:
                items[key] = Candidate(**base)
            else:
                # Ưu tiên payload đầu tiên, bổ sung signal có sẵn ở các leg sau.
                items[key] = replace(
                    previous, rrf_score=previous.rrf_score + incr,
                    dense_score=previous.dense_score if previous.dense_score is not None else dense,
                    raw_score=previous.raw_score if previous.raw_score is not None else hit.get("raw_score"),
                    leg_ranks=previous.leg_ranks + ((ranked.leg, rank),),
                    phrase_match=previous.phrase_match or base["phrase_match"],
                    metadata_match=previous.metadata_match or base["metadata_match"],
                    payload=(_merge_media_evidence(previous.payload, hit) if group == "media"
                             else previous.payload),
                )
    return sorted(items.values(), key=lambda c: -c.rrf_score)


def fuse_text_lists(lists: list[RankedList], *, rrf_k: int = 60) -> list[Candidate]:
    return _fuse(lists, "text", rrf_k)


def fuse_media_lists(lists: list[RankedList], *, rrf_k: int = 60) -> list[Candidate]:
    return _fuse(lists, "media", rrf_k)
