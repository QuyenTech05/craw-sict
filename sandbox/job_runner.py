"""Worker bounded cho Vercel Sandbox, checkpoint bền qua VM Job API.

Đầu vào là artifact input/items.json do owner upload cho job trước khi launch.
Chỉ thao tác trên file tạm của phiên và artifact server; không ghi collection live.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID


MAX_BYTES = 8 * 1024 * 1024


class ApiError(RuntimeError):
    pass


class JobClient:
    def __init__(self, base: str, token: str, job_id: str):
        try:
            if str(UUID(job_id)) != job_id:
                raise ValueError
        except ValueError as exc:
            raise ValueError("job_id phải là UUID chuẩn") from exc
        if not base.startswith("https://") and not base.startswith("http://127.0.0.1:"):
            raise ValueError("SICT_API_BASE phải dùng HTTPS (trừ localhost test)")
        if not token:
            raise ValueError("MVP_JOB_CAPABILITY_TOKEN đang thiếu")
        self.base = base.rstrip("/") + "/internal/jobs/" + job_id
        self.token = token
        self.attempt: int | None = None

    def request(self, suffix: str = "", method: str = "GET", json_body=None,
                data: bytes | None = None, checksum: str | None = None):
        headers = {"Authorization": "Bearer " + self.token}
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        if checksum:
            headers["X-Content-SHA256"] = checksum
            if suffix.startswith(("/artifacts/output/", "/artifacts/work/")):
                if self.attempt is None:
                    raise ApiError("Worker chưa claim job")
                headers["X-Job-Attempt"] = str(self.attempt)
        req = Request(self.base + suffix, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=25 if suffix == "/report" else 15) as resp:
                raw = resp.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ApiError("Phản hồi vượt giới hạn")
                return raw if suffix.startswith("/artifacts/") and method == "GET" else json.loads(raw)
        except HTTPError as exc:
            raise ApiError(f"Job API trả HTTP {exc.code}") from exc

    def upload(self, area: str, name: str, content: bytes):
        if len(content) > MAX_BYTES:
            raise ApiError("Artifact vượt 8 MiB, cần chia batch")
        return self.request(f"/artifacts/{area}/{name}", method="PUT", data=content,
                            checksum=hashlib.sha256(content).hexdigest())


def _run(command: list[str], deadline: float, cwd: Path | None = None) -> str:
    remaining = int(deadline - time.time()) - 30
    if remaining <= 0:
        raise TimeoutError("Gần đến deadline, cần checkpoint")
    result = subprocess.run(command, cwd=cwd, timeout=remaining, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError(f"Job command exit={result.returncode}: {result.stdout[-250:]}")
    return result.stdout[-4000:]


def _archive(folder: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.add(folder, arcname=folder.name)
    if buffer.tell() > MAX_BYTES:
        raise ApiError("Archive vượt 8 MiB, cần tách thành nhiều job/artifact")
    return buffer.getvalue()


def process_item(kind: str, item: dict, client: JobClient, deadline: float,
                 workspace: Path, run_command=_run) -> dict:
    """Mỗi item hoàn tất mới checkpoint, output hash cố định để retry idempotent."""
    identifier = item["id"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", identifier):
        raise ValueError("item.id không hợp lệ")
    target = workspace / identifier
    target.mkdir(parents=True, exist_ok=True)

    if kind in {"ocr", "video"}:
        name = item.get("input")
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", name):
            raise ValueError("input phải là tên artifact đơn")
        payload = client.request(f"/artifacts/input/{name}")
        if len(payload) > MAX_BYTES:
            raise ValueError("Input vượt giới hạn")
        if kind == "ocr":
            url = os.environ.get("MVP_OCR_URL", "")
            token = os.environ.get("MVP_OCR_TOKEN", "")
            if not url.startswith("https://") or not token:
                raise RuntimeError("Sandbox OCR cần MVP_OCR_URL (HTTPS) và MVP_OCR_TOKEN")
            body = json.dumps({"image_base64": base64.b64encode(payload).decode()}).encode()
            req = Request(url, data=body, method="POST", headers={
                "Authorization": "Bearer " + token, "Content-Type": "application/json"})
            with urlopen(req, timeout=max(1, min(50, deadline - time.time() - 30))) as response:
                result = json.loads(response.read(1024 * 1024))
            if (not isinstance(result, dict) or not isinstance(result.get("text"), str)
                    or not isinstance(result.get("language"), str)):
                raise ApiError(f"OCR Function trả dữ liệu không hợp lệ cho {identifier}")
            output = {"id": identifier, "text": result["text"],
                      "language": result["language"]}
            client.upload("output", identifier + ".json", json.dumps(output, ensure_ascii=False).encode())
            return output
        input_path = target / "input.mp4"
        input_path.write_bytes(payload)
        frame_pattern = str(target / "frame-%02d.jpg")
        run_command(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                     "-i", str(input_path), "-vf", "fps=1/30,scale='min(640,iw)':-2",
                     "-frames:v", "3", frame_pattern], deadline)
        frames = []
        # Frame đã upload ở phiên trước là immutable. Sau crash giữa các PUT,
        # đối chiếu checksum rồi tiếp tục phần còn thiếu, tránh lỗi 409 khi retry.
        known = client.request("/manifest")["artifacts"]
        for frame in sorted(target.glob("frame-*.jpg")):
            key = f"{identifier}-{frame.name}"
            content = frame.read_bytes()
            artifact_key = f"output/{key}"
            if artifact_key in known:
                previous = client.request(f"/artifacts/{artifact_key}")
                if hashlib.sha256(previous).digest() != hashlib.sha256(content).digest():
                    raise ApiError(f"Keyframe {key} khác bản đã checkpoint")
            else:
                client.upload("output", key, content)
            frames.append(key)
        if not frames:
            raise RuntimeError("Không tạo được keyframe")
        info = {"id": identifier, "frames": frames}
        client.upload("output", identifier + ".json", json.dumps(info).encode())
        return info

    if kind in {"reconcile-dry-run", "graph-stats"}:
        response = client.request("/report", method="POST",
                                  json_body={"expected_attempt": client.attempt})
        if response.get("kind") != kind or not isinstance(response.get("report"), dict):
            raise ApiError("Báo cáo datastore không hợp lệ")
        report = response["report"]
    elif kind == "snapshot":
        output = target / "snapshot"
        run_command(["uv", "run", "python", "-m", "sict_crawler.pipeline.snapshot",
                     "--out", str(output), "--max-pages", str(min(int(item.get("max_pages", 2)), 5))], deadline)
        client.upload("output", identifier + ".tar.gz", _archive(output))
        return {"id": identifier, "archive": identifier + ".tar.gz"}
    elif kind == "compute":
        # Compute chỉ chạy khi owner cung cấp snapshot test qua artifact VM.
        name = item.get("input")
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}\.tar\.gz", name):
            raise ValueError("compute cần input tar.gz của snapshot test")
        packed = client.request(f"/artifacts/input/{name}")
        # Mỗi lần thử dùng thư mục riêng, output không lấy từ artifact cũ trong input.
        with tempfile.TemporaryDirectory(dir=target) as tmp:
            extraction = Path(tmp) / "input"
            with tarfile.open(fileobj=io.BytesIO(packed), mode="r:gz") as archive:
                members = archive.getmembers()
                if len(members) > 1000 or sum(m.size for m in members) > 64 * 1024 * 1024:
                    raise ValueError("Snapshot tar vượt giới hạn giải nén")
                for member in members:
                    if (not (member.isfile() or member.isdir()) or member.name.startswith("/")
                            or ".." in Path(member.name).parts):
                        raise ValueError("Snapshot tar có đường dẫn không an toàn")
                archive.extractall(extraction, filter="data")
            roots = list(extraction.iterdir())
            if len(roots) != 1 or not roots[0].is_dir():
                raise ValueError("Snapshot input phải có một thư mục gốc")
            snapshot = roots[0]
            for filename, field in (("pages.jsonl", "html_path"), ("files.jsonl", "path")):
                manifest = snapshot / filename
                if not manifest.is_file():
                    raise ValueError(f"Snapshot thiếu {filename}")
                for line in manifest.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    path = row.get(field) if isinstance(row, dict) else None
                    if (not isinstance(path, str) or not path or Path(path).is_absolute()
                            or ".." in Path(path).parts):
                        raise ValueError(f"Snapshot {filename} có đường dẫn không an toàn")
            out = Path(tmp) / "artifacts"
            run_command(["uv", "run", "--no-sync", "--offline", "python", "-m",
                         "sict_crawler.pipeline.compute", "--snapshot", str(snapshot),
                         "--out", str(out), "--stages", "docs", "--limit-docs", "5",
                         "--no-semantic"], deadline)
            client.upload("output", identifier + ".tar.gz", _archive(out))
        return {"id": identifier, "archive": identifier + ".tar.gz"}
    else:
        raise ValueError("Kind không được hỗ trợ")
    output = {"id": identifier, "report": report}
    client.upload("output", identifier + ".json", json.dumps(output, ensure_ascii=False).encode())
    return output


def run_job(client: JobClient, deadline: float, workspace: Path, process=process_item) -> dict:
    # items.json là artifact input bền, được nạp lại sau mỗi phiên Sandbox.
    payload = client.request("/artifacts/input/items.json")
    manifest = json.loads(payload)
    items = manifest.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError("items.json cần từ 1 đến 100 items")
    ids = [item.get("id") if isinstance(item, dict) else None for item in items]
    if (any(not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", identifier)
            for identifier in ids) or len(ids) != len(set(ids))):
        raise ValueError("item.id không hợp lệ hoặc trùng")

    state = client.request("/claim", method="POST")
    if state["status"] == "succeeded":
        return state
    client.attempt = state["attempt"]
    completed = state.get("checkpoint", {}).get("completed", [])
    stop = threading.Event()
    heartbeat_error: list[Exception] = []

    def renew_lease():
        while not stop.wait(25):
            try:
                client.request("/heartbeat", method="POST",
                               json_body={"expected_attempt": state["attempt"]})
            except Exception as exc:
                heartbeat_error.append(exc)
                break

    heartbeat = threading.Thread(target=renew_lease, daemon=True)
    heartbeat.start()
    try:
        if (not isinstance(completed, list)
                or any(not isinstance(identifier, str) or identifier not in ids
                       for identifier in completed)
                or len(completed) != len(set(completed))):
            raise ApiError("Checkpoint chứa item không thuộc input hoặc bị trùng")
        artifacts = client.request("/manifest")["artifacts"]
        for item in items:
            # Xác nhận cả những item đã ghi vào checkpoint, phòng trường hợp
            # artifact bị mất hoặc sai checksum sau khi session kết thúc.
            output_name = "output/" + item["id"] + (
                ".tar.gz" if state["kind"] in {"snapshot", "compute"} else ".json")
            was_completed = item["id"] in completed
            if was_completed and output_name not in artifacts:
                raise ApiError(f"Checkpoint thiếu artifact {output_name}")
            if not was_completed and time.time() >= deadline - 90:
                break
            if heartbeat_error:
                raise ApiError("Mất heartbeat, dừng xử lý để worker khác resume") from heartbeat_error[0]
            # Output luôn upload sau cùng và bất biến. Khi worker chết trước PATCH,
            # manifest của output đủ để tiếp tục mà không tính lại item.
            if output_name in artifacts:
                # Manifest chỉ ghi metadata. GET bắt VM xác minh SHA256 trên disk.
                saved = client.request("/artifacts/" + output_name)
                if state["kind"] == "ocr":
                    try:
                        info = json.loads(saved)
                        if (not isinstance(info, dict) or info.get("id") != item["id"]
                                or not isinstance(info.get("text"), str)
                                or not isinstance(info.get("language"), str)):
                            raise ValueError("Output OCR thiếu trường bắt buộc")
                    except (ValueError, TypeError) as exc:
                        raise ApiError(f"OCR artifact {item['id']} không hợp lệ") from exc
                elif state["kind"] == "video":
                    try:
                        info = json.loads(saved)
                        frames = info["frames"]
                        if (info["id"] != item["id"] or not isinstance(frames, list)
                                or not 1 <= len(frames) <= 3 or len(set(frames)) != len(frames)):
                            raise ValueError("Danh sách frame không hợp lệ")
                        for frame in frames:
                            if (not isinstance(frame, str)
                                    or not re.fullmatch(re.escape(item["id"]) + r"-frame-\d{2}\.jpg", frame)
                                    or "output/" + frame not in artifacts):
                                raise ValueError("Thiếu frame trong manifest")
                            client.request("/artifacts/output/" + frame)
                    except (KeyError, ValueError, TypeError) as exc:
                        raise ApiError("Video manifest chưa hoàn tất") from exc
            else:
                process(state["kind"], item, client, deadline, workspace)
            if was_completed:
                continue
            if heartbeat_error:
                raise ApiError("Mất heartbeat") from heartbeat_error[0]
            completed.append(item["id"])
            state = client.request("", method="PATCH", json_body={
                "expected_attempt": state["attempt"], "expected_revision": state["revision"],
                "status": "running", "checkpoint": {"completed": completed},
            })
            artifacts = client.request("/manifest")["artifacts"]
        state = client.request("", method="PATCH", json_body={
            "expected_attempt": state["attempt"], "expected_revision": state["revision"],
            "status": "succeeded" if len(completed) == len(items) else "paused",
            "checkpoint": {"completed": completed},
        })
    except Exception:
        try:
            client.request("", method="PATCH", json_body={
                "expected_attempt": state["attempt"], "expected_revision": state["revision"],
                "status": "paused", "checkpoint": {"completed": completed},
            })
        except ApiError:
            pass
        raise
    finally:
        stop.set()
        heartbeat.join(timeout=2)
    return state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    args = parser.parse_args()
    try:
        if str(UUID(args.job_id)) != args.job_id:
            raise ValueError
    except ValueError:
        parser.error("job_id không hợp lệ")
    client = JobClient(os.environ["SICT_API_BASE"], os.environ["MVP_JOB_CAPABILITY_TOKEN"], args.job_id)
    deadline = float(os.environ.get("JOB_DEADLINE", str(time.time() + 40 * 60)))
    with tempfile.TemporaryDirectory(prefix="sict-sandbox-") as directory:
        result = run_job(client, deadline, Path(directory))
    print(json.dumps({"job_id": args.job_id, "status": result["status"],
                      "completed": len(result["checkpoint"].get("completed", []))}))


if __name__ == "__main__":
    main()
