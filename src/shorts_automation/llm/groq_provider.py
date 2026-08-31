"""Provider sinh tiêu đề bằng Groq API (mặc định model: openai/gpt-oss-120b)."""

from __future__ import annotations

import logging

import requests

from .base import TitleProvider, TitleProviderError

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM_PROMPT = (
    "Bạn là chuyên gia đặt tiêu đề YouTube Shorts tiếng Việt. "
    "Nhiệm vụ: đọc đoạn transcript được cung cấp và viết ĐÚNG 1 tiêu đề video "
    "ngắn gọn, hấp dẫn, gây tò mò, bám sát nội dung quan trọng nhất trong đoạn. "
    "Không dùng dấu ngoặc kép bao quanh tiêu đề. Không thêm giải thích. "
    "Không thêm hashtag. Chỉ trả về duy nhất dòng tiêu đề."
)


class GroqTitleProvider(TitleProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, temperature: float = 0.6, timeout: float = 30.0):
        if not api_key:
            raise TitleProviderError("Thiếu GROQ_API_KEY.")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def generate_title(self, transcript_text: str, *, max_length: int) -> str:
        if not transcript_text.strip():
            raise TitleProviderError("Transcript rỗng, không thể sinh tiêu đề.")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Đoạn transcript (tối đa {max_length} ký tự cho tiêu đề):\n"
                        f"\"\"\"\n{transcript_text.strip()}\n\"\"\""
                    ),
                },
            ],
            "temperature": self.temperature,
            "max_tokens": 100,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        try:
            resp = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            title = data["choices"][0]["message"]["content"].strip()
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            raise TitleProviderError(f"Lỗi gọi Groq API: {e}") from e

        title = title.strip().strip('"').strip("'")
        if not title:
            raise TitleProviderError("Groq trả về tiêu đề rỗng.")
        if len(title) > max_length:
            title = title[: max_length - 1].rstrip() + "…"
        return title
