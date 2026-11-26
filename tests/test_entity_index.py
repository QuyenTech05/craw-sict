"""Alias có nguồn, bảo toàn dấu và xử lý an toàn khi trùng tên."""

from sict_crawler.service.retrieval.entity_index import AliasIndex, build_alias_index


def _person(entity_id="person:nghien", name="Nguyễn Bá Nghiễn", alias="Nghiễn"):
    return {"entity_id": entity_id, "entity_type": "person", "canonical_name": name,
            "aliases": [alias], "confidence": 0.98, "source_document_ids": [7],
            "provenance": ["document:7:reviewed"], "method": "alias"}


def test_full_short_title_no_accent_and_unknown_alias():
    index = build_alias_index([_person()])
    assert index.unique(index.resolve("Nguyễn Bá Nghiễn", "Nguyễn Bá Nghiễn"))
    assert index.unique(index.resolve("Nghiễn", "thầy Nghiễn"))
    assert index.unique(index.resolve("Nguyen Ba Nghien", "Nguyen Ba Nghien"))
    assert index.unique(index.resolve("Nghiễn", "Nghiễn")) is None
    assert index.lookup("Tên không có trong corpus") == []
    assert [e.matched_surface for e in index.match_question("thông tin về thầy Nghiễn") ] == ["Nghiễn"]


def test_ambiguous_alias_never_resolves_unique():
    index = build_alias_index([_person(), _person("person:other", "Trần Văn Nghiễn")])
    candidates = index.resolve("Nghiễn", "thầy Nghiễn", entity_type="person")
    assert len(candidates) == 2
    assert {c.ambiguity_count for c in candidates} == {2}
    assert index.unique(candidates) is None


def test_missing_source_or_bad_type_is_ignored():
    bad = _person()
    bad["source_document_ids"] = []
    wrong_type = _person("concept:1", "Chương trình đào tạo")
    wrong_type["entity_type"] = "concept"
    assert AliasIndex(build_alias_index([bad, wrong_type]).entries).entries == ()
