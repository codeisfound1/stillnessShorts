"""Sinh prompt ảnh (tiếng Anh, mô tả 1 cảnh cụ thể) từ tiêu đề + transcript của 1 short.

Dùng cùng LLM provider (Groq/Claude) đã cấu hình cho title; nếu provider không khả dụng
hoặc lỗi, fallback về template ghép trực tiếp từ tiêu đề (không cần LLM).
"""

from __future__ import annotations

import logging

from .config import LLMConfig
from .llm.base import TitleProviderError
from .llm.factory import build_configured_provider

logger = logging.getLogger(__name__)


def _fallback_prompt(title: str, transcript_text: str) -> str:
    basis = title.strip() or transcript_text.strip()[:120]
    return f"A serene, symbolic photograph representing the idea: {basis}"


def generate_image_prompt(transcript_text: str, title: str, llm_cfg: LLMConfig) -> str:
    """Sinh prompt ảnh cho short, dùng provider LLM cấu hình, fallback template khi lỗi/không hỗ trợ."""
    provider = build_configured_provider(llm_cfg)

    if provider is not None:
        try:
            prompt = provider.generate_image_prompt(transcript_text, title, max_length=300)
            logger.info("Sinh image prompt bằng provider '%s': %s", provider.name, prompt)
            return prompt
        except TitleProviderError as e:
            logger.warning("Provider '%s' không sinh được image prompt (%s), dùng template.", provider.name, e)

    prompt = _fallback_prompt(title, transcript_text)
    logger.info("Sinh image prompt bằng template: %s", prompt)
    return prompt
