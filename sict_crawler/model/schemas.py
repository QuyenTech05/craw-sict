"""Schema vào/ra của API hỏi đáp (pydantic): câu hỏi và nguồn trả về."""
from __future__ import annotations

import base64
import binascii
import io
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator


class QueryFilters(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sections: list[StrictStr] | None = None
    doc_types: list[StrictStr] | None = None
    year_from: StrictInt | None = None
    year_to: StrictInt | None = None


class QueryIn(BaseModel):
    question: str = Field(default='', max_length=2000)
    top_k: int = Field(default=8, ge=1, le=30)
    image: str | None = None  # base64 (không có tiền tố data:) — truy vấn bằng ảnh (D21); question có thể rỗng
    # lọc cứng metadata: {"sections": [...], "doc_types": [...], "year_from": int, "year_to": int}
    filters: dict | None = None

    @field_validator('filters')
    @classmethod
    def valid_filters(cls, value):
        return QueryFilters.model_validate(value).model_dump(exclude_none=True) if value is not None else None

    @field_validator('question', mode='before')
    @classmethod
    def strip_question(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator('image')
    @classmethod
    def valid_image(cls, value):
        if value is None:
            return value
        try:
            if len(value) > ((5 * 1024 * 1024 + 2) // 3) * 4:
                raise ValueError('Ảnh vượt quá 5 MB')
            raw = base64.b64decode(value, validate=True)
            if len(raw) > 5 * 1024 * 1024:
                raise ValueError('Ảnh vượt quá 5 MB')
            with Image.open(io.BytesIO(raw)) as img:
                if img.width * img.height > 20_000_000:
                    raise ValueError('Ảnh vượt quá 20 megapixel')
                img.convert('RGB').load()
        except (ValueError, OSError, binascii.Error, Image.DecompressionBombError) as exc:
            raise ValueError('Ảnh không hợp lệ hoặc quá lớn') from exc
        return value

    @model_validator(mode='after')
    def require_input(self):
        if not self.question and not self.image:
            raise ValueError('Cần câu hỏi hoặc ảnh')
        return self


class Source(BaseModel):
    url: str
    title: str
    kind: str  # text | image | video_frame
    score: float
    excerpt: str = ""
    media_id: int | None = None      # index v1 → GET /media/{media_id}
    media_key: str | None = None     # index v2 (sha256) → GET /media/s/{media_key}
    timestamp: float | None = None
    published_at: str | None = None  # index spec v2 (thiếu ở index cũ)
    section: str | None = None
    parent_url: str | None = None    # file đính kèm → trang chứa nó (url = link tải file)
    via: str | None = None           # D21: nhánh tìm ra nguồn này: text | i2t | i2i-doc | graph | clip | i2i | i2t | caption …
    heading_path: list[str] | None = None   # D23: mục chứa đoạn trích trong bài
    page: int | None = None                 # D24: trang (từ 1) trong file PDF/PPTX; None = không có trang
    cite: str = ""                          # D24: nhãn trích dẫn dựng sẵn (citations.make_cite)
    # D27: nội dung đầy đủ của đoạn cho ngữ cảnh LLM (excerpt chỉ 300 ký tự để hiển thị). Có trong cache truy vấn,
    # không trả qua HTTP (routes bỏ trường này — RESPONSE_EXCLUDE).
    content: str = ""
    cosine: float | None = None             # D27: cosine câu hỏi↔đoạn (raw_score) — tín hiệu "đủ bằng chứng"
