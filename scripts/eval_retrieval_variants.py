"""Đo cặp baseline/candidate qua API local, giữ query cache và index cô lập.

Chạy hai tiến trình API lần lượt từ cùng config, chỉ đổi retrieval flags.
Không gọi /chat hay RAGAS judge: chỉ số answer và token/cost là N/A.
Tệp đánh giá và ảnh được đọc từ đĩa; ảnh thật được gửi đến /query.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import signal
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml

if __package__ in (None, ""):
    # Hỗ trợ cả `python scripts/...` và `python -m scripts...` như runbook.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import eval_api, eval_media


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETS = ("golden=eval/golden_v2.jsonl,list=eval/list_v2.jsonl,"
                "person=eval/person_v1.jsonl,media=eval/media_v1.jsonl,"
                "mm=eval/multimodal_v1.jsonl")
GROUPS = ("text", "media", "answer", "operation")
METRICS = {
    "text": ("recall@5", "recall@10", "mrr@10", "list_coverage", "full_coverage",
             "sufficient_acc", "url_hit"),
    "media": ("media_mode_acc", "required_has_media", "media_on_target", "media_precision",
              "none_clean", "video_hit", "wants_file_acc", "media_key_hit"),
    "answer": ("faithfulness", "answer_relevancy", "context_precision", "context_recall"),
    "operation": ("latency_ms",),
}
CANDIDATE_FLAGS = {
    "entity_index_enabled", "entity_alias_path", "entity_alias_min_confidence",
    "media_first_enabled", "parallel_multimodal_enabled", "media_coupled_optional",
    "graph_route_on_relation", "graph_route_on_complexity", "rerank_profile",
    "text_candidate_limit", "media_candidate_limit", "max_retrieval_calls",
}


def digest(value: object) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def validate_manifest(manifest: dict) -> None:
    """Fail-closed với bản ghi thiếu provenance hoặc nhóm metric."""
    for name in ("git_sha", "index_tag", "model", "config_fingerprint", "common_config_fingerprint",
                 "cache_mode", "variant", "timestamp", "latency", "metrics", "datasets",
                 "top_k", "prompt_fingerprint"):
        if name not in manifest or manifest[name] is None or manifest[name] == "":
            raise ValueError(f"manifest thiếu trường {name}")
    for name in ("git_sha", "index_tag", "model", "config_fingerprint", "cache_mode",
                 "common_config_fingerprint", "prompt_fingerprint"):
        if not isinstance(manifest[name], str):
            raise ValueError(f"manifest.{name} không hợp lệ")
    if manifest["variant"] not in {"baseline", "candidate"}:
        raise ValueError("manifest.variant phải là baseline hoặc candidate")
    if manifest["cache_mode"] != "isolated_namespace":
        raise ValueError("manifest.cache_mode phải đảm bảo query cache cô lập")
    try:
        datetime.fromisoformat(manifest["timestamp"])
    except (TypeError, ValueError) as exc:
        raise ValueError("manifest.timestamp không hợp lệ") from exc
    if not isinstance(manifest["latency"], dict):
        raise ValueError("manifest.latency phải là object")
    for key in ("p50_ms", "p95_ms", "scored"):
        if key not in manifest["latency"]:
            raise ValueError(f"manifest.latency thiếu {key}")
    if not isinstance(manifest["metrics"], dict):
        raise ValueError("manifest.metrics phải là object")
    for group in GROUPS:
        if group not in manifest["metrics"] or not isinstance(manifest["metrics"][group], dict):
            raise ValueError(f"manifest.metrics thiếu nhóm {group}")
    if not isinstance(manifest["datasets"], dict) or not manifest["datasets"]:
        raise ValueError("manifest.datasets phải chứa hash bộ đánh giá")
    if not isinstance(manifest["top_k"], int) or manifest["top_k"] < 1:
        raise ValueError("manifest.top_k không hợp lệ")


def assert_comparable(baseline: dict, candidate: dict) -> None:
    validate_manifest(baseline)
    validate_manifest(candidate)
    if baseline["variant"] != "baseline" or candidate["variant"] != "candidate":
        raise ValueError("phải so sánh baseline với candidate")
    for field in ("git_sha", "index_tag", "model", "common_config_fingerprint",
                  "prompt_fingerprint", "datasets", "top_k"):
        if baseline[field] != candidate[field]:
            raise ValueError(f"mismatch {field}, không được ghép cặp")


def dataset_paths(spec: str) -> dict[str, Path]:
    result = {}
    for item in spec.split(","):
        if "=" not in item:
            raise ValueError(f"--sets cần tên=đường_dẫn: {item}")
        name, location = item.split("=", 1)
        if not name or not location or name in result:
            raise ValueError(f"Tên bộ trùng/rỗng: {name}")
        path = Path(location)
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            raise FileNotFoundError(path)
        result[name] = path.resolve()
    return result


def load_datasets(paths: dict[str, Path], limit: int = 0) -> dict[str, list[dict]]:
    result = {}
    for name, path in paths.items():
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if limit:
            rows = rows[:limit]
        ids = [r["id"] for r in rows]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Trùng ID trong {path}")
        result[name] = rows
    return result


def _image_bytes(location: str) -> str:
    path = Path(location)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        raise FileNotFoundError(f"Thiếu ảnh đầu vào: {path}")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def post_query(api: str, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(f"{api}/query", json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def _rank(row: dict, res: dict) -> int | None:
    want = {eval_api.norm(url) for url in row.get("expected_urls") or []}
    docs = list(dict.fromkeys(eval_api.norm(s.get("parent_url") or s.get("url"))
                              for s in res.get("text") or []))
    return next((i for i, url in enumerate(docs[:10], 1) if url in want), None)


def score_response(row: dict, res: dict) -> dict[str, dict]:
    """None = không có nhãn/không áp dụng, không cộng vào mẫu số."""
    text = {"recall@5": None, "recall@10": None, "mrr@10": None}
    media = {}
    if row.get("expected_urls"):
        rank = _rank(row, res)
        text.update({"recall@5": rank is not None and rank <= 5,
                     "recall@10": rank is not None,
                     "mrr@10": 1 / rank if rank else 0.0})
    if "expected_items" in row:
        expected = row["expected_items"]
        context = eval_api.fold(res.get("context") or "")
        hits = [any(eval_api.fold(alias) in context for alias in aliases) for aliases in expected]
        if hits:
            text["list_coverage"] = sum(hits) / len(hits)
            text["full_coverage"] = all(hits)
    answerable = row.get("answerable")
    if answerable is not None or "kind" in row and row["kind"] == "out_of_scope":
        expected_sufficient = bool(answerable) if answerable is not None else False
        text["sufficient_acc"] = res.get("sufficient") is expected_sufficient
    if "media_mode" in row:
        scored = eval_media.score_row(row, res)
        text["url_hit"] = scored["url_hit"]
        media.update({
            "media_mode_acc": scored["mode_ok"],
            "required_has_media": scored["required_has_media"],
            "media_on_target": scored["media_on_target"],
            "none_clean": scored["none_clean"],
            "video_hit": scored["video_hit"],
            "wants_file_acc": scored["wants_file_ok"],
        })
        if scored["media_total"]:
            media["media_precision"] = scored["media_good"] / scored["media_total"]
        if row.get("expected_media_keys"):
            keys = [s.get("media_key") or "" for s in res.get("media") or []]
            media["media_key_hit"] = any(key.startswith(known) for key in keys
                                         for known in row["expected_media_keys"])
    return {"text": text, "media": media, "answer": {}, "operation": {}}


def evaluate_row(api: str, set_name: str, row: dict, *, top_k: int, timeout: int) -> dict:
    record = {"set": set_name, "id": row["id"], "success": False, "image_sent": False}
    start = time.perf_counter()
    try:
        image = _image_bytes(row["image"]) if row.get("image") else None
        body = {"question": row["question"], "top_k": top_k, "filters": row.get("filters"), "image": image}
        record["image_sent"] = image is not None
        res = post_query(api, body, timeout)
        record["scores"] = score_response(row, res)
        record["scores"]["operation"]["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
        record["top_docs"] = [s.get("parent_url") or s.get("url") for s in (res.get("text") or [])[:10]]
        record["top_media"] = [s.get("media_key") or s.get("url") for s in (res.get("media") or [])[:10]]
        record["context_chars"] = len(res.get("context") or "")
        record["success"] = True
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
    return record


def aggregate(scores: list[dict]) -> dict[str, dict]:
    result = {group: {} for group in GROUPS}
    for group, metrics in METRICS.items():
        for metric in metrics:
            values = [row.get(group, {}).get(metric) for row in scores]
            observed = [float(value) for value in values if value is not None]
            if observed:
                result[group][metric] = {"value": round(statistics.mean(observed), 4),
                                         "scored": len(observed)}
    return result


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    left = int(position)
    return round(ordered[left] + (ordered[min(left + 1, len(ordered) - 1)] - ordered[left])
                 * (position - left), 2)


def summarize(records: list[dict]) -> tuple[dict, dict]:
    good = [r for r in records if r["success"]]
    latency = [r["latency_ms"] for r in good]
    return aggregate([r["scores"] for r in good]), {
        "p50_ms": _percentile(latency, 0.5), "p95_ms": _percentile(latency, 0.95),
        "scored": len(good), "failed": len(records) - len(good),
    }


def paired_metric_scores(pairs: list[tuple[dict, dict]]) -> dict[str, dict]:
    """Chỉ tính delta khi cả hai variant có điểm trên cùng một câu và metric."""
    result = {group: {} for group in GROUPS}
    for group, names in METRICS.items():
        for metric in names:
            values = [(left.get("scores", {}).get(group, {}).get(metric),
                       right.get("scores", {}).get(group, {}).get(metric))
                      for left, right in pairs]
            if not any(left is not None or right is not None for left, right in values):
                continue
            eligible = [(float(left), float(right)) for left, right in values
                        if left is not None and right is not None]
            b_mean = round(statistics.mean(left for left, _ in eligible), 4) if eligible else None
            c_mean = round(statistics.mean(right for _, right in eligible), 4) if eligible else None
            result[group][metric] = {
                "baseline": b_mean,
                "candidate": c_mean,
                "delta": round(c_mean - b_mean, 4) if eligible else None,
                "paired_scored": len(eligible),
                "metric_excluded": len(pairs) - len(eligible),
                "missing_baseline": sum(left is None for left, _ in values),
                "missing_candidate": sum(right is None for _, right in values),
            }
    return result


def compare(baseline: dict, candidate: dict, baseline_rows: list[dict],
            candidate_rows: list[dict]) -> dict:
    assert_comparable(baseline, candidate)
    b = {(r["set"], r["id"]): r for r in baseline_rows}
    c = {(r["set"], r["id"]): r for r in candidate_rows}
    if len(b) != len(baseline_rows) or len(c) != len(candidate_rows):
        raise ValueError("duplicate set/id trong file kết quả")
    pairs = [(b[key], c[key]) for key in sorted(b.keys() & c.keys())
             if b[key]["success"] and c[key]["success"]]
    metrics = paired_metric_scores(pairs)
    by_set = {}
    for set_name in baseline["datasets"]:
        subset = [(x, y) for x, y in pairs if x["set"] == set_name]
        by_set[set_name] = {
            "paired": len(subset),
            "metrics": paired_metric_scores(subset),
        }
    paired_keys = {(x["set"], x["id"]) for x, _ in pairs}
    excluded_ids = sorted((set(b) | set(c)) - paired_keys)
    return {"paired": len(pairs), "excluded": len(excluded_ids),
            "excluded_ids": [f"{s}:{i}" for s, i in excluded_ids],
            "baseline_success": sum(r["success"] for r in baseline_rows),
            "candidate_success": sum(r["success"] for r in candidate_rows),
            "metrics": metrics, "by_set": by_set,
            "ragas": {"status": "not_scored", "reason": "Cần collect /chat và RAGAS judge riêng"},
            "cost": {"status": "not_measured", "reason": "API /query không trả token/cost"}}


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def make_manifest(variant: str, config: dict, common: dict, files: dict[str, str],
                  records: list[dict], *, top_k: int, run_id: str) -> dict:
    metrics, latency = summarize(records)
    q = config.get("qdrant") or {}
    embedding = config.get("embedding") or {}
    llm = config.get("llm") or {}
    result = {
        "git_sha": _git_sha(),
        "index_tag": "|".join(os.environ.get(env, q.get(key, ""))
                              for env, key in (("QDRANT_COLLECTION_TEXT", "collection_text"),
                                               ("QDRANT_COLLECTION_IMAGE", "collection_image"),
                                               ("QDRANT_COLLECTION_OCR", "collection_ocr"))),
        "model": os.environ.get("EMBED_MODEL") or os.environ.get("EMBEDDING_MODEL") or embedding.get("model", ""),
        "config_fingerprint": digest(config), "common_config_fingerprint": digest(common),
        "prompt_fingerprint": digest({"llm": {k: v for k, v in llm.items() if "key" not in k.lower()},
                                      "env_model": os.environ.get("LLM_MODEL"),
                                      "env_router": os.environ.get("LLM_ROUTER_MODE")}),
        "cache_mode": "isolated_namespace", "variant": variant,
        "timestamp": datetime.now(timezone.utc).isoformat(), "latency": latency,
        "metrics": metrics, "datasets": files, "top_k": top_k,
        "run_id": run_id, "requested": len(records),
        "answer_metrics_reason": "Chỉ đo /query; RAGAS cần collect + score riêng",
        "cost_metrics_reason": "Không có token usage từ /query",
    }
    validate_manifest(result)
    return result


@contextmanager
def start_server(config_path: Path, port: int, namespace: str, log_path: Path):
    """API trong tiến trình riêng để settings và cache không rò giữa hai variant."""
    with socket.socket() as probe:
        # Uvicorn dùng SO_REUSEADDR; probe cần cùng tuỳ chọn để bỏ qua TIME_WAIT.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(f"Cổng localhost {port} đang dùng; cần cổng trống cho eval") from exc
    env = {**os.environ, "SICT_CONFIG": str(config_path),
           "SICT_EVAL_CACHE_NAMESPACE": namespace, "PROMPT_CACHE_ENABLED": "0"}
    api = f"http://127.0.0.1:{port}"
    with log_path.open("w", encoding="utf-8") as logfile:
        process = subprocess.Popen(["uv", "run", "uvicorn", "sict_crawler.api.routes:app",
                                    "--host", "127.0.0.1", "--port", str(port)],
                                   cwd=ROOT, env=env, stdout=logfile, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(f"API dừng với mã {process.returncode}; xem {log_path}")
                try:
                    with urllib.request.urlopen(f"{api}/openapi.json", timeout=1):
                        break
                except (urllib.error.URLError, TimeoutError, OSError):
                    time.sleep(0.3)
            else:
                raise TimeoutError(f"API chưa ready sau 30s; xem {log_path}")
            yield api
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_rows(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def render_report(result: dict, baseline: dict, candidate: dict) -> str:
    lines = ["# Paired retrieval upgrade evaluation", "",
             f"- Git SHA: `{baseline['git_sha']}`",
             f"- Index: `{baseline['index_tag']}`",
             f"- Embedding: `{baseline['model']}`",
             f"- Cache: `{baseline['cache_mode']}` (mỗi tiến trình/run có namespace riêng)",
             f"- Top-k: {baseline['top_k']}",
             f"- Đo thành công ghép cặp: {result['paired']} mẫu, loại khỏi so sánh {result['excluded']} mẫu",
             f"- Baseline thành công: {result['baseline_success']}/{baseline['requested']}",
             f"- Candidate thành công: {result['candidate_success']}/{candidate['requested']}",
             "", "## Metrics trên mẫu ghép cặp", "",
             "| Nhóm | Chỉ số | Baseline | Candidate | Δ | n | Thiếu cặp |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for group in ("text", "media", "operation"):
        for metric, values in result["metrics"][group].items():
            lines.append(f"| {group} | {metric} | {values['baseline']} | {values['candidate']} | "
                         f"{values['delta']} | {values['paired_scored']} | {values['metric_excluded']} |")
    lines += ["", "## Độ trễ", "",
              f"- Baseline p50/p95 (ms): {baseline['latency']['p50_ms']} / {baseline['latency']['p95_ms']}",
              f"- Candidate p50/p95 (ms): {candidate['latency']['p50_ms']} / {candidate['latency']['p95_ms']}",
              "", "## Chưa chấm", "",
              "- Answer/RAGAS (faithfulness, answer_relevancy, context_precision, context_recall): "
              "N/A. Cần chạy collect /chat và score bằng cùng judge/provider trên golden multimodal_v1 (150 câu).",
              "- Token/cost, embedding stage, Qdrant call count: N/A do /query không công bố trường đo này.",
              "- Chỉ so sánh mỗi metric trên các câu mà cả hai variant đều có điểm cho metric đó.",
              "- `Thiếu cặp` đếm số câu thành công cả hai variant nhưng thiếu nhãn hoặc điểm ở ít nhất một phía.",
              "- Mẫu lỗi không được tính điểm 0.",
              "", "## Lỗi hoặc mẫu thiếu trong cặp", ""]
    lines.extend(f"- `{case}`" for case in result["excluded_ids"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Khởi chạy API local lần lượt để đo baseline/candidate")
    run.add_argument("--config", default="config.yaml")
    run.add_argument("--sets", default=DEFAULT_SETS)
    run.add_argument("--out-dir", required=True)
    run.add_argument("--candidate-flags", default="{}", help="JSON object chỉ gồm retrieval flags")
    run.add_argument("--port", type=int, default=18081)
    run.add_argument("--top-k", type=int, default=8)
    run.add_argument("--timeout", type=int, default=120)
    run.add_argument("--limit", type=int, default=0, help="smoke N dòng/bộ; 0 = toàn bộ")
    run.add_argument("--dry-run", action="store_true")
    check = sub.add_parser("compare", help="Đọc lại 2 manifest và rows; không gọi API")
    check.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    if args.command == "compare":
        b = json.loads((out_dir / "baseline.manifest.json").read_text(encoding="utf-8"))
        c = json.loads((out_dir / "candidate.manifest.json").read_text(encoding="utf-8"))
        result = compare(b, c, _read_rows(out_dir / "baseline.rows.jsonl"),
                         _read_rows(out_dir / "candidate.rows.jsonl"))
        _write_json(out_dir / "paired.json", result)
        (out_dir / "paired.md").write_text(render_report(result, b, c), encoding="utf-8")
        print(json.dumps({"paired": result["paired"], "excluded": result["excluded"]}))
        return

    config_path = Path(args.config).resolve()
    common = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(common, dict):
        raise ValueError("config YAML phải là object")
    paths = dataset_paths(args.sets)
    datasets = load_datasets(paths, args.limit)
    flags = json.loads(args.candidate_flags)
    if not isinstance(flags, dict) or set(flags) - CANDIDATE_FLAGS:
        raise ValueError("candidate-flags chỉ được chứa retrieval flags cho phép")
    configurations = {}
    for variant in ("baseline", "candidate"):
        conf = copy.deepcopy(common)
        conf.setdefault("retrieval", {})["planner_mode"] = variant
        if variant == "candidate":
            conf["retrieval"].update(flags)
        configurations[variant] = conf
    files = {name: "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
             for name, path in paths.items()}
    files = {name: digest({"file_sha256": value, "limit": args.limit}) for name, value in files.items()}
    if args.dry_run:
        print(json.dumps({"dry_run": True, "datasets": {name: len(rows) for name, rows in datasets.items()},
                          "index": common.get("qdrant"), "model": common.get("embedding", {}).get("model"),
                          "candidate_flags": flags, "port": args.port}, ensure_ascii=False))
        return

    if args.top_k < 1 or args.timeout < 1 or not 1024 <= args.port < 65535 or args.limit < 0:
        raise ValueError("top-k/timeout/port/limit không hợp lệ")
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    manifests = {}
    all_records = {}
    for variant_index, variant in enumerate(("baseline", "candidate")):
        cfg = out_dir / f"{variant}.config.yaml"
        cfg.write_text(yaml.safe_dump(configurations[variant], allow_unicode=True), encoding="utf-8")
        records = []
        namespace = f"retrieval-eval:{run_id}:{variant}"
        # Cổng vừa đóng có thể còn TIME_WAIT; tránh bind lại ngay khi chạy candidate.
        with start_server(cfg.resolve(), args.port + variant_index, namespace,
                          out_dir / f"{variant}.server.log") as api:
            for set_name, rows in datasets.items():
                for row in rows:
                    record = evaluate_row(api, set_name, row, top_k=args.top_k, timeout=args.timeout)
                    records.append(record)
                    print(f"{variant} {set_name}:{row['id']} "
                          f"{'ok' if record['success'] else record['error']}", flush=True)
        manifest = make_manifest(variant, configurations[variant], common, files, records,
                                 top_k=args.top_k, run_id=run_id)
        _write_json(out_dir / f"{variant}.manifest.json", manifest)
        _write_rows(out_dir / f"{variant}.rows.jsonl", records)
        all_records[variant] = records
        manifests[variant] = manifest
    result = compare(manifests["baseline"], manifests["candidate"],
                     all_records["baseline"], all_records["candidate"])
    _write_json(out_dir / "paired.json", result)
    (out_dir / "paired.md").write_text(render_report(result, manifests["baseline"],
                                                     manifests["candidate"]), encoding="utf-8")
    print(json.dumps({"report": str(out_dir / "paired.md"),
                      "paired": result["paired"], "excluded": result["excluded"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
