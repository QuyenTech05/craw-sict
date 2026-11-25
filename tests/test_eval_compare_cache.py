"""Không dùng lẫn vector benchmark từ model hoặc endpoint khác nhau."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.eval_compare import _input_hash, cmd_score


@pytest.mark.parametrize(
    ("case", "expected_error"),
    [
        ("model", "không phải embedding API"),
        ("endpoint", "model/endpoint khác"),
        ("shape", "sai shape"),
    ],
)
def test_benchmark_rejects_incompatible_cached_vectors(tmp_path, case, expected_error):
    out = tmp_path / "compare"
    out.mkdir()
    questions = tmp_path / "questions.jsonl"
    questions.write_text(json.dumps({"id": "q1", "question": "Học phí?", "type": "text", "expected_urls": []}) + "\n")
    (out / "corpus.jsonl").write_text(json.dumps({"text": "Học phí", "url": "https://example.com"}) + "\n")
    (out / "images.jsonl").write_text("")

    for name, items in (("queries", ["Học phí?"]), ("chunks", ["Học phí"])):
        metadata = {
            "input_sha256": _input_hash(items),
            "count": len(items),
            "model": "jina-clip-v2", "dim": 1024, "backend": "api",
            "api_base": "http://embed-a:8090/v1", "kind": name,
        }
        if case == "model" and name == "queries":
            metadata["model"] = "legacy-model"
        if case == "endpoint" and name == "chunks":
            metadata["api_base"] = "http://embed-b:8090/v1"
        (out / f"vec_jina_api_{name}.meta.json").write_text(json.dumps(metadata))
        width = 512 if case == "shape" and name == "queries" else 1024
        np.save(out / f"vec_jina_api_{name}.npy", np.zeros((len(items), width), dtype=np.float32))

    with pytest.raises(ValueError, match=expected_error):
        cmd_score(SimpleNamespace(out=str(out), questions=str(questions)))
