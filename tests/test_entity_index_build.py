"""Bản alias artifact có thể tái nạp mà không thêm entity suy đoán."""

from sict_crawler.service.retrieval.entity_index import (
    build_alias_index, load_alias_index, save_alias_index,
)


def test_reviewed_artifact_roundtrip_and_method_policy(tmp_path):
    approved = {"entity_type": "person", "canonical_name": "Nguyễn Bá Nghiễn",
                "aliases": ["Nghiễn"], "source_document_ids": [12],
                "provenance": ["reviewed-source:12"], "method": "gazetteer"}
    rejected = [{**approved, "method": method, "entity_id": method}
                for method in ("llm", "ner")]
    index = build_alias_index([approved, *rejected], min_confidence=0.88)
    assert len(index.entries) == 1
    artifact = tmp_path / "aliases.json"
    save_alias_index(index, artifact)
    restored = load_alias_index(artifact)
    assert restored.entries == index.entries
    assert restored.min_confidence == 0.88
    assert restored.lookup("Nguyen Ba Nghien")[0].source_document_ids == (12,)
