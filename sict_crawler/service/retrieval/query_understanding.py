"""Phân tích truy vấn bằng luật, giữ metadata do suy đoán tách khỏi filter của caller."""
from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping

from sict_crawler.core.text import fold
from sict_crawler.service.retrieval import query_rewriter, router
from sict_crawler.service.retrieval.entity_index import AliasIndex, EntityCandidate

RetrievalMode = Literal["text_only", "text_grounded", "media_first", "parallel_multimodal"]

_RELATION = re.compile(r"\b(?:moi quan he|lien quan|phoi hop|hop tac|tham gia cung|cung voi|giua|ket noi|do ai to chuc)\b")
_TEMPORAL = re.compile(r"\b(?:nam (?:19|20)\d{2}|khi nao|bao gio|truoc day|sau do|theo thoi gian)\b")
_MULTIHOP = re.compile(r"\b(?:so sanh|khac nhau|nhieu giai doan|qua cac nam|tu .* den)\b")
_TEXT_MEDIA = re.compile(r"\b(?:mo ta.*(?:hinh anh|video)|vua.*(?:noi dung|hinh anh)|noi dung.*(?:hinh anh|video))\b")


@dataclass(frozen=True)
class QueryUnderstanding:
    original_question: str
    normalized_question: str
    rewritten_question: str
    restored_question: str | None
    terms: tuple[str, ...]
    name_phrases: tuple[str, ...]
    entities: tuple[EntityCandidate, ...]
    relation_intent: str | None
    metadata_hints: Mapping[str, object]
    explicit_filters: Mapping[str, object]
    media_intent: Literal["none", "optional", "required"]
    wants_file: bool
    wants_video: bool
    list_question: bool
    complexity: Literal["simple", "entity", "event", "relation", "multi_hop"]
    mode: RetrievalMode
    confidence: float
    provenance: tuple[str, ...]


def understand(question: str, *, has_image: bool = False, filters: dict | None = None,
               alias_index: AliasIndex | None = None,
               allow_ner: bool = False, allow_llm: bool = False) -> QueryUnderstanding:
    """Không gọi LLM/NER/Qdrant. Cờ fallback là capability contract, để dành provider được duyệt.

    Trường hợp chưa resolve được giữ tên như phrase và cho dense/BM25 tìm kiếm,
    không tạo entity giả bằng câu trả lời của model.
    """
    normalized = fold(question.strip())
    rewritten = query_rewriter._rule_rewrite(question.strip())
    route = router.classify_rules(question, has_image=has_image)
    entities = tuple(alias_index.match_question(question)) if alias_index else ()
    relation = "relation" if _RELATION.search(normalized) else (
        "temporal" if _TEMPORAL.search(normalized) else None)
    complexity: Literal["simple", "entity", "event", "relation", "multi_hop"] = "simple"
    if _MULTIHOP.search(normalized):
        complexity = "multi_hop"
    elif relation:
        complexity = "relation"
    elif router._EVENT.search(normalized):
        complexity = "event"
    elif entities:
        complexity = "entity"
    mode: RetrievalMode = "text_grounded"
    if route.media == "required":
        mode = "media_first"
    if has_image or _TEXT_MEDIA.search(normalized):
        mode = "parallel_multimodal"
    if not question.strip() and not has_image:
        mode = "text_only"
    hints: dict[str, object] = {}
    if years := re.findall(r"\b(?:19|20)\d{2}\b", normalized):
        hints["years"] = tuple(dict.fromkeys(years))
    unique = alias_index.unique(entities) if alias_index else None
    confidence = 0.95 if unique or route.media == "required" or has_image else 0.75
    if any(e.ambiguity_count > 1 for e in entities):
        confidence = min(confidence, 0.55)
    provenance = ("rules", "alias-index") if entities else ("rules",)
    return QueryUnderstanding(
        original_question=question, normalized_question=normalized,
        rewritten_question=rewritten, restored_question=None,
        terms=tuple(query_rewriter._terms(question)),
        name_phrases=tuple(dict.fromkeys(
            query_rewriter.name_phrases(question)
            + [e.matched_surface for e in entities if e.matched_surface]
            + ([unique.canonical_name] if unique else [])
        )),
        entities=entities, relation_intent=relation,
        metadata_hints=MappingProxyType(hints),
        explicit_filters=MappingProxyType(dict(filters or {})),
        media_intent=route.media, wants_file=route.wants_file, wants_video=route.wants_video,
        list_question=router.is_list_question(question), complexity=complexity,
        mode=mode, confidence=confidence, provenance=provenance)
