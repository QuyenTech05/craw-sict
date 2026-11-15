"""nginx là cửa duy nhất ra Internet: không được chuyển /metrics của API ra ngoài."""
import re
from pathlib import Path

CONF = (Path(__file__).resolve().parents[1] / "nginx" / "nginx.conf").read_text(encoding="utf-8")


def test_metrics_blocked_at_edge():
    m = re.search(r"location\s*=\s*/metrics\s*\{([^}]*)\}", CONF)
    assert m, "thiếu location = /metrics"
    assert "return 404" in m.group(1) and "proxy_pass" not in m.group(1)


def test_body_size_allows_query_image():
    """Ảnh truy vấn là base64 trong JSON: mặc định 1m trả 413 cho ảnh ~1,5 MB (2026-11-07)."""
    m = re.search(r"client_max_body_size\s+(\d+)([mk])?\s*;", CONF)
    assert m, "thiếu client_max_body_size (mặc định 1m → 413 với ảnh base64)"
    n, unit = int(m.group(1)), (m.group(2) or "b")
    limit = n * {"b": 1, "k": 1024, "m": 1024 * 1024}[unit]
    assert limit >= 8 * 1024 * 1024, f"client_max_body_size {n}{unit} quá nhỏ cho ảnh base64"


def test_chat_stream_unbuffered():
    m = re.search(r"location\s+/chat\s*\{([^}]*)\}", CONF)
    assert m and "proxy_buffering off" in m.group(1)
