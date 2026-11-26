"""Nối media về nguồn có chứng cứ cụ thể, tránh xác nhận bằng cosine đơn lẻ."""
from __future__ import annotations

from dataclasses import dataclass

from sict_crawler.core.text import fold
from sict_crawler.service.retrieval.entity_index import EntityCandidate
from sict_crawler.service.retrieval.fusion import Candidate


@dataclass(frozen=True)
class EvidenceLink:
    text_id: str | None
    media_id: str
    path: str
    document_id: int | None


@dataclass(frozen=True)
class EvidenceLinks:
    links: tuple[EvidenceLink, ...]
    unlinked_media_ids: tuple[str, ...]


def link_evidence(question_context: str, text_candidates: list[Candidate],
                  media_candidates: list[Candidate],
                  entities: tuple[EntityCandidate, ...]) -> EvidenceLinks:
    links: list[EvidenceLink] = []
    missing: list[str] = []
    doc_text = {doc_id: t for t in text_candidates for doc_id in t.document_ids if t.source_url}
    # Chỉ entity đã xác minh và không mơ hồ mới được gắn trực tiếp với media.
    confirmed = tuple(entity for entity in entities if entity.provenance
                      and entity.ambiguity_count == 1 and entity.confidence >= 0.85)
    confirmed_ids = {entity.entity_id for entity in confirmed}
    for media in media_candidates:
        # ID thực thể tường minh mâu thuẫn với thực thể duy nhất trong câu hỏi.
        # document_id chung có thể chứa nhiều người/ảnh, nên không được ghi đè mismatch.
        if confirmed_ids and media.entity_ids and confirmed_ids.isdisjoint(media.entity_ids):
            missing.append(media.candidate_id)
            continue
        if not media.source_url and not media.payload.get("page_url"):
            missing.append(media.candidate_id)
            continue
        # Caption, OCR, subtitle hoặc frame có media source và đoạn mô tả gắn nguồn.
        caption = str(media.payload.get("caption") or media.payload.get("ocr_text") or
                      media.payload.get("subtitle") or "").strip()
        provenance = bool(media.media_key or media.video_key or media.payload.get("media_id"))
        shared = next((doc for doc in media.document_ids if doc in doc_text), None)
        if shared is not None and provenance:
            links.append(EvidenceLink(doc_text[shared].candidate_id, media.candidate_id, "text-document-media", shared))
        elif caption and provenance:
            doc = media.document_ids[0] if media.document_ids else None
            # Chỉ nhận entity-media khi media chứng minh danh tính bằng ID hoặc
            # caption chứa tên đã duyệt, đồng thời có provenance tài liệu.
            caption_folded = fold(caption)
            has_entity = any(doc in entity.source_document_ids and (
                entity.entity_id in media.entity_ids or
                any(fold(name) in caption_folded for name in
                    (entity.canonical_name, *entity.aliases) if name)
            ) for entity in confirmed)
            path = "entity-media" if has_entity else (
                "caption-document" if doc is not None else "media-caption-provenance")
            links.append(EvidenceLink(None, media.candidate_id, path, doc))
        else:
            missing.append(media.candidate_id)
    return EvidenceLinks(tuple(links), tuple(missing))
