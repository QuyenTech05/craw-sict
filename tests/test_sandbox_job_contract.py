"""Mô phỏng Vercel Sandbox dừng phiên và khôi phục từ VM job store."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import time

import pytest

from sandbox import job_runner


class FakeJobClient:
    def __init__(self, kind, items):
        self.kind = kind
        self.items = items
        self.state = {"status": "queued", "kind": kind, "attempt": 0,
                      "revision": 0, "checkpoint": {"completed": []}}
        self.files = {"input/items.json": json.dumps({"items": items}).encode()}
        self.manifest = {"artifacts": {}}
        self.attempt = None

    def upload(self, area, name, payload):
        key = f"{area}/{name}"
        digest = hashlib.sha256(payload).hexdigest()
        if key in self.manifest["artifacts"]:
            if self.manifest["artifacts"][key]["sha256"] != digest:
                raise RuntimeError("Artifact checksum mismatch")
            return self.manifest["artifacts"][key]
        self.files[key] = payload
        meta = {"sha256": digest, "bytes": len(payload)}
        self.manifest["artifacts"][key] = meta
        return meta

    def request(self, suffix="", method="GET", json_body=None, **kwargs):
        if suffix.startswith("/artifacts/") and method == "GET":
            key = suffix.removeprefix("/artifacts/")
            payload = self.files[key]
            expected = self.manifest["artifacts"].get(key)
            if expected and hashlib.sha256(payload).hexdigest() != expected["sha256"]:
                raise job_runner.ApiError("Artifact sai checksum")
            return payload
        if suffix == "/manifest":
            return self.manifest
        if suffix == "/claim":
            if self.state["status"] != "succeeded":
                self.state = {**self.state, "status": "running",
                              "attempt": self.state["attempt"] + 1,
                              "revision": self.state["revision"] + 1}
            return self.state.copy()
        if suffix == "/heartbeat":
            return self.state.copy()
        if suffix == "" and method == "PATCH":
            assert json_body["expected_attempt"] == self.state["attempt"]
            assert json_body["expected_revision"] == self.state["revision"]
            self.state = {**self.state, "status": json_body["status"],
                          "checkpoint": json_body["checkpoint"],
                          "revision": self.state["revision"] + 1}
            return self.state.copy()
        raise AssertionError(f"Unexpected request {method} {suffix}")


def test_sandbox_resume_from_uploaded_manifest_after_crash(tmp_path):
    client = FakeJobClient("ocr", [{"id": "poster"}, {"id": "banner"}])
    processed = []

    def simulate_crash(kind, item, gateway, deadline, workspace):
        gateway.upload("output", item["id"] + ".json", json.dumps({
            "id": item["id"], "text": "Kết quả", "language": "vie+eng",
        }).encode())
        processed.append(item["id"])
        if item["id"] == "poster":
            raise RuntimeError("Sandbox chết sau upload trước checkpoint")

    with pytest.raises(RuntimeError, match="Sandbox chết"):
        job_runner.run_job(client, time.time() + 360, tmp_path, process=simulate_crash)
    assert client.state["status"] == "paused"
    assert client.state["checkpoint"]["completed"] == []
    assert "output/poster.json" in client.manifest["artifacts"]

    result = job_runner.run_job(client, time.time() + 360, tmp_path,
                                process=simulate_crash)
    assert result["status"] == "succeeded"
    assert result["attempt"] == 2
    assert result["checkpoint"]["completed"] == ["poster", "banner"]
    assert processed == ["poster", "banner"]
    assert job_runner.run_job(client, time.time() + 360, tmp_path,
                              process=simulate_crash)["status"] == "succeeded"
    assert processed == ["poster", "banner"]


def test_sandbox_pauses_at_deadline_then_resumes(tmp_path):
    client = FakeJobClient("ocr", [{"id": "a"}])
    calls = []

    def fake_process(kind, item, gateway, deadline, workspace):
        calls.append(item["id"])
        gateway.upload("output", item["id"] + ".json", b"done")

    result = job_runner.run_job(client, time.time() + 10, tmp_path, process=fake_process)
    assert result["status"] == "paused"
    assert calls == []
    result = job_runner.run_job(client, time.time() + 360, tmp_path, process=fake_process)
    assert result["status"] == "succeeded" and calls == ["a"]


def test_sandbox_rejects_duplicate_items_and_live_writer(tmp_path):
    client = FakeJobClient("ocr", [{"id": "same"}, {"id": "same"}])
    with pytest.raises(ValueError, match="trùng"):
        job_runner.run_job(client, time.time() + 360, tmp_path)
    assert client.state["attempt"] == 0
    for kind in ("incremental-small", "loader-staging", "graph", "reconcile-small"):
        with pytest.raises(ValueError, match="không được hỗ trợ"):
            job_runner.process_item(kind, {"id": "safe"}, client, time.time() + 360,
                                    tmp_path)


def test_reconcile_graph_read_only_reports(tmp_path):
    for kind in ("reconcile-dry-run", "graph-stats"):
        client = FakeJobClient(kind, [{"id": "read_only"}])
        client.attempt = 1
        def request(suffix, method, json_body):
            assert (suffix, method, json_body) == ("/report", "POST", {"expected_attempt": 1})
            return {"kind": kind, "report": {"status": "ok"}}
        client.request = request
        result = job_runner.process_item(kind, {"id": kind.replace("-", "_")}, client,
                                         time.time() + 360, tmp_path,
                                         run_command=lambda *_: pytest.fail("Không chạy datastore trong Sandbox"))
        assert result["report"] == {"status": "ok"}


def test_compute_rejects_archive_traversal(tmp_path):
    client = FakeJobClient("compute", [{"id": "test"}])
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w:gz") as archive:
        metadata = tarfile.TarInfo("../escape.txt")
        payload = b"malicious"
        metadata.size = len(payload)
        archive.addfile(metadata, io.BytesIO(payload))
    client.files["input/test.tar.gz"] = tar_bytes.getvalue()
    with pytest.raises(ValueError, match="không an toàn"):
        job_runner.process_item("compute", {"id": "test", "input": "test.tar.gz"},
                                client, time.time() + 360, tmp_path)
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.parametrize("filename, field", [("pages.jsonl", "html_path"), ("files.jsonl", "path")])
def test_compute_rejects_manifest_path_traversal(tmp_path, filename, field):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "pages.jsonl").touch()
    (snapshot / "files.jsonl").touch()
    (snapshot / filename).write_text(json.dumps({field: "../outside"}) + "\n")
    client = FakeJobClient("compute", [{"id": "test"}])
    client.files["input/test.tar.gz"] = job_runner._archive(snapshot)
    with pytest.raises(ValueError, match="đường dẫn không an toàn"):
        job_runner.process_item("compute", {"id": "test", "input": "test.tar.gz"},
                                client, time.time() + 360, tmp_path,
                                run_command=lambda *_: pytest.fail("Không chạy snapshot lỗi"))


def test_compute_runs_docs_only_from_snapshot(tmp_path):
    from tests.test_compute import _make_snapshot

    snapshot = tmp_path / "snapshot"
    _make_snapshot(snapshot)
    # Artifact giả trong input không được dùng làm output của lần compute mới.
    old = snapshot / "artifacts"
    old.mkdir()
    (old / "stale.txt").write_text("old artifact")
    client = FakeJobClient("compute", [{"id": "test"}])
    client.files["input/test.tar.gz"] = job_runner._archive(snapshot)
    job_runner.process_item("compute", {"id": "test", "input": "test.tar.gz"},
                            client, time.time() + 360, tmp_path)
    with tarfile.open(fileobj=io.BytesIO(client.files["output/test.tar.gz"]), mode="r:gz") as archive:
        manifest = json.load(archive.extractfile("artifacts/manifest.json"))
        assert set(manifest["stages"]) == {"docs"}
        assert manifest["stages"]["docs"]["documents"] > 0
        assert manifest["semantic_chunking"] is False
        assert "artifacts/stale.txt" not in archive.getnames()
        assert "artifacts/chunks.npy" not in archive.getnames()


def test_video_resume_after_partial_frame_upload(tmp_path):
    client = FakeJobClient("video", [{"id": "clip", "input": "clip.mp4"}])
    client.files["input/clip.mp4"] = b"fake-video"
    original_upload = client.upload
    should_crash = True

    def interrupted_upload(area, name, payload):
        nonlocal should_crash
        if name == "clip-frame-02.jpg" and should_crash:
            should_crash = False
            raise ConnectionError("Mất kết nối sau frame đầu tiên")
        return original_upload(area, name, payload)

    def fake_ffmpeg(command, deadline, cwd=None):
        folder = Path(command[-1]).parent
        (folder / "frame-01.jpg").write_bytes(b"frame one")
        (folder / "frame-02.jpg").write_bytes(b"frame two")
        return ""

    def process(kind, item, gateway, deadline, workspace):
        return job_runner.process_item(kind, item, gateway, deadline, workspace,
                                       run_command=fake_ffmpeg)

    client.upload = interrupted_upload
    with pytest.raises(ConnectionError, match="Mất kết nối"):
        job_runner.run_job(client, time.time() + 360, tmp_path / "first", process=process)
    assert "output/clip-frame-01.jpg" in client.manifest["artifacts"]
    assert "output/clip.json" not in client.manifest["artifacts"]

    result = job_runner.run_job(client, time.time() + 360, tmp_path / "second", process=process)
    assert result["status"] == "succeeded"
    info = json.loads(client.files["output/clip.json"])
    assert info["frames"] == ["clip-frame-01.jpg", "clip-frame-02.jpg"]


def test_video_completed_manifest_requires_frames(tmp_path):
    client = FakeJobClient("video", [{"id": "clip", "input": "clip.mp4"}])
    client.upload("output", "clip.json", json.dumps({
        "id": "clip", "frames": ["clip-frame-01.jpg"]}).encode())
    with pytest.raises(job_runner.ApiError, match="Video manifest chưa hoàn tất"):
        job_runner.run_job(client, time.time() + 360, tmp_path,
                           process=lambda *_: pytest.fail("Không được tính lại video"))
    assert client.state["status"] == "paused"
    assert client.state["checkpoint"]["completed"] == []


def test_checkpoint_completed_requires_verified_output(tmp_path):
    client = FakeJobClient("ocr", [{"id": "poster"}])
    client.state.update(status="paused", checkpoint={"completed": ["poster"]})
    with pytest.raises(job_runner.ApiError, match="Checkpoint thiếu artifact"):
        job_runner.run_job(client, time.time() + 360, tmp_path,
                           process=lambda *_: pytest.fail("Không được OCR lại"))
    assert client.state["status"] == "paused"

    client.upload("output", "poster.json", b'{"id":"poster","text":"ok"}')
    client.files["output/poster.json"] = b"corrupted"
    with pytest.raises(job_runner.ApiError, match="checksum"):
        job_runner.run_job(client, time.time() + 360, tmp_path,
                           process=lambda *_: pytest.fail("Không được OCR lại"))
    assert client.state["status"] == "paused"


def test_ocr_artifact_with_valid_checksum_but_invalid_payload_cannot_resume(tmp_path):
    client = FakeJobClient("ocr", [{"id": "poster"}])
    for payload in (b"not-json", b'{"id":"other","text":"ok","language":"vie+eng"}',
                    b'{"id":"poster","text":42,"language":"vie+eng"}'):
        client.upload("output", "poster.json", payload)
        with pytest.raises(job_runner.ApiError, match="OCR artifact poster không hợp lệ"):
            job_runner.run_job(client, time.time() + 360, tmp_path,
                               process=lambda *_: pytest.fail("Không được OCR lại artifact đã có"))
        assert client.state["status"] == "paused"
        client.manifest["artifacts"].pop("output/poster.json")
        client.files.pop("output/poster.json")


def test_sandbox_ocr_function_must_return_valid_payload(tmp_path, monkeypatch):
    client = FakeJobClient("ocr", [{"id": "poster", "input": "poster.png"}])
    client.files["input/poster.png"] = b"fake-image"
    monkeypatch.setenv("MVP_OCR_URL", "https://vercel.example/api/ocr")
    monkeypatch.setenv("MVP_OCR_TOKEN", "ocr-token")

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, *_):
            return json.dumps(self.payload).encode()

    for payload in ({"text": 42, "language": "vie+eng"},
                    {"text": "Poster"}, ["not-an-object"]):
        monkeypatch.setattr(job_runner, "urlopen", lambda *_, **__: FakeResponse(payload))
        with pytest.raises(job_runner.ApiError, match="OCR Function trả dữ liệu không hợp lệ"):
            job_runner.process_item("ocr", {"id": "poster", "input": "poster.png"},
                                    client, time.time() + 360, tmp_path)
        assert "output/poster.json" not in client.manifest["artifacts"]

    monkeypatch.setattr(job_runner, "urlopen", lambda *_, **__: FakeResponse({
        "text": "Nội dung poster", "language": "vie+eng",
    }))
    output = job_runner.process_item("ocr", {"id": "poster", "input": "poster.png"},
                                     client, time.time() + 360, tmp_path)
    assert output == {"id": "poster", "text": "Nội dung poster", "language": "vie+eng"}
    assert json.loads(client.files["output/poster.json"]) == output


def test_checkpoint_rejects_unknown_or_repeated_item(tmp_path):
    client = FakeJobClient("ocr", [{"id": "poster"}])
    for completed in (["unknown"], ["poster", "poster"], [{"id": "poster"}]):
        client.state.update(status="paused", checkpoint={"completed": completed})
        with pytest.raises(job_runner.ApiError, match="Checkpoint chứa item"):
            job_runner.run_job(client, time.time() + 360, tmp_path,
                               process=lambda *_: pytest.fail("Không được OCR"))
        assert client.state["status"] == "paused"
