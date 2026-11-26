"""Hợp đồng phân bố hai máy serving theo plan 2 GiB / 4 GiB."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _compose(name):
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def test_serving_composes_are_isolated():
    assert set(_compose("docker-compose.yml")["services"]) == {
        "postgres", "redis", "qdrant", "api", "nginx"
    }
    assert set(_compose("docker-compose.embed.yml")["services"]) == {"embed"}


def test_offline_batch_does_not_start_by_default():
    worker = _compose("docker-compose.worker.yml")
    assert set(worker["services"]) == {"cron", "svc-ocr", "obscura"}
    for service in worker["services"].values():
        assert "batch" in service.get("profiles", []) or "manual" in service.get("profiles", [])


def test_v3_contract_in_both_env_examples():
    for name in (".env.example", ".env.worker.example"):
        content = (ROOT / name).read_text(encoding="utf-8")
        for setting in (
            "EMBED_BACKEND=api", "EMBED_MODEL=jina-clip-v2", "EMBED_DIM=1024",
            "QDRANT_COLLECTION_TEXT=sict_text_v3", "QDRANT_COLLECTION_IMAGE=sict_image_v3",
            "QDRANT_COLLECTION_OCR=sict_ocr_v3", "QDRANT_TEXT_DIM=1024",
            "QDRANT_IMAGE_DIM=1024"
        ):
            assert setting in content, (name, setting)


def test_vm_inventory_and_dependency_order_documented():
    report = (ROOT / "docs/placement-baseline-2gb-4gb.md").read_text(encoding="utf-8")
    for keyword in ("2 GiB", "4 GiB", "PostgreSQL", "Qdrant", "8090", "/readyz",
                    "EBS", "fingerprint"):
        assert keyword in report


def test_cd_does_not_automatically_launch_batch_on_vm_embed():
    workflow = (ROOT / ".github/workflows/cd.yml").read_text(encoding="utf-8")
    assert "up -d obscura cron" not in workflow
    assert "up -d cron" not in workflow
    assert "pull cron" not in workflow
