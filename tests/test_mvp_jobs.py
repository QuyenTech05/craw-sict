"""Hợp đồng Job API bền vững và an toàn khi retry cho Vercel MVP."""

import hashlib
import json
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from sict_crawler.api import mvp_jobs


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("MVP_JOB_ROOT", str(tmp_path))
    monkeypatch.setenv("MVP_JOB_TOKEN", "demo-secret")
    clock = type("Clock", (), {"now": 1000.0, "time": lambda self: self.now})()
    monkeypatch.setattr(mvp_jobs, "time", clock)
    app = FastAPI()
    app.include_router(mvp_jobs.router)
    with TestClient(app) as client:
        yield client, clock, tmp_path


def request(client, method, path, *, token="demo-secret", **kwargs):
    headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
    return client.request(method, "/internal/jobs" + path, headers=headers, **kwargs)


def create(client, job_id=None, kind="ocr"):
    job_id = job_id or str(uuid4())
    fingerprint = "a" * 64
    body = {"job_id": job_id, "kind": kind, "input_fingerprint": fingerprint}
    response = request(client, "POST", "", json=body)
    assert response.status_code == 200, response.text
    return job_id, body, response.json()


def upload(client, job_id, area, name, data, attempt=None, sha256=None):
    headers = {"X-Content-SHA256": sha256 or hashlib.sha256(data).hexdigest()}
    if attempt is not None:
        headers["X-Job-Attempt"] = str(attempt)
    return request(client, "PUT", f"/{job_id}/artifacts/{area}/{name}",
                   headers=headers, content=data)


def patch(client, job_id, state, status, completed):
    return request(client, "PATCH", f"/{job_id}", json={
        "expected_attempt": state["attempt"], "expected_revision": state["revision"],
        "status": status, "checkpoint": {"completed": completed},
    })


def test_auth_idempotent_create_and_fingerprint(gateway):
    client, _, _ = gateway
    assert request(client, "GET", f"/{uuid4()}", token="bad").status_code == 401
    job_id, body, state = create(client)
    assert state["status"] == "queued" and state["attempt"] == 0
    assert request(client, "POST", "", json=body).json() == state
    assert request(client, "POST", "", json={**body, "input_fingerprint": "b" * 64}).status_code == 409
    assert request(client, "POST", "", json={**body, "job_id": "../bad"}).status_code == 422


def test_job_kind_contract_rejects_unimplemented_writers(gateway):
    client, _, _ = gateway
    for kind in ("incremental-small", "loader-staging", "graph", "reconcile-small"):
        resp = request(client, "POST", "", json={"job_id": str(uuid4()),
            "kind": kind, "input_fingerprint": "a" * 64})
        assert resp.status_code == 422
    for kind in ("graph-stats", "reconcile-dry-run"):
        create(client, kind=kind)


def test_report_gateway_scope_lease_and_fixed_commands(gateway, monkeypatch):
    client, clock, _ = gateway
    job_id, _, _ = create(client, kind="graph-stats")
    other, _, _ = create(client, kind="ocr")
    path = f"/{job_id}/report"
    body = {"expected_attempt": 1}
    token = request(client, "POST", f"/{job_id}/capabilities", json={
        "scopes": ["report", "claim"]}).json()["token"]
    read = request(client, "POST", f"/{job_id}/capabilities", json={
        "scopes": ["read"]}).json()["token"]
    assert request(client, "POST", f"/{other}/capabilities", json={"scopes": ["report"]}).status_code == 422
    assert request(client, "POST", path, token=read, json=body).status_code == 401
    assert request(client, "POST", f"/{other}/report", token=token, json=body).status_code == 401
    assert request(client, "POST", path, token=token, json=body).status_code == 409
    request(client, "POST", f"/{job_id}/claim", token=token)
    def run(command, **kwargs):
        assert command[1:] == ["-m", "sict_crawler.service.graph.graphsync", "stats"]
        assert kwargs["timeout"] == 20 and kwargs["check"]
        return mvp_jobs.subprocess.CompletedProcess(command, 0, stdout='{"links": 2}', stderr="")
    monkeypatch.setattr(mvp_jobs.subprocess, "run", run)
    response = request(client, "POST", path, token=token, json=body)
    assert response.json() == {"kind": "graph-stats", "report": {"links": 2}}
    def fail(command, **kwargs):
        raise mvp_jobs.subprocess.CalledProcessError(1, command, stderr="private DSN")
    monkeypatch.setattr(mvp_jobs.subprocess, "run", fail)
    response = request(client, "POST", path, token=token, json=body)
    assert response.status_code == 502 and "private DSN" not in response.text
    clock.now += 91
    assert request(client, "POST", path, token=token, json=body).status_code == 409


def test_capability_job_scope_expiry_and_owner_only_input(gateway):
    client, clock, _ = gateway
    first, _, _ = create(client)
    second, _, _ = create(client)
    path = f"/{first}/capabilities"
    assert request(client, "POST", path, token="bad", json={}).status_code == 401
    assert request(client, "POST", path, json={"scopes": ["admin"]}).status_code == 422
    response = request(client, "POST", path, json={"scopes": ["read", "claim", "write"],
                                                      "ttl_seconds": 120})
    assert response.status_code == 200
    capability = response.json()["token"]
    assert request(client, "GET", f"/{first}", token=capability).status_code == 200
    assert request(client, "GET", f"/{second}", token=capability).status_code == 401
    assert request(client, "POST", "", token=capability, json={
        "job_id": str(uuid4()), "kind": "ocr", "input_fingerprint": "a" * 64,
    }).status_code == 401
    assert request(client, "POST", path, token=capability, json={}).status_code == 401
    payload = b"input"
    assert request(client, "PUT", f"/{first}/artifacts/input/secret",
                   token=capability, content=payload,
                   headers={"X-Content-SHA256": hashlib.sha256(payload).hexdigest()}).status_code == 403
    assert request(client, "POST", f"/{first}/claim", token=capability).status_code == 200
    clock.now += 121
    assert request(client, "GET", f"/{first}", token=capability).status_code == 401


def test_capability_scopes_and_rate_limit(gateway, monkeypatch):
    client, _, _ = gateway
    job_id, _, _ = create(client)
    path = f"/{job_id}/capabilities"
    read = request(client, "POST", path, json={"scopes": ["read"]}).json()["token"]
    assert request(client, "GET", f"/{job_id}", token=read).status_code == 200
    assert request(client, "POST", f"/{job_id}/claim", token=read).status_code == 401
    monkeypatch.setenv("MVP_CAP_RATE_PER_MINUTE", "2")
    fresh = request(client, "POST", path, json={"scopes": ["read"]}).json()["token"]
    assert request(client, "GET", f"/{job_id}", token=fresh).status_code == 200
    assert request(client, "GET", f"/{job_id}/manifest", token=fresh).status_code == 200
    assert request(client, "GET", f"/{job_id}", token=fresh).status_code == 429


def test_lease_checkpoint_resume_and_manifest(gateway):
    client, clock, root = gateway
    job_id, _, _ = create(client)
    data = b'{"items":[{"id":"a"},{"id":"b"}]}'
    assert upload(client, job_id, "input", "items.json", data).status_code == 200
    state = request(client, "POST", f"/{job_id}/claim").json()
    assert state["attempt"] == 1
    assert request(client, "POST", f"/{job_id}/claim").status_code == 409
    assert upload(client, job_id, "output", "a.json", b"a").status_code == 422
    assert upload(client, job_id, "output", "a.json", b"a", attempt=state["attempt"]).status_code == 200
    assert upload(client, job_id, "output", "a.json", b"other", attempt=state["attempt"]).status_code == 409
    assert patch(client, job_id, state, "running", ["a"]).status_code == 200
    assert patch(client, job_id, state, "running", ["a"]).status_code == 409
    state = request(client, "GET", f"/{job_id}").json()
    clock.now += mvp_jobs.LEASE_SECONDS - 1
    assert request(client, "POST", f"/{job_id}/heartbeat", json={"expected_attempt": 1}).status_code == 200
    clock.now += 2
    assert request(client, "POST", f"/{job_id}/claim").status_code == 409
    clock.now += mvp_jobs.LEASE_SECONDS + 1
    assert upload(client, job_id, "output", "b.json", b"b", attempt=1).status_code == 409
    # PUT đã thành công nhưng client mất response vẫn idempotent sau lease hết hạn.
    assert upload(client, job_id, "output", "a.json", b"a", attempt=1).status_code == 200
    resumed = request(client, "POST", f"/{job_id}/claim").json()
    assert resumed["attempt"] == 2 and resumed["checkpoint"] == {"completed": ["a"]}
    assert patch(client, job_id, state, "paused", ["a"]).status_code == 409
    assert upload(client, job_id, "output", "b.json", b"b", attempt=2).status_code == 200
    complete = patch(client, job_id, resumed, "succeeded", ["a", "b"])
    assert complete.status_code == 200 and complete.json()["status"] == "succeeded"
    manifest = request(client, "GET", f"/{job_id}/manifest").json()
    assert manifest["artifacts"]["output/b.json"]["sha256"] == hashlib.sha256(b"b").hexdigest()
    assert request(client, "GET", f"/{job_id}/artifacts/input/items.json").content == data
    assert json.loads((root / job_id / "checkpoint.json").read_text()) == {"completed": ["a", "b"]}
    assert request(client, "POST", f"/{job_id}/claim").json()["status"] == "succeeded"


def test_invalid_artifacts_checksum_missing_output_and_cleanup(gateway):
    client, clock, root = gateway
    job_id, _, _ = create(client)
    assert upload(client, job_id, "input", "x", b"x", sha256="0" * 64).status_code == 422
    assert upload(client, job_id, "input", "../secrets", b"x").status_code in (404, 422)
    assert upload(client, job_id, "input", "huge", b"X" * (mvp_jobs.MAX_ARTIFACT_BYTES + 1)).status_code == 413
    state = request(client, "POST", f"/{job_id}/claim").json()
    assert patch(client, job_id, state, "succeeded", ["a"]).status_code == 409
    assert upload(client, job_id, "input", "late", b"x").status_code == 409
    assert upload(client, job_id, "output", "a.json", b"a", attempt=1).status_code == 200
    (root / job_id / "output" / "a.json").write_bytes(b"tampered")
    assert patch(client, job_id, state, "succeeded", ["a"]).status_code == 409
    (root / job_id / "output" / "a.json").write_bytes(b"a")
    assert patch(client, job_id, state, "succeeded", ["a"]).status_code == 200
    assert mvp_jobs.cleanup_completed(3600) == []
    clock.now += 3601
    assert mvp_jobs.cleanup_completed(3600) == [job_id]
    assert not (root / job_id).exists()
    # GET job đã dọn không tạo lại thư mục rỗng.
    assert request(client, "GET", f"/{job_id}").status_code == 404
    assert not (root / job_id).exists()


def test_artifact_download_checksum_and_lock_survives_cleanup(gateway):
    client, clock, root = gateway
    job_id, _, _ = create(client)
    assert upload(client, job_id, "input", "data.bin", b"original").status_code == 200
    file_response = request(client, "GET", f"/{job_id}/artifacts/input/data.bin")
    assert file_response.content == b"original"
    assert file_response.headers["cache-control"] == "no-store"
    (root / job_id / "input" / "data.bin").write_bytes(b"corrupted")
    assert request(client, "GET", f"/{job_id}/artifacts/input/data.bin").status_code == 409
    state = request(client, "POST", f"/{job_id}/claim").json()
    assert upload(client, job_id, "output", "done", b"ok", attempt=1).status_code == 200
    assert patch(client, job_id, state, "succeeded", ["a"]).status_code == 409
    (root / job_id / "input" / "data.bin").write_bytes(b"original")
    assert patch(client, job_id, state, "succeeded", ["a"]).status_code == 200
    clock.now += 3601
    assert mvp_jobs.cleanup_completed(3600) == [job_id]
    assert (root / ".locks" / f"{job_id}.lock").exists()


def test_succeeded_requires_all_input_items_and_matching_outputs(gateway):
    client, _, root = gateway
    job_id, _, _ = create(client)
    items = {"items": [{"id": "poster", "sha256": "a" * 64},
                       {"id": "banner", "sha256": "b" * 64}]}
    assert upload(client, job_id, "input", "items.json", json.dumps(items).encode()).status_code == 200
    state = request(client, "POST", f"/{job_id}/claim").json()
    assert upload(client, job_id, "output", "poster.json", b"poster", attempt=1).status_code == 200
    assert patch(client, job_id, state, "succeeded", ["poster"]).status_code == 409
    assert patch(client, job_id, state, "succeeded", ["poster", "missing"]).status_code == 409
    assert patch(client, job_id, state, "succeeded", ["poster", "poster"]).status_code == 409
    assert patch(client, job_id, state, "succeeded", ["poster", "banner"]).status_code == 409
    assert upload(client, job_id, "output", "banner.json", b"banner", attempt=1).status_code == 200
    assert patch(client, job_id, state, "succeeded", ["poster", "banner"]).status_code == 200
    assert (root / job_id / "state.json").is_file()


@pytest.mark.parametrize("items", [
    {"items": [{"id": "a"}, {"id": "a"}]},
    {"items": [{"id": "../invalid"}]},
    {"items": [{"missing_id": "a"}]},
    {"items": []},
    {"items": "invalid"},
    {"invalid": []},
])
def test_invalid_input_manifest_cannot_finish(gateway, items):
    client, _, _ = gateway
    job_id, _, _ = create(client)
    assert upload(client, job_id, "input", "items.json", json.dumps(items).encode()).status_code == 200
    state = request(client, "POST", f"/{job_id}/claim").json()
    assert upload(client, job_id, "output", "a.json", b"a", attempt=1).status_code == 200
    assert patch(client, job_id, state, "succeeded", ["a"]).status_code == 409
