"""Contract của phép đo cặp baseline/candidate retrieval upgrade."""

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from scripts import eval_retrieval_variants as variants


def manifest():
    return {
        "git_sha": "abc123", "index_tag": "text_v3|image_v3|ocr_v3",
        "model": "jina-clip-v2", "config_fingerprint": "sha256:abc",
        "common_config_fingerprint": "sha256:common", "cache_mode": "isolated_namespace",
        "variant": "baseline", "timestamp": "2026-11-23T16:00:00+00:00",
        "latency": {"p50_ms": 30.0, "p95_ms": 50.0, "scored": 2},
        "metrics": {"text": {}, "media": {}, "answer": {}, "operation": {}},
        "datasets": {"golden": "sha256:dataset"},
        "top_k": 8, "prompt_fingerprint": "sha256:prompt",
    }


@pytest.mark.parametrize("field", [
    "git_sha", "index_tag", "model", "config_fingerprint", "cache_mode",
    "variant", "timestamp", "latency", "metrics",
])
def test_manifest_rejects_required_fields(field):
    candidate = manifest()
    del candidate[field]
    with pytest.raises(ValueError, match=field):
        variants.validate_manifest(candidate)


@pytest.mark.parametrize("group", ["text", "media", "answer", "operation"])
def test_manifest_requires_each_metric_group(group):
    candidate = manifest()
    del candidate["metrics"][group]
    with pytest.raises(ValueError, match=group):
        variants.validate_manifest(candidate)


def test_manifest_accepts_complete_schema():
    variants.validate_manifest(manifest())


def test_scoring_keeps_missing_labels_out_of_denominator():
    yes = {"id": "g1", "question": "A", "expected_urls": ["https://example.org/a"], "media_mode": "none"}
    missing = {"id": "g2", "question": "B", "media_mode": "none"}
    response = {"text": [{"url": "https://example.org/a", "kind": "text"}],
                "media": [], "media_mode": "none", "context": "hello", "sufficient": True}
    a = variants.score_response(yes, response)
    b = variants.score_response(missing, response)
    assert a["text"]["recall@5"] is True
    assert b["text"]["recall@5"] is None
    assert variants.aggregate([a, b])["text"]["recall@5"] == {"value": 1.0, "scored": 1}


def test_image_input_sends_real_bytes(tmp_path, monkeypatch):
    image = tmp_path / "sample.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nhello")
    captured = {}

    def fake_post(api, body, timeout):
        captured.update(body)
        return {"text": [], "media": [], "context": "", "media_mode": "none", "sufficient": False}

    monkeypatch.setattr(variants, "post_query", fake_post)
    row = {"id": "img-1", "question": "", "image": str(image)}
    got = variants.evaluate_row("http://127.0.0.1:8888", "mm", row, top_k=8, timeout=1)
    assert got["success"] is True
    assert got["image_sent"] is True
    assert captured["image"].startswith("iVBOR")
    assert "image" not in got  # không ghi base64 vào báo cáo


def test_paired_comparison_rejects_different_indexes():
    baseline = manifest()
    candidate = manifest() | {"variant": "candidate", "index_tag": "different"}
    with pytest.raises(ValueError, match="index_tag"):
        variants.assert_comparable(baseline, candidate)


def test_paired_comparison_excludes_failed_and_unpaired_rows():
    baseline = manifest()
    candidate = manifest() | {"variant": "candidate"}
    records_baseline = [
        {"set": "golden", "id": "one", "success": True, "scores": {"text": {"recall@5": False}}},
        {"set": "golden", "id": "two", "success": True, "scores": {"text": {"recall@5": True}}},
    ]
    records_candidate = [
        {"set": "golden", "id": "one", "success": True, "scores": {"text": {"recall@5": True}}},
        {"set": "golden", "id": "two", "success": False, "error": "TimeoutError"},
    ]
    result = variants.compare(baseline, candidate, records_baseline, records_candidate)
    assert result["paired"] == 1
    assert result["excluded"] == 1
    assert result["metrics"]["text"]["recall@5"]["baseline"] == 0.0
    assert result["metrics"]["text"]["recall@5"]["candidate"] == 1.0


def test_comparison_scores_each_metric_on_identical_case_ids():
    baseline = manifest()
    candidate = manifest() | {"variant": "candidate"}

    def record(case_id, recall, coverage):
        return {"set": "golden", "id": case_id, "success": True,
                "scores": {"text": {"recall@5": recall, "list_coverage": coverage}}}

    b_rows = [record("both", False, 0.25), record("only-b", True, None),
              record("only-c", None, None)]
    c_rows = [record("both", True, 0.75), record("only-b", None, None),
              record("only-c", False, None)]
    result = variants.compare(baseline, candidate, b_rows, c_rows)
    recall = result["metrics"]["text"]["recall@5"]
    assert result["paired"] == 3
    assert recall == {"baseline": 0.0, "candidate": 1.0, "delta": 1.0,
                      "paired_scored": 1, "metric_excluded": 2,
                      "missing_baseline": 1, "missing_candidate": 1}
    assert result["by_set"]["golden"]["metrics"]["text"]["recall@5"] == recall
    coverage = result["metrics"]["text"]["list_coverage"]
    assert coverage["paired_scored"] == 1
    assert coverage["delta"] == 0.5


def test_comparison_reports_metrics_with_no_eligible_pairs():
    baseline = manifest()
    candidate = manifest() | {"variant": "candidate"}
    left = [{"set": "golden", "id": "one", "success": True,
             "scores": {"media": {"media_precision": 0.9}}}]
    right = [{"set": "golden", "id": "one", "success": True,
              "scores": {"media": {"media_precision": None}}}]
    result = variants.compare(baseline, candidate, left, right)
    metric = result["metrics"]["media"]["media_precision"]
    assert metric["paired_scored"] == 0
    assert metric["metric_excluded"] == 1
    assert metric["baseline"] is None and metric["delta"] is None


def test_dry_run_does_not_create_output_or_start_server(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.yaml"
    config.write_text("qdrant: {collection_text: text_v3, collection_image: image_v3, collection_ocr: ocr_v3}\n"
                      "embedding: {model: jina-clip-v2}\nllm: {model: judge}\nretrieval: {}\n")
    questions = tmp_path / "questions.jsonl"
    questions.write_text(json.dumps({"id": "one", "question": "hello"}) + "\n")
    out = tmp_path / "out"
    monkeypatch.setattr(variants, "start_server", lambda *args, **kwargs: pytest.fail("started server"))
    variants.main(["run", "--config", str(config), "--sets", f"test={questions}",
                   "--out-dir", str(out), "--dry-run"])
    assert not out.exists()
    assert "dry_run" in capsys.readouterr().out


def test_evaluation_uses_separate_ports_for_variants(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("qdrant: {collection_text: text_v3, collection_image: image_v3}\n"
                      "embedding: {model: jina-clip-v2}\nllm: {model: sict}\nretrieval: {}\n")
    questions = tmp_path / "questions.jsonl"
    questions.write_text(json.dumps({"id": "one", "question": "hello"}) + "\n")
    ports = []

    @contextmanager
    def fake_server(config_path, port, namespace, log_path):
        ports.append(port)
        yield "http://127.0.0.1"

    def fake_evaluate(api, set_name, row, *, top_k, timeout):
        return {"set": set_name, "id": row["id"], "success": True,
                "latency_ms": 1, "scores": {"text": {}, "media": {},
                                            "answer": {}, "operation": {"latency_ms": 1}}}

    monkeypatch.setattr(variants, "start_server", fake_server)
    monkeypatch.setattr(variants, "evaluate_row", fake_evaluate)
    variants.main(["run", "--config", str(config), "--sets", f"test={questions}",
                   "--out-dir", str(tmp_path / "results"), "--port", "18081"])
    assert ports == [18081, 18082]


def test_cache_namespace_default_remains_compatible(monkeypatch):
    from sict_crawler.service.retrieval import retriever

    monkeypatch.delenv("SICT_EVAL_CACHE_NAMESPACE", raising=False)
    legacy = retriever.query_cache_key("abc", 8, "", index="test")
    monkeypatch.setenv("SICT_EVAL_CACHE_NAMESPACE", "run-a")
    isolated = retriever.query_cache_key("abc", 8, "", index="test")
    monkeypatch.setenv("SICT_EVAL_CACHE_NAMESPACE", "run-b")
    other = retriever.query_cache_key("abc", 8, "", index="test")
    assert len({legacy, isolated, other}) == 3
    monkeypatch.delenv("SICT_EVAL_CACHE_NAMESPACE")
    assert retriever.query_cache_key("abc", 8, "", index="test") == legacy
