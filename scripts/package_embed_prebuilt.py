"""Đóng gói artifact ONNX INT8 đã build trên host RAM >= 6 GiB để chuyển sang VM-EMBED.

Chỉ đọc dữ liệu local, không gọi API cloud và không tự build model.
Usage: uv run --group embed python scripts/package_embed_prebuilt.py --output /tmp/sict-embed-prebuilt.tar
"""

import argparse
import hashlib
import json
import tarfile
from pathlib import Path

from sict_crawler.service.embedding import embed_server


def package(output: Path) -> str:
    src = embed_server.model_dir()
    built = embed_server.build_dir()
    expected = f"{embed_server.REVISION[:12]}-{embed_server.RECIPE}"
    if built.name != expected:
        raise RuntimeError(f"EMBED_BUILD_DIR phải có tên {expected} để khớp đường dẫn runtime")
    towers = embed_server.prebuilt_towers(src, built)
    files = [(src / name, f"sict-source/{name}") for name in
             ("tokenizer.json", "preprocessor_config.json", "config.json")]
    files.extend((path, f"sict-embed/{expected}/{path.name}") for path, _ in towers.values())
    files.append((built / "towers.json", f"sict-embed/{expected}/towers.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "x") as archive:
        for path, arcname in files:
            archive.add(path, arcname=arcname, recursive=False)
    with output.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    digest = package(args.output)
    print(json.dumps({"file": str(args.output), "sha256": digest,
                      "model_revision": embed_server.REVISION, "recipe": embed_server.RECIPE}))


if __name__ == "__main__":
    main()
