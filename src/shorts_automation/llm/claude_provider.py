"""Provider sinh tiêu đề bằng Claude API (tùy chọn thay thế cho Groq)."""

from __future__ import annotations

import logging

from .base import TitleProvider, TitleProviderError

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Bạn là chuyên gia đặt tiêu đề YouTube Shorts tiếng Việt. "
    "Nhiệm vụ: đọc đoạn transcript được cung cấp và viết ĐÚNG 1 tiêu đề video "
    "ngắn gọn, hấp dẫn, gây tò mò, bám sát nội dung quan trọng nhất trong đoạn. "
    "Không dùng dấu ngoặc kép bao quanh tiêu đề. Không thêm giải thích. "
    "Không thêm hashtag. Chỉ trả về duy nhất dòng tiêu đề."
)


class ClaudeTitleProvider(TitleProvider):
    name = "claude"

    def __init__(self, api_key: str, model: str, temperature: float = 0.6, timeout: float = 30.0):
        if not api_key:
            raise TitleProviderError("Thiếu ANTHROPIC_API_KEY.")
        try:
            import anthropic
        except ImportError as e:
            raise TitleProviderError(
                "Thư viện 'anthropic' chưa được cài. Thêm 'anthropic' vào requirements.txt."
            ) from e

        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        self.model = model
        self.temperature = temperature

    def generate_title(self, transcript_text: str, *, max_length: int) -> str:
        if not transcript_text.strip():
            raise TitleProviderError("Transcript rỗng, không thể sinh tiêu đề.")

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=100,
                temperature=self.temperature,
                system=_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Đoạn transcript (tối đa {max_length} ký tự cho tiêu đề):\n"
                            f"\"\"\"\n{transcript_text.strip()}\n\"\"\""
                        ),
                    }
                ],
            )
            title = "".join(block.text for block in message.content if hasattr(block, "text")).strip()
        except Exception as e:  # noqa: BLE001 - muốn bắt mọi lỗi từ SDK để fallback được
            raise TitleProviderError(f"Lỗi gọi Claude API: {e}") from e

        title = title.strip().strip('"').strip("'")
        if not title:
            raise TitleProviderError("Claude trả về tiêu đề rỗng.")
        if len(title) > max_length:
            title = title[: max_length - 1].rstrip() + "…"
        return title
