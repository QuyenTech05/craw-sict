"""Hồi quy collect ảnh thật và mẫu số từng chỉ số của golden RAGAS."""
from __future__ import annotations

import base64
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("eval_ragas", ROOT / "scripts" / "eval_ragas.py")
ragas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ragas)


def args_for(tmp_path: Path, golden: Path) -> SimpleNamespace:
    return SimpleNamespace(sets=f"mm={golden}", golden="", list="", limit=0,
                           out=str(tmp_path / "measure"), api="http://dev.local", top_k=5,
                           timeout=5, rpm=600)


def test_collect_sends_real_image_to_query_and_chat_without_saving_base64(tmp_path, monkeypatch):
    image = tmp_path / "sample.jpg"
    image.write_bytes(b"test-image-bytes")
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"id": "i1", "question": "", "image": str(image),
                                  "answerable": True, "reference": "Thông tin từ ảnh"}), encoding="utf-8")
    args = args_for(tmp_path, golden)
    calls = []

    def fake_post(api, path, body, timeout):
        calls.append((path, body))
        if path == "/query":
            return io.BytesIO(json.dumps({"context": "Nguồn A", "text": [], "media": []}).encode())
        return io.BytesIO(b'data: {"delta": "Tra loi tu anh"}\n\ndata: [DONE]\n\n')

    monkeypatch.setattr(ragas, "post", fake_post)
    monkeypatch.setattr(ragas.time, "sleep", lambda seconds: None)
    ragas.collect(args)

    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    assert [path for path, _ in calls] == ["/query", "/chat"]
    assert all(body == {"question": "", "top_k": 5, "filters": None, "image": encoded}
               for _, body in calls)
    saved = json.loads(Path(args.out + ".answers.jsonl").read_text(encoding="utf-8"))
    assert saved["image"] == str(image)
    assert saved["image_sent"] is True
    assert saved["answer"] == "Tra loi tu anh"
    assert saved["contexts"] == ["Nguồn A"]
    assert encoded not in json.dumps(saved)
    ragas.collect(args)
    assert len(calls) == 2  # chạy lại giữ kết quả hoàn tất


def test_collect_missing_image_fails_before_request(tmp_path, monkeypatch):
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"id": "missing", "question": "", "image": "no-photo.jpg"}), encoding="utf-8")
    monkeypatch.setattr(ragas, "post", lambda *a: pytest.fail("Không được gửi truy vấn thiếu ảnh"))
    with pytest.raises(FileNotFoundError, match="mm:missing"):
        ragas.collect(args_for(tmp_path, golden))


def test_collect_concurrent_writes_complete_jsonl_rows(tmp_path, monkeypatch):
    golden = tmp_path / "golden.jsonl"
    golden.write_text("".join(json.dumps({"id": str(i), "question": f"Câu {i}"}) + "\n"
                              for i in range(6)), encoding="utf-8")
    args = args_for(tmp_path, golden)
    args.concurrency = 3

    def fake_post(api, path, body, timeout):
        if path == "/query":
            return io.BytesIO(json.dumps({"context": "Nguồn", "text": [], "media": []}).encode())
        return io.BytesIO(b'data: {"answer": "Co thong tin"}\n\ndata: [DONE]\n\n')

    monkeypatch.setattr(ragas, "post", fake_post)
    monkeypatch.setattr(ragas.time, "sleep", lambda seconds: None)
    ragas.collect(args)
    rows = [json.loads(line) for line in Path(args.out + ".answers.jsonl").read_text().splitlines()]
    assert len(rows) == 6
    assert {row["id"] for row in rows} == {f"mm:{i}" for i in range(6)}
    assert all(row["answer"] == "Co thong tin" and row["contexts"] == ["Nguồn"] for row in rows)


def test_collect_refuses_stale_image_only_answers(tmp_path):
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"id": "i1", "question": "", "image": "photo.jpg"}), encoding="utf-8")
    args = args_for(tmp_path, golden)
    Path(args.out + ".answers.jsonl").write_text(json.dumps({"id": "mm:i1", "question": "",
                                                           "image": "photo.jpg", "filters": None}) + "\n")
    with pytest.raises(ValueError, match="chưa gửi ảnh"):
        ragas.collect(args)


def test_coverage_separates_excluded_missing_and_valid_zero_score():
    expected = [
        {"id": "mm:t", "question": "Thông tin?", "answerable": True, "reference": "Có"},
        {"id": "mm:i", "question": "", "image": "photo.jpg", "answerable": True, "reference": "Có"},
        {"id": "mm:ti", "question": "Đây là gì?", "image": "photo2.jpg", "answerable": True},
        {"id": "mm:o", "question": "Ngoài phạm vi", "answerable": False},
    ]
    answers = {
        "mm:t": {"answer": "Thông tin", "contexts": ["Nguồn"]},
        "mm:i": {"answer": "Ảnh", "contexts": ["Nguồn"], "image_sent": True},
    }
    scored = {"mm:t": {"faithfulness": 0.0, "answer_relevancy": None,
                        "context_precision": 0.9, "errors": {"answer_relevancy": "Timeout"}},
              "mm:i": {"faithfulness": 0.8}}
    result = ragas.coverage(expected, answers, scored,
                            ["faithfulness", "answer_relevancy", "context_precision", "context_recall"])
    assert (result["expected"], result["collected"], result["score_rows"]) == (4, 2, 2)
    assert (result["input_images"], result["collected_images"]) == (2, 1)
    assert result["metrics"]["faithfulness"] == {
        "eligible": 3, "scored": 2, "excluded": {"out_of_scope": 1}, "missing": {"not_collected": 1}}
    assert result["metrics"]["answer_relevancy"] == {
        "eligible": 2, "scored": 0, "excluded": {"image_only_without_text": 1, "out_of_scope": 1},
        "missing": {"judge_error": 1, "not_collected": 1}}
    assert result["metrics"]["context_precision"]["scored"] == 1
    assert result["metrics"]["context_recall"] == {
        "eligible": 1, "scored": 0,
        "excluded": {"image_only_without_text": 1, "missing_reference": 1, "out_of_scope": 1},
        "missing": {"missing_score": 1}}


def test_summary_with_no_scores_reports_uncollected_cases(tmp_path):
    out = tmp_path / "mm.scores.jsonl"
    expected = [{"id": "mm:1", "set": "mm", "question": "Nội dung", "reference": "Tham chiếu"}]
    ragas.summary(out, ["context_precision"], expected)
    result = json.loads((tmp_path / "mm.summary.json").read_text(encoding="utf-8"))
    assert result["coverage"]["metrics"]["context_precision"]["missing"] == {"not_collected": 1}
