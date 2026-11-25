"""Hiểu truy vấn và metadata hint đều deterministic, không hard-link suy đoán."""

from sict_crawler.service.retrieval.entity_index import build_alias_index
from sict_crawler.service.retrieval.query_understanding import understand


def _index(ambiguous=False):
    rows = [{"entity_id": "one", "entity_type": "person", "canonical_name": "Nguyễn Bá Nghiễn",
             "aliases": ["Nghiễn"], "source_document_ids": [9], "provenance": ["review:9"]}]
    if ambiguous:
        rows.append({"entity_id": "two", "entity_type": "person", "canonical_name": "Trần Văn Nghiễn",
                     "aliases": ["Nghiễn"], "source_document_ids": [10], "provenance": ["review:10"]})
    return build_alias_index(rows)


def test_short_name_passes_original_surface_and_unique_canonical():
    result = understand("thầy Nghiễn", alias_index=_index())
    assert "Nghiễn" in result.name_phrases
    assert "Nguyễn Bá Nghiễn" in result.name_phrases
    assert result.entities[0].matched_surface == "Nghiễn"


def test_ambiguous_name_does_not_add_wrong_canonical():
    result = understand("thầy Nghiễn", alias_index=_index(ambiguous=True))
    assert "Nghiễn" in result.name_phrases
    assert "Nguyễn Bá Nghiễn" not in result.name_phrases
    assert "Trần Văn Nghiễn" not in result.name_phrases
    assert result.confidence < 0.6


def test_intent_filters_hints_and_graph_signals_are_separate():
    result = understand("Sự kiện hợp tác năm 2025 với ai?", filters={"section": "Tin tức"})
    assert result.explicit_filters["section"] == "Tin tức"
    assert result.metadata_hints["years"] == ("2025",)
    assert result.relation_intent == "relation"
    assert result.complexity == "relation"
    assert result.media_intent != "required"


def test_image_intent_and_unknown_entity():
    assert understand("Cho xem video giới thiệu").media_intent == "required"
    assert understand("Ảnh này nói về gì?", has_image=True).mode == "parallel_multimodal"
    assert understand("Tên người chưa được review", alias_index=_index()).entities == ()
