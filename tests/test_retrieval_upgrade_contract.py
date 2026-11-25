from types import SimpleNamespace

from sict_crawler.service.retrieval.entity_index import EntityCandidate, AliasIndex
from sict_crawler.service.retrieval.evidence_linking import link_evidence
from sict_crawler.service.retrieval.fusion import Candidate, RankedList
from sict_crawler.service.retrieval.planner import make_plan
from sict_crawler.service.retrieval.query_understanding import understand


def _entity(alias="Nghiễn"):
    return EntityCandidate(
        entity_id="person:nguyen-ba-nghien", entity_type="person",
        canonical_name="Nguyễn Bá Nghiễn", matched_surface=alias,
        aliases=(alias,), confidence=1.0, ambiguity_count=1,
        source_document_ids=(7,), provenance=("reviewed:7",), method="alias",
    )


def test_planner_declares_graph_leg_when_graph_routing_is_selected():
    index = AliasIndex([_entity()])
    understanding = understand("thầy Nghiễn là ai", alias_index=index)
    settings = SimpleNamespace(
        media_first_enabled=False, parallel_multimodal_enabled=False,
        graph_route_on_relation=True, graph_route_on_complexity=True,
        rerank_profile="baseline_rrf", text_candidate_limit=50,
        media_candidate_limit=32, max_retrieval_calls=20,
    )

    plan = make_plan(understanding, enabled=True, settings=settings)

    assert plan.graph_enabled is True
    assert "graph" in plan.text_legs


def test_alias_candidate_is_exposed_as_a_name_phrase_for_retrieval():
    index = AliasIndex([_entity()])
    understanding = understand("tìm thông tin thầy Nghiễn", alias_index=index)

    assert understanding.entities[0].matched_surface == "Nghiễn"
    assert "Nghiễn" in understanding.name_phrases


def test_media_only_caption_with_provenance_is_kept_without_text_hit():
    media = Candidate(
        candidate_id="media:abc", group="media", via="caption", modality="caption",
        document_ids=(), entity_ids=(), rrf_score=1.0, dense_score=.8,
        raw_score=.8, leg_ranks=(("caption", 1),), source_url="https://example.test/post",
        chunk_id=None, media_key="abc", video_key=None, phrase_match=False,
        metadata_match=False, payload={"caption": "Hình ảnh thầy Nghiễn tại sự kiện"},
    )

    result = link_evidence("thầy Nghiễn", [], [media], ())

    assert result.unlinked_media_ids == ()
    assert result.links[0].path == "media-caption-provenance"


def test_alias_artifact_rejects_llm_or_ner_entity_methods():
    from sict_crawler.service.retrieval.entity_index import build_alias_index

    index = build_alias_index([{
        "entity_id": "person:bad", "entity_type": "person",
        "canonical_name": "Tên suy đoán", "method": "llm",
        "source_document_ids": [1], "provenance": ["generated"],
    }])

    assert index.entries == ()
