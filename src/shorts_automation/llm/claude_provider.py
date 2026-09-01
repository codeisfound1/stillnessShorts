"""Provider dùng Claude API (tùy chọn thay thế Groq) cho title + image prompt."""

from __future__ import annotations

import logging

from .base import TitleProvider, TitleProviderError

logger = logging.getLogger(__name__)


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

    def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int) -> str:
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=self.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return "".join(block.text for block in message.content if hasattr(block, "text"))
        except Exception as e:  # noqa: BLE001 - muốn bắt mọi lỗi từ SDK để fallback được
            raise TitleProviderError(f"Lỗi gọi Claude API: {e}") from e
