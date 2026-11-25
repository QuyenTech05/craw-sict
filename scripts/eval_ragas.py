"""Đánh giá RAG bằng RAGAS qua HTTP: câu trả lời thật của /chat + ngữ cảnh LLM nhận (/query `context`).

Hai bước, đều chạy tiếp được (bỏ qua id đã có trong file):
  1. collect — mỗi câu hỏi gọi /query (ngữ cảnh, nguồn) rồi /chat (câu trả lời) → <out>.answers.jsonl
  2. score   — chấm RAGAS bằng LLM (OpenAI-compatible) → <out>.scores.jsonl + bảng tổng kết

Chỉ số (ragas.metrics.collections):
  faithfulness         câu trả lời có bám ngữ cảnh không (bịa = thấp)
  answer_relevancy     câu trả lời có trả lời đúng câu hỏi không (cần embedding: dịch vụ embed :8090)
  context_precision    nguồn liên quan có đứng đầu không (không cần đáp án, 1 lượt LLM / nguồn)
  context_recall       ngữ cảnh có đủ các ý của đáp án không — chỉ bộ liệt kê (expected_items làm đáp án)

LLM chấm mặc định là LLM_* trong .env (cùng model trả lời → điểm có thiên vị tự chấm; đổi bằng RAGAS_LLM_*).
Model miễn phí kiraai giới hạn 20 lượt / phút cho cả API lẫn chấm → --rpm (mặc định 15) và chạy 2 bước tuần tự.

  uv run --group eval python scripts/eval_ragas.py collect --sets mm=eval/multimodal_v1.jsonl --out eval/results/ragas/mm-2026-11-23
  uv run --group eval python scripts/eval_ragas.py score --sets mm=eval/multimodal_v1.jsonl --out eval/results/ragas/mm-2026-11-23

Giám khảo RAGAS collections nhận user_input là chữ; ảnh-only chỉ chấm faithfulness
trên ngữ cảnh chữ. Các chỉ số khác bỏ qua ảnh-only và báo rõ số mẫu không áp dụng.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path

SEP = "\n\n---\n\n"           # sources.build_context nối các phần bằng chuỗi này
ECHO = "(LLM chưa trả lời"   # routes./chat: LLM lỗi / hết lượt → trả lại ngữ cảnh
# Cùng câu hỏi mặc định với api/routes.py khi chỉ có ảnh đầu vào.
# RAGAS Faithfulness yêu cầu user_input không rỗng; giám khảo vẫn chỉ thấy context dạng chữ.
IMAGE_ONLY_QUESTION = "Người dùng gửi một ảnh, không kèm câu hỏi. Hãy cho biết thông tin liên quan đến ảnh này."


def load_env(path: str) -> dict:
    env = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return {**env, **os.environ}


def question_sets(args) -> list[tuple[str, str]]:
    """--sets để chọn bộ; mặc định lấy golden multimodal mới nhất."""
    if args.sets:
        return [tuple(x.split("=", 1)) for x in args.sets.split(",") if x.strip()]
    return [(k, p) for k, p in (("golden", args.golden), ("list", args.list)) if p]


def questions(args) -> list[dict]:
    rows = []
    for kind, path in question_sets(args):
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            g = json.loads(line)
            # list_v1: câu ngoài phạm vi không có đáp án để chấm RAGAS. golden_v2 giữ chúng (answerable=false)
            # để đo tỉ lệ từ chối đúng.
            if g.get("kind") == "out_of_scope" and "answerable" not in g:
                continue
            ref = g.get("reference")
            if ref is None and g.get("expected_items"):
                ref = "Các mục cần có: " + "; ".join(alts[0] for alts in g["expected_items"]) + "."
            rows.append({"id": f"{kind}:{g.get('id', len(rows))}", "set": kind, "question": g["question"],
                         "image": g.get("image"), "filters": g.get("filters"), "reference": ref,
                         **{k: g[k] for k in ("case", "style", "answerable", "expected_urls", "variant_of",
                                              "expected_items") if k in g}})
    return rows[:args.limit] if args.limit else rows


def done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(x)["id"] for x in path.read_text(encoding="utf-8").splitlines() if x.strip()}


def post(api: str, path: str, body: dict, timeout: int):
    req = urllib.request.Request(f"{api}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def image_base64(q: dict) -> str | None:
    """Ảnh của golden là đường dẫn tính từ gốc repo; API nhận base64 thuần."""
    if not q.get("image"):
        return None
    path = Path(q["image"])
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    if not path.is_file():
        raise FileNotFoundError(f"{q['id']}: thiếu ảnh đầu vào {path}")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def request_body(q: dict, top_k: int, image: str | None) -> dict:
    return {"question": q["question"], "top_k": top_k, "filters": q["filters"], "image": image}


def chat(api: str, q: dict, top_k: int, timeout: int, image: str | None = None) -> str:
    deltas, answer = [], None
    with post(api, "/chat", request_body(q, top_k, image), timeout) as r:
        for raw in r:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            d = json.loads(line[6:])
            if "delta" in d:
                deltas.append(d["delta"])
            if "answer" in d:
                answer = d["answer"]
    return answer or "".join(deltas)


def collect(args) -> None:
    out = Path(f"{args.out}.answers.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    have = done_ids(out)
    selected = questions(args)
    if have:
        previous = {r["id"]: r for r in (json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip())}
        for q in selected:
            old = previous.get(q["id"])
            if old and any(old.get(k) != q.get(k) for k in ("question", "image", "filters", "reference")):
                raise ValueError(f"{q['id']}: golden đã đổi sau collect; dùng --out mới để đo lại")
            if old and q.get("image") and not old.get("image_sent"):
                raise ValueError(f"{q['id']}: kết quả cũ chưa gửi ảnh; dùng --out mới để đo lại")
    # Giới hạn tốc độ chung cho cả /query và /chat, kể cả khi nhiều câu chạy đồng thời.
    # /query có thể gọi LLM router, do đó mỗi request đều chiếm một lượt trong ngân sách.
    gap = 60.0 / args.rpm
    gate = threading.Lock()
    next_request = [0.0]

    def throttle() -> None:
        with gate:
            pause = next_request[0] - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            next_request[0] = time.monotonic() + gap

    def collect_one(q: dict) -> dict | None:
        image = image_base64(q)
        for attempt in range(4):
            throttle()
            t = time.time()
            with post(args.api, "/query", request_body(q, args.top_k, image), args.timeout) as r:
                res = json.loads(r.read())
            t_query = time.time() - t
            throttle()
            t0_chat = time.time()
            ans = chat(args.api, q, args.top_k, args.timeout, image)
            t_chat = time.time() - t0_chat
            if not ans.startswith(ECHO):
                break
            print(f"{q['id']} LLM không trả lời (hết lượt?), chờ 60 s", flush=True)
            time.sleep(60)
        else:
            print(f"{q['id']} bỏ qua: LLM không trả lời sau 4 lần", flush=True)
            return None
        contexts = [c for c in res.get("context", "").split(SEP) if c.strip()]
        row = {**q, "image_sent": image is not None, "answer": ans, "contexts": contexts,
               "sufficient": res.get("sufficient"),
               "list_question": res.get("list_question"), "urls": [s["url"] for s in res.get("text", [])],
               "media_urls": [s.get("url") for s in res.get("media", [])],
               "latency_s": {"query": round(t_query, 2), "chat": round(t_chat, 2)}}
        print(f"{q['id']} {time.time() - t:.1f}s nguồn={len(contexts)} trả lời={len(ans)} ký tự", flush=True)
        return row

    pending = [q for q in selected if q["id"] not in have]
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, getattr(args, "concurrency", 1))) as pool:
        futures = {pool.submit(collect_one, q): q for q in pending}
        for future in as_completed(futures):
            try:
                row = future.result()
            except Exception as exc:
                errors.append((futures[future]["id"], exc))
                print(f"{futures[future]['id']} lỗi collect: {type(exc).__name__}: {exc}", flush=True)
                continue
            if row:
                # Chỉ luồng chính append, tránh xen lẫn JSONL khi nhiều câu xong cùng lúc.
                with out.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if errors:
        raise errors[0][1] if len(errors) == 1 else RuntimeError(f"{len(errors)} câu collect lỗi; chạy lại để tiếp tục")


class RateLimiter:
    """≤ rpm lượt / phút (cửa sổ trượt 60 s) cho mọi lượt gọi LLM chấm."""

    def __init__(self, rpm: int):
        self.rpm, self.ts, self.lock = rpm, [], asyncio.Lock()

    async def wait(self):
        async with self.lock:
            while True:
                now = time.monotonic()
                self.ts = [t for t in self.ts if now - t < 60]
                if len(self.ts) < self.rpm:
                    self.ts.append(now)
                    return
                await asyncio.sleep(60 - (now - self.ts[0]) + 0.05)


STATS = {"calls": 0, "429": 0, "errors": 0, "llm_s": 0.0}   # lượt gọi LLM chấm (in sau mỗi câu)

# RAGAS collections nhận user_input dạng chữ. Với ảnh-only, các chỉ số đối chiếu
# câu hỏi cần giám khảo đa phương thức; không tự chế câu hỏi thay thế từ ảnh.
QUESTION_METRICS = {"answer_relevancy", "context_precision", "context_recall"}
CONTEXT_METRICS = {"faithfulness", "context_precision", "context_recall"}


def metric_exclusion_reason(row: dict, name: str) -> str | None:
    """Lý do nằm ngoài mẫu số của chỉ số."""
    if row.get("answerable") is False:
        return "out_of_scope"
    if name in QUESTION_METRICS and not row.get("question", "").strip():
        return "image_only_without_text" if row.get("image") else "empty_question"
    if name == "context_recall" and not row.get("reference"):
        return "missing_reference"
    return None


def metric_skip_reason(row: dict, name: str) -> str | None:
    """Lý do không áp dụng hoặc chưa đủ dữ liệu để chấm."""
    reason = metric_exclusion_reason(row, name)
    if reason:
        return reason
    if not row.get("answer", "").strip():
        return "empty_answer"
    if name in CONTEXT_METRICS and not row.get("contexts"):
        return "empty_context"
    return None


def throttled_client(base: str, key: str, rpm: int):
    """AsyncOpenAI có giới hạn tốc độ + chờ lại khi 429 (thông báo kiraai: "Vui lòng đợi N giây")."""
    from openai import AsyncOpenAI, RateLimitError
    cli = AsyncOpenAI(base_url=base, api_key=key, max_retries=0, timeout=180)
    create, limiter = cli.chat.completions.create, RateLimiter(rpm)

    async def create_throttled(*a, **kw):
        for _ in range(8):
            await limiter.wait()
            t = time.monotonic()
            try:
                r = await create(*a, **kw)
                STATS["calls"] += 1
                STATS["llm_s"] += time.monotonic() - t
                return r
            except RateLimitError as e:
                STATS["429"] += 1
                m = re.search(r"(\d+)\s*giây", str(e))
                await asyncio.sleep(int(m.group(1)) + 1 if m else 30)
            except Exception:
                STATS["errors"] += 1
                raise
        return await create(*a, **kw)
    cli.chat.completions.create = create_throttled   # gán trước llm_factory: instructor bọc hàm này
    return cli


def make_embeddings(base: str, model: str):
    """Embedding cho answer_relevancy qua dịch vụ embed tự host (Jina-style, nhận chuỗi thuần)."""
    import httpx
    from ragas.embeddings.base import BaseRagasEmbedding

    class ServiceEmbedding(BaseRagasEmbedding):
        def _body(self, texts):
            return {"model": model, "input": [{"text": t} for t in texts], "normalized": True}

        def embed_text(self, text: str, **kw) -> list[float]:
            return self.embed_texts([text])[0]

        def embed_texts(self, texts: list[str], **kw) -> list[list[float]]:
            r = httpx.post(f"{base}/embeddings", json=self._body(texts), timeout=120)
            r.raise_for_status()
            return [d["embedding"] for d in r.json()["data"]]

        async def aembed_text(self, text: str, **kw) -> list[float]:
            return (await self.aembed_texts([text]))[0]

        async def aembed_texts(self, texts: list[str], **kw) -> list[list[float]]:
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(f"{base}/embeddings", json=self._body(texts))
                r.raise_for_status()
                return [d["embedding"] for d in r.json()["data"]]
    return ServiceEmbedding()


async def score_all(args) -> None:
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerRelevancy, ContextPrecisionWithoutReference, ContextRecall, Faithfulness
    env = load_env(args.env_file)
    base = env.get("RAGAS_LLM_BASE") or env["LLM_API_BASE"]
    model = env.get("RAGAS_LLM_MODEL") or env["LLM_MODEL"]
    llm = llm_factory(model, client=throttled_client(base, env.get("RAGAS_LLM_KEY") or env["LLM_API_KEY"], args.rpm),
                      max_tokens=args.max_tokens)
    emb = make_embeddings(args.embed_base, env.get("EMBED_MODEL", "jina-clip-v2"))
    metrics = {"faithfulness": Faithfulness(llm=llm), "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=emb),
               "context_precision": ContextPrecisionWithoutReference(llm=llm), "context_recall": ContextRecall(llm=llm)}
    use = [m for m in args.metrics.split(",") if m]
    rows = [json.loads(x) for x in Path(f"{args.out}.answers.jsonl").read_text(encoding="utf-8").splitlines() if x]
    out = Path(f"{args.out}.scores.jsonl")
    have = done_ids(out)
    # --retry-errors: chấm lại đúng các chỉ số bị lỗi (504 / timeout của LLM chấm), giữ nguyên chỉ số đã có
    old = {r["id"]: r for r in (json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip())} \
        if out.exists() else {}
    retry = {i: [m for m in r["errors"] if m in use] for i, r in old.items() if r.get("errors")} \
        if args.retry_errors else {}
    # Câu đã có dòng điểm nhưng thiếu chỉ số trong --metrics (VD chấm F/CP/CR trước, AR sau khi dịch vụ embed rảnh):
    # chấm thêm đúng chỉ số thiếu rồi gộp vào dòng cũ. context_recall chỉ áp cho câu có reference.
    for r in rows:
        o = old.get(r["id"])
        if o is None or r.get("answerable") is False:
            continue
        miss = [m for m in use if m not in o and metric_skip_reason(r, m) is None]
        if miss:
            retry[r["id"]] = sorted(set(retry.get(r["id"], [])) | set(miss))
    print(f"chấm {len(rows) - len(have & {r['id'] for r in rows})}/{len(rows)} câu"
          + (f", chấm lại / chấm thêm {len(retry)} câu" if retry else "") + f", LLM chấm {model}", flush=True)

    async def one(r):
        res = {}
        use_here = [m for m in retry.get(r["id"], use) if metric_skip_reason(r, m) is None]
        for name in use_here:
            m = metrics[name]
            try:
                if name == "faithfulness":
                    judge_input = r["question"].strip() or IMAGE_ONLY_QUESTION
                    v = await m.ascore(user_input=judge_input, response=r["answer"], retrieved_contexts=r["contexts"])
                elif name == "answer_relevancy":
                    v = await m.ascore(user_input=r["question"], response=r["answer"])
                elif name == "context_precision":
                    v = await m.ascore(user_input=r["question"], response=r["answer"],
                                       retrieved_contexts=r["contexts"])
                elif r.get("reference"):   # context_recall: chỉ câu có đáp án tham chiếu
                    v = await m.ascore(user_input=r["question"], retrieved_contexts=r["contexts"],
                                       reference=r["reference"])
                else:
                    continue
                res[name] = round(float(v.value), 4)
            except Exception as e:   # 1 chỉ số lỗi không làm hỏng cả câu; ghi lại để biết
                res[name] = None
                res.setdefault("errors", {})[name] = f"{type(e).__name__}: {str(e)[:200]}"
        row = {"id": r["id"], "set": r["set"], "question": r["question"], **res,
               **{k: r[k] for k in ("case", "style", "answerable", "variant_of") if k in r}}
        if r["id"] in retry:                 # gộp thêm chỉ số vào dòng hiện có
            merged = {**old[r["id"]], **{k: v for k, v in res.items() if k != "errors"}}
            errs = {k: v for k, v in merged.pop("errors", {}).items() if k not in use_here}   # lỗi cũ của chỉ số không chấm lại
            errs.update(res.get("errors", {}))
            if errs:
                merged["errors"] = errs
            row = merged
        # Chấm mới và chấm bổ sung cùng cập nhật một bản đồ, tránh mất dòng mới
        # khi --retry-errors chạy đồng thời. Thay file nguyên tử trong lock.
        async with write_lock:
            old[r["id"]] = row
            tmp = out.with_name(out.name + ".tmp")
            tmp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in old.values()), encoding="utf-8")
            tmp.replace(out)
        print(json.dumps(row, ensure_ascii=False)[:300], flush=True)
        print(f"  LLM: {STATS['calls']} lượt, {STATS['429']} lần 429, {STATS['errors']} lỗi, "
              f"trung bình {STATS['llm_s'] / max(STATS['calls'], 1):.1f} s / lượt", flush=True)

    sem = asyncio.Semaphore(args.concurrency)
    write_lock = asyncio.Lock()

    async def guarded(r):
        async with sem:
            await one(r)
    await asyncio.gather(*(guarded(r) for r in rows if r["id"] not in have or r["id"] in retry))
    summary(out, use, questions(args))


ABSTAIN_RE = re.compile(r"khong (co|tim thay|du) (thong tin|du lieu|ngu canh|noi dung)|nam ngoai|ngoai pham vi"
                        r"|chua co thong tin|khong the (tra loi|xac dinh|cung cap)|khong lien quan")


def _fold(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", t.lower()).replace("đ", "d")
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def abstained(answer: str) -> bool:
    """Câu trả lời có ý "không có / ngoài phạm vi" (gần đúng, theo cụm từ)."""
    return bool(ABSTAIN_RE.search(_fold(answer)))


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return (round(sum(vals) / len(vals), 3), len(vals)) if vals else (None, 0)


def _group(rows, answers, use) -> dict:
    out = {"n": len(rows)}
    for m in use:
        v, n = _mean([r.get(m) for r in rows])
        if n:
            out[m], out[f"{m}_n"] = v, n
    ans = [answers[r["id"]] for r in rows if r["id"] in answers]
    hit = [any(u in a.get("urls", []) + a.get("media_urls", []) for u in a["expected_urls"])
           for a in ans if a.get("expected_urls") and a.get("answerable", True)]
    if hit:
        out["url_hit"] = round(sum(hit) / len(hit), 3)          # nguồn đúng có trong top-k (chữ hoặc media)
    ok = [a for a in ans if a.get("answerable", True)]
    no = [a for a in ans if a.get("answerable") is False]
    if ok and any("answerable" in a for a in ok):
        out["false_abstain"] = round(sum(abstained(a["answer"]) for a in ok) / len(ok), 3)
    if no:
        out["abstain_ok"] = round(sum(abstained(a["answer"]) for a in no) / len(no), 3)
    return out


def coverage(expected: list[dict], answers: dict, scored: dict, use: list[str]) -> dict:
    """Đếm đủ bộ golden, cả câu chưa collect/chưa score và lỗi giám khảo."""
    result = {
        "expected": len(expected),
        "collected": sum(q["id"] in answers for q in expected),
        "score_rows": sum(q["id"] in scored for q in expected),
        "input_images": sum(bool(q.get("image")) for q in expected),
        "collected_images": sum(bool(q.get("image")) and answers.get(q["id"], {}).get("image_sent") is True
                                for q in expected),
        "metrics": {},
        "judge_modality": "RAGAS collections chỉ chấm user_input dạng chữ và context dạng chữ; "
                          "với ảnh-only, faithfulness dùng cùng câu hỏi mặc định của API; "
                          "ảnh đã gửi tới API nhưng pixel không được đưa vào giám khảo RAGAS.",
    }
    for name in use:
        excluded, missing = {}, {}
        eligible = graded = 0
        for q in expected:
            reason = metric_exclusion_reason(q, name)
            if reason:
                excluded[reason] = excluded.get(reason, 0) + 1
                continue
            eligible += 1
            a = answers.get(q["id"])
            if a is None:
                reason = "not_collected"
            else:
                reason = metric_skip_reason({**a, **q}, name)
                if reason is None and q["id"] not in scored:
                    reason = "not_scored"
                if reason is None and scored[q["id"]].get(name) is None:
                    reason = "judge_error" if name in scored[q["id"]].get("errors", {}) else "missing_score"
            if reason:
                missing[reason] = missing.get(reason, 0) + 1
            else:
                graded += 1
        result["metrics"][name] = {"eligible": eligible, "scored": graded,
                                   "excluded": excluded, "missing": missing}
    return result


def summary(path: Path, use: list[str], expected: list[dict] | None = None) -> None:
    """Bảng theo bộ; bộ có cột case/style (golden_v2) thêm bảng theo loại câu, cách gõ và cặp biến thể."""
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []
    ap = Path(str(path).replace(".scores.jsonl", ".answers.jsonl"))
    answers = {a["id"]: a for a in (json.loads(x) for x in ap.read_text(encoding="utf-8").splitlines() if x.strip())} \
        if ap.exists() else {}
    if expected is not None:
        selected_ids = {q["id"] for q in expected}
        rows = [r for r in rows if r["id"] in selected_ids]
        answers = {i: a for i, a in answers.items() if i in selected_ids}
    for r in rows:   # bộ cũ: cột case/style chỉ có trong answers
        for k in ("case", "style", "answerable", "variant_of"):
            if k not in r and k in answers.get(r["id"], {}):
                r[k] = answers[r["id"]][k]
    table = {}
    for s in sorted({r["set"] for r in rows}) + ["all"]:
        table[s] = _group([r for r in rows if s == "all" or r["set"] == s], answers, use)
    if expected is not None:
        table["coverage"] = coverage(expected, answers, {r["id"]: r for r in rows}, use)
    for key in ("case", "style"):
        vals = sorted({r[key] for r in rows if r.get(key)})
        if vals:
            table[f"by_{key}"] = {v: _group([r for r in rows if r.get(key) == v], answers, use) for v in vals}
    pairs = [(r, next((b for b in rows if b["id"].split(":")[-1] == r["variant_of"] and b["set"] == r["set"]), None))
             for r in rows if r.get("variant_of")]
    pairs = [(v, b) for v, b in pairs if b]
    if pairs:
        table["variants"] = {m: {"goc": _mean([b.get(m) for _, b in pairs])[0],
                                 "bien_the": _mean([v.get(m) for v, _ in pairs])[0]}
                             for m in use if any(v.get(m) is not None for v, _ in pairs)}
        table["variants"]["n_pairs"] = len(pairs)
    # độ trễ từ collect (latency_s.{query,chat} trong answers.jsonl): p50/p90
    lat = [a.get("latency_s") for a in answers.values() if a.get("latency_s")]
    if lat:
        def _pct(vals, p):
            vals = sorted(vals)
            return vals[min(len(vals) - 1, int(round(p / 100 * (len(vals) - 1))))]
        table["latency_s"] = {k: {"p50": _pct([x[k] for x in lat], 50), "p90": _pct([x[k] for x in lat], 90),
                                  "mean": round(sum(x[k] for x in lat) / len(lat), 2), "n": len(lat)}
                              for k in ("query", "chat")}
    print(json.dumps(table, ensure_ascii=False, indent=1))
    Path(str(path).replace(".scores.jsonl", ".summary.json")).write_text(
        json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["collect", "score", "summary"])
    ap.add_argument("--out", required=True, help="tiền tố file kết quả (VD eval/results/ragas/2026-10-26)")
    ap.add_argument("--api", default="http://localhost:8003")
    ap.add_argument("--golden", default="eval/multimodal_v1.jsonl")
    ap.add_argument("--list", default="")
    ap.add_argument("--sets", default="", help='thay --golden/--list: "g2=eval/golden_v2.jsonl,golden=…"')
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--rpm", type=int, default=15, help="trần lượt gọi LLM / phút (kiraai miễn phí: 20)")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--metrics", default="faithfulness,answer_relevancy,context_precision,context_recall")
    ap.add_argument("--embed-base", default="http://localhost:8090/v1")
    ap.add_argument("--retry-errors", action="store_true", help="score: chấm lại các chỉ số đã lỗi")
    ap.add_argument("--env-file", default=".env")
    args = ap.parse_args()
    if args.step == "collect":
        collect(args)
    elif args.step == "score":
        asyncio.run(score_all(args))
    else:
        summary(Path(f"{args.out}.scores.jsonl"), [m for m in args.metrics.split(",") if m], questions(args))


if __name__ == "__main__":
    sys.exit(main())
