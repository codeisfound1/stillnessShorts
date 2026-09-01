"""Interface chung cho các LLM provider: sinh tiêu đề video và prompt ảnh AI từ transcript.

Mỗi provider (Groq, Claude) chỉ cần implement `complete()` (1 lệnh gọi chat completion
chung chung); `generate_title()` và `generate_image_prompt()` được implement sẵn ở lớp
base, dùng chung `complete()` với 2 system prompt khác nhau. RuleBasedTitleProvider là
ngoại lệ: nó override `generate_title()` bằng thuật toán rule-based (không gọi complete()).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

_TITLE_SYSTEM_PROMPT = (
    "Bạn là chuyên gia đặt tiêu đề YouTube Shorts tiếng Việt. "
    "Nhiệm vụ: đọc đoạn transcript được cung cấp và viết ĐÚNG 1 tiêu đề video "
    "ngắn gọn, hấp dẫn, gây tò mò, bám sát nội dung quan trọng nhất trong đoạn. "
    "Không dùng dấu ngoặc kép bao quanh tiêu đề. Không thêm giải thích. "
    "Không thêm hashtag. Chỉ trả về duy nhất dòng tiêu đề."
)

_IMAGE_PROMPT_SYSTEM = (
    "You are a visual prompt writer for an AI image generator. Given a Vietnamese video "
    "title and narration excerpt, write ONE short English prompt (max 40 words) describing "
    "a single concrete visual scene that captures the main idea. Describe concrete subjects, "
    "setting, mood, lighting - not abstract concepts. Never include any text/words/letters "
    "that should appear in the image. Return ONLY the prompt, no explanation, no quotes."
)


class TitleProviderError(RuntimeError):
    """Raised khi provider không sinh được title/image prompt (lỗi API, thiếu key, timeout...)."""


def _clean_and_truncate(text: str, max_length: int) -> str:
    cleaned = text.strip().strip('"').strip("'").strip()
    if len(cleaned) > max_length:
        cleaned = cleaned[: max_length - 1].rstrip() + "…"
    return cleaned


class TitleProvider(ABC):
    """Mỗi provider (Groq, Claude, rule-based) implement cùng 1 interface này."""

    name: str = "base"

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int) -> str:
        """Gọi 1 lượt chat completion chung chung, trả về text thô (chưa xử lý)."""
        raise NotImplementedError

    def generate_title(self, transcript_text: str, *, max_length: int) -> str:
        """Sinh 1 tiêu đề ngắn gọn, hấp dẫn, bám sát nội dung transcript_text.

        Raises TitleProviderError nếu không sinh được (để caller fallback sang provider khác).
        """
        if not transcript_text.strip():
            raise TitleProviderError("Transcript rỗng, không thể sinh tiêu đề.")
        user_prompt = (
            f"Đoạn transcript (tối đa {max_length} ký tự cho tiêu đề):\n"
            f"\"\"\"\n{transcript_text.strip()}\n\"\"\""
        )
        raw = self.complete(_TITLE_SYSTEM_PROMPT, user_prompt, max_tokens=100)
        title = _clean_and_truncate(raw, max_length)
        if not title:
            raise TitleProviderError(f"Provider '{self.name}' trả về tiêu đề rỗng.")
        return title

    def generate_image_prompt(self, transcript_text: str, title: str, *, max_length: int = 300) -> str:
        """Sinh 1 prompt ảnh (tiếng Anh) mô tả cảnh chính từ tiêu đề + transcript.

        Raises TitleProviderError nếu không sinh được (để caller fallback sang template).
        """
        if not transcript_text.strip() and not title.strip():
            raise TitleProviderError("Không đủ nội dung để sinh image prompt.")
        user_prompt = f"Title: {title.strip()}\nNarration excerpt: {transcript_text.strip()}"
        raw = self.complete(_IMAGE_PROMPT_SYSTEM, user_prompt, max_tokens=120)
        prompt = _clean_and_truncate(raw, max_length)
        if not prompt:
            raise TitleProviderError(f"Provider '{self.name}' trả về image prompt rỗng.")
        return prompt
