"""Khởi tạo LLM provider (Groq/Claude) theo config, dùng chung cho title_generator và
image_prompt_generator."""

from __future__ import annotations

import logging

from ..config import LLMConfig
from .base import TitleProvider, TitleProviderError

logger = logging.getLogger(__name__)


def build_configured_provider(llm_cfg: LLMConfig) -> TitleProvider | None:
    """Khởi tạo provider theo config (groq/claude). Trả None nếu provider = rule_based hoặc lỗi init."""
    try:
        if llm_cfg.provider == "groq":
            from .groq_provider import GroqTitleProvider

            return GroqTitleProvider(
                api_key=llm_cfg.groq_api_key or "",
                model=llm_cfg.groq_model,
                temperature=llm_cfg.temperature,
            )
        if llm_cfg.provider == "claude":
            from .claude_provider import ClaudeTitleProvider

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
