"""Bộ v2 không có trường intent của bộ v1."""
import json
import sys
from pathlib import Path

import numpy as np


def test_offline_eval_accepts_golden_v2_case(tmp_path, monkeypatch):
    from scripts import eval_retrieval
    from sict_crawler.service.embedding import embedder
    from sict_crawler.core.config import get_settings

    row = json.loads(Path('eval/golden_v2.jsonl').read_text(encoding='utf-8').splitlines()[0])
    assert 'intent' not in row and row.get('case')
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    emb = get_settings().embedding
    (artifacts / 'manifest.json').write_text(json.dumps({
        'backend': 'api', 'text_model': emb.model, 'image_model': emb.model,
        'dim': emb.dim, 'query_prefix': emb.query_prefix,
    }))
    (artifacts / 'chunks.jsonl').write_text(json.dumps({'text': 'trường công nghệ', 'url': 'https://example.org/test'}) + '\n')
    vector = np.zeros(emb.dim, dtype=np.float32)
    vector[0] = 1.0
    np.save(artifacts / 'chunks.npy', vector[None, :])
    monkeypatch.setattr(embedder, 'embed_query', lambda question: vector.tolist())
    out = tmp_path / 'out'
    monkeypatch.setattr(sys, 'argv', ['eval_retrieval.py', '--artifacts', str(artifacts), '--out', str(out)])
    eval_retrieval.main()
    result = json.loads((out / 'jina-clip-v2.json').read_text())
    assert row['case'] in result['by_intent']['dense']
    assert len(result['per_question']['dense']) == 88
