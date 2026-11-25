"""Lập kế hoạch truy xuất thuần cho từng mode, có budget cứng và fallback baseline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sict_crawler.service.retrieval.query_understanding import QueryUnderstanding, RetrievalMode


@dataclass(frozen=True)
class RetrievalPlan:
    mode: RetrievalMode
    text_legs: tuple[str, ...]
    media_legs: tuple[str, ...]
    graph_enabled: bool
    graph_hard_filter: bool
    metadata_policy: Literal["none", "soft", "explicit_hard"]
    rerank_profile: str
    text_candidate_limit: int
    media_candidate_limit: int
    max_qdrant_calls: int
    timeout_ms: int
    provenance: tuple[str, ...]


def make_plan(understanding: QueryUnderstanding, *, enabled: bool, settings: object,
              has_graph_concepts: bool = False) -> RetrievalPlan:
    mode = understanding.mode if enabled else "text_grounded"
    if enabled and understanding.confidence < 0.6:
        mode = "text_grounded"
    if mode == "media_first" and not getattr(settings, "media_first_enabled", False):
        mode = "text_grounded"
    if mode == "parallel_multimodal" and not getattr(settings, "parallel_multimodal_enabled", False):
        mode = "text_grounded"
    if not understanding.original_question.strip() and mode == "text_grounded":
        mode = "text_only" if understanding.media_intent == "none" else "parallel_multimodal"
    graph_enabled = has_graph_concepts or bool(understanding.entities) or understanding.complexity == "event" or (
        bool(understanding.relation_intent) and getattr(settings, "graph_route_on_relation", True)) or (
        understanding.complexity == "multi_hop" and getattr(settings, "graph_route_on_complexity", True))
    text_legs = ("dense", "bm25", "i2t", "name_phrase", "scope", "dense_alt", "bm25_alt") if mode != "text_only" else ()
    if graph_enabled and mode != "text_only":
        text_legs += ("graph",)
    media_legs = {
        "text_only": (),
        "text_grounded": (("image", "caption", "video", "coupled")
                          if understanding.media_intent in {"optional", "required"}
                          else (("coupled",) if getattr(settings, "media_coupled_optional", False) else ())),
        "media_first": ("image", "caption", "video"),
        "parallel_multimodal": ("image", "caption", "video", "coupled"),
    }[mode]
    # Chỉ concept graph D33 có thể chạy. Relation graph cần cạnh có provenance trước khi hard-filter.
    profile = getattr(settings, "rerank_profile", "baseline_rrf") if enabled else "baseline_rrf"
    if profile not in {"baseline_rrf", "feature_v1", "cross_encoder", "cosine_control"}:
        profile = "baseline_rrf"
    return RetrievalPlan(
        mode=mode, text_legs=text_legs, media_legs=media_legs,
        graph_enabled=graph_enabled,
        graph_hard_filter=False, metadata_policy="explicit_hard" if understanding.explicit_filters else "soft",
        rerank_profile=profile,
        text_candidate_limit=max(1, min(200, int(getattr(settings, "text_candidate_limit", 50)))),
        media_candidate_limit=max(1, min(100, int(getattr(settings, "media_candidate_limit", 32)))),
        max_qdrant_calls=max(1, min(30, int(getattr(settings, "max_retrieval_calls", 20)))),
        timeout_ms=5000,
        provenance=("planner-v1", *understanding.provenance),
    )
