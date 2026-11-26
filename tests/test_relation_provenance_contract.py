"""Task 14: hợp đồng dữ liệu cạnh quan hệ tương lai, chưa tạo relation graph.

Fixture này mô tả các trường bắt buộc để review trước khi bất kỳ cạnh quan hệ
nào được phép dùng làm bằng chứng trả lời. Graph D33 hiện chỉ lưu concept.
"""

from sict_crawler.service.retrieval.agent import evidence


REQUIRED = (
    "subject", "predicate", "object", "source_document_id", "source_chunk_id",
    "source_page", "extraction_method", "confidence", "created_signature",
)
ALLOWED_METHODS = {"alias", "gazetteer", "regex", "reviewed_rule"}


def _supported_edge(row: dict) -> bool:
    """Chính sách schema ở tầng test, chưa có luồng production nào tiêu thụ cạnh."""
    if not all(field in row for field in REQUIRED):
        return False
    if not all(isinstance(row[field], str) and row[field].strip() for field in
               ("subject", "predicate", "object", "source_chunk_id", "created_signature")):
        return False
    if not isinstance(row["source_document_id"], int) or row["source_document_id"] <= 0:
        return False
    if not isinstance(row["source_page"], int) or row["source_page"] < 1:
        return False
    if row["extraction_method"] not in ALLOWED_METHODS:
        return False
    confidence = row["confidence"]
    return isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and 0 <= confidence <= 1


def test_relation_edge_requires_traceable_provenance():
    valid = dict(subject="org:1", predicate="hosts", object="event:2",
                 source_document_id=7, source_chunk_id="chunk-7", source_page=1,
                 extraction_method="reviewed_rule", confidence=0.94,
                 created_signature="rules-v1:corpus-2026-11-24")
    assert _supported_edge(valid)
    for field in REQUIRED:
        assert not _supported_edge({k: v for k, v in valid.items() if k != field}), field
    for method in ("llm", "ner", "unknown"):
        assert not _supported_edge({**valid, "extraction_method": method})


def test_unverified_relation_cannot_replace_source_evidence():
    # Concept/intent là tín hiệu tìm kiếm. Không có nguồn thực thì agent phải từ chối.
    result = evidence("Đơn vị nào tổ chức sự kiện?", [], [],
                      "org:1 hosts event:2, không có source_document_id")
    assert result["sufficient"] is False
    assert result["reason"] == "không có nguồn"
