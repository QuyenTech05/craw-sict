"""Job/checkpoint/artifact gateway cho Vercel MVP, dữ liệu bền trên disk VM-SERVE.

Mọi mutation trên một job được serialize bằng flock và ghi JSON atomic.
Không có code kết nối trực tiếp store Qdrant/PG ở lớp này.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field


router = APIRouter()
KINDS = {"ocr", "reconcile-dry-run", "video", "graph-stats", "snapshot", "compute"}
STATUSES = {"queued", "running", "paused", "succeeded", "failed"}
AREAS = {"input", "work", "output"}
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
LEASE_SECONDS = 90
CAPABILITY_SCOPES = {"read", "write", "claim", "report"}
REPORT_COMMANDS = {
    "graph-stats": ("sict_crawler.service.graph.graphsync", "stats"),
    "reconcile-dry-run": ("sict_crawler.pipeline.reconcile", "--dry-run"),
}
_report_slot = threading.Lock()
CAPABILITY_MAX_TTL = 3600
_rate_lock = threading.Lock()
_rate_windows: dict[tuple[str, str], tuple[int, int]] = {}


def _root() -> Path:
    return Path(os.environ.get("MVP_JOB_ROOT", "/var/lib/sict-mvp/jobs")).resolve()


def _directory(job_id: str) -> Path:
    try:
        if str(UUID(job_id)) != job_id:
            raise ValueError("uuid chưa chuẩn hóa")
    except ValueError as exc:
        raise HTTPException(422, "job_id phải là UUID chuẩn") from exc
    return _root() / job_id


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _reject_auth() -> None:
    raise HTTPException(401, "Token không hợp lệ hoặc hết hạn",
                        headers={"WWW-Authenticate": "Bearer"})


def _authorize(request: Request, job_id: str | None = None, scope: str | None = None,
               *, owner_only: bool = False) -> bool:
    """Trả True nếu owner. Worker chỉ nhận capability đúng job/scope."""
    secret = os.environ.get("MVP_JOB_TOKEN", "")
    if not secret:
        raise HTTPException(503, "Job API chưa được cấu hình")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        _reject_auth()
    supplied = auth[7:]
    if hmac.compare_digest(supplied.encode(), secret.encode()):
        return True
    if owner_only or not job_id or not scope:
        _reject_auth()
    try:
        payload_part, signature = supplied.split(".", 1)
        expected = _encode(hmac.new(secret.encode(), payload_part.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            _reject_auth()
        data = json.loads(base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4)))
        now = time.time()
        if (data.get("v") != 1 or data.get("job_id") != job_id
                or scope not in data.get("scopes", [])
                or not isinstance(data.get("iat"), (float, int))
                or not isinstance(data.get("exp"), (float, int))
                or data["iat"] > now + 30 or data["exp"] <= now
                or data["exp"] - data["iat"] > CAPABILITY_MAX_TTL
                or not re.fullmatch(r"[a-f0-9]{32}", data.get("jti", ""))):
            _reject_auth()
    except (ValueError, TypeError, KeyError, UnicodeError):
        _reject_auth()

    # Rate limit theo cặp capability/job, có khóa giữa các request đồng thời.
    bucket = (data["jti"], job_id)
    window = int(now // 60)
    limit = max(1, min(5000, int(os.getenv("MVP_CAP_RATE_PER_MINUTE", "600"))))
    with _rate_lock:
        if len(_rate_windows) > 20000:
            _rate_windows.clear()
        old_window, count = _rate_windows.get(bucket, (window, 0))
        count = count + 1 if old_window == window else 1
        if count > limit:
            raise HTTPException(429, "Vượt giới hạn request capability")
        _rate_windows[bucket] = (window, count)
    return False


class CapabilityRequest(BaseModel):
    scopes: list[str] = Field(default_factory=lambda: ["read", "write", "claim"])
    ttl_seconds: int = Field(default=2700, ge=60, le=CAPABILITY_MAX_TTL)


@router.post("/internal/jobs/{job_id}/capabilities")
def issue_capability(job_id: str, body: CapabilityRequest, request: Request):
    _authorize(request, owner_only=True)
    if not body.scopes or set(body.scopes) - CAPABILITY_SCOPES:
        raise HTTPException(422, "Scopes không hợp lệ")
    with _locked(job_id) as path:
        state = _load(path, "state.json")
        if state["status"] in {"succeeded", "failed"}:
            raise HTTPException(409, "Job đã kết thúc")
        if "report" in body.scopes and state["kind"] not in REPORT_COMMANDS:
            raise HTTPException(422, "Scope report chỉ dành cho job báo cáo")
    now = time.time()
    payload = {"v": 1, "job_id": job_id, "scopes": sorted(set(body.scopes)),
               "iat": now, "exp": now + body.ttl_seconds, "jti": secrets.token_hex(16)}
    part = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _encode(hmac.new(os.environ["MVP_JOB_TOKEN"].encode(), part.encode(), hashlib.sha256).digest())
    return {"token": f"{part}.{signature}", "expires_at": payload["exp"],
            "job_id": job_id, "scopes": payload["scopes"]}


@contextmanager
def _locked(job_id: str, *, create: bool = False):
    path = _directory(job_id)
    # Lock sống ngoài thư mục job để cleanup không xóa inode trong khi còn waiter.
    locks = _root() / ".locks"
    locks.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (locks / f"{job_id}.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            if create:
                path.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not path.is_dir():
                raise HTTPException(404, "Job chưa tồn tại")
            yield path
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    filename = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".staging-",
                                         encoding="utf-8", delete=False) as file:
            filename = file.name
            json.dump(data, file, ensure_ascii=False, sort_keys=True)
            file.flush()
            os.fsync(file.fileno())
        os.replace(filename, path)
        fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if filename and os.path.exists(filename):
            os.unlink(filename)


def _load(path: Path, filename: str) -> dict:
    try:
        with (path / filename).open(encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Job chưa tồn tại") from exc


class CreateJob(BaseModel):
    job_id: str
    kind: str
    input_fingerprint: str


class UpdateJob(BaseModel):
    expected_attempt: int = Field(ge=1)
    expected_revision: int = Field(ge=1)
    status: str
    checkpoint: dict = Field(default_factory=dict)


class Heartbeat(BaseModel):
    expected_attempt: int = Field(ge=1)


@router.post("/internal/jobs")
def create_job(body: CreateJob, request: Request):
    _authorize(request)
    if body.kind not in KINDS or not re.fullmatch(r"[a-f0-9]{64}", body.input_fingerprint):
        raise HTTPException(422, "kind hoặc input_fingerprint không hợp lệ")
    with _locked(body.job_id, create=True) as path:
        if (path / "state.json").exists():
            state = _load(path, "state.json")
            if state["kind"] != body.kind or state["input_fingerprint"] != body.input_fingerprint:
                raise HTTPException(409, "job_id đã có fingerprint/kind khác")
            return state
        for area in AREAS:
            (path / area).mkdir(mode=0o700, exist_ok=True)
        now = time.time()
        state = dict(job_id=body.job_id, kind=body.kind, input_fingerprint=body.input_fingerprint,
                     status="queued", attempt=0, revision=0, checkpoint={}, lease_until=0,
                     created_at=now, updated_at=now)
        _atomic_json(path / "checkpoint.json", {})
        _atomic_json(path / "manifest.json", {"artifacts": {}})
        _atomic_json(path / "state.json", state)
        return state


@router.get("/internal/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    _authorize(request, job_id, "read")
    with _locked(job_id) as path:
        return _load(path, "state.json")


@router.post("/internal/jobs/{job_id}/claim")
def claim_job(job_id: str, request: Request):
    _authorize(request, job_id, "claim")
    with _locked(job_id) as path:
        state = _load(path, "state.json")
        if state["status"] == "succeeded":
            return state
        if state["status"] == "running" and state["lease_until"] > time.time():
            raise HTTPException(409, "Job đang được xử lý")
        state.update(status="running", attempt=state["attempt"] + 1,
                     revision=state["revision"] + 1,
                     lease_until=time.time() + LEASE_SECONDS, updated_at=time.time())
        _atomic_json(path / "state.json", state)
        return state


def _check_lease(state: dict, attempt: int) -> None:
    if (state["status"] != "running" or state["attempt"] != attempt
            or state["lease_until"] <= time.time()):
        raise HTTPException(409, "Lease đã hết hạn hoặc job đã được worker khác nhận")


@router.post("/internal/jobs/{job_id}/report")
def run_report(job_id: str, body: Heartbeat, request: Request):
    """Chỉ chạy báo cáo cố định trên VM, không cấp credential datastore cho Sandbox."""
    _authorize(request, job_id, "report")
    with _locked(job_id) as path:
        state = _load(path, "state.json")
        _check_lease(state, body.expected_attempt)
        command = REPORT_COMMANDS.get(state["kind"])
        if command is None:
            raise HTTPException(422, "Job không hỗ trợ báo cáo")
    if not _report_slot.acquire(blocking=False):
        raise HTTPException(429, "Đang có báo cáo datastore")
    try:
        # Timeout nhỏ hơn nginx 30s; chỉ trả JSON tổng hợp, không trả log/DSN.
        result = subprocess.run([sys.executable, "-m", *command],
                                capture_output=True, text=True, timeout=20, check=True)
        line = result.stdout.strip().splitlines()[-1]
        report = json.loads(line.removeprefix("[reconcile] "))
        if not isinstance(report, dict):
            raise ValueError("Report phải là object")
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "Báo cáo datastore quá thời hạn") from exc
    except (OSError, subprocess.CalledProcessError, ValueError, IndexError) as exc:
        raise HTTPException(502, "Không tạo được báo cáo datastore") from exc
    finally:
        _report_slot.release()
    with _locked(job_id) as path:
        _check_lease(_load(path, "state.json"), body.expected_attempt)
    return {"kind": state["kind"], "report": report}


@router.post("/internal/jobs/{job_id}/heartbeat")
def heartbeat_job(job_id: str, body: Heartbeat, request: Request):
    """Gia hạn lease không tăng revision để checkpoint đồng thời vẫn dùng CAS."""
    _authorize(request, job_id, "write")
    with _locked(job_id) as path:
        state = _load(path, "state.json")
        _check_lease(state, body.expected_attempt)
        now = time.time()
        state.update(lease_until=now + LEASE_SECONDS, updated_at=now)
        _atomic_json(path / "state.json", state)
        return state


@router.patch("/internal/jobs/{job_id}")
def update_job(job_id: str, body: UpdateJob, request: Request):
    _authorize(request, job_id, "write")
    if body.status not in ("running", "paused", "failed", "succeeded"):
        raise HTTPException(422, "Trạng thái không hợp lệ")
    if len(json.dumps(body.checkpoint, ensure_ascii=False)) > 128 * 1024:
        raise HTTPException(413, "Checkpoint quá lớn")
    with _locked(job_id) as path:
        state = _load(path, "state.json")
        _check_lease(state, body.expected_attempt)
        if state["revision"] != body.expected_revision:
            raise HTTPException(409, "Job đã thay đổi, cần đọc lại checkpoint")
        if body.status == "succeeded":
            manifest = _load(path, "manifest.json")
            # Manifest phải chứa ít nhất một output còn nguyên checksum khi hoàn thành.
            if not any(name.startswith("output/") for name in manifest["artifacts"]):
                raise HTTPException(409, "Thiếu output manifest")
            # Các job mới upload danh sách item bất biến trước khi claim.
            # Checkpoint chỉ được coi là xong khi đủ đúng tập input và output.
            input_manifest = path / "input" / "items.json"
            if "input/items.json" in manifest["artifacts"]:
                try:
                    items = json.loads(input_manifest.read_bytes())["items"]
                    ids = [item["id"] for item in items]
                    completed = body.checkpoint["completed"]
                    valid = (isinstance(items, list) and 1 <= len(items) <= 100
                             and all(isinstance(identifier, str)
                                     and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", identifier)
                                     for identifier in ids)
                             and len(ids) == len(set(ids))
                             and isinstance(completed, list)
                             and len(completed) == len(ids)
                             and all(isinstance(identifier, str) for identifier in completed)
                             and set(completed) == set(ids))
                except (OSError, ValueError, TypeError, KeyError, IndexError):
                    valid = False
                if not valid:
                    raise HTTPException(409, "Checkpoint chưa khớp danh sách input")
                suffix = ".tar.gz" if state["kind"] in {"snapshot", "compute"} else ".json"
                if any(f"output/{identifier}{suffix}" not in manifest["artifacts"]
                       for identifier in ids):
                    raise HTTPException(409, "Thiếu output tương ứng với input")
            for name, meta in manifest["artifacts"].items():
                item = path / name
                if not item.is_file() or hashlib.sha256(item.read_bytes()).hexdigest() != meta["sha256"]:
                    raise HTTPException(409, "Artifact chưa hoàn tất hoặc sai checksum")
        state.update(status=body.status, checkpoint=body.checkpoint,
                     revision=state["revision"] + 1,
                     lease_until=time.time() + LEASE_SECONDS if body.status == "running" else 0,
                     updated_at=time.time())
        _atomic_json(path / "checkpoint.json", body.checkpoint)
        _atomic_json(path / "state.json", state)
        return state


def _artifact_path(path: Path, area: str, name: str) -> Path:
    if area not in AREAS or not name or "\\" in name or any(
            piece in ("", ".", "..") for piece in name.split("/")):
        raise HTTPException(422, "Đường dẫn artifact không hợp lệ")
    target = (path / area / name).resolve()
    if not target.is_relative_to(path / area):
        raise HTTPException(422, "Artifact nằm ngoài thư mục job")
    return target


@router.put("/internal/jobs/{job_id}/artifacts/{area}/{name:path}")
async def upload_artifact(job_id: str, area: str, name: str, request: Request):
    owner = _authorize(request, job_id, "write")
    if area == "input" and not owner:
        raise HTTPException(403, "Chỉ owner được ghi input")
    checksum = request.headers.get("x-content-sha256", "")
    if not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise HTTPException(422, "Thiếu SHA256 hợp lệ")
    # Đọc streaming với chặn size trước khi tạo artifact để không giữ nhiều RAM.
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_ARTIFACT_BYTES:
            raise HTTPException(413, "Artifact vượt giới hạn")
        content.extend(chunk)
    actual = hashlib.sha256(content).hexdigest()
    if actual != checksum:
        raise HTTPException(422, "Checksum không khớp")
    with _locked(job_id) as path:
        state = _load(path, "state.json")
        target = _artifact_path(path, area, name)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        manifest = _load(path, "manifest.json")
        key = f"{area}/{name}"
        existing = manifest["artifacts"].get(key)
        if existing and existing["sha256"] != checksum:
            raise HTTPException(409, "Artifact cùng tên có nội dung khác")
        if existing:
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == checksum:
                return existing
            raise HTTPException(409, "Artifact đã ghi nhưng file bị mất hoặc hỏng")
        if area == "input":
            if state["status"] != "queued":
                raise HTTPException(409, "Input chỉ được ghi trước khi job được claim")
        else:
            attempt = request.headers.get("x-job-attempt", "")
            if not attempt.isascii() or not attempt.isdecimal():
                raise HTTPException(422, "Thiếu X-Job-Attempt")
            _check_lease(state, int(attempt))
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".upload-", delete=False) as out:
                tmp = out.name
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, target)
            tmp = None
            fd = os.open(target.parent, os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            meta = {"sha256": checksum, "bytes": len(content)}
            manifest["artifacts"][key] = meta
            _atomic_json(path / "manifest.json", manifest)
            return meta
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)


@router.get("/internal/jobs/{job_id}/manifest")
def get_manifest(job_id: str, request: Request):
    _authorize(request, job_id, "read")
    with _locked(job_id) as path:
        _load(path, "state.json")
        return _load(path, "manifest.json")


@router.get("/internal/jobs/{job_id}/artifacts/{area}/{name:path}")
def download_artifact(job_id: str, area: str, name: str, request: Request):
    _authorize(request, job_id, "read")
    with _locked(job_id) as path:
        _load(path, "state.json")
        target = _artifact_path(path, area, name)
        manifest = _load(path, "manifest.json")
        if f"{area}/{name}" not in manifest["artifacts"] or not target.is_file():
            raise HTTPException(404, "Artifact chưa sẵn sàng")
        # Đọc tối đa 8 MiB dưới lock để cleanup không xóa file trước khi gửi.
        payload = target.read_bytes()
        if len(payload) > MAX_ARTIFACT_BYTES:
            raise HTTPException(409, "Artifact vượt giới hạn")
        if hashlib.sha256(payload).hexdigest() != manifest["artifacts"][f"{area}/{name}"]["sha256"]:
            raise HTTPException(409, "Artifact sai checksum")
        return Response(payload, media_type="application/octet-stream",
                        headers={"Cache-Control": "no-store"})


def cleanup_completed(ttl_seconds: int) -> list[str]:
    """Chỉ dọn job kết thúc quá TTL, không xóa queued/running/paused."""
    import shutil

    removed = []
    root = _root()
    if not root.is_dir():
        return removed
    for candidate in root.iterdir():
        if not candidate.is_dir():
            continue
        try:
            with _locked(candidate.name) as path:
                state = _load(path, "state.json")
                if (state["status"] not in ("succeeded", "failed")
                        or time.time() - state["updated_at"] < ttl_seconds
                        or not (path / "manifest.json").is_file()):
                    continue
                shutil.rmtree(path)
            removed.append(candidate.name)
        except (HTTPException, OSError, ValueError):
            continue
    return removed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cleanup", choices=["cleanup"])
    parser.add_argument("--ttl-hours", type=int, default=168)
    args = parser.parse_args()
    print(json.dumps({"removed": cleanup_completed(args.ttl_hours * 3600)}))
