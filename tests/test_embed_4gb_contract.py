"""Hợp đồng VM-EMBED 4 GiB, chỉ chạy một lượt ONNX mỗi thời điểm."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_onnx_embed_resources_and_endpoint():
    compose = yaml.safe_load((ROOT / "docker-compose.embed.yml").read_text())
    assert set(compose["services"]) == {"embed"}
    embed = compose["services"]["embed"]
    assert embed["mem_limit"] == "${EMBED_MEM_LIMIT:-3500m}"
    assert embed["environment"] == {
        "EMBED_THREADS": "${EMBED_THREADS:-2}",
        "EMBED_TEXT_MAX_LEN": "${EMBED_TEXT_MAX_LEN:-1536}",
        "EMBED_TOKEN_BUDGET": "${EMBED_TOKEN_BUDGET:-1536}",
        "EMBED_CONCURRENCY": "${EMBED_CONCURRENCY:-1}",
        "EMBED_IMAGE_BATCH": "${EMBED_IMAGE_BATCH:-1}",
        "EMBED_API_KEY": "${EMBED_API_KEY:-}",
        "EMBED_QUERY_IMAGE_SIZES": "${EMBED_QUERY_IMAGE_SIZES:-336}",
        "EMBED_REQUIRE_PREBUILT": "1",
        "EMBED_ONNX_DIR": "/hf/sict-source",
    }
    assert ":8090" in embed["ports"][0]
    dockerfile = (ROOT / "Dockerfile.embed").read_text(encoding="utf-8")
    assert "--group embed" in dockerfile
    assert "/healthz" in dockerfile
    server = (ROOT / "sict_crawler/service/embedding/embed_server.py").read_text()
    assert '"/v1/embeddings"' in server and '"/healthz"' in server
    alloy = (ROOT / "monitor/alloy/vm2-services.alloy").read_text()
    assert 'credentials = sys.env("EMBED_API_KEY")' in alloy


def test_embedding_env_example_matches_4gb_trial():
    env = (ROOT / ".env.worker.example").read_text(encoding="utf-8")
    for name, value in {
        "EMBED_MEM_LIMIT": "3500m", "EMBED_THREADS": "2",
        "EMBED_CONCURRENCY": "1", "EMBED_IMAGE_BATCH": "1",
        "EMBED_TEXT_MAX_LEN": "1536", "EMBED_TOKEN_BUDGET": "1536",
        "EMBED_QUERY_IMAGE_SIZES": "336",
    }.items():
        assert f"{name}={value}" in env
