"""Giữ đầu vào ảnh và tách lượt lỗi khỏi mẫu RAGAS mới nhất."""

import io
import json
import urllib.error
from types import SimpleNamespace

from scripts import eval_ragas


def test_latest_golden_reads_image_from_dataset_root(tmp_path):
    dataset = tmp_path / 'eval' / 'multimodal_v1.jsonl'
    dataset.parent.mkdir()
    dataset.write_text(json.dumps({'id': 'mm-1', 'question': 'Ảnh này là gì?',
                                   'image': 'eval/images/test.jpg'}), encoding='utf-8')
    args = SimpleNamespace(sets=f'mm={dataset}', golden='', list='', limit=0)
    [row] = eval_ragas.questions(args)
    assert row['image_path'] == str(tmp_path / 'eval' / 'images' / 'test.jpg')


def test_chat_sends_real_image_and_detects_incomplete(monkeypatch):
    sent = []

    def fake_post(api, path, body, timeout):
        sent.append((path, body))
        return io.BytesIO(b'data: {"delta":"abc"}\n' +
                          b'data: {"status":{"generation":"incomplete"}}\n' +
                          b'data: [DONE]\n')

    monkeypatch.setattr(eval_ragas, 'post', fake_post)
    answer, statuses, done = eval_ragas.chat('http://dev',
        {'question': 'Ảnh gì?', 'filters': None, 'image_b64': 'aW1hZ2U='}, 8, 30)
    assert answer == 'abc' and done
    assert statuses == [{'generation': 'incomplete'}]
    assert sent[0][1]['image'] == 'aW1hZ2U='


def test_invalid_llm_or_image_runs_are_excluded_from_ragas():
    base = {'question': 'Ảnh này là gì?', 'answer': 'Một tòa nhà',
            'image_input': True, 'image_status': 'ok', 'finished': True}
    assert eval_ragas.score_exclusion(base) is None
    assert eval_ragas.score_exclusion({**base, 'image_status': 'embedding_failed'}) == 'image_embedding_failed'
    assert eval_ragas.score_exclusion({**base, 'generation_incomplete': True}) == 'generation_incomplete'
    assert eval_ragas.score_exclusion({**base, 'answer': '(LLM chưa trả lời được)'}) == 'llm_fallback'
    assert eval_ragas.score_exclusion({**base, 'question': ''}) == 'image_only_no_text_for_judge'


def test_collect_sends_image_to_both_endpoints(tmp_path, monkeypatch):
    image = tmp_path / 'eval' / 'images' / 'test.jpg'
    image.parent.mkdir(parents=True)
    image.write_bytes(b'example-image')
    golden = tmp_path / 'eval' / 'multimodal_v1.jsonl'
    golden.write_text(json.dumps({'id': 'mm-1', 'question': 'Ảnh gì?',
                                  'image': 'eval/images/test.jpg'}), encoding='utf-8')
    sent = []

    def fake_post(api, path, body, timeout):
        sent.append((path, body))
        if path == '/query':
            return io.BytesIO(json.dumps({'image_status': 'ok', 'context': '[1] nguồn',
                                          'text': [], 'media': []}).encode())
        return io.BytesIO(b'data: {"delta":"Toa nha [1]"}\n' + b'data: [DONE]\n')

    monkeypatch.setattr(eval_ragas, 'post', fake_post)
    monkeypatch.setattr(eval_ragas.time, 'sleep', lambda n: None)
    args = SimpleNamespace(sets='', golden=str(golden), list='', limit=0,
                           out=str(tmp_path / 'measurement'), rpm=15, top_k=5,
                           api='http://dev', timeout=30)
    eval_ragas.collect(args)
    assert [path for path, _ in sent] == ['/query', '/chat']
    assert sent[0][1]['image'] == sent[1][1]['image']
    [row] = [json.loads(x) for x in (tmp_path / 'measurement.answers.jsonl').read_text().splitlines()]
    assert row['image_input'] and row['finished'] and row['image_status'] == 'ok'


def test_collect_records_request_error_without_stopping_dataset(tmp_path, monkeypatch):
    golden = tmp_path / 'eval' / 'multimodal_v1.jsonl'
    golden.parent.mkdir()
    golden.write_text(json.dumps({'id': 'mm-1', 'question': 'Học phí?'}) + '\n' +
                      json.dumps({'id': 'mm-2', 'question': 'Ngành gì?'}), encoding='utf-8')
    def fake_post(api, path, body, timeout):
        if body['question'] == 'Học phí?':
            raise urllib.error.URLError('offline')
        if path == '/query':
            return io.BytesIO(json.dumps({'context': '[1] nguồn', 'text': [], 'media': []}).encode())
        return io.BytesIO('data: {"delta":"Ngành CNTT"}\n'.encode() + b'data: [DONE]\n')
    monkeypatch.setattr(eval_ragas, 'post', fake_post)
    monkeypatch.setattr(eval_ragas.time, 'sleep', lambda n: None)
    args = SimpleNamespace(sets='', golden=str(golden), list='', limit=0,
                           out=str(tmp_path / 'measurement'), rpm=15, top_k=5,
                           api='http://dev', timeout=30)
    eval_ragas.collect(args)
    [skipped] = [json.loads(x) for x in (tmp_path / 'measurement.skipped.jsonl').read_text().splitlines()]
    assert skipped['reason'].startswith('request_error:')
    [answer] = [json.loads(x) for x in (tmp_path / 'measurement.answers.jsonl').read_text().splitlines()]
    assert answer['id'] == 'golden:mm-2'


def test_collect_does_not_retry_llm_http_4xx(tmp_path, monkeypatch):
    golden = tmp_path / 'eval' / 'multimodal_v1.jsonl'
    golden.parent.mkdir()
    golden.write_text(json.dumps({'id': 'mm-1', 'question': 'Học phí?'}), encoding='utf-8')
    sent = []

    def fake_post(api, path, body, timeout):
        sent.append(path)
        if path == '/query':
            return io.BytesIO(json.dumps({'context': '[1] nguồn', 'text': [], 'media': []}).encode())
        return io.BytesIO(b'data: {"status":{"generation":"incomplete","error_code":"http_4xx"}}\n'
                          + b'data: [DONE]\n')

    monkeypatch.setattr(eval_ragas, 'post', fake_post)
    args = SimpleNamespace(sets='', golden=str(golden), list='', limit=0,
                           out=str(tmp_path / 'measurement'), rpm=15, top_k=5,
                           api='http://dev', timeout=30)
    eval_ragas.collect(args)
    assert sent == ['/query', '/chat']
    [skipped] = [json.loads(x) for x in (tmp_path / 'measurement.skipped.jsonl').read_text().splitlines()]
    assert skipped['reason'] == 'generation_http_4xx'


def test_summary_drops_invalid_old_scores_and_reports_p95(tmp_path, capsys):
    prefix = tmp_path / 'test'
    good = {'id': 'golden:1', 'set': 'golden', 'question': 'Câu gì?', 'answer': 'Câu trả lời',
            'latency_s': {'query': 1.0, 'chat': 2.0}}
    bad = {**good, 'id': 'golden:2', 'answer': '(LLM chưa trả lời được)'}
    (tmp_path / 'test.answers.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in (good, bad)))
    (tmp_path / 'test.scores.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in (
        {'id': 'golden:1', 'set': 'golden', 'context_precision': 1.0},
        {'id': 'golden:2', 'set': 'golden', 'context_precision': 0.0})))
    (tmp_path / 'test.skipped.jsonl').write_text(json.dumps({'id': 'golden:3', 'reason': 'request_error'}) + '\n')
    eval_ragas.summary(tmp_path / 'test.scores.jsonl', ['context_precision'])
    table = json.loads((tmp_path / 'test.summary.json').read_text())
    assert table['collection']['n_requested'] == 3
    assert table['collection']['n_eligible'] == 1
    assert table['collection']['excluded'] == {'llm_fallback': 1, 'request_error': 1}
    assert table['all']['context_precision'] == 1.0
    assert table['all']['context_precision_n'] == 1
    assert table['latency_s']['chat']['p95'] == 2.0
