"""Chỉ mục alias có nguồn kiểm chứng. Xây từ rows đã duyệt, không suy đoán tên người.

Artifact JSON dùng để tái hiện bản index trong môi trường eval. Không tự nạp dữ liệu
cá nhân chưa qua kiểm duyệt và không thay đổi graph khái niệm D33.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Literal

from sict_crawler.core.text import fold

EntityType = Literal["person", "organization", "event", "program", "place"]
EntityMethod = Literal["regex", "alias", "gazetteer", "ner", "llm"]
TYPES = {"person", "organization", "event", "program", "place"}
TITLES = ("thay", "co", "tien si", "ts", "pgs", "gs", "pho giao su", "giao su")


def normalize(surface: str) -> str:
    return " ".join(fold(unicodedata.normalize("NFC", surface)).split())


@dataclass(frozen=True)
class EntityCandidate:
    entity_id: str
    entity_type: EntityType
    canonical_name: str
    matched_surface: str
    aliases: tuple[str, ...]
    confidence: float
    ambiguity_count: int
    source_document_ids: tuple[int, ...]
    provenance: tuple[str, ...]
    method: EntityMethod = "alias"

    def __post_init__(self):
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("Entity confidence phải trong [0,1]")
        if self.entity_type not in TYPES or self.ambiguity_count < 1:
            raise ValueError("Entity type/ambiguity không hợp lệ")


class AliasIndex:
    def __init__(self, entries: Iterable[EntityCandidate] = (), *, min_confidence: float = 0.85):
        if not 0 <= min_confidence <= 1:
            raise ValueError("min_confidence phải trong [0,1]")
        self.min_confidence = min_confidence
        self.entries = tuple(entries)
        self._by_alias: dict[str, list[EntityCandidate]] = {}
        for entry in self.entries:
            for name in (entry.canonical_name, *entry.aliases):
                key = normalize(name)
                if key and all(x.entity_id != entry.entity_id for x in self._by_alias.get(key, [])):
                    self._by_alias.setdefault(key, []).append(entry)

    def lookup(self, surface: str) -> list[EntityCandidate]:
        key = normalize(surface)
        found = self._by_alias.get(key, [])
        return [replace(e, matched_surface=surface, ambiguity_count=len(found)) for e in found]

    def resolve(self, surface: str, context: str, entity_type: str | None = None) -> list[EntityCandidate]:
        candidates = self.lookup(surface)
        if entity_type is not None:
            candidates = [c for c in candidates if c.entity_type == entity_type]
        context_folded = normalize(context)
        # Title gần alias một từ làm rõ ý định người; không tự khẳng định danh tính
        # nếu nhiều entity dùng chung alias.
        contextual_person = any(re.search(rf"\b{re.escape(title)}\s+{re.escape(normalize(surface))}\b", context_folded)
                                for title in TITLES)
        out = []
        for c in candidates:
            short = len(normalize(surface).split()) == 1
            conf = c.confidence
            if short and normalize(surface) != normalize(c.canonical_name):
                conf = min(conf, 0.72 if not (contextual_person and c.entity_type == "person") else 0.9)
            out.append(replace(c, confidence=conf, ambiguity_count=len(candidates)))
        return out

    def unique(self, candidates: Iterable[EntityCandidate]) -> EntityCandidate | None:
        good = [c for c in candidates if c.ambiguity_count == 1 and c.confidence >= self.min_confidence
                and c.provenance and c.source_document_ids]
        return good[0] if len(good) == 1 else None

    def match_question(self, question: str) -> list[EntityCandidate]:
        # Bảo toàn vị trí ký tự gốc qua phép bỏ dấu (NFD có thể đổi độ dài).
        original = unicodedata.normalize("NFC", question)
        folded, offsets = [], []
        for pos, char in enumerate(original):
            for normalized_char in fold(char):
                folded.append(normalized_char)
                offsets.append(pos)
        q = "".join(folded)
        matches: list[tuple[int, int, EntityCandidate]] = []
        for alias in self._by_alias:
            pattern = r"\s+".join(re.escape(part) for part in alias.split())
            surface_match = re.search(rf"(?<!\w){pattern}(?!\w)", q)
            if surface_match:
                surface = original[offsets[surface_match.start()]:offsets[surface_match.end() - 1] + 1]
                for c in self.resolve(surface, question):
                    matches.append((len(alias), surface_match.start(), c))
        # Full name thắng short alias cùng thực thể.
        matches.sort(key=lambda item: (-item[0], item[1]))
        selected: dict[str, EntityCandidate] = {}
        for _, _, cand in matches:
            selected.setdefault(cand.entity_id, cand)
        return list(selected.values())


def build_alias_index(rows: Iterable[dict], *, min_confidence: float = 0.85) -> AliasIndex:
    """Rows bắt buộc có source_document_ids và provenance chứng minh nguồn."""
    entries = []
    for row in rows:
        if row.get("entity_type") not in TYPES:
            continue  # bỏ concept phrase và loại không xác minh
        canonical = str(row.get("canonical_name") or "").strip()
        doc_ids = tuple(int(x) for x in row.get("source_document_ids", ()))
        provenance = tuple(str(x) for x in row.get("provenance", ()) if x)
        if not canonical or not doc_ids or not provenance:
            continue
        method = row.get("method", "alias")
        # Chỉ nhận alias/gazetteer/regex đã review; không mở lại NER/LLM extraction.
        if method not in {"alias", "gazetteer", "regex"}:
            continue
        aliases = tuple(str(a).strip() for a in row.get("aliases", ()) if normalize(str(a)))
        entries.append(EntityCandidate(
            entity_id=str(row.get("entity_id") or f"{row['entity_type']}:{normalize(canonical)}"),
            entity_type=row["entity_type"], canonical_name=canonical, matched_surface=canonical,
            aliases=aliases, confidence=float(row.get("confidence", 1.0)), ambiguity_count=1,
            source_document_ids=doc_ids, provenance=provenance,
            method=method))
    return AliasIndex(entries, min_confidence=min_confidence)


def save_alias_index(index: AliasIndex, path: str | Path) -> None:
    from dataclasses import asdict
    output = {"schema_version": 1, "min_confidence": index.min_confidence,
              "entries": [asdict(e) for e in index.entries]}
    Path(path).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


def load_alias_index(path: str | Path) -> AliasIndex:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Alias index schema không được hỗ trợ")
    return build_alias_index(data["entries"], min_confidence=data["min_confidence"])
