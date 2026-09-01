"""Sinh tiêu đề cho 1 short: thử provider LLM đã cấu hình, fallback về rule-based nếu lỗi."""

from __future__ import annotations

import logging

from .config import LLMConfig
from .llm.base import TitleProviderError
from .llm.factory import build_configured_provider
from .llm.rule_based import RuleBasedTitleProvider

logger = logging.getLogger(__name__)


def generate_title(transcript_text: str, llm_cfg: LLMConfig) -> str:
    """Sinh tiêu đề cho đoạn transcript_text, dùng provider cấu hình, fallback rule-based khi lỗi."""
    provider = build_configured_provider(llm_cfg)
    rule_based = RuleBasedTitleProvider()

    if provider is not None:
        try:
            title = provider.generate_title(transcript_text, max_length=llm_cfg.max_title_length)
            logger.info("Sinh title bằng provider '%s': %s", provider.name, title)
            return title
        except TitleProviderError as e:
            logger.warning("Provider '%s' lỗi (%s), fallback sang rule-based.", provider.name, e)

    title = rule_based.generate_title(transcript_text, max_length=llm_cfg.max_title_length)
    logger.info("Sinh title bằng rule-based: %s", title)
    return title
