"""Budget và mode planner không làm thay đổi baseline khi chưa bật."""

from dataclasses import replace
from types import SimpleNamespace

from sict_crawler.service.retrieval.planner import make_plan
from sict_crawler.service.retrieval.query_understanding import understand


def _settings(**overrides):
    defaults = dict(media_first_enabled=True, parallel_multimodal_enabled=True,
                    media_coupled_optional=True, rerank_profile="feature_v1",
                    max_retrieval_calls=20, text_candidate_limit=50,
                    media_candidate_limit=32, graph_route_on_relation=True,
                    graph_route_on_complexity=True)
    return SimpleNamespace(**(defaults | overrides))


def test_fact_text_uses_text_legs_and_no_graph_without_signal():
    plan = make_plan(understand("Học phí ngành CNTT bao nhiêu?"), enabled=True, settings=_settings())
    assert plan.mode == "text_grounded"
    assert "dense" in plan.text_legs and "bm25" in plan.text_legs
    assert plan.graph_enabled is False
    assert plan.graph_hard_filter is False
    assert plan.media_legs == ("coupled",)


def test_available_concept_graph_adds_graph_leg_without_hard_filter():
    query = understand("Cố vấn học tập của trường gồm những ai?")
    assert not query.entities and query.complexity == "simple"
    plan = make_plan(query, enabled=True, settings=_settings(), has_graph_concepts=True)
    assert plan.graph_enabled
    assert "graph" in plan.text_legs
    assert plan.graph_hard_filter is False


def test_optional_event_preserves_independent_media_search():
    query = understand("Hội thảo nghiên cứu khoa học diễn ra thế nào?")
    plan = make_plan(query, enabled=True, settings=_settings(media_coupled_optional=False))
    assert query.media_intent == "optional"
    assert plan.mode == "text_grounded"
    assert {"image", "caption"} <= set(plan.media_legs)
    assert make_plan(understand("Học phí ngành CNTT?"), enabled=True,
                     settings=_settings(media_coupled_optional=False)).media_legs == ()


def test_image_only_planner_retains_media_search():
    query = understand("", has_image=True)
    plan = make_plan(query, enabled=True, settings=_settings(media_coupled_optional=False))
    assert plan.mode == "parallel_multimodal"
    assert "image" in plan.media_legs


def test_media_first_and_parallel_are_feature_gated():
    video = understand("Cho tôi xem video giới thiệu trường")
    assert make_plan(video, enabled=True, settings=_settings()).mode == "media_first"
    assert make_plan(video, enabled=True, settings=_settings(media_first_enabled=False)).mode == "text_grounded"
    mixed = understand("Ảnh này về sự kiện nào?", has_image=True)
    assert make_plan(mixed, enabled=True, settings=_settings()).mode == "parallel_multimodal"
    assert make_plan(mixed, enabled=True, settings=_settings(parallel_multimodal_enabled=False)).mode == "text_grounded"


def test_unknown_confidence_fallback_and_hard_budgets():
    low = replace(understand("Sự kiện nào?"), confidence=0.3, mode="parallel_multimodal")
    plan = make_plan(low, enabled=True, settings=_settings(
        max_retrieval_calls=999, text_candidate_limit=999, media_candidate_limit=999))
    assert plan.mode == "text_grounded"
    assert (plan.max_qdrant_calls, plan.text_candidate_limit, plan.media_candidate_limit) == (30, 200, 100)
    assert plan.metadata_policy == "soft"
    assert make_plan(low, enabled=False, settings=_settings()).rerank_profile == "baseline_rrf"


def test_graph_leg_is_additive_and_does_not_assert_relation_edge():
    query = understand("Hai khoa phối hợp tổ chức sự kiện năm 2025 như thế nào?")
    plan = make_plan(query, enabled=True, settings=_settings())
    assert plan.graph_enabled and "graph" in plan.text_legs
    assert plan.graph_hard_filter is False
    assert plan.metadata_policy == "soft"
