"""Entry point tương thích cho dịch vụ Jina-CLIP v2 ONNX Runtime INT8.

Dùng `uv run --group embed python scripts/serve_jina_clip.py --port 8090`.
Mọi xử lý embedding nằm trong `sict_crawler.service.embedding.embed_server`.
"""

from sict_crawler.service.embedding.embed_server import main


if __name__ == "__main__":
    main()
