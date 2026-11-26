"""OCR fallback demo sau visual retrieval, chỉ kích hoạt qua env MVP_OCR_POLICY.

Kết quả OCR từ ảnh người dùng là đầu vào bổ trợ, không được tính là nguồn SICT.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
import re
from urllib.parse import urlsplit

import httpx

from sict_crawler.model.schemas import QueryIn


_LOG = logging.getLogger(__name__)
_MAX_IMAGE_BYTES = 3 * 1024 * 1024
_READ_TEXT = re.compile(
    r"\b(?:ocr|đọc chữ|đọc nội dung|trích xuất chữ|văn bản|chữ gì|ghi gì|viết gì|"
    r"read text|extract text|what does .* say)\b", re.IGNORECASE,
)


def _should_ocr(question: str, result: dict) -> bool:
    policy = os.getenv("MVP_OCR_POLICY", "off").strip().lower()
    if policy not in ("weak", "always") or result.get("oos"):
        return False
    return policy == "always" or not result.get("sufficient", False) or bool(_READ_TEXT.search(question))


def _has_sict_evidence(result: dict) -> bool:
    sources = result.get("text", []) + result.get("media", [])
    if not result.get("sufficient") or result.get("oos") or not sources or not result.get("context"):
        return False
    for source in sources:
        try:
            url = urlsplit(source.parent_url or source.url)
        except ValueError:
            return False
        if url.scheme not in ("http", "https") or url.hostname != "sict.haui.edu.vn":
            return False
    return True


def _unverified_result(result: dict, supplemental: str, ocr: dict) -> dict:
    if _has_sict_evidence(result):
        return {**result, "context": result["context"] + "\n\n" + supplemental, "ocr": ocr}
    return {**result, "text": [], "media": [], "sufficient": False,
            "context": supplemental, "ocr": ocr}


async def add_query_ocr(q: QueryIn, result: dict) -> dict:
    """OCR → truy xuất lại SICT bằng chữ OCR trước khi tạo câu trả lời."""
    if not q.image or not _should_ocr(q.question, result):
        return result

    url = os.getenv("MVP_OCR_URL", "").strip()
    token = os.getenv("MVP_OCR_TOKEN", "")
    if not url.startswith("https://") or not token:
        return result

    try:
        encoded = q.image.split(",", 1)[-1] if q.image.startswith("data:image/") else q.image
        if len(encoded) > (_MAX_IMAGE_BYTES + 2) // 3 * 4 + 4:
            return {**result, "ocr": {"status": "skipped", "reason": "image_too_large"}}
        image_bytes = base64.b64decode(encoded, validate=True)
        if len(image_bytes) > _MAX_IMAGE_BYTES:
            return {**result, "ocr": {"status": "skipped", "reason": "image_too_large"}}

        async with httpx.AsyncClient(timeout=httpx.Timeout(18.0)) as client:
            response = await client.post(url, json={"image_base64": encoded},
                                         headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
            try:
                body = response.json()
            except ValueError:
                return {**result, "ocr": {"status": "unavailable"}}
            if not isinstance(body, dict):
                return {**result, "ocr": {"status": "unavailable"}}

        text = body.get("text", "")
        if not isinstance(text, str) or not text.strip():
            return {**result, "ocr": {"status": "empty"}}
        text = text.strip()[:2048]

        from starlette.concurrency import run_in_threadpool
        from sict_crawler.service.embedding.embedder import query_embedding_budget
        from sict_crawler.service.retrieval import agent, retriever

        def retrieve_ocr():
            # Bỏ ảnh để buộc retriever thực hiện dense/BM25 theo chữ OCR.
            ocr_query = f"{q.question.strip()}\n{text}".strip()
            scope = hashlib.sha256(image_bytes + b"\x00" + text.encode()).hexdigest()
            cache_token = retriever.OCR_CACHE_SCOPE.set(scope)
            try:
                with query_embedding_budget():
                    return agent.run(ocr_query, q.top_k, None, q.filters)
            finally:
                retriever.OCR_CACHE_SCOPE.reset(cache_token)

        verified_context = "[Chữ OCR từ ảnh người dùng, chưa được xác minh trên SICT]\n" + text
        try:
            grounded = await run_in_threadpool(retrieve_ocr)
        except Exception as exc:
            _LOG.warning("OCR re-query SICT thất bại: %s", type(exc).__name__)
            return _unverified_result(result, verified_context,
                {"status": "unverified", "text": text, "language": body.get("language"),
                 "source_verified": False, "reason": "retrieval_unavailable"})

        # Tránh citation từ kết quả visual retrieval không liên quan với chữ OCR.
        verified = bool(grounded.get("text") and _has_sict_evidence(grounded))
        ocr = {"status": "ok" if verified else "unverified", "text": text,
               "language": body.get("language"), "source_verified": verified}
        if verified:
            return {**grounded, "image_status": result.get("image_status", "none"),
                    "inputs": result.get("inputs", ["image"]),
                    "context": grounded["context"] + "\n\n" + verified_context, "ocr": ocr}
        # Khi không có nguồn xác thực, vẫn cho phép đọc chữ từ ảnh, tách rõ
        # ngữ cảnh OCR khỏi trích dẫn SICT và không suy diễn ra nguồn khác.
        return _unverified_result(result, verified_context, ocr)
    except (binascii.Error, ValueError):
        return {**result, "ocr": {"status": "skipped", "reason": "invalid_image"}}
    except (httpx.HTTPError, KeyError, TypeError) as exc:
        _LOG.warning("MVP OCR fallback thất bại: %s", type(exc).__name__)
        return {**result, "ocr": {"status": "unavailable"}}
