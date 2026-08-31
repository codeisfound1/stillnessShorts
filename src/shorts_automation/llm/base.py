"""Interface chung cho các LLM provider dùng để sinh tiêu đề video từ transcript."""

from __future__ import annotations

from abc import ABC, abstractmethod


class TitleProviderError(RuntimeError):
    """Raised khi provider không sinh được title (lỗi API, thiếu key, timeout...)."""


class TitleProvider(ABC):
    """Mỗi provider (Groq, Claude, rule-based) implement cùng 1 interface này."""

    name: str = "base"

    @abstractmethod
    def generate_title(self, transcript_text: str, *, max_length: int) -> str:
        """Sinh 1 tiêu đề ngắn gọn, hấp dẫn, bám sát nội dung transcript_text.

        Raises TitleProviderError nếu không sinh được (để caller fallback sang provider khác).
        """
        raise NotImplementedError
