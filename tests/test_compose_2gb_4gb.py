"""Giới hạn cgroup khởi tạo để thử VM-SERVE 2 GiB."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _default(raw):
    return raw.split(":-", 1)[1].rstrip("}")


def test_vm_serve_budget_1746_mib():
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    expected = {"api": 320, "postgres": 384, "redis": 128, "qdrant": 850, "nginx": 64}
    limits = {name: int(_default(services[name]["mem_limit"]).removesuffix("m"))
              for name in expected}
    assert limits == expected
    assert sum(limits.values()) == 1746 < 2048


def test_store_memory_tuning():
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    pg_command = " ".join(services["postgres"]["command"])
    redis_command = " ".join(services["redis"]["command"])
    assert "${PG_SHARED_BUFFERS:-64MB}" in pg_command
    assert "${PG_MAX_CONNECTIONS:-20}" in pg_command
    assert "${REDIS_MAXMEMORY:-64mb}" in redis_command
    assert "volatile-ttl" in redis_command


def test_api_docker_image_only_uses_api_group():
    dockerfile = (ROOT / "Dockerfile.api").read_text(encoding="utf-8")
    install = next(line for line in dockerfile.splitlines() if "uv sync" in line)
    assert "--group api" in install
    for forbidden in ("--group worker", "--group embed", "--group graph", "torch", "transformers"):
        assert forbidden not in install


def test_serve_env_example_contains_all_limits():
    content = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name, expected in {
        "API_MEM_LIMIT": "320m", "PG_MEM_LIMIT": "384m", "PG_SHARED_BUFFERS": "64MB",
        "PG_MAX_CONNECTIONS": "20", "REDIS_MEM_LIMIT": "128m", "REDIS_MAXMEMORY": "64mb",
        "QDRANT_MEM_LIMIT": "850m", "NGINX_MEM_LIMIT": "64m",
    }.items():
        assert f"{name}={expected}" in content


def test_live_qdrant_volume_is_preserved():
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    assert "qdata:/qdrant/storage" in services["qdrant"]["volumes"]
    assert "./.pgdata:/var/lib/postgresql/data" in services["postgres"]["volumes"]
