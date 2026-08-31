"""Sinh tiêu đề cho 1 short: thử provider LLM đã cấu hình, fallback về rule-based nếu lỗi."""

from __future__ import annotations

import logging

from .config import LLMConfig
from .llm.base import TitleProvider, TitleProviderError
from .llm.rule_based import RuleBasedTitleProvider

logger = logging.getLogger(__name__)


def _build_configured_provider(llm_cfg: LLMConfig) -> TitleProvider | None:
    """Khởi tạo provider theo config (groq/claude). Trả None nếu provider = rule_based hoặc lỗi init."""
    try:
        if llm_cfg.provider == "groq":
            from .llm.groq_provider import GroqTitleProvider

            return GroqTitleProvider(
                api_key=llm_cfg.groq_api_key or "",
                model=llm_cfg.groq_model,
                temperature=llm_cfg.temperature,
            )
        if llm_cfg.provider == "claude":
            from .llm.claude_provider import ClaudeTitleProvider

            return ClaudeTitleProvider(
                api_key=llm_cfg.anthropic_api_key or "",
                model=llm_cfg.claude_model,
                temperature=llm_cfg.temperature,
            )
        if llm_cfg.provider == "rule_based":
            return None
        logger.warning("LLM provider '%s' không hợp lệ, dùng rule-based.", llm_cfg.provider)
        return None
    except TitleProviderError as e:
        logger.warning("Không khởi tạo được provider '%s' (%s), sẽ fallback rule-based.", llm_cfg.provider, e)
        return None


def generate_title(transcript_text: str, llm_cfg: LLMConfig) -> str:
    """Sinh tiêu đề cho đoạn transcript_text, dùng provider cấu hình, fallback rule-based khi lỗi."""
    provider = _build_configured_provider(llm_cfg)
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
