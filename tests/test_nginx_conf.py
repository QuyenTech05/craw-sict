"""nginx là cửa duy nhất ra Internet: không được chuyển /metrics của API ra ngoài."""
import re
from pathlib import Path

CONF = (Path(__file__).resolve().parents[1] / "nginx" / "nginx.conf").read_text(encoding="utf-8")
# nginx CỬA 1 trên host (TLS + redirect), cài vào /etc/nginx/conf.d/ trên VM1
HOST_CONF = (Path(__file__).resolve().parents[1] / "nginx" / "sict-http.conf").read_text(encoding="utf-8")


def _body_limit(text: str) -> int:
    """Trả về client_max_body_size tính bằng byte của NGỮ CẢNH truyền vào."""
    m = re.search(r"client_max_body_size\s+(\d+)([mk])?\s*;", text)
    assert m, "thiếu client_max_body_size (mặc định 1m → 413 với ảnh base64)"
    n, unit = int(m.group(1)), (m.group(2) or "b")
    return n * {"b": 1, "k": 1024, "m": 1024 * 1024}[unit]


def test_body_size_allows_query_image():
    """Ảnh truy vấn là base64 trong JSON: mặc định 1m trả 413 cho ảnh ~1,5 MB (2026-11-07)."""
    assert _body_limit(CONF) >= 8 * 1024 * 1024


def test_host_conf_body_size_on_both_blocks():
    """Khối 80 kiểm body size TRƯỚC return 301 → thiếu directive là POST lớn nhận 413 (2026-11-16)."""
    blocks = re.findall(r"server\s*\{(.*?)\n\}", HOST_CONF, re.S)
    assert len(blocks) == 2, f"chờ 2 khối server (80 + 443), thấy {len(blocks)}"
    for b in blocks:
        assert _body_limit(b) >= 8 * 1024 * 1024


def test_metrics_blocked_at_edge():
    m = re.search(r"location\s*=\s*/metrics\s*\{([^}]*)\}", CONF)
    assert m, "thiếu location = /metrics"
    assert "return 404" in m.group(1) and "proxy_pass" not in m.group(1)


def test_chat_stream_unbuffered():
    m = re.search(r"location\s+/chat\s*\{([^}]*)\}", CONF)
    assert m and "proxy_buffering off" in m.group(1)
